# SPDX-License-Identifier: GPL-3.0-or-later
"""
Exemplo de fonte extra: as imagens do dia do Bing (até 15 dias, em 4K).

Para usar, copie este arquivo para ~/.config/plasma-wallpaper-collage/fontes/
e crie um perfil no config.toml:

    [perfis.bing]
    fonte = "bing"
    mercado = "pt-BR"     # opcional: região das imagens
    paginas = 2           # opcional: 1 = últimos 8 dias, 2 = últimos 15

Uma fonte extra define FONTE e imagens(perfil, app); PAGINAS, OPCOES e
aceitar(img, perfil, app) são opcionais. `app` é o módulo principal: use
app.http (curl_cffi), app.cfg (configuração) e app.logger.
"""

FONTE = "bing"
PAGINAS = 2
OPCOES = {"mercado": "en-US"}   # chaves extras aceitas no perfil → perfil.opcoes


def imagens(perfil, app):
    """Devolve, para cada imagem, as URLs candidatas em ordem de preferência."""
    urls = []
    with app.http.Session(impersonate=app.cfg.imitar_navegador) as s:
        # A API só volta 8 imagens por pedido e até 7 dias no passado
        for idx in (0, 7)[:perfil.paginas]:
            r = s.get("https://www.bing.com/HPImageArchive.aspx", timeout=app.cfg.timeout,
                      params={"format": "js", "idx": idx, "n": 8, "mkt": perfil.opcoes["mercado"]})
            r.raise_for_status()
            # As duas páginas se sobrepõem em um dia; o programa descarta repetidas
            for img in r.json().get("images", []):
                base = "https://www.bing.com" + img["urlbase"]
                urls.append([base + "_UHD.jpg", base + "_1920x1080.jpg"])
    return urls
