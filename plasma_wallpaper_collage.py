#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 José Roberto (jrazeponi)
"""
plasma-wallpaper-collage — troca o wallpaper do KDE Plasma 6 por colagens (uma
por monitor) montadas com imagens de subreddits, de buscas do wallhaven ou de
fontes extras escritas por você.

Uso:
    plasma-wallpaper-collage [PERFIL] [--sem-aplicar] [-v] [--config ARQ] [--listar]

Configuração em ~/.config/plasma-wallpaper-collage/config.toml (modelo em
config.example.toml). Chave ausente no arquivo usa o padrão da classe Config
abaixo; perfis só existem se estiverem no arquivo. Fontes extras: arquivos .py
em ~/.config/plasma-wallpaper-collage/fontes/ (ver carregar_fontes_extras).
"""

import argparse
import hashlib
import html
import importlib.util
import io
import json
import logging
import os
import random
import shutil
import subprocess
import sys
import threading
import time
import tomllib
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import rookiepy
from curl_cffi import requests as http
from PIL import Image, ImageFilter, ImageOps

__version__ = "1.0.1"
APP = "plasma-wallpaper-collage"
PASTA_CONFIG = Path(os.environ.get("XDG_CONFIG_HOME") or "~/.config").expanduser() / APP
PASTA_CACHE = Path(os.environ.get("XDG_CACHE_HOME") or "~/.cache").expanduser() / APP
CONFIG_PADRAO = PASTA_CONFIG / "config.toml"


@dataclass(frozen=True)
class Perfil:
    fonte: str                  # "reddit", "wallhaven" ou uma fonte extra
    cache: Path                 # pasta das imagens baixadas (colagens em cache/collage)
    subreddit: str = ""         # reddit ("a+b" junta vários)
    sort: str = "hot"           # reddit: hot | new | top | rising | controversial
    top_time: str = "day"       # reddit, com top/controversial: hour ... all
    url: str = ""               # wallhaven: URL de busca do site; livre para fontes extras
    paginas: int = 1            # páginas lidas da fonte (padrão por fonte: PAGINAS_PADRAO)
    min_largura: int = 1920     # descarta imagens mais estreitas (0 desliga)
    opcoes: dict = field(default_factory=dict)  # chaves extras declaradas pela fonte (OPCOES)


@dataclass(frozen=True)
class Config:
    """Valores padrão das chaves do config.toml (ver SECOES)."""
    perfil_padrao: str = "sfw"
    pasta_wallpapers: Path = Path.home() / "Wallpapers"
    # Downloads ficam aqui até serem validados. Precisa estar no mesmo sistema de
    # arquivos do cache para o os.replace() ser atômico; se não estiver, usa o cache.
    pasta_temporaria: Path = PASTA_CACHE / "tmp"
    navegador_cookies: tuple = ("firefox",)
    imitar_navegador: str = "firefox"
    timeout: int = 15
    downloads_paralelos: int = 6
    max_imagens: int = 50
    novas_por_execucao: int = 20
    # Imagem já baixada (ou rejeitada/apagada) não é baixada de novo por esse
    # tempo — sem isso, o que sai do cache e continua no feed volta a cada execução.
    historico_dias: int = 7
    largura: int = 1920
    altura: int = 1080
    imagens_por_colagem: int = 4
    formato: str = "jpg"
    qualidade: int = 90
    desfoque: int = 18
    ajuste_kde: str = "centralizar"
    monitores: int = 0          # 0 = detectar
    monitores_fallback: int = 3
    wallhaven_chave_api: str = ""
    perfis: dict = field(default_factory=dict)


# Seção do config.toml → chaves. Nas seções gerais a chave é o próprio campo de
# Config; nas de fonte, o campo leva a seção como prefixo
# ([wallhaven] chave_api → wallhaven_chave_api).
SECOES = {
    "geral": ("perfil_padrao", "pasta_wallpapers", "pasta_temporaria", "navegador_cookies",
              "imitar_navegador", "timeout", "downloads_paralelos"),
    "cache": ("max_imagens", "novas_por_execucao", "historico_dias"),
    "colagem": ("largura", "altura", "imagens_por_colagem", "formato", "qualidade",
                "desfoque", "ajuste_kde", "monitores", "monitores_fallback"),
    "wallhaven": ("chave_api",),
}


def campo_config(secao, chave):
    return chave if secao in ("geral", "cache", "colagem") else f"{secao}_{chave}"


cfg = Config()  # substituída em main() pela configuração lida do arquivo

PAGINAS_PADRAO = {"reddit": 1, "wallhaven": 3}
OPCOES_FONTE = {}   # fonte extra → {chave extra do perfil: valor padrão}
FILTROS = {}        # fonte extra → aceitar(img, perfil)
SORTS_REDDIT = ("hot", "new", "top", "rising", "controversial")
PERIODOS_REDDIT = ("hour", "day", "week", "month", "year", "all")
NAVEGADORES_COOKIES = ("firefox", "chrome", "chromium", "edge", "brave", "opera",
                       "opera_gx", "vivaldi", "librewolf", "arc")
FORMATOS = {"jpg": "JPEG", "png": "PNG", "webp": "WEBP"}
# FillMode do plugin org.kde.image
AJUSTES_KDE = {"centralizar": 6, "cortar": 2, "ajustar": 1, "esticar": 0, "lado_a_lado": 3}
# O qdbus do Qt 6 muda de nome conforme a distro: qdbus6 (Arch, Debian 13+,
# Ubuntu 25.04+), qdbus-qt6 (Fedora) ou só /usr/lib/qt6/bin/qdbus, fora do PATH
# (Debian/Ubuntu mais antigos). O qdbus puro vem por último: mesmo o do Qt 5 serve.
QDBUS = ("qdbus6", "qdbus-qt6", "/usr/lib/qt6/bin/qdbus", "qdbus")
# Layout do grid (colunas, linhas) conforme o número de imagens na colagem
LAYOUTS = {1: (1, 1), 2: (2, 1), 3: (3, 1), 4: (2, 2), 6: (3, 2), 9: (3, 3)}

WALLHAVEN_API = "https://wallhaven.cc/api/v1/search"
IMG_EXTS = (".jpg", ".jpeg", ".png", ".webp")

# i.redd.it faz content-negotiation pelo Accept: sem este header ele devolve
# uma página HTML (200) em vez da imagem crua.
IMAGE_ACCEPT = "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"

logger = logging.getLogger(APP)


# ── Configuração ─────────────────────────────────────────────────────────────

class ErroConfig(Exception):
    pass


def converter(valor, padrao, onde):
    """Confere o tipo do valor lido do TOML contra o valor padrão do campo."""
    if isinstance(padrao, Path):
        caminho = Path(valor).expanduser() if isinstance(valor, str) else None
        if caminho is None or not caminho.is_absolute():
            raise ErroConfig(f"{onde}: use um caminho absoluto ou começando com ~")
        return caminho
    if isinstance(padrao, tuple):   # navegador_cookies: um nome ou uma lista
        lista = [valor] if isinstance(valor, str) else valor
        if not (isinstance(lista, list) and lista and all(isinstance(v, str) for v in lista)):
            raise ErroConfig(f"{onde}: use um texto ou uma lista de textos")
        return tuple(lista)
    if isinstance(padrao, float) and isinstance(valor, int) and not isinstance(valor, bool):
        return float(valor)
    if type(valor) is not type(padrao):   # compara o tipo exato: bool não vale como int
        raise ErroConfig(f"{onde}: esperado {type(padrao).__name__}, veio {valor!r}")
    return valor


def carregar_perfil(nome, tabela, base):
    onde = f"[perfis.{nome}]"
    if not isinstance(tabela, dict):
        raise ErroConfig(f"{onde} precisa ser uma tabela")
    fonte = tabela.get("fonte")
    if fonte not in FONTES:
        raise ErroConfig(f"{onde} fonte deve ser uma de: {', '.join(FONTES)}")
    extras = OPCOES_FONTE.get(fonte, {})
    campos = {f.name for f in fields(Perfil)} - {"opcoes"}
    if desconhecidas := set(tabela) - campos - set(extras):
        raise ErroConfig(f"{onde} chave desconhecida: {', '.join(sorted(desconhecidas))}")

    padrao = Perfil(fonte=fonte, cache=base.pasta_wallpapers / nome,
                    paginas=PAGINAS_PADRAO.get(fonte, 1))
    p = replace(padrao,
                **{k: converter(v, getattr(padrao, k), f"{onde} {k}")
                   for k, v in tabela.items() if k in campos},
                opcoes={k: converter(tabela.get(k, d), d, f"{onde} {k}")
                        for k, d in extras.items()})
    checagens = [
        (fonte != "reddit" or p.subreddit, "subreddit é obrigatório para a fonte reddit"),
        (fonte != "wallhaven" or p.url, "url é obrigatória para a fonte wallhaven"),
        (p.sort in SORTS_REDDIT, f"sort deve ser um de: {', '.join(SORTS_REDDIT)}"),
        (p.top_time in PERIODOS_REDDIT, f"top_time deve ser um de: {', '.join(PERIODOS_REDDIT)}"),
        (p.paginas >= 1, "paginas deve ser >= 1"),
        (p.min_largura >= 0, "min_largura não pode ser negativa"),
    ]
    for ok, msg in checagens:
        if not ok:
            raise ErroConfig(f"{onde} {msg}")
    return p


def carregar_config(caminho):
    try:
        with open(caminho, "rb") as f:
            doc = tomllib.load(f)
    except FileNotFoundError:
        raise ErroConfig(f"arquivo não encontrado: {caminho} "
                         f"(copie o config.example.toml do projeto para lá)") from None
    except tomllib.TOMLDecodeError as e:
        raise ErroConfig(f"{caminho}: {e}") from None

    if desconhecidas := set(doc) - set(SECOES) - {"perfis"}:
        raise ErroConfig(f"seção desconhecida: {', '.join(f'[{s}]' for s in sorted(desconhecidas))}")
    padrao, valores = Config(), {}
    for secao, chaves in SECOES.items():
        tabela = doc.get(secao, {})
        if desconhecidas := set(tabela) - set(chaves):
            raise ErroConfig(f"[{secao}] chave desconhecida: {', '.join(sorted(desconhecidas))}")
        for k, v in tabela.items():
            nome = campo_config(secao, k)
            valores[nome] = converter(v, getattr(padrao, nome), f"[{secao}] {k}")
    c = replace(padrao, **valores)
    c = replace(c, perfis={nome: carregar_perfil(nome, t, c)
                           for nome, t in doc.get("perfis", {}).items()})

    checagens = [
        (c.perfis, "nenhum perfil definido (tabelas [perfis.NOME])"),
        (c.perfil_padrao in c.perfis, f"[geral] perfil_padrao '{c.perfil_padrao}' não existe em [perfis]"),
        (all(n in NAVEGADORES_COOKIES for n in c.navegador_cookies),
         f"[geral] navegador_cookies aceita: {', '.join(NAVEGADORES_COOKIES)}"),
        (c.timeout > 0 and c.downloads_paralelos > 0,
         "[geral] timeout e downloads_paralelos devem ser > 0"),
        (c.max_imagens > 0, "[cache] max_imagens deve ser > 0"),
        (c.novas_por_execucao >= 0 and c.historico_dias >= 0,
         "[cache] novas_por_execucao e historico_dias não podem ser negativos"),
        (c.largura > 0 and c.altura > 0, "[colagem] largura e altura devem ser > 0"),
        (c.imagens_por_colagem in LAYOUTS,
         f"[colagem] imagens_por_colagem deve ser um de: {', '.join(map(str, LAYOUTS))}"),
        (c.formato in FORMATOS, f"[colagem] formato deve ser um de: {', '.join(FORMATOS)}"),
        (1 <= c.qualidade <= 100, "[colagem] qualidade vai de 1 a 100"),
        (c.desfoque >= 0, "[colagem] desfoque não pode ser negativo"),
        (c.ajuste_kde in AJUSTES_KDE, f"[colagem] ajuste_kde deve ser um de: {', '.join(AJUSTES_KDE)}"),
        (c.monitores >= 0 and c.monitores_fallback > 0,
         "[colagem] monitores deve ser >= 0 e monitores_fallback > 0"),
    ]
    for ok, msg in checagens:
        if not ok:
            raise ErroConfig(msg)
    if c.wallhaven_chave_api and caminho.stat().st_mode & 0o077:
        logger.warning(f"{caminho} guarda a chave da API do wallhaven e pode ser lido por "
                       f"outros usuários: rode chmod 600 {caminho}")
    return c


# ── Fontes ───────────────────────────────────────────────────────────────────

# O anti-bot do Reddit bloqueia clientes HTTP comuns (403 por fingerprint de
# TLS). Driblamos com curl_cffi imitando o navegador + os cookies do navegador
# já logado, lidos do disco em tempo de execução. Os cookies vão SÓ no pedido
# do feed: o curl_cffi manda cookies passados por parâmetro para qualquer host,
# e os links de imagem podem apontar para servidores de terceiros.
def reddit_cookies():
    """Lê os cookies do reddit.com dos navegadores configurados, na ordem."""
    for nome in cfg.navegador_cookies:
        try:
            cj = getattr(rookiepy, nome)(domains=["reddit.com"])
        except Exception as e:
            logger.warning(f"Falha ao ler cookies do {nome}: {e}")
            continue
        if cj:
            logger.info(f"{len(cj)} cookies do Reddit lidos do {nome}.")
            return {c["name"]: c["value"] for c in cj}
    logger.warning(f"Nenhum cookie do Reddit encontrado ({', '.join(cfg.navegador_cookies)}).")
    return {}


def imagens_reddit(perfil):
    """
    Lê o feed JSON do subreddit e devolve, para cada imagem, a lista de URLs
    candidatas (link direto → preview), em ordem de preferência.
    """
    url = f"https://www.reddit.com/r/{perfil.subreddit}/{perfil.sort}.json"
    params = {"limit": 100, "raw_json": 1}   # raw_json=1 evita &amp; nas URLs
    if perfil.sort in ("top", "controversial"):
        params["t"] = perfil.top_time

    posts = []
    with http.Session(impersonate=cfg.imitar_navegador) as s:
        cookies = reddit_cookies()
        for pagina in range(perfil.paginas):
            try:
                r = s.get(url, params=params, headers={"Accept": "application/json"},
                          cookies=cookies, timeout=cfg.timeout)
                r.raise_for_status()
                dados = r.json().get("data", {})
            except Exception as e:
                if pagina == 0:
                    raise
                logger.warning(f"reddit: falha na página {pagina + 1}, seguindo com "
                               f"{len(posts)} posts: {resumo_erro(e)}")
                break
            posts += dados.get("children", [])
            params["after"] = dados.get("after")
            if not params["after"]:
                break

    imagens = []
    for child in posts:
        d = child.get("data", {})

        # Galeria: cada imagem do post vira uma fonte de wallpaper separada
        if d.get("is_gallery") and isinstance(d.get("media_metadata"), dict):
            for meta in d["media_metadata"].values():
                src = meta.get("s", {})
                if meta.get("e") != "Image" or meta.get("status") != "valid":
                    continue
                if src.get("x") and src["x"] < perfil.min_largura:
                    continue
                if src.get("u"):
                    imagens.append([html.unescape(src["u"])])
            continue

        candidatos = []

        # 1. Link direto da imagem (i.redd.it, imgur .jpg etc.)
        direto = d.get("url_overridden_by_dest") or d.get("url") or ""
        if direto.split("?")[0].lower().endswith(IMG_EXTS):
            candidatos.append(direto)

        # 2. Preview do Reddit como fallback
        previews = (d.get("preview") or {}).get("images") or []
        if previews:
            source = previews[0].get("source", {})
            if source.get("width") and source["width"] < perfil.min_largura:
                continue   # pequena demais para wallpaper
            if source.get("url"):
                candidatos.append(html.unescape(source["url"]))

        if candidatos:
            imagens.append(candidatos)
    return imagens


def imagens_wallhaven(perfil):
    """
    Repassa os filtros da URL de busca do site para a API e lê perfil.paginas
    páginas a partir da página da URL (ou da 1ª). Limite da API: 45 pedidos/min.
    """
    params = dict(parse_qsl(urlsplit(perfil.url).query))
    chave = os.environ.get("WALLHAVEN_API_KEY") or cfg.wallhaven_chave_api
    if not chave and params.get("purity", "100").endswith("1"):
        logger.warning("Sem chave da API do wallhaven (WALLHAVEN_API_KEY ou [wallhaven] "
                       "chave_api): a API não devolve conteúdo NSFW sem ela.")
    # A chave vai no header, não na URL, para não aparecer em mensagem de erro/log
    headers = {"X-API-Key": chave} if chave else {}

    imagens = []
    primeira = int(params.get("page", 1))
    with http.Session(impersonate=cfg.imitar_navegador) as s:
        for pagina in range(primeira, primeira + perfil.paginas):
            params["page"] = pagina
            try:
                r = s.get(WALLHAVEN_API, params=params, headers=headers, timeout=cfg.timeout)
                if r.status_code == 401:
                    raise RuntimeError("chave da API recusada (401): confira WALLHAVEN_API_KEY "
                                       "ou [wallhaven] chave_api")
                r.raise_for_status()
                j = r.json()
            except Exception as e:
                if pagina == primeira:
                    raise
                logger.warning(f"wallhaven: falha na página {pagina}, seguindo com "
                               f"{len(imagens)} imagens: {resumo_erro(e)}")
                break
            imagens += [[d["path"]] for d in j.get("data", [])
                        if d.get("path") and d.get("dimension_x", 0) >= perfil.min_largura]
            meta = j.get("meta") or {}
            if meta.get("seed"):
                params["seed"] = meta["seed"]   # sorting=random: mesma sequência entre páginas
            if pagina >= meta.get("last_page", pagina):
                break
    return imagens


FONTES = {"reddit": imagens_reddit, "wallhaven": imagens_wallhaven}


def carregar_fontes_extras(pasta):
    """
    Carrega as fontes extras: cada arquivo .py em `pasta` define

        FONTE = "nome"                      usado em fonte = "nome" nos perfis
        def imagens(perfil, app): ...       devolve [[url, url_reserva, ...], ...]
        PAGINAS = 1                         (opcional) padrão de perfil.paginas
        OPCOES = {"chave": padrão}          (opcional) chaves extras aceitas no perfil,
                                            lidas em perfil.opcoes["chave"]
        def aceitar(img, perfil, app): ...  (opcional) filtro depois do download; img
                                            é a imagem PIL já decodificada (reduzida)

    `app` é este módulo (app.cfg, app.logger, app.http, app.resumo_erro...).
    Exemplo em exemplos/fontes/bing.py.
    """
    app = sys.modules[__name__]
    for arq in sorted(pasta.glob("*.py")):
        try:
            spec = importlib.util.spec_from_file_location(f"fonte_extra_{arq.stem}", arq)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            nome = mod.FONTE
            if nome in FONTES:
                raise ValueError(f"já existe uma fonte chamada '{nome}'")
        except Exception as e:
            logger.error(f"Fonte extra {arq} ignorada: {e}")
            continue
        FONTES[nome] = lambda perfil, m=mod: m.imagens(perfil, app)
        if hasattr(mod, "aceitar"):
            FILTROS[nome] = lambda img, perfil, m=mod: m.aceitar(img, perfil, app)
        PAGINAS_PADRAO[nome] = getattr(mod, "PAGINAS", 1)
        OPCOES_FONTE[nome] = dict(getattr(mod, "OPCOES", {}))
        logger.debug(f"Fonte extra '{nome}' carregada de {arq}")


# ── Download e cache ─────────────────────────────────────────────────────────

def resumo_erro(e):
    """Mensagem do erro sem o rodapé da libcurl ("See https://curl.se/...")."""
    return str(e).split(" See https://curl.se/")[0]


def hash_url(url):
    return hashlib.md5(url.encode(), usedforsecurity=False).hexdigest()


def arquivo_cache(cache, url):
    return cache / (hash_url(url) + ".jpg")


def pasta_tmp_para(cache):
    cfg.pasta_temporaria.mkdir(parents=True, exist_ok=True)
    if cfg.pasta_temporaria.stat().st_dev == cache.stat().st_dev:
        return cfg.pasta_temporaria
    return cache


def ler_historico(arq):
    """{hash da URL: timestamp} do que foi baixado ou descartado nos últimos historico_dias."""
    try:
        historico = json.loads(arq.read_text())
    except (OSError, ValueError):
        return {}
    limite = time.time() - cfg.historico_dias * 86400
    return {k: t for k, t in historico.items() if t >= limite}


def gravar_historico(arq, historico):
    tmp = arq.with_name(f"{arq.name}.{os.getpid()}.part")
    tmp.write_text(json.dumps(historico))
    os.replace(tmp, arq)


_local = threading.local()


def sessao():
    """Uma sessão curl por thread: reaproveita conexão e DNS entre os downloads."""
    if not hasattr(_local, "sessao"):
        _local.sessao = http.Session(impersonate=cfg.imitar_navegador)
    return _local.sessao


# Resultados de baixar() que vão para o histórico (não adianta tentar de novo)
REJEITADA = "rejeitada"   # imagem boa, mas barrada pela largura ou pelo filtro da fonte
APAGADA = "apagada"       # todas as URLs deram 404/410 (post removido na origem)


def baixar(candidatos, perfil, tmp_dir):
    """
    Tenta as URLs candidatas em ordem. A imagem é validada em memória e só
    então gravada (temporário + os.replace), para o cache nunca ter arquivo
    parcial ou inválido. Devolve o caminho no cache, REJEITADA, APAGADA, ou
    None se falhou (rede/HTTP/arquivo inválido — tenta de novo na próxima).
    """
    apagadas = 0
    for url in candidatos:
        try:
            r = sessao().get(url, headers={"Accept": IMAGE_ACCEPT}, timeout=cfg.timeout)
            apagadas += r.status_code in (404, 410)
            if r.status_code != 200:
                logger.debug(f"HTTP {r.status_code} para {url}, tentando fallback...")
                continue

            try:
                img = Image.open(io.BytesIO(r.content))
                largura = img.width
                img.draft("RGB", (256, 256))  # JPEG: decodifica reduzido, mas lê o arquivo todo
                img.load()                    # falha se estiver truncada ou corrompida
            except Exception:
                logger.debug(f"Não é uma imagem válida: {url}")
                continue

            # Largura e filtro são da imagem, não da URL: não adianta tentar o fallback
            if largura < perfil.min_largura:
                logger.debug(f"Estreita demais ({largura}px): {url}")
                return REJEITADA
            filtro = FILTROS.get(perfil.fonte)
            if filtro and not filtro(img, perfil):
                logger.debug(f"Recusada pelo filtro da fonte {perfil.fonte}: {url}")
                return REJEITADA

            destino = arquivo_cache(perfil.cache, url)
            tmp = tmp_dir / f"{destino.name}.{os.getpid()}.part"
            try:
                tmp.write_bytes(r.content)
                os.replace(tmp, destino)
            finally:
                tmp.unlink(missing_ok=True)
            return destino
        except Exception as e:
            logger.warning(f"Erro ao baixar {url}: {resumo_erro(e)}")
    return APAGADA if apagadas == len(candidatos) else None


def baixar_novas(perfil):
    """Busca a lista na fonte e baixa até novas_por_execucao imagens fora do cache."""
    if not cfg.novas_por_execucao:
        return 0
    try:
        imagens = FONTES[perfil.fonte](perfil)
    except Exception as e:
        logger.error(f"Erro ao buscar a lista de imagens ({perfil.fonte}): {resumo_erro(e)}")
        return 0
    if not imagens:
        logger.warning("A fonte não devolveu nenhuma imagem — layout mudou ou bloqueio (403/429)?")

    arq_historico = perfil.cache / ".historico.json"
    historico = ler_historico(arq_historico)
    agora = time.time()
    novas, vistas = [], set()
    for candidatos in imagens:
        chave = hash_url(candidatos[0])
        if chave in vistas:
            continue
        vistas.add(chave)
        if any(arquivo_cache(perfil.cache, u).exists() for u in candidatos):
            historico.setdefault(chave, agora)   # já no cache: não volta ao sair dele
        elif chave not in historico:
            novas.append(candidatos)
    logger.info(f"{len(vistas)} imagens na fonte, {len(novas)} novas "
                f"(fora do cache e dos últimos {cfg.historico_dias} dias).")

    random.shuffle(novas)
    lote = novas[:cfg.novas_por_execucao * 2]   # sobra: algumas falham ou são rejeitadas
    tmp_dir = pasta_tmp_para(perfil.cache)
    with ThreadPoolExecutor(max_workers=cfg.downloads_paralelos) as pool:
        futuros = [pool.submit(baixar, c, perfil, tmp_dir) for c in lote]
        ok = 0
        for fut in as_completed(futuros):
            ok += isinstance(fut.result(), Path)
            if ok >= cfg.novas_por_execucao:
                pool.shutdown(cancel_futures=True)  # cancela as pendentes
                break
    # Só chega aqui com todos os downloads em andamento terminados: as
    # colagens nunca veem arquivo pela metade.
    resultados = [None if f.cancelled() else f.result() for f in futuros]
    for candidatos, res in zip(lote, resultados):
        if res is not None:
            historico[hash_url(candidatos[0])] = agora
    gravar_historico(arq_historico, historico)

    for motivo, texto in ((REJEITADA, "rejeitada(s) pela largura ou pelo filtro da fonte"),
                          (APAGADA, "apagada(s) na origem (404)")):
        if n := resultados.count(motivo):
            logger.info(f"{n} imagem(ns) {texto}.")
    return sum(isinstance(r, Path) for r in resultados)


def limpar_cache(cache):
    """Mantém só as max_imagens mais recentes (as recém-baixadas ficam)."""
    arquivos = sorted(cache.glob("*.jpg"), key=lambda f: f.stat().st_mtime, reverse=True)
    for f in arquivos[cfg.max_imagens:]:
        f.unlink(missing_ok=True)
    if len(arquivos) > cfg.max_imagens:
        logger.info(f"Cache cheio: {len(arquivos) - cfg.max_imagens} imagem(ns) antiga(s) removida(s).")


# ── Colagem e KDE ────────────────────────────────────────────────────────────

def set_wallpapers(paths):
    """Define wallpapers diferentes para cada monitor no KDE Plasma. Devolve True se aplicou."""
    # 1ª passagem: garante que o plugin org.kde.image está carregado em todos os desktops
    js_load_plugin = """
    var desktopList = desktops();
    for (var i = 0; i < desktopList.length; i++) {
        desktopList[i].wallpaperPlugin = 'org.kde.image';
    }
    """

    # 2ª passagem: aplica a imagem usando d.screen para mapear ao monitor correto
    js_apply = f"""
    var paths = {json.dumps(paths)};
    var desktopList = desktops();
    for (var i = 0; i < desktopList.length; i++) {{
        var d = desktopList[i];
        var idx = d.screen % paths.length;
        d.currentConfigGroup = ['Wallpaper', 'org.kde.image', 'General'];
        d.writeConfig('Image', 'file://' + paths[idx]);
        d.writeConfig('FillMode', {AJUSTES_KDE[cfg.ajuste_kde]});
    }}
    """

    qdbus = next(filter(None, map(shutil.which, QDBUS)), None)
    if not qdbus:
        logger.error(f"qdbus do Qt 6 não encontrado (procurado: {', '.join(QDBUS)}). "
                     f"No Debian/Ubuntu, instale o pacote qdbus-qt6.")
        return False
    logger.debug(f"Usando {qdbus}")

    env = {**os.environ}
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path=/run/user/{os.getuid()}/bus")

    def run_script(script):
        result = subprocess.run([
            qdbus, "org.kde.plasmashell", "/PlasmaShell",
            "org.kde.PlasmaShell.evaluateScript", script
        ], check=True, capture_output=True, text=True, env=env)
        if result.stderr:
            logger.warning(f"qdbus stderr: {result.stderr.strip()}")

    try:
        run_script(js_load_plugin)   # carrega o plugin em todos os desktops
        time.sleep(1)                # aguarda o plugin inicializar
        run_script(js_apply)         # aplica as imagens por screen index
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        detalhe = getattr(e, "stderr", "") or ""
        logger.error(f"Erro ao definir wallpaper via DBus: {e} {detalhe.strip()}")
        return False
    logger.info("Wallpapers aplicados via DBus.")
    return True


def get_num_monitors():
    if cfg.monitores:
        return cfg.monitores
    # Lê direto do kernel — funciona sem sessão gráfica, X11 ou Wayland
    try:
        n = sum(
            1 for status in Path("/sys/class/drm").glob("*/status")
            if status.read_text().strip() == "connected"
        )
        if n > 0:
            logger.info(f"Monitores detectados via sysfs: {n}")
            return n
    except Exception as e:
        logger.warning(f"sysfs falhou: {e}")

    logger.warning(f"Usando monitores_fallback={cfg.monitores_fallback}")
    return cfg.monitores_fallback


def sortear_grupos(arquivos, n, por_grupo):
    """n grupos de até por_grupo imagens, sem repetir imagem entre monitores enquanto der."""
    fila, grupos = [], []
    for _ in range(n):
        if len(fila) < por_grupo:
            resto = [f for f in arquivos if f not in fila]
            random.shuffle(resto)
            fila += resto
        grupos.append(fila[:por_grupo])
        fila = fila[por_grupo:]
    return grupos


def make_cell(img_path, cell_w, cell_h):
    img = Image.open(img_path)
    img.draft("RGB", (cell_w, cell_h))  # JPEG: decodifica já reduzido (1/2, 1/4, 1/8)
    img = ImageOps.exif_transpose(img).convert("RGB")

    # Fundo: a mesma imagem preenchendo a célula, borrada. O blur é feito em
    # 1/8 da resolução e ampliado: visualmente igual e bem mais barato.
    bg = ImageOps.fit(img, (max(cell_w // 8, 1), max(cell_h // 8, 1)), method=Image.BILINEAR)
    bg = bg.filter(ImageFilter.GaussianBlur(radius=cfg.desfoque / 8))
    bg = bg.resize((cell_w, cell_h), Image.BILINEAR)

    # Frente: escala proporcional para caber dentro da célula, centralizada
    ratio = min(cell_w / img.width, cell_h / img.height)
    fg = img.resize((int(img.width * ratio), int(img.height * ratio)), Image.LANCZOS)
    bg.paste(fg, ((cell_w - fg.width) // 2, (cell_h - fg.height) // 2))
    return bg


def make_collage(images, out_path):
    # Menor grid que comporta as imagens (ex.: 5 imagens → 3x2, com uma célula vazia)
    cols, rows = LAYOUTS[min(k for k in LAYOUTS if k >= len(images))]
    cell_w, cell_h = cfg.largura // cols, cfg.altura // rows
    canvas = Image.new("RGB", (cfg.largura, cfg.altura))
    for i, img_path in enumerate(images):
        col, row = i % cols, i // cols
        try:
            canvas.paste(make_cell(img_path, cell_w, cell_h), (col * cell_w, row * cell_h))
        except Exception as e:
            logger.warning(f"Erro ao processar célula {img_path}: {e}")
    canvas.save(out_path, FORMATOS[cfg.formato], quality=cfg.qualidade)
    return out_path


# ── Principal ────────────────────────────────────────────────────────────────

def listar_perfis(caminho):
    print(f"Fontes: {', '.join(FONTES)}")
    print(f"Perfis em {caminho} (padrão: {cfg.perfil_padrao}):")
    for nome, p in cfg.perfis.items():
        origem = f"r/{p.subreddit} ({p.sort})" if p.fonte == "reddit" else p.url or "-"
        print(f"  {nome:<12} {p.fonte:<10} {origem}\n  {'':<12} {'':<10} → {p.cache}")


def main():
    global cfg
    ap = argparse.ArgumentParser(
        prog=APP, description="Troca o wallpaper do KDE Plasma por colagens de imagens baixadas.")
    ap.add_argument("perfil", nargs="?",
                    help="perfil definido em [perfis.NOME] (padrão: [geral] perfil_padrao)")
    ap.add_argument("--sem-aplicar", action="store_true",
                    help="baixa e gera as colagens, mas não troca o wallpaper")
    ap.add_argument("--config", type=Path, default=CONFIG_PADRAO,
                    help=f"arquivo de configuração (padrão: {CONFIG_PADRAO})")
    ap.add_argument("--listar", action="store_true", help="lista fontes e perfis e sai")
    ap.add_argument("-v", "--verbose", action="store_true", help="mostra mensagens de depuração")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, datefmt="%Y-%m-%d %H:%M:%S",
                        format="%(asctime)s %(levelname)s: %(message)s")
    if args.verbose:
        logger.setLevel(logging.DEBUG)

    carregar_fontes_extras(args.config.parent / "fontes")
    try:
        cfg = carregar_config(args.config)
    except ErroConfig as e:
        logger.error(f"Configuração: {e}")
        return 2
    if args.listar:
        listar_perfis(args.config)
        return 0

    nome = args.perfil or cfg.perfil_padrao
    if nome not in cfg.perfis:
        logger.error(f"Perfil '{nome}' não existe. Disponíveis: {', '.join(cfg.perfis)}")
        return 2
    # Daqui em diante as mensagens levam o nome do perfil
    for h in logging.getLogger().handlers:
        h.setFormatter(logging.Formatter(f"%(asctime)s [{nome}] %(levelname)s: %(message)s",
                                         "%Y-%m-%d %H:%M:%S"))

    perfil = cfg.perfis[nome]
    collage_dir = perfil.cache / "collage"
    collage_dir.mkdir(parents=True, exist_ok=True)

    # 1. Baixa imagens novas e só depois poda o cache: se a rede falhar,
    #    nada é descartado.
    logger.info(f"{baixar_novas(perfil)} imagem(ns) nova(s) baixada(s).")
    limpar_cache(perfil.cache)

    # 2. Gera colagens — uma por monitor
    arquivos = list(perfil.cache.glob("*.jpg"))
    if not arquivos:
        logger.error("Nenhuma imagem disponível no cache para definir como wallpaper.")
        return 1

    num_monitors = get_num_monitors()
    ts = int(time.time())  # timestamp garante nome único — força o KDE a detectar arquivo novo
    collage_paths = []
    for i, grupo in enumerate(sortear_grupos(arquivos, num_monitors, cfg.imagens_por_colagem)):
        out = collage_dir / f"collage_{i}_{ts}.{cfg.formato}"
        try:
            make_collage(grupo, out)
            collage_paths.append(str(out.absolute()))
            logger.debug(f"Colagem {i} gerada: {out.name}")
        except Exception as e:
            logger.error(f"Erro ao gerar colagem {i}: {e}")

    if not collage_paths:
        logger.error("Nenhuma colagem gerada.")
        return 1

    if args.sem_aplicar:
        logger.info(f"--sem-aplicar: colagens em {collage_dir}")
        return 0

    # 3. Aplica. Deu certo: remove as colagens antigas. Falhou (ex.: cron rodando
    #    sem sessão gráfica): remove as novas e mantém as que o KDE está usando,
    #    senão ele ficaria apontando para arquivo apagado (fundo preto).
    aplicou = set_wallpapers(collage_paths)
    for f in collage_dir.glob("collage_*"):
        if (str(f.absolute()) in collage_paths) != aplicou:
            f.unlink(missing_ok=True)
    if not aplicou:
        return 1

    logger.info(f"{len(collage_paths)}/{num_monitors} colagem(ns) aplicada(s) "
                f"com {len(arquivos)} imagens no pool.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
