# redditWallpaper

A Python script that pulls wallpaper-worthy images from a subreddit, blends them into per-monitor collages, and sets them as your desktop background on **KDE Plasma**. Built to run unattended (e.g. via cron or a systemd timer) and refresh your desktop with a new mosaic each time.

## Features

- **Reddit feed scraping** — reads a subreddit's public `.json` feed (no API key required), supports `hot` / `new` / `top` sorting, and handles both single-image posts and galleries.
- **Anti-bot bypass** — uses [`curl_cffi`](https://github.com/lexiforest/curl_cffi) with browser TLS impersonation plus cookies read live from your browser (via [`rookiepy`](https://github.com/thewh1teagle/rookiepy)) to get past Reddit's fingerprint-based blocking.
- **Smart caching** — downloads images to a local cache folder, validates that each file is a real image, and prunes the oldest files once a size cap is reached.
- **Multi-monitor collages** — auto-detects the number of connected monitors via `/sys/class/drm`, and builds a separate 1–4 image collage (blurred-background + centered foreground per cell) for each one using Pillow.
- **KDE Plasma integration** — applies the generated collages per-screen through `qdbus-qt6` / Plasma's scripting API, and cleans up old collage files after they're applied.
- **Concurrent downloads** — fetches candidate images in parallel with a thread pool and stops as soon as it has enough successful downloads.

## Requirements

- Linux with **KDE Plasma** (uses `qdbus-qt6` and the `org.kde.image` wallpaper plugin — this script won't do anything useful on GNOME, XFCE, etc.)
- Python 3.9+
- A supported browser (Edge, Chrome, or Firefox) logged into reddit.com, since cookies are read from it at runtime
- Python packages:
  ```
  curl_cffi
  rookiepy
  Pillow
  ```

## Installation

```bash
git clone https://github.com/jrzeponi/redditWallpaper.git
cd redditWallpaper

python3 -m venv .venv
source .venv/bin/activate
pip install curl_cffi rookiepy Pillow
```

The script's shebang points at a venv (`.venv/bin/python`) — either adjust the first line to your own venv path, or just run it explicitly with `python3 wallpaper_sfw.py`.

## Configuration

All settings live as constants near the top of `wallpaper_sfw.py`:

| Variable | Description | Default |
|---|---|---|
| `SUBREDDIT` | Subreddit to pull images from | `TVWallpapersSFW` |
| `SORT` | `hot`, `new`, or `top` | `top` |
| `TOP_TIME` | Time window when `SORT == "top"` (`hour`/`day`/`week`/`month`/`year`/`all`) | `month` |
| `CACHE_DIR` | Where downloaded images are cached | `~/Wallpapers/sfw` |
| `MAX_CACHE` | Max images kept in cache before pruning | `50` |
| `BATCH_SIZE` | New images downloaded per run | `20` |
| `MIN_WIDTH` | Minimum image width accepted | `1920` |
| `COLLAGE_W`, `COLLAGE_H` | Collage canvas resolution | `1920x1080` |
| `NUM_MONITORS` | Fallback monitor count if auto-detection fails | `3` |
| `BROWSER` | Browser to read cookies from (`edge`, `chrome`, `firefox`, `any`) | `edge` |
| `IMPERSONATE` | TLS/browser fingerprint to impersonate | `edge` |

## Usage

Run it manually:

```bash
python3 wallpaper_sfw.py
```

Each run:
1. Prunes the cache if it's near `MAX_CACHE`.
2. Downloads up to `BATCH_SIZE` new images from the configured subreddit.
3. Detects your monitor count and builds one collage per screen from the cached images.
4. Applies each collage as that screen's wallpaper via Plasma's DBus interface.
5. Deletes collages that are no longer in use.

### Automating it

To refresh your wallpaper periodically, add a cron entry:

```cron
# every hour
0 * * * * /path/to/.venv/bin/python /path/to/wallpaper_sfw.py >> /path/to/wallpaper.log 2>&1
```

or a systemd user timer if you prefer that over cron.

## Notes & caveats

- Since the script relies on cookies read directly from your browser's cookie store, that browser must be installed and logged into reddit.com; otherwise the feed request is more likely to be blocked.
- Image collages use a blurred, scaled copy of the same photo as filler behind a centered, aspect-correct copy — so oddly-shaped source images still fill the whole cell without stretching.
- Only tested against KDE Plasma's DBus scripting interface; other desktop environments aren't supported out of the box.

## License

Licensed under the [MIT License](LICENSE).
