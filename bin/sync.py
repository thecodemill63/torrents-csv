#!/usr/bin/env python3
"""Sync heretic/torrents-csv-data from Codeberg into a local SQLite store.

Pipeline:
  1. Conditional GET on the upstream torrents.csv (If-None-Match / ETag)
     so no-change days cost zero bandwidth.
  2. SHA256 double-check against the last ingested file.
  3. Bulk-load the CSV into a temp staging table.
  4. On bootstrap (empty DB): straight bulk insert.
     Otherwise: diff against `torrents`, append per-field change rows to
     `changes`, then UPSERT (UPDATE changed rows, INSERT new rows).
  5. Record every run in `syncs`.

Infohashes are 40-char hex (qBittorrent origin), so a row maps directly to
magnet:?xt=urn:btih:<infohash>.

Schema:
  torrents      current state, PK=infohash, + first_seen_local / last_updated_local
  syncs         one row per run (started_at, status, counts, upstream etag/sha/lastmod)
  changes       append-only: 'new' -> 1 JSON row/torrent; 'updated' -> 1 scalar row/changed field
"""
import csv
import hashlib
import json
import logging
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from logging.handlers import RotatingFileHandler
from pathlib import Path

DATA_DIR = Path(os.environ.get("TORRENTS_CSV_DIR", Path(__file__).resolve().parent.parent))
UPSTREAM_URL = "https://codeberg.org/heretic/torrents-csv-data/raw/branch/main/torrents.csv"

DB_PATH = DATA_DIR / "torrents.db"
DOWNLOADS_DIR = DATA_DIR / "downloads"
STATE_DIR = DATA_DIR / "state"
LOG_DIR = DATA_DIR / "logs"
CSV_PATH = DOWNLOADS_DIR / "torrents.csv"
CSV_TMP = DOWNLOADS_DIR / "torrents.csv.new"
ETAG_PATH = STATE_DIR / "last_etag"
SHA_PATH = STATE_DIR / "last_sha256"
LOG_PATH = LOG_DIR / "sync.log"
CHUNK_BYTES = 1 << 20          # 1 MiB download buffer
BATCH_ROWS = 5000              # executemany batch size for staging load
HTTP_TIMEOUT = 180

# Public trackers appended to every magnet (not part of the upstream dataset).
# These are well-known, currently-operational open trackers; the URL params
# get fully percent-encoded when built into the magnet string.
TRACKERS = [
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://open.demonii.com:1337/announce",
    "udp://tracker.openbittorrent.com:6969/announce",
    "udp://exodus.desync.com:6969/announce",
    "udp://tracker.torrent.eu.org:451/announce",
]
_TRACKER_PARAMS = "".join(
    "&tr=" + urllib.parse.quote(t, safe="") for t in TRACKERS
)

# Upstream CSV column order (matches the file header line exactly).
CSV_COLS = ["infohash", "name", "size_bytes", "created_unix", "seeders",
            "leechers", "completed", "scraped_date", "published"]
# Fields tracked for change-diffing (everything except the PK infohash).
TRACKED_FIELDS = CSV_COLS[1:]
INT_FIELDS = {"size_bytes", "created_unix", "seeders", "leechers",
              "completed", "scraped_date", "published"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS torrents (
    infohash           TEXT PRIMARY KEY,
    name               TEXT,
    size_bytes         INTEGER,
    created_unix       INTEGER,
    seeders            INTEGER,
    leechers           INTEGER,
    completed          INTEGER,
    scraped_date       INTEGER,
    published          INTEGER,
    magnet             TEXT,
    first_seen_local   INTEGER NOT NULL,
    last_updated_local INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS syncs (
    sync_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at        INTEGER NOT NULL,
    finished_at       INTEGER,
    status            TEXT NOT NULL,
    rows_total        INTEGER,
    rows_new          INTEGER,
    rows_updated      INTEGER,
    rows_unchanged    INTEGER,
    bytes_downloaded  INTEGER,
    upstream_sha256   TEXT,
    upstream_etag     TEXT,
    upstream_lastmod  TEXT,
    note              TEXT
);
CREATE TABLE IF NOT EXISTS changes (
    sync_id     INTEGER NOT NULL,
    infohash    TEXT NOT NULL,
    change_type TEXT NOT NULL,
    field       TEXT,
    old_value   TEXT,
    new_value   TEXT,
    ts          INTEGER NOT NULL,
    FOREIGN KEY (sync_id) REFERENCES syncs(sync_id)
);
CREATE INDEX IF NOT EXISTS idx_changes_infohash ON changes(infohash);
CREATE INDEX IF NOT EXISTS idx_changes_sync      ON changes(sync_id);
CREATE INDEX IF NOT EXISTS idx_changes_type      ON changes(change_type);
CREATE INDEX IF NOT EXISTS idx_torrents_first_seen ON torrents(first_seen_local);
"""


def init_logging():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    root.addHandler(sh)
    fh = RotatingFileHandler(LOG_PATH, maxBytes=5 * (1 << 20), backupCount=3)
    fh.setFormatter(fmt)
    root.addHandler(fh)


def ensure_dirs():
    for d in (DATA_DIR, DOWNLOADS_DIR, STATE_DIR, LOG_DIR):
        d.mkdir(parents=True, exist_ok=True)


def ensure_schema(conn):
    conn.executescript(SCHEMA)
    # Idempotent migration: add `magnet` column if missing on a pre-existing DB.
    cols = {r[1] for r in conn.execute("PRAGMA table_info(torrents)")}
    if "magnet" not in cols:
        conn.execute("ALTER TABLE torrents ADD COLUMN magnet TEXT")
        logging.info("migrated: added torrents.magnet column")


def set_pragmas(conn):
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA cache_size=-200000")     # ~200 MiB
    conn.execute("PRAGMA mmap_size=268435456")    # 256 MiB


def build_magnet(infohash, name):
    """Build a magnet:?xt=urn:btih:<hash>&dn=<name>&tr=... from row fields."""
    dn = urllib.parse.quote(name or "", safe="")
    return f"magnet:?xt=urn:btih:{infohash}&dn={dn}{_TRACKER_PARAMS}"


def to_int(v):
    v = (v or "").strip()
    if not v:
        return None
    try:
        return int(v)
    except ValueError:
        return None


def parse_row(row):
    """Map a raw CSV row (list of 9 strings) to a staging tuple, or None.

    Tuple layout matches `staging` table (10 cols): 9 upstream fields + magnet.
    """
    if len(row) != len(CSV_COLS):
        return None
    ih = (row[0] or "").strip()
    if not ih:
        return None
    name = row[1] if len(row[1]) else None
    out = [ih, name]
    for i in range(2, len(CSV_COLS)):
        out.append(to_int(row[i]) if CSV_COLS[i] in INT_FIELDS else (row[i] or None))
    out.append(build_magnet(ih, name))
    return tuple(out)


def iter_rows(path):
    """Yield parsed staging tuples from the CSV, skipping header and bad rows."""
    skipped = 0
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f, delimiter=",")
        header = next(reader, None)
        if not header or header[0].strip() != "infohash":
            logging.warning("unexpected CSV header: %r", header)
        for row in reader:
            if not row:
                continue
            parsed = parse_row(row)
            if parsed is None:
                skipped += 1
                continue
            yield parsed
    if skipped:
        logging.warning("skipped %d malformed rows during parse", skipped)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch():
    """Conditional GET. Returns (status, etag, lastmod, bytes_downloaded, tmp_path|None).

    status 304 -> upstream unchanged, no body downloaded.
    status 200 -> body written to CSV_TMP.
    """
    last_etag = ETAG_PATH.read_text().strip() if ETAG_PATH.exists() else ""
    req = urllib.request.Request(UPSTREAM_URL, headers={"User-Agent": "torrents-csv-sync/1.0"})
    if last_etag:
        req.add_header("If-None-Match", last_etag)
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            etag = resp.headers.get("ETag", "") or last_etag
            lastmod = resp.headers.get("Last-Modified", "")
            with open(CSV_TMP, "wb") as out:
                size = 0
                while True:
                    chunk = resp.read(CHUNK_BYTES)
                    if not chunk:
                        break
                    out.write(chunk)
                    size += len(chunk)
            return 200, etag, lastmod, size, CSV_TMP
    except urllib.error.HTTPError as e:
        if e.code == 304:
            return 304, last_etag, "", 0, None
        raise


def load_staging(conn):
    """Truncate/recreate staging temp table and bulk-load the CSV into it.
    Returns the count of staged rows."""
    conn.execute("DROP TABLE IF EXISTS staging")
    conn.execute(
        "CREATE TEMP TABLE staging ("
        "infohash TEXT, name TEXT, size_bytes INTEGER, created_unix INTEGER, "
        "seeders INTEGER, leechers INTEGER, completed INTEGER, "
        "scraped_date INTEGER, published INTEGER, magnet TEXT)"
    )
    conn.execute("CREATE INDEX idx_staging_infohash ON staging(infohash)")
    cur = conn.cursor()
    batch = []
    total = 0
    for parsed in iter_rows(CSV_PATH):
        batch.append(parsed)
        if len(batch) >= BATCH_ROWS:
            cur.executemany("INSERT INTO staging VALUES (?,?,?,?,?,?,?,?,?,?)", batch)
            total += len(batch)
            batch.clear()
    if batch:
        cur.executemany("INSERT INTO staging VALUES (?,?,?,?,?,?,?,?,?,?)", batch)
        total += len(batch)
    logging.info("staged %d rows", total)
    return total


def ingest_bootstrap(conn, sync_id, now, rows_total):
    """First-ever sync: bulk insert all rows, no change-log (nothing to diff against)."""
    conn.execute(
        "INSERT INTO torrents (infohash, name, size_bytes, created_unix, seeders, "
        "leechers, completed, scraped_date, published, magnet, first_seen_local, last_updated_local) "
        "SELECT infohash, name, size_bytes, created_unix, seeders, leechers, completed, "
        "scraped_date, published, magnet, ?, ? FROM staging",
        (now, now),
    )
    conn.execute(
        "UPDATE syncs SET rows_total=?, rows_new=?, rows_updated=0, rows_unchanged=0, "
        "note='bootstrap (initial load)' WHERE sync_id=?",
        (rows_total, rows_total, sync_id),
    )


def _field_diff_sql(field):
    """Build the per-field change-diff INSERT for one tracked column."""
    return (
        "INSERT INTO changes(sync_id, infohash, change_type, field, old_value, new_value, ts) "
        "SELECT ?, s.infohash, 'updated', ?, "
        "CAST(t." + field + " AS TEXT), CAST(s." + field + " AS TEXT), ? "
        "FROM staging s JOIN torrents t ON s.infohash = t.infohash "
        "WHERE s." + field + " IS NOT t." + field
    )


def ingest_diff(conn, sync_id, now, rows_total):
    """Subsequent sync: diff staging vs torrents, log changes, UPSERT."""
    cur = conn.cursor()
    # New torrents -> one JSON row each.
    cur.execute(
        "INSERT INTO changes(sync_id, infohash, change_type, field, old_value, new_value, ts) "
        "SELECT ?, s.infohash, 'new', NULL, NULL, "
        "json_object('name', s.name, 'size_bytes', s.size_bytes, 'created_unix', s.created_unix, "
        "'seeders', s.seeders, 'leechers', s.leechers, 'completed', s.completed, "
        "'scraped_date', s.scraped_date, 'published', s.published), ? "
        "FROM staging s LEFT JOIN torrents t ON s.infohash = t.infohash "
        "WHERE t.infohash IS NULL",
        (sync_id, now),
    )
    rows_new = cur.rowcount
    # Updated torrents -> one scalar row per changed field.
    for field in TRACKED_FIELDS:
        cur.execute(_field_diff_sql(field), (sync_id, field, now))
    # Count distinct updated infohashes.
    cur.execute(
        "SELECT COUNT(DISTINCT infohash) FROM changes "
        "WHERE sync_id=? AND change_type='updated'", (sync_id,)
    )
    rows_updated = cur.fetchone()[0]
    # UPSERT: update changed rows (bump last_updated_local; refresh magnet too,
    # since magnet is derived from name which may have changed), then insert new.
    set_clause = ", ".join(f"{f}=s.{f}" for f in TRACKED_FIELDS) + ", magnet=s.magnet"
    where_diff = " OR ".join(f"torrents.{f} IS NOT s.{f}" for f in TRACKED_FIELDS)
    cur.execute(
        "UPDATE torrents SET " + set_clause + ", last_updated_local=? "
        "FROM staging s WHERE torrents.infohash = s.infohash AND (" + where_diff + ")",
        (now,),
    )
    cur.execute(
        "INSERT INTO torrents (infohash, name, size_bytes, created_unix, seeders, "
        "leechers, completed, scraped_date, published, magnet, first_seen_local, last_updated_local) "
        "SELECT s.infohash, s.name, s.size_bytes, s.created_unix, s.seeders, s.leechers, "
        "s.completed, s.scraped_date, s.published, s.magnet, ?, ? "
        "FROM staging s LEFT JOIN torrents t ON s.infohash = t.infohash WHERE t.infohash IS NULL",
        (now, now),
    )
    rows_unchanged = rows_total - rows_new - rows_updated
    cur.execute(
        "UPDATE syncs SET rows_total=?, rows_new=?, rows_updated=?, rows_unchanged=? "
        "WHERE sync_id=?",
        (rows_total, rows_new, rows_updated, rows_unchanged, sync_id),
    )
    logging.info("diff: new=%d updated=%d unchanged=%d",
                 rows_new, rows_updated, rows_unchanged)


def main():
    init_logging()
    ensure_dirs()
    now = int(time.time())
    started = now
    conn = sqlite3.connect(DB_PATH)
    try:
        ensure_schema(conn)
        set_pragmas(conn)
        cur = conn.cursor()
        cur.execute("INSERT INTO syncs(started_at, status) VALUES (?, 'running')", (started,))
        sync_id = cur.lastrowid
        conn.commit()
        try:
            status, etag, lastmod, size, tmp = fetch()
            if status == 304:
                cur.execute(
                    "UPDATE syncs SET finished_at=?, status='no-change', bytes_downloaded=0, "
                    "upstream_etag=?, upstream_lastmod=?, note='etag match, not downloaded' "
                    "WHERE sync_id=?",
                    (int(time.time()), etag, lastmod, sync_id),
                )
                conn.commit()
                logging.info("no-change (HTTP 304); nothing to do")
                return 0
            sha = sha256_file(tmp)
            last_sha = SHA_PATH.read_text().strip() if SHA_PATH.exists() else ""
            if last_sha and sha == last_sha:
                CSV_TMP.replace(CSV_PATH)
                cur.execute(
                    "UPDATE syncs SET finished_at=?, status='no-change', bytes_downloaded=?, "
                    "upstream_sha256=?, upstream_etag=?, upstream_lastmod=?, "
                    "note='sha256 match, not ingested' WHERE sync_id=?",
                    (int(time.time()), size, sha, etag, lastmod, sync_id),
                )
                conn.commit()
                logging.info("downloaded %d bytes but sha256 unchanged; not ingested", size)
                return 0
            # Real change: move file into place and ingest.
            CSV_TMP.replace(CSV_PATH)
            try:
                rows_total = load_staging(conn)
                cur.execute(
                    "SELECT COUNT(*) FROM torrents WHERE infohash IS NOT NULL"
                )
                pre = cur.fetchone()[0]
                if pre == 0:
                    ingest_bootstrap(conn, sync_id, int(time.time()), rows_total)
                else:
                    ingest_diff(conn, sync_id, int(time.time()), rows_total)
                ETAG_PATH.write_text(etag)
                SHA_PATH.write_text(sha)
                cur.execute(
                    "UPDATE syncs SET finished_at=?, status='ok', bytes_downloaded=?, "
                    "upstream_sha256=?, upstream_etag=?, upstream_lastmod=? WHERE sync_id=?",
                    (int(time.time()), size, sha, etag, lastmod, sync_id),
                )
                conn.commit()
                logging.info("sync ok (rows_total=%d)", rows_total)
            except Exception:
                conn.rollback()
                # The 'running' syncs row is already committed; mark it failed.
                cur.execute(
                    "UPDATE syncs SET finished_at=?, status='failed', bytes_downloaded=?, "
                    "upstream_sha256=?, upstream_etag=?, note=? WHERE sync_id=?",
                    (int(time.time()), size, sha, etag, "ingest error", sync_id),
                )
                conn.commit()
                raise
        except Exception as e:
            cur.execute(
                "UPDATE syncs SET finished_at=?, status='failed', note=? WHERE sync_id=?",
                (int(time.time()), ("fetch error: " + str(e))[:500], sync_id),
            )
            conn.commit()
            logging.exception("sync failed")
            return 1
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
