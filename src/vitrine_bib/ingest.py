"""Ingestão DOM determinística de listas HTML <ul><li>...</li></ul>."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import html
from pathlib import Path
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from vitrine_bib.models import normalizar_texto

_MARCADORES_PROFUNDOS = ("handle/", "bitstream/", "jspui/", "tede/", "article/", "detalhes", "sucupira", "doi.org", "bdtd", "noticia/", "docman", ".pdf", ".htm", ".html")
_RAIZES_GENERICAS = frozenset({"", "index.html", "index.htm", "index.php", "home", "inicio", "pt", "pt-br", "en"})
_TEXTOS_AUX = frozenset({"link", "acesse", "aqui", "clique aqui", "disponivel"})


@dataclass(frozen=True)
class EntradaBruta:
    texto_limpo: str
    chave_dedup: str
    link_obra: str | None
    link_lattes: str | None
    url_rejeitada_homepage: bool = False


def calcular_chave_dedup(texto: str) -> str:
    return hashlib.sha256(normalizar_texto(texto).encode("utf-8")).hexdigest()[:16]


def classificar_url(url: str) -> tuple[str | None, str]:
    limpa = (url or "").strip().rstrip(".,;)")
    parsed = urlparse(limpa)
    if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
        return None, "invalida"
    if any(h in parsed.netloc.lower() for h in ("lattes.cnpq.br", "escavador.com")):
        return limpa, "lattes"

    path = parsed.path.strip("/")
    segs = [s for s in path.split("/") if s]
    if path.lower() in _RAIZES_GENERICAS and not parsed.query:
        return None, "rejeitada_homepage"
    if any(m in limpa.lower() for m in _MARCADORES_PROFUNDOS) or len(segs) >= 2 or parsed.query:
        return limpa, "obra"
    if any(ch.isdigit() for ch in segs[0]) or (len(segs[0]) >= 8 and "-" in segs[0]):
        return limpa, "obra"
    return None, "rejeitada_homepage"


def _limpar_texto(texto: str) -> str:
    texto = re.sub(r"\s+", " ", html.unescape(texto).replace("\xa0", " ")).strip()
    texto = re.sub(r"\s*Dispon[ií]vel\s+em\s*:?\s*(?:\.\s*Acesso\s+em\s*:.*)?\.?$", "", texto, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", texto).strip()


def carregar_html(caminho: Path | str) -> list[EntradaBruta]:
    soup = BeautifulSoup(Path(caminho).read_text(encoding="utf-8"), "html.parser")
    por_chave: dict[str, EntradaBruta] = {}
    for li in soup.find_all("li"):
        link_obra: str | None = None
        link_lattes: str | None = None
        rejeitada = False
        for a in li.find_all("a", href=True):
            u, tipo = classificar_url(a["href"])
            if tipo == "lattes" and not link_lattes:
                link_lattes = u
            elif tipo == "obra" and not link_obra:
                link_obra = u
            elif tipo == "rejeitada_homepage":
                rejeitada = True
            t_a = a.get_text(" ", strip=True)
            if normalizar_texto(t_a) in _TEXTOS_AUX or t_a.lower().startswith("http"):
                a.decompose()
        texto = _limpar_texto(li.get_text(" ", strip=True))
        for m in re.finditer(r"https?://[^\s<>\"']+", texto):
            u, tipo = classificar_url(m.group(0))
            if tipo == "lattes" and not link_lattes:
                link_lattes = u
            elif tipo == "obra" and not link_obra:
                link_obra = u
            elif tipo == "rejeitada_homepage":
                rejeitada = True
            texto = texto.replace(m.group(0), " ")
        texto = _limpar_texto(texto)
        if len(texto) >= 15:
            chave = calcular_chave_dedup(texto)
            if prev := por_chave.get(chave):
                por_chave[chave] = EntradaBruta(
                    prev.texto_limpo,
                    chave,
                    prev.link_obra or link_obra,
                    prev.link_lattes or link_lattes,
                    prev.url_rejeitada_homepage or rejeitada,
                )
            else:
                por_chave[chave] = EntradaBruta(texto, chave, link_obra, link_lattes, rejeitada)
    return list(por_chave.values())
