# torrents-csv

A self-hosted torrent search UI backed by [heretic/torrents-csv-data](https://codeberg.org/heretic/torrents-csv-data) — a community-maintained CSV of ~1.1M torrents with live seeder/leecher counts, refreshed daily.

## What it does

- **Syncs** the upstream `torrents.csv` (175 MB, ~1.1M torrents) into a local SQLite database
- **Searches** by name with sortable columns (seeders, leechers, size, date) and pagination
- **Downloads** torrents directly to qBittorrent with category tagging (Movie / TV Show)
- **Organises** TV downloads into show/season folder structures with an interactive picker
- **Tracks** every download in a history view with one-click re-download and magnet copy
- **Updates** automatically via a systemd timer (daily, ETag-aware — skips unchanged days)

## Requirements

- **Linux** or **macOS**
- **Python 3.10+** (stdlib only — no pip packages needed for the sync pipeline)
- **Django 5.x** (installed automatically by the installer)
- **qBittorrent** with WebUI enabled (for the download feature)
- **systemd** (Linux) or **launchd** (mac) for scheduled syncs

## Quick install

```bash
git clone https://github.com/thecodemill63/torrents-csv.git
cd torrents-csv
bash install.sh
```

The installer walks you through everything interactively — paths, ports, qBittorrent credentials. No manual config editing required.

## Architecture

```
torrents-csv/
├── bin/
│   └── sync.py              Sync pipeline: fetch CSV → SQLite UPSERT + change log
├── ui/
│   ├── manage.py             Django entrypoint
│   ├── shell.nix             Nix shell with Django (optional, NixOS only)
│   ├── start.sh              Launch script (wraps Django runserver)
│   ├── torrentsearch/        Django project (settings, urls, wsgi)
│   └── torrents/             The app
│       ├── models.py         Read-only Torrent model (managed=False)
│       ├── views.py          Search + download + history + folder picker endpoints
│       ├── qbt.py            qBittorrent WebUI API gateway (stdlib urllib)
│       ├── templatetags/     Custom filters (relative time, short date)
│       └── templates/        Dark-themed UI with inline CSS (no framework)
├── install.sh                Interactive cross-platform installer
└── README.md
```

## How the sync works

1. Conditional GET on upstream `torrents.csv` using `If-None-Match` (ETag) — unchanged days cost zero bandwidth.
2. SHA256 double-check against last ingested file.
3. Bulk-load CSV into a temp staging table.
4. First run: straight bulk insert. Subsequent runs: diff against existing rows, append changes to a `changes` table, UPSERT (UPDATE changed + INSERT new).
5. Every run recorded in a `syncs` table with status, row counts, and upstream metadata.

## Configuration

All config lives in environment variables (set by the installer in the systemd/launchd service file):

| Variable | Default | Purpose |
|----------|---------|---------|
| `TORRENTS_CSV_DIR` | `~/torrents-csv` | Root dir for DB, downloads, state, logs |
| `TORRENTS_TV_ROOT` | `~/media/TV` | TV shows root for the folder picker |
| `TORRENTS_UI_PORT` | `8888` | Port for the Django dev server |
| `DJANGO_SECRET_KEY` | (auto-generated) | Django secret key |

qBittorrent config lives in `~/.config/torrents-ui/qbt.json` (created by the installer).

## Data sources

- **Upstream data**: [heretic/torrents-csv-data](https://codeberg.org/heretic/torrents-csv-data) on Codeberg (actively updated, ~1.1M torrents, refreshed every few days)
- **No scraping**: the pipeline downloads a static CSV file, not a scraper — it doesn't break when torrent sites change their markup

## License

MIT