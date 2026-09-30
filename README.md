# plasma-wallpaper-collage

*[Leia em português](README.pt-BR.md)*

Per-monitor wallpaper **collages for KDE Plasma 6**, built from Reddit,
wallhaven or any image source you plug in. Meant to run unattended (cron or a
systemd timer): every run gives each screen a fresh mosaic.

> Formerly `redditWallpaper`. Configuration keys and log messages are in
> Portuguese; this README explains each of them.

## Features

- **Sources**
  - **Reddit**: one or several subreddits (`wallpaper+MinimalWallpaper`),
    `hot`/`new`/`top`/`rising`/`controversial` sorting, galleries and
    pagination.
  - **wallhaven**: build a search on the site and paste its URL. Every filter
    (categories, purity, resolution, ratio, color, sorting, query) is passed to
    the API. An API key unlocks NSFW results, which are saved in a separate
    `nsfw/` folder.
  - **Extra sources**: drop a small `.py` file in the config folder to add any
    site. A Bing "image of the day" example is included.
- **Collages**
  - One collage per monitor, detected automatically via `/sys/class/drm`.
  - 1, 2, 3, 4, 6 or 9 images per collage, at any resolution, saved as
    jpg/png/webp.
  - Each image is shown whole, over a blurred copy of itself that fills the
    cell.
- **Cache**
  - Images are validated in memory before being written, so the cache never
    holds a half-written or broken file.
  - Only the newest N images are kept.
  - A 7-day history prevents re-downloading images that were rotated out,
    rejected by a filter, or deleted at the source.
- **Safe apply**
  - Wallpapers are set through Plasma's DBus scripting API.
  - If applying fails (for example, no Plasma session), the current collages
    are kept instead of leaving you with a black desktop.
- **Configuration**: one commented TOML file. Mistakes are reported with the
  section and key at fault.
- **Privacy**
  - Reddit cookies go only to the reddit.com feed request, never to image
    hosts.
  - The wallhaven key travels in a request header and never appears in logs.

## Requirements

- Linux with **KDE Plasma 6** (the `org.kde.image` wallpaper plugin and Qt 6's
  `qdbus`: package `qdbus-qt6` on Debian/Ubuntu, `qt6-tools` on Arch).
- Python 3.11+. On 3.13 or newer, rookiepy is compiled during the install (see
  [Installation](#installation)).
- For Reddit: a browser logged in to reddit.com. The cookies are read locally
  with [rookiepy](https://github.com/thewh1teagle/rookiepy); Reddit blocks
  anonymous clients.

## Installation

With [pipx](https://pipx.pypa.io):

```bash
pipx install git+https://github.com/jrazeponi/plasma-wallpaper-collage
mkdir -p ~/.config/plasma-wallpaper-collage
curl -o ~/.config/plasma-wallpaper-collage/config.toml \
  https://raw.githubusercontent.com/jrazeponi/plasma-wallpaper-collage/main/config.example.toml
```

Or from a clone, in a virtualenv:

```bash
git clone https://github.com/jrazeponi/plasma-wallpaper-collage.git
cd plasma-wallpaper-collage
python3 -m venv .venv
.venv/bin/pip install -e .          # -e: a `git pull` updates the installed command
mkdir -p ~/.config/plasma-wallpaper-collage
cp config.example.toml ~/.config/plasma-wallpaper-collage/config.toml
```

Python 3.13 or newer: rookiepy only ships wheels up to 3.12, so pip compiles
it during the install. That needs Rust (`cargo`) and
`PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1` in front of the install command:

```bash
PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 pipx install git+https://github.com/jrazeponi/plasma-wallpaper-collage
```

## Usage

```bash
plasma-wallpaper-collage                 # run the default profile (perfil_padrao)
plasma-wallpaper-collage sfw             # run a specific profile
plasma-wallpaper-collage --listar        # list sources and profiles
plasma-wallpaper-collage --sem-aplicar   # download and build collages, don't apply
plasma-wallpaper-collage -v              # debug output (URLs, rejections, each collage)
plasma-wallpaper-collage --config X.toml # use another config file
```

Exit codes:
- `0`: ok;
- `1`: no collage could be built or applied;
- `2`: configuration error or unknown profile.

## Configuration

The config file lives at `~/.config/plasma-wallpaper-collage/config.toml`
(`$XDG_CONFIG_HOME` is honored). [`config.example.toml`](config.example.toml)
documents every key. Any key missing from `[geral]`, `[cache]`, `[colagem]` or
`[wallhaven]` falls back to its default. Profiles exist only if defined in the
file.

| Section | Key | Default | Meaning |
|---|---|---|---|
| `[geral]` | `perfil_padrao` | `"sfw"` | profile used when none is given |
| | `pasta_wallpapers` | `"~/Wallpapers"` | each profile's cache defaults to `<this>/<profile>` (NSFW wallhaven searches: `<this>/nsfw/<profile>`) |
| | `pasta_temporaria` | `~/.cache/plasma-wallpaper-collage/tmp` | in-progress downloads (same disk as the cache) |
| | `navegador_cookies` | `"firefox"` | browser (or list, tried in order) to read Reddit cookies from |
| | `imitar_navegador` | `"firefox"` | TLS fingerprint to impersonate (`firefox`, `chrome`, `edge`, `safari`…) |
| | `timeout` / `downloads_paralelos` | `15` / `6` | seconds per request / parallel downloads |
| `[cache]` | `max_imagens` | `50` | images kept per cache folder |
| | `novas_por_execucao` | `20` | new images per run (`0` = only rebuild collages) |
| | `historico_dias` | `7` | days before a seen image may be downloaded again |
| `[colagem]` | `largura` / `altura` | `1920` / `1080` | collage size |
| | `imagens_por_colagem` | `4` | 1, 2, 3, 4, 6 or 9 |
| | `formato` / `qualidade` | `"jpg"` / `90` | `jpg`, `png` or `webp`; quality 1–100 |
| | `desfoque` | `18` | background blur radius (`0` = none) |
| | `ajuste_kde` | `"centralizar"` | KDE fill mode: `centralizar`, `cortar`, `ajustar`, `esticar`, `lado_a_lado` |
| | `monitores` / `monitores_fallback` | `0` / `3` | fixed collage count (`0` = detect) / count if detection fails |
| `[wallhaven]` | `chave_api` | `""` | wallhaven API key (see below) |

### Profiles

Each `[perfis.NAME]` table is a profile, run with
`plasma-wallpaper-collage NAME`.

- Common keys:
  - `fonte`: the source (required);
  - `cache`: cache folder (default `<pasta_wallpapers>/NAME`; for NSFW wallhaven
    searches see [NSFW search folder](#nsfw-search-folder));
  - `paginas`: pages read from the source;
  - `min_largura`: minimum image width in px (default 1920; `0` disables).
- Reddit keys:
  - `subreddit`: join several with `+`;
  - `sort`;
  - `top_time`: used with `top`/`controversial`.
  - NSFW posts are not filtered out: the subreddit you pick defines the content.
- wallhaven key:
  - `url`: a search URL copied from wallhaven.cc.
  - With a fixed sort (`views`, `favorites`) every run gets the same images.
    Use `sorting=random` or `sorting=toplist&topRange=1w` for variety.

```toml
[perfis.sfw]
fonte = "reddit"
subreddit = "wallpaper+MinimalWallpaper"

[perfis.nature]
fonte = "wallhaven"
url = "https://wallhaven.cc/search?q=nature&categories=100&purity=100&atleast=1920x1080&ratios=16x9&sorting=random"
```

Useful wallhaven query syntax:
- `+tag1 +tag2`: both tags;
- `-tag`: exclude a tag;
- `type:png`: only png files;
- `@user`: one user's uploads;
- `like:ID`: images similar to another one.

### wallhaven API key (NSFW)

The key is only needed for NSFW results, that is, when the last digit of
`purity=` in the URL is `1`, as in `purity=001` or `purity=111`. Without it the
search comes back empty and a warning is logged.

1. Create an account on [wallhaven.cc](https://wallhaven.cc).
2. Copy your key from **Settings → Account → API Key**
   (<https://wallhaven.cc/settings/account>).
3. Give it to the program in **one** of these ways:
   - the `WALLHAVEN_API_KEY` environment variable. It takes precedence over the
     file.
   - the config file, in which case protect the file with
     `chmod 600 ~/.config/plasma-wallpaper-collage/config.toml` (the program
     warns if others can read it):
     ```toml
     [wallhaven]
     chave_api = "your-key"
     ```

Cron does not load your shell profile. For cron, either use the config file or
load the variable in the cron line itself (see [Automation](#automation)).

### NSFW search folder

A wallhaven profile whose URL allows NSFW results needs no special name: it is
stored in `<pasta_wallpapers>/nsfw/NAME`. The test is the same one used for the
API key: the last digit of `purity=` is `1`, alone (`001`) or together with the
others (`011`, `101`, `111`).

- The whole profile goes there (images, history and collages), even for a mixed
  search like `purity=111`: a collage blends everything in the folder, so any
  image may be 18+.
- `sketchy` alone (`purity=010` or `110`) does not count.
- The profile named `nsfw` uses `<pasta_wallpapers>/nsfw` itself, not
  `nsfw/nsfw`.
- `cache` in the profile wins over all of this.
- Each profile keeps its own cache: two NSFW profiles never mix images.

```toml
[perfis.nsfwallhaven]
fonte = "wallhaven"
url = "https://wallhaven.cc/search?categories=111&purity=001&sorting=random"
# images end up in ~/Wallpapers/nsfw/nsfwallhaven
```

## Extra sources

Every `.py` file in `~/.config/plasma-wallpaper-collage/fontes/` is loaded at
startup and may register a new source:

```python
FONTE = "mysource"                 # used as fonte = "mysource" in profiles
PAGINAS = 1                        # optional: default for perfil.paginas
OPCOES = {"region": "en-US"}       # optional: extra profile keys → perfil.opcoes

def imagens(perfil, app):          # required: [[url, fallback_url, ...], ...]
    ...

def aceitar(img, perfil, app):     # optional: filter run after download
    return True                    # img is the decoded PIL image (downscaled)
```

`app` is the main module. Use `app.http` (a curl_cffi session with browser
impersonation), `app.cfg` for the settings and `app.logger`.

A complete, working example is
[`exemplos/fontes/bing.py`](exemplos/fontes/bing.py), which fetches Bing's
images of the day in 4K. Copy it to the `fontes/` folder and add:

```toml
[perfis.bing]
fonte = "bing"
mercado = "en-US"
```

A broken extra source is skipped with an error message; the rest keep working.

## Automation

Cron, every hour:

```cron
@hourly $HOME/.local/bin/plasma-wallpaper-collage >> $HOME/.cache/plasma-wallpaper-collage.log 2>&1
```

- With a virtualenv install, use `/path/to/.venv/bin/plasma-wallpaper-collage`
  instead.
- To pass the wallhaven key through the environment, start the line with
  `WALLHAVEN_API_KEY=... ` or `set -a; . /path/to/secrets.env; set +a;`.
- A systemd user timer works just as well.

## How it works

1. Fetch the image list from the profile's source.
2. Skip images already in the cache or in the history.
3. Download up to `novas_por_execucao` images in parallel. Each one is
   validated in memory (a real, complete image, wide enough, accepted by the
   source's filter) and only then written to the cache.
4. Trim the cache to `max_imagens`, dropping the oldest images first. Trimming
   happens after downloading, so a network failure never costs you images.
5. Pick images for each monitor without repeating them across monitors while
   possible, and build the collages.
6. Apply them through Qt 6's `qdbus`, one per screen. Old collages are deleted
   only after the new ones are applied.

## Troubleshooting

| Log message | Likely cause |
|---|---|
| `Erro ao buscar a lista de imagens (reddit): HTTP Error 403` | missing/expired Reddit cookies: open reddit.com logged in, in the browser set in `navegador_cookies` |
| `Nenhum cookie do Reddit encontrado` | wrong browser in `navegador_cookies`, or not logged in |
| `Sem chave da API do wallhaven` | NSFW search without a key |
| `chave da API recusada (401)` | wrong wallhaven key |
| `A fonte não devolveu nenhuma imagem` | empty search, site layout change, or blocked (403/429) |
| `apagada(s) na origem (404)` | normal: removed posts still listed in the feed |
| `qdbus do Qt 6 não encontrado` | Qt 6's qdbus is not installed (Debian/Ubuntu: package `qdbus-qt6`) |
| `Erro ao definir wallpaper via DBus` | no Plasma session (e.g. logged out); current collages are kept |
| `Configuração: ...` | config file error; the message names the section and key |

## License

[GPL-3.0-or-later](LICENSE). Copyright © 2026 José Roberto (jrazeponi).
