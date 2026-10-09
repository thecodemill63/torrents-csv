"""
qbt.py — minimal gateway to the local qBittorrent WebUI API.

Uses only Python stdlib (no `requests` dependency required).
Session cookie is reused across requests; re-login on 403/401.
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar

CONFIG_PATH = os.path.expanduser("~/.config/torrents-ui/qbt.json")

# Category -> save path. These are defaults used only when the config file
# is absent. The install script generates a proper config file with paths
# chosen by the user at install time.
DEFAULT_CONFIG = {
    "api_url": "http://localhost:8081",
    "username": "admin",
    "password": "",
    "categories": {
        "Movie": os.path.join(os.path.expanduser("~"), "Downloads", "Movies"),
        "TV Show": os.path.join(os.path.expanduser("~"), "Downloads", "TV"),
    },
}


def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
        # Merge defaults so missing keys don't crash.
        merged = dict(DEFAULT_CONFIG)
        merged.update(cfg)
        merged["categories"] = dict(DEFAULT_CONFIG["categories"], **cfg.get("categories", {}))
        return merged
    return DEFAULT_CONFIG


class QbtError(Exception):
    pass


class QbtClient:
    def __init__(self, cfg=None):
        self.cfg = cfg or load_config()
        self.base = self.cfg["api_url"].rstrip("/")
        self._cookies = CookieJar()
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self._cookies)
        )
        self._logged_in = False

    def _post(self, path, data):
        body = urllib.parse.urlencode(data).encode("utf-8")
        req = urllib.request.Request(self.base + path, data=body, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        try:
            return self._opener.open(req, timeout=15)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403) and not self._logged_in:
                self.login()
                return self._opener.open(req, timeout=15)
            raise QbtError(f"qBt {path} failed: HTTP {e.code} {e.reason}")

    def login(self):
        resp = self._opener.open(
            urllib.request.Request(
                self.base + "/api/v2/auth/login",
                data=urllib.parse.urlencode(
                    {"username": self.cfg["username"], "password": self.cfg["password"]}
                ).encode("utf-8"),
                method="POST",
            ),
            timeout=15,
        )
        if resp.status not in (200, 204):
            raise QbtError(f"qBt login failed: HTTP {resp.status}")
        self._logged_in = True

    def add_torrent(self, magnet, category, save_path=None):
        """Add a torrent by magnet URL, tagged with `category`, saved at the
        configured path for that category (or `save_path` if given).

        Returns the raw response text from qBittorrent.
        """
        if save_path is None:
            save_path = self.cfg["categories"].get(category, "")
        data = {"urls": magnet, "tags": category}
        if save_path:
            data["savepath"] = save_path
        if not self._logged_in:
            self.login()
        resp = self._post("/api/v2/torrents/add", data)
        return resp.read().decode().strip()
