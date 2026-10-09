"""Search view: name LIKE query, sortable columns, paginated results.
Also: a /download/ endpoint that adds a torrent to the local qBittorrent,
and /list-tv-folders/ + /create-tv-folder/ for the TV Show folder picker.
"""
import json
import logging
import os
from urllib.parse import urlencode

from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt

from .models import Torrent
from .qbt import QbtClient, QbtError, load_config

TV_ROOT = os.environ.get("TORRENTS_TV_ROOT", os.path.join(os.path.expanduser("~"), "media", "TV"))

DOWNLOADS_SCHEMA = """
CREATE TABLE IF NOT EXISTS downloads (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          INTEGER NOT NULL,
    name        TEXT,
    magnet      TEXT NOT NULL,
    category    TEXT NOT NULL,
    save_path   TEXT,
    status      TEXT,
    qbt_reply   TEXT
);
"""

def ensure_downloads_table():
    from django.db import connection
    with connection.cursor() as cur:
        cur.execute(DOWNLOADS_SCHEMA)

log = logging.getLogger(__name__)

PAGE_SIZE = 50
SORTABLE = {
    "seeders": "seeders",
    "leechers": "leechers",
    "size_bytes": "size_bytes",
    "name": "name",
    "created_unix": "created_unix",
    "published": "published",
}


def search(request):
    q = request.GET.get("q", "").strip()
    sort = request.GET.get("sort", "seeders")
    direction = request.GET.get("dir", "desc")
    if sort not in SORTABLE:
        sort = "seeders"
    if direction not in ("asc", "desc"):
        direction = "desc"

    qs = Torrent.objects.all()
    if q:
        qs = qs.filter(name__icontains=q)
    order_field = SORTABLE[sort]
    qs = qs.order_by(("-" if direction == "desc" else "") + order_field)

    paginator = Paginator(qs, PAGE_SIZE)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    opposite_dir = "asc" if direction == "desc" else "desc"

    def url_for(page, sort_key, dir_key):
        params = {}
        if q:
            params["q"] = q
        params["sort"] = sort_key
        params["dir"] = dir_key
        params["page"] = page
        return "?" + urlencode(params)

    sort_links = {}
    for col in SORTABLE:
        sort_links[col] = url_for(
            1,
            col,
            opposite_dir if col == sort else "desc",
        )

    sort_arrows = {}
    for col in SORTABLE:
        if col == sort:
            sort_arrows[col] = "\u25bc" if direction == "desc" else "\u25b2"
        else:
            sort_arrows[col] = ""

    base_for_page = {}
    if q:
        base_for_page["q"] = q
    base_for_page["sort"] = sort
    base_for_page["dir"] = direction

    def page_url(n):
        params = dict(base_for_page)
        params["page"] = n
        return "?" + urlencode(params)

    context = {
        "page_obj": page_obj,
        "q": q,
        "sort": sort,
        "direction": direction,
        "sort_links": sort_links,
        "sort_arrows": sort_arrows,
        "page_url_prev": page_url(page_obj.previous_page_number()) if page_obj.has_previous() else None,
        "page_url_next": page_url(page_obj.next_page_number()) if page_obj.has_next() else None,
        "total_count": paginator.count,
        "first_index": page_obj.start_index(),
        "last_index": page_obj.end_index(),
    }
    return render(request, "torrents/search.html", context)


@csrf_exempt
def download(request):
    """POST /download/  body: {"magnet": "...", "category": "Movie"|"TV Show", "save_path": "..."}

    save_path is optional — overrides the configured default for the category
    (used by the TV Show folder picker).
    """
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)
    try:
        body = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse({"error": "invalid JSON body"}, status=400)
    infohash = (body.get("infohash") or "").strip().lower()
    category = (body.get("category") or "").strip()
    if not category:
        return JsonResponse({"error": "category is required"}, status=400)
    cfg = load_config()
    if category not in cfg.get("categories", {}):
        return JsonResponse({"error": f"unknown category: {category!r}"}, status=400)
    magnet = body.get("magnet")
    if not magnet:
        if not infohash:
            return JsonResponse({"error": "either magnet or infohash is required"}, status=400)
        try:
            t = Torrent.objects.get(infohash=infohash)
            magnet = t.magnet
        except Torrent.DoesNotExist:
            return JsonResponse({"error": "infohash not in local DB"}, status=404)
    save_path = body.get("save_path")
    try:
        client = QbtClient(cfg)
        result = client.add_torrent(magnet, category, save_path=save_path)
    except QbtError as e:
        log.warning("qBt add failed: %s", e)
        return JsonResponse({"error": str(e)}, status=502)
    except Exception as e:
        log.exception("qBt add crashed")
        return JsonResponse({"error": f"internal: {e}"}, status=500)
    ok = (result == "Ok.") or (result and "added_torrent_ids" in result)
    # Log to downloads history table.
    import time as _time
    try:
        ensure_downloads_table()
        from django.db import connection
        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO downloads (ts, name, magnet, category, save_path, status, qbt_reply) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [int(_time.time()),
                 body.get("name") or _extract_name_from_magnet(magnet),
                 magnet, category, save_path or "",
                 "ok" if ok else "unknown", result],
            )
    except Exception as exc:
        log.warning("failed to log download: %s", exc)
    if ok:
        return JsonResponse({"ok": True, "message": f"added to qBittorrent as {category}"})
    return JsonResponse({"ok": True, "message": f"added to qBittorrent as {category} (qBt reply: {result!r})"})


def _extract_name_from_magnet(magnet):
    """Pull the &dn= value from a magnet URL."""
    import urllib.parse as _up
    p = _up.urlparse(magnet)
    params = _up.parse_qs(p.query)
    vals = params.get("xt") or params.get("dn")
    for k, v in _up.parse_qsl(p.query):
        if k == "dn":
            return v
    return magnet[:80]


@csrf_exempt
def app_config(request):
    """GET /config/ → {"tv_root": "/path/to/TV"}
    Exposes server-side config to the frontend so JS doesn't hardcode paths.
    """
    if request.method != "GET":
        return JsonResponse({"error": "GET required"}, status=405)
    return JsonResponse({"tv_root": TV_ROOT})


@csrf_exempt
def history(request):
    """GET /history/ → {"downloads": [{id, ts, name, magnet, category, save_path}, ...]}
    Returns the most recent 200 downloads, newest first.
    """
    if request.method != "GET":
        return JsonResponse({"error": "GET required"}, status=405)
    ensure_downloads_table()
    from django.db import connection
    with connection.cursor() as cur:
        cur.execute(
            "SELECT id, ts, name, magnet, category, save_path FROM downloads "
            "ORDER BY id DESC LIMIT 200"
        )
        rows = cur.fetchall()
    items = [
        {"id": r[0], "ts": r[1], "name": r[2], "magnet": r[3],
         "category": r[4], "save_path": r[5]}
        for r in rows
    ]
    return JsonResponse({"downloads": items})


@csrf_exempt
def list_tv_folders(request):
    """GET /list-tv-folders/?show=<name>
    No show param → list shows in the TV root (env: TORRENTS_TV_ROOT).
    With show param → list season folders in <TV_ROOT>/<show>.
    Returns {"folders": ["1883", "MobLand", ...]} or {"folders": ["Season 1", ...]}.
    """
    if request.method != "GET":
        return JsonResponse({"error": "GET required"}, status=405)
    show = request.GET.get("show", "").strip()
    base = TV_ROOT
    if show:
        if "/" in show or "\\" in show or show in (".", ".."):
            return JsonResponse({"error": "invalid show name"}, status=400)
        base = os.path.join(TV_ROOT, show)
    try:
        entries = sorted(os.listdir(base), key=str.lower)
        folders = [e for e in entries if os.path.isdir(os.path.join(base, e))]
    except OSError as e:
        return JsonResponse({"error": str(e)}, status=500)
    return JsonResponse({"folders": folders})


@csrf_exempt
def create_tv_folder(request):
    """POST /create-tv-folder/  body: {"name": "NewShow", "show": "OptionalShowName"}
    Without show → creates <TV_ROOT>/<name>.
    With show → creates <TV_ROOT>/<show>/<name> (a season folder).
    Returns {"ok": true, "path": "...", "name": "..."}.
    """
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)
    try:
        body = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse({"error": "invalid JSON body"}, status=400)
    name = (body.get("name") or "").strip()
    show = (body.get("show") or "").strip()
    if not name or len(name) > 100:
        return JsonResponse({"error": "folder name must be 1-100 characters"}, status=400)
    if "/" in name or "\\" in name or name in (".", "..") or name.startswith("."):
        return JsonResponse({"error": "invalid characters in folder name"}, status=400)
    if show and ("/" in show or "\\" in show or show in (".", "..")):
        return JsonResponse({"error": "invalid show name"}, status=400)
    base = os.path.join(TV_ROOT, show) if show else TV_ROOT
    path = os.path.join(base, name)
    try:
        os.makedirs(path, exist_ok=True)
    except OSError as e:
        return JsonResponse({"error": str(e)}, status=500)
    return JsonResponse({"ok": True, "path": path, "name": name})
