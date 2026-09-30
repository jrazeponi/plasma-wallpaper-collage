# plasma-wallpaper-collage

*[Read in English](README.md)*

**Colagens de wallpaper para o KDE Plasma 6**, uma por monitor, montadas com
imagens do Reddit, do wallhaven ou de qualquer fonte que você acrescentar.
Feito para rodar sozinho (cron ou timer do systemd): a cada execução, cada tela
ganha um mosaico novo.

> Antigo `redditWallpaper`.

## Recursos

- **Fontes**
  - **Reddit**: um ou vários subreddits (`wallpaper+MinimalWallpaper`),
    ordenação `hot`/`new`/`top`/`rising`/`controversial`, galerias e paginação.
  - **wallhaven**: monte a busca no site e cole a URL. Todos os filtros
    (categorias, pureza, resolução, proporção, cor, ordenação e termos) vão
    para a API. Com a chave da API, a busca também traz conteúdo NSFW, salvo
    numa pasta `nsfw/` à parte.
  - **Fontes extras**: um arquivo `.py` pequeno na pasta de configuração
    acrescenta qualquer site. Vem um exemplo com a imagem do dia do Bing.
- **Colagens**
  - Uma colagem por monitor, detectado automaticamente via `/sys/class/drm`.
  - 1, 2, 3, 4, 6 ou 9 imagens por colagem, em qualquer resolução, em
    jpg/png/webp.
  - Cada imagem aparece inteira, sobre uma cópia desfocada dela mesma que
    preenche a célula.
- **Cache**
  - As imagens são validadas em memória antes de serem gravadas, então o cache
    nunca fica com arquivo pela metade ou corrompido.
  - Guarda só as N imagens mais recentes.
  - Um histórico de 7 dias evita baixar de novo o que já saiu do cache, foi
    recusado por um filtro ou foi apagado na origem.
- **Aplicação segura**
  - O wallpaper é trocado pela API de scripts do Plasma via DBus.
  - Se a troca falhar (por exemplo, sem sessão do Plasma), as colagens atuais
    são mantidas, em vez de deixar o fundo preto.
- **Configuração**: um único arquivo TOML comentado. Um erro no arquivo gera
  uma mensagem dizendo a seção e a chave.
- **Privacidade**
  - Os cookies do Reddit vão só no pedido do feed do reddit.com, nunca para os
    servidores das imagens.
  - A chave do wallhaven vai num header da requisição e nunca aparece no log.

## Requisitos

- Linux com **KDE Plasma 6** (o plugin de wallpaper `org.kde.image` e o `qdbus`
  do Qt 6: pacote `qdbus-qt6` no Debian/Ubuntu, `qt6-tools` no Arch).
- Python 3.11+. No 3.13 ou mais novo, o rookiepy é compilado na instalação (ver
  [Instalação](#instalação)).
- Para o Reddit: um navegador logado no reddit.com. Os cookies são lidos
  localmente com o [rookiepy](https://github.com/thewh1teagle/rookiepy); o
  Reddit bloqueia clientes anônimos.

## Instalação

Com o [pipx](https://pipx.pypa.io):

```bash
pipx install git+https://github.com/jrazeponi/plasma-wallpaper-collage
mkdir -p ~/.config/plasma-wallpaper-collage
curl -o ~/.config/plasma-wallpaper-collage/config.toml \
  https://raw.githubusercontent.com/jrazeponi/plasma-wallpaper-collage/main/config.example.toml
```

Ou a partir de um clone, num virtualenv:

```bash
git clone https://github.com/jrazeponi/plasma-wallpaper-collage.git
cd plasma-wallpaper-collage
python3 -m venv .venv
.venv/bin/pip install -e .          # -e: um `git pull` já atualiza o comando instalado
mkdir -p ~/.config/plasma-wallpaper-collage
cp config.example.toml ~/.config/plasma-wallpaper-collage/config.toml
```

Python 3.13 ou mais novo: o rookiepy só tem wheel até o 3.12, então o pip o
compila na instalação. Isso exige o Rust (`cargo`) e
`PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1` na frente do comando de instalação:

```bash
PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 pipx install git+https://github.com/jrazeponi/plasma-wallpaper-collage
```

## Uso

```bash
plasma-wallpaper-collage                 # roda o perfil padrão (perfil_padrao)
plasma-wallpaper-collage sfw             # roda um perfil específico
plasma-wallpaper-collage --listar        # lista fontes e perfis
plasma-wallpaper-collage --sem-aplicar   # baixa e gera as colagens, sem trocar o wallpaper
plasma-wallpaper-collage -v              # detalhes (URLs, rejeições, cada colagem)
plasma-wallpaper-collage --config X.toml # usa outro arquivo de configuração
```

Códigos de saída:
- `0`: ok;
- `1`: não conseguiu montar ou aplicar as colagens;
- `2`: erro na configuração ou perfil inexistente.

## Configuração

O arquivo fica em `~/.config/plasma-wallpaper-collage/config.toml` (respeita
`$XDG_CONFIG_HOME`). O [`config.example.toml`](config.example.toml) comenta
cada chave. Uma chave que falte em `[geral]`, `[cache]`, `[colagem]` ou
`[wallhaven]` usa o padrão. Os perfis só existem se estiverem no arquivo.

| Seção | Chave | Padrão | O que é |
|---|---|---|---|
| `[geral]` | `perfil_padrao` | `"sfw"` | perfil usado quando nenhum é informado |
| | `pasta_wallpapers` | `"~/Wallpapers"` | cache padrão de cada perfil: `<esta pasta>/<perfil>` (busca NSFW do wallhaven: `<esta pasta>/nsfw/<perfil>`) |
| | `pasta_temporaria` | `~/.cache/plasma-wallpaper-collage/tmp` | downloads em andamento (mesmo disco do cache) |
| | `navegador_cookies` | `"firefox"` | navegador (ou lista, tentada em ordem) de onde ler os cookies do Reddit |
| | `imitar_navegador` | `"firefox"` | fingerprint TLS imitado (`firefox`, `chrome`, `edge`, `safari`…) |
| | `timeout` / `downloads_paralelos` | `15` / `6` | segundos por requisição / downloads simultâneos |
| `[cache]` | `max_imagens` | `50` | imagens guardadas por pasta de cache |
| | `novas_por_execucao` | `20` | imagens novas por execução (`0` = só remonta as colagens) |
| | `historico_dias` | `7` | dias até uma imagem já vista poder ser baixada de novo |
| `[colagem]` | `largura` / `altura` | `1920` / `1080` | tamanho da colagem |
| | `imagens_por_colagem` | `4` | 1, 2, 3, 4, 6 ou 9 |
| | `formato` / `qualidade` | `"jpg"` / `90` | `jpg`, `png` ou `webp`; qualidade de 1 a 100 |
| | `desfoque` | `18` | raio do desfoque do fundo (`0` = sem) |
| | `ajuste_kde` | `"centralizar"` | encaixe no KDE: `centralizar`, `cortar`, `ajustar`, `esticar`, `lado_a_lado` |
| | `monitores` / `monitores_fallback` | `0` / `3` | nº fixo de colagens (`0` = detectar) / nº se a detecção falhar |
| `[wallhaven]` | `chave_api` | `""` | chave da API do wallhaven (ver abaixo) |

### Perfis

Cada tabela `[perfis.NOME]` é um perfil, rodado com
`plasma-wallpaper-collage NOME`.

- Chaves comuns:
  - `fonte`: a fonte (obrigatória);
  - `cache`: pasta do cache (padrão `<pasta_wallpapers>/NOME`; para buscas NSFW
    do wallhaven, ver [Pasta das buscas NSFW](#pasta-das-buscas-nsfw));
  - `paginas`: páginas lidas da fonte;
  - `min_largura`: largura mínima em px (padrão 1920; `0` desliga).
- Reddit:
  - `subreddit`: vários juntos com `+`;
  - `sort`;
  - `top_time`: usado com `top`/`controversial`.
  - Posts +18 não são filtrados: o subreddit escolhido define o conteúdo.
- wallhaven:
  - `url`: uma URL de busca copiada do wallhaven.cc.
  - Com ordenação fixa (`views`, `favorites`) vêm sempre as mesmas imagens.
    Use `sorting=random` ou `sorting=toplist&topRange=1w` para variar.

```toml
[perfis.sfw]
fonte = "reddit"
subreddit = "wallpaper+MinimalWallpaper"

[perfis.natureza]
fonte = "wallhaven"
url = "https://wallhaven.cc/search?q=nature&categories=100&purity=100&atleast=1920x1080&ratios=16x9&sorting=random"
```

Sintaxe útil na busca do wallhaven:
- `+tag1 +tag2`: as duas tags;
- `-tag`: exclui a tag;
- `type:png`: só arquivos png;
- `@usuario`: uploads de um usuário;
- `like:ID`: imagens parecidas com outra.

### Chave da API do wallhaven (NSFW)

A chave só é necessária para conteúdo NSFW, ou seja, quando o último dígito de
`purity=` na URL é `1`, como em `purity=001` ou `purity=111`. Sem ela, a busca
volta vazia e o log mostra um aviso.

1. Crie uma conta no [wallhaven.cc](https://wallhaven.cc).
2. Copie sua chave em **Settings → Account → API Key**
   (<https://wallhaven.cc/settings/account>).
3. Informe a chave de **uma** destas formas:
   - na variável de ambiente `WALLHAVEN_API_KEY`, que tem prioridade sobre o
     arquivo;
   - no arquivo de configuração. Nesse caso, proteja o arquivo com
     `chmod 600 ~/.config/plasma-wallpaper-collage/config.toml` (o programa
     avisa se outros usuários puderem lê-lo):
     ```toml
     [wallhaven]
     chave_api = "sua-chave"
     ```

O cron não carrega o seu perfil do shell. No cron, use o arquivo de
configuração ou carregue a variável na própria linha (ver [Automação](#automação)).

### Pasta das buscas NSFW

Um perfil wallhaven cuja URL aceita conteúdo NSFW não precisa de nome especial:
o programa o guarda em `<pasta_wallpapers>/nsfw/NOME`. O critério é o mesmo da
chave da API: o último dígito de `purity=` é `1`, sozinho (`001`) ou junto dos
outros (`011`, `101`, `111`).

- O perfil inteiro vai para lá (imagens, histórico e colagens), mesmo numa busca
  mista como `purity=111`: a colagem mistura tudo o que está na pasta, então
  qualquer imagem pode ser +18.
- `sketchy` sozinho (`purity=010` ou `110`) não conta.
- O perfil chamado `nsfw` usa `<pasta_wallpapers>/nsfw` direto, não `nsfw/nsfw`.
- Com `cache` no perfil, vale a pasta que você escreveu.
- Cada perfil mantém o próprio cache: dois perfis NSFW não misturam imagens.

```toml
[perfis.nsfwallhaven]
fonte = "wallhaven"
url = "https://wallhaven.cc/search?categories=111&purity=001&sorting=random"
# imagens em ~/Wallpapers/nsfw/nsfwallhaven
```

## Fontes extras

Cada arquivo `.py` em `~/.config/plasma-wallpaper-collage/fontes/` é carregado
na inicialização e pode registrar uma fonte nova:

```python
FONTE = "minhafonte"               # usado como fonte = "minhafonte" nos perfis
PAGINAS = 1                        # opcional: padrão de perfil.paginas
OPCOES = {"regiao": "pt-BR"}       # opcional: chaves extras do perfil → perfil.opcoes

def imagens(perfil, app):          # obrigatório: [[url, url_reserva, ...], ...]
    ...

def aceitar(img, perfil, app):     # opcional: filtro depois do download
    return True                    # img é a imagem PIL decodificada (reduzida)
```

`app` é o módulo principal. Use `app.http` (uma sessão curl_cffi que imita um
navegador), `app.cfg` para a configuração e `app.logger`.

Um exemplo completo e funcionando está em
[`exemplos/fontes/bing.py`](exemplos/fontes/bing.py), que baixa as imagens do
dia do Bing em 4K. Copie-o para a pasta `fontes/` e acrescente:

```toml
[perfis.bing]
fonte = "bing"
mercado = "pt-BR"
```

Uma fonte extra com erro é ignorada com uma mensagem no log; as demais
continuam funcionando.

## Automação

Cron, de hora em hora:

```cron
@hourly $HOME/.local/bin/plasma-wallpaper-collage >> $HOME/.cache/plasma-wallpaper-collage.log 2>&1
```

- Se instalou num virtualenv, use `/caminho/.venv/bin/plasma-wallpaper-collage`.
- Para passar a chave do wallhaven pelo ambiente, comece a linha com
  `WALLHAVEN_API_KEY=... ` ou com `set -a; . /caminho/segredos.env; set +a;`.
- Um timer de usuário do systemd funciona igualmente bem.

## Como funciona

1. Busca a lista de imagens na fonte do perfil.
2. Descarta as que já estão no cache ou no histórico.
3. Baixa até `novas_por_execucao` imagens em paralelo. Cada uma é validada em
   memória (imagem real e completa, larga o bastante, aceita pelo filtro da
   fonte) e só então gravada no cache.
4. Poda o cache para `max_imagens`, removendo primeiro as mais antigas. A poda
   vem depois do download, então uma falha de rede não custa imagens.
5. Sorteia as imagens para cada monitor, sem repetir entre monitores enquanto
   der, e monta as colagens.
6. Aplica pelo `qdbus` do Qt 6, uma por tela. As colagens antigas só são apagadas
   depois que as novas são aplicadas.

## Problemas comuns

| Mensagem no log | Causa provável |
|---|---|
| `Erro ao buscar a lista de imagens (reddit): HTTP Error 403` | cookies do Reddit ausentes ou expirados: abra o reddit.com logado no navegador de `navegador_cookies` |
| `Nenhum cookie do Reddit encontrado` | navegador errado em `navegador_cookies`, ou não está logado |
| `Sem chave da API do wallhaven` | busca NSFW sem chave |
| `chave da API recusada (401)` | chave do wallhaven errada |
| `A fonte não devolveu nenhuma imagem` | busca vazia, site mudou de layout, ou bloqueio (403/429) |
| `apagada(s) na origem (404)` | normal: posts removidos que ainda aparecem no feed |
| `qdbus do Qt 6 não encontrado` | o qdbus do Qt 6 não está instalado (Debian/Ubuntu: pacote `qdbus-qt6`) |
| `Erro ao definir wallpaper via DBus` | sem sessão do Plasma (ex.: deslogado); as colagens atuais são mantidas |
| `Configuração: ...` | erro no arquivo de configuração; a mensagem diz a seção e a chave |

## Licença

[GPL-3.0-or-later](LICENSE). Copyright © 2026 José Roberto (jrazeponi).
