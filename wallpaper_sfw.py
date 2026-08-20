#!/usr/bin/env python3

import random
import os
import hashlib
import html
import json
import logging
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
from pathlib import Path
from curl_cffi import requests as http
import rookiepy
from PIL import Image, ImageOps, ImageFilter

#import browser_cookie3
# CONFIG
SUBREDDIT = "TVWallpapersSFW"
SORT = "top"  # hot | new | top
# Só usado quando SORT == "top": hour | day | week | month | year | all
TOP_TIME = "month"
BASE_URL = f"https://www.reddit.com/r/{SUBREDDIT}/{SORT}.json"
CACHE_DIR = Path.home() / "Wallpapers/sfw"
COLLAGE_DIR = CACHE_DIR / "collage"
MAX_CACHE = 50
BATCH_SIZE = 20
MIN_WIDTH = 1920
COLLAGE_W, COLLAGE_H = 1920, 1080
NUM_MONITORS = 3  # fallback caso a detecção automática falhe

CACHE_DIR.mkdir(parents=True, exist_ok=True)
COLLAGE_DIR.mkdir(parents=True, exist_ok=True)

# Configuração básica de logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# O anti-bot do Reddit bloqueia clientes HTTP comuns (403 por fingerprint de
# TLS). Driblamos com curl_cffi (impersonate de Chrome) + os cookies do
# navegador já logado, lidos do disco em tempo de execução.
#IMPERSONATE = "chrome"
IMPERSONATE = "edge"
BROWSER = "edge"  # navegador de onde ler os cookies do reddit.com
#BROWSER = "firefox"  # navegador de onde ler os cookies do reddit.com
#BROWSER = "any"  # navegador de onde ler os cookies do reddit.com
_COOKIES = None


def reddit_cookies():
    """Lê os cookies do reddit.com do navegador usando rookiepy."""
    global _COOKIES
    if _COOKIES is None:
        try:
            cj = None
            # 1. Se escolher um navegador específico
            if BROWSER == "firefox":
                cj = rookiepy.firefox(domains=["reddit.com"])
            elif BROWSER == "chrome":
                cj = rookiepy.chrome(domains=["reddit.com"])
            elif BROWSER == "edge":
                cj = rookiepy.edge(domains=["reddit.com"])
            
            # 2. Se escolher "any", testa os principais um por um
            elif BROWSER == "any":
                for metodo_busca in [rookiepy.edge, rookiepy.chrome, rookiepy.firefox]:
                    try:
                        cj = metodo_busca(domains=["reddit.com"])
                        if cj:  # Se achou os cookies, interrompe o laço
                            break
                    except Exception:
                        continue

            # Processa os cookies se algum navegador funcionou
            if cj:
                _COOKIES = {c["name"]: c["value"] for c in cj}
                logger.info(f"{len(_COOKIES)} cookies do Reddit lidos com rookiepy do {BROWSER}.")
            else:
                logger.warning(f"Nenhum cookie encontrado para o navegador: {BROWSER}")
                _COOKIES = {}
                
        except Exception as e:
            logger.warning(f"Falha ao ler cookies com rookiepy do {BROWSER}: {e}")
            _COOKIES = {}
    return _COOKIES

# Layout do grid (colunas, linhas) conforme o número de imagens na colagem
LAYOUTS = {1: (1, 1), 2: (2, 1), 3: (3, 1), 4: (2, 2)}

IMG_EXTS = (".jpg", ".jpeg", ".png", ".webp")

# i.redd.it faz content-negotiation pelo Accept: sem este header ele devolve
# uma página HTML (200) em vez da imagem crua.
IMAGE_ACCEPT = "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"


def get_images():
    """
    Lê o feed JSON público do subreddit e devolve, para cada imagem, uma lista
    de URLs candidatas (link direto → preview), em ordem de preferência.
    Sem Selenium: o Reddit expõe tudo via .json (raw_json=1 evita &amp;).
    """
    params = {"limit": 100, "raw_json": 1}
    if SORT == "top":
        params["t"] = TOP_TIME

    try:
        r = http.get(BASE_URL, params=params,
                     headers={"Accept": "application/json"},
                     cookies=reddit_cookies(), impersonate=IMPERSONATE, timeout=15)
        r.raise_for_status()
        payload = r.json()
    except Exception as e:
        logger.error(f"Erro ao buscar o feed do Reddit: {e}")
        return []

    posts = payload.get("data", {}).get("children", [])
    seen = set()
    images = []

    def add(candidates):
        candidates = [c for c in candidates if c]
        if candidates and candidates[0] not in seen:
            seen.add(candidates[0])
            images.append(candidates)

    for child in posts:
        d = child.get("data", {})

        # Pula posts NSFW, fixados ou self-posts (sem imagem)
        if d.get("over_18") or d.get("stickied") or d.get("is_self"):
           continue

        # Galeria: cada imagem do post vira uma fonte de wallpaper separada
        if d.get("is_gallery") and isinstance(d.get("media_metadata"), dict):
            for meta in d["media_metadata"].values():
                if meta.get("e") != "Image" or meta.get("status") != "valid":
                    continue
                src = meta.get("s", {})
                if src.get("x", 0) and src["x"] < MIN_WIDTH:
                    continue
                if src.get("u"):
                    add([html.unescape(src["u"])])
            continue

        candidates = []

        # 1. Link direto da imagem (i.redd.it, imgur .jpg, etc.)
        direct = d.get("url_overridden_by_dest") or d.get("url") or ""
        if direct.split("?")[0].lower().endswith(IMG_EXTS):
            candidates.append(direct)

        # 2. Preview do Reddit como fallback
        prev_imgs = (d.get("preview") or {}).get("images") or []
        if prev_imgs:
            source = prev_imgs[0].get("source", {})
            # Descarta imagens pequenas demais para wallpaper
            if source.get("width", 0) and source["width"] < MIN_WIDTH:
                continue
            if source.get("url"):
                candidates.append(html.unescape(source["url"]))

        add(candidates)

    if not images:
        logger.warning("Nenhuma imagem encontrada — feed vazio ou bloqueado (403/429?).")
    logger.info(f"Encontradas {len(images)} imagens em r/{SUBREDDIT}.")
    return images


def download_image(candidates):
    for url in filter(None, candidates):
        try:
            name = hashlib.md5(url.encode(), usedforsecurity=False).hexdigest() + ".jpg"
            path = CACHE_DIR / name
            if path.exists():
                return str(path.absolute())

            r = http.get(url, headers={"Accept": IMAGE_ACCEPT},
                         cookies=reddit_cookies(), impersonate=IMPERSONATE, timeout=15)
            if r.status_code != 200:
                logger.debug(f"HTTP {r.status_code} para {url}, tentando fallback...")
                continue

            with open(path, "wb") as f:
                f.write(r.content)

            # Garante que baixamos uma imagem de verdade (e não uma página de erro)
            try:
                Image.open(path).verify()
            except Exception:
                logger.debug(f"Arquivo não é imagem válida: {url}")
                path.unlink(missing_ok=True)
                continue

            return str(path.absolute())
        except Exception as e:
            logger.error(f"Erro ao baixar {url}: {e}")
    return None


def cleanup_cache():
    files = sorted(CACHE_DIR.glob("*.jpg"), key=os.path.getmtime)

    # Mantém o cache abaixo do teto, abrindo espaço para o próximo batch
    excess = len(files) - (MAX_CACHE - BATCH_SIZE)
    if excess > 0:
        for f in files[:excess]:
            os.remove(f)
        logger.info(f"Cache cheio: {excess} imagem(ns) antiga(s) removida(s).")


def set_wallpapers(paths):
    """
    Define wallpapers diferentes para cada monitor no KDE Plasma.
    """
    # Converte a lista de caminhos para uma string JSON que o JS do Plasma entenda
    paths_json = json.dumps(paths)

    # 1ª passagem: garante que o plugin org.kde.image está carregado em todos os desktops
    js_load_plugin = """
    var desktopList = desktops();
    for (var i = 0; i < desktopList.length; i++) {
        desktopList[i].wallpaperPlugin = 'org.kde.image';
    }
    """

    # 2ª passagem: aplica a imagem usando d.screen para mapear ao monitor correto
    js_apply = f"""
    var paths = {paths_json};
    var desktopList = desktops();
    for (var i = 0; i < desktopList.length; i++) {{
        var d = desktopList[i];
        var idx = d.screen % paths.length;
        d.currentConfigGroup = ['Wallpaper', 'org.kde.image', 'General'];
        d.writeConfig('Image', 'file://' + paths[idx]);
        d.writeConfig('FillMode', 6);
    }}
    """

    uid = os.getuid()
    env = {**os.environ}
    if "DBUS_SESSION_BUS_ADDRESS" not in env:
        env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path=/run/user/{uid}/bus"

    def run_script(script):
        result = subprocess.run([
            "qdbus-qt6", "org.kde.plasmashell", "/PlasmaShell",
            "org.kde.PlasmaShell.evaluateScript", script
        ], check=True, capture_output=True, text=True, env=env)
        if result.stderr:
            logger.warning(f"qdbus stderr: {result.stderr.strip()}")

    try:
        run_script(js_load_plugin)   # carrega o plugin em todos os desktops
        time.sleep(1)                # aguarda o plugin inicializar
        run_script(js_apply)         # aplica as imagens por screen index
        logger.info("Wallpapers aplicados via DBus.")
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        logger.error(f"Erro ao definir wallpaper via DBus: {e}")


def get_num_monitors():
    # Lê direto do kernel — funciona sem sessão gráfica, X11 ou Wayland
    try:
        drm = Path("/sys/class/drm")
        n = sum(
            1 for status in drm.glob("*/status")
            if status.read_text().strip() == "connected"
        )
        if n > 0:
            logger.info(f"Monitores detectados via sysfs: {n}")
            return n
    except Exception as e:
        logger.warning(f"sysfs falhou: {e}")

    logger.warning(f"Usando fallback NUM_MONITORS={NUM_MONITORS}")
    return NUM_MONITORS


def make_cell(img_path, cell_w, cell_h):
    img = ImageOps.exif_transpose(Image.open(img_path)).convert("RGB")

    # Fundo: a mesma imagem escalada para preencher a célula + blur
    bg = ImageOps.fit(img, (cell_w, cell_h), method=Image.LANCZOS)
    bg = bg.filter(ImageFilter.GaussianBlur(radius=18))

    # Frente: escala proporcional para caber dentro da célula
    ratio = min(cell_w / img.width, cell_h / img.height)
    fg_w = int(img.width * ratio)
    fg_h = int(img.height * ratio)
    fg = img.resize((fg_w, fg_h), Image.LANCZOS)

    # Cola centralizado sobre o fundo borrado
    x = (cell_w - fg_w) // 2
    y = (cell_h - fg_h) // 2
    bg.paste(fg, (x, y))
    return bg


def make_collage(images, out_path):
    images = images[:4]
    cols, rows = LAYOUTS.get(len(images), (2, 2))
    cell_w, cell_h = COLLAGE_W // cols, COLLAGE_H // rows
    canvas = Image.new("RGB", (COLLAGE_W, COLLAGE_H))
    for i, img_path in enumerate(images):
        col, row = i % cols, i // cols
        try:
            cell = make_cell(img_path, cell_w, cell_h)
            canvas.paste(cell, (col * cell_w, row * cell_h))
        except Exception as e:
            logger.warning(f"Erro ao processar célula {img_path}: {e}")
    canvas.save(out_path, "JPEG", quality=90)
    return out_path


def main():
    # 1. Limpa o cache se cheio, abrindo espaço para o novo batch
    cleanup_cache()

    # 2. Busca e baixa até BATCH_SIZE novas imagens
    imgs = get_images()
    if imgs:
        random.shuffle(imgs)
        # Tenta mais candidatos que o BATCH_SIZE: alguns falham (HTTP/validação)
        candidates_pool = imgs[:BATCH_SIZE * 2]
        downloaded = 0
        pool = ThreadPoolExecutor(max_workers=6)
        try:
            futures = [pool.submit(download_image, c) for c in candidates_pool]
            for fut in as_completed(futures):
                if fut.result():
                    downloaded += 1
                if downloaded >= BATCH_SIZE:
                    break
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        logger.info(f"{downloaded} novas imagens baixadas.")

    # 3. Gera colagens — uma por monitor
    all_files = list(CACHE_DIR.glob("*.jpg"))

    if not all_files:
        logger.error("Nenhuma imagem disponível no cache para definir como wallpaper.")
        return

    num_monitors = get_num_monitors()
    ts = int(time.time())  # timestamp garante nome único — força KDE a detectar arquivo novo
    collage_paths = []
    pool = all_files.copy()  # consumido conforme as fotos vão sendo usadas
    for i in range(num_monitors):
        needed = min(4, len(pool))
        if needed == 0:
            logger.warning("Pool esgotado, reciclando imagens já usadas.")
            pool = all_files.copy()
            needed = min(4, len(pool))
    
        sample = random.sample(pool, needed)
        pool = [f for f in pool if f not in sample]  # remove as usadas do pool
    
        out = COLLAGE_DIR / f"collage_{i}_{ts}.jpg"
        try:
            make_collage(sample, out)
            collage_paths.append(str(out.absolute()))
            logger.info(f"Colagem {i} gerada: {out.name}")
        except Exception as e:
            logger.error(f"Erro ao gerar colagem {i}: {e}")

    if not collage_paths:
        logger.error("Nenhuma colagem gerada.")
        return

    set_wallpapers(collage_paths)

    # Remove colagens antigas APÓS aplicar — evita que KDE acesse arquivo deletado
    for old in COLLAGE_DIR.glob("*.jpg"):
        if str(old.absolute()) not in collage_paths:
            old.unlink()

    logger.info(f"{len(collage_paths)}/{num_monitors} colagem(ns) aplicada(s) com {len(all_files)} imagens no pool.")


if __name__ == "__main__":
    main()
