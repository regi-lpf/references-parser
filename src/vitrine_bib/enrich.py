"""Enriquecimento seletivo: BDTD (>= 0.88, retry/backoff) e busca CV Lattes via lzstring."""

from __future__ import annotations

from difflib import SequenceMatcher
import json
import re
import time
from urllib.parse import quote

from lzstring import LZString
import requests

from vitrine_bib.ingest import classificar_url
from vitrine_bib.models import normalizar_texto
from vitrine_bib.parser import eh_autor_institucional

BDTD_API = "https://bdtd.ibict.br/vufind/api/v1/search"
LATTES_BUSCA_BASE = "https://busca-cv-lattes.cnpq.br/busca"


def similaridade_normalizada(a: str, b: str) -> float:
    na = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", normalizar_texto(a))).strip()
    nb = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", normalizar_texto(b))).strip()
    return SequenceMatcher(None, na, nb).ratio() if na and nb else 0.0


def gerar_url_lattes(autor: str | None) -> str | None:
    if not autor or eh_autor_institucional(autor):
        return None
    primeiro = autor.split(";")[0].strip()
    if not primeiro or eh_autor_institucional(primeiro):
        return None
    payload = json.dumps({"modoBusca": "NOME", "keyword": primeiro, "orderBy": "nome"}, ensure_ascii=False, separators=(",", ":"))
    comprimido = LZString().compressToEncodedURIComponent(payload)
    return f"{LATTES_BUSCA_BASE}?keyword={quote(primeiro)}&mode=NOME&q={quote(comprimido)}&page=1&size=10"


def buscar_na_bdtd(
    titulo: str,
    *,
    session: requests.Session | None = None,
    timeout: float = 8.0,
    max_retries: int = 3,
    backoff_base: float = 0.5,
    sleep_fn=time.sleep,
) -> str | None:
    titulo_limpo = (titulo or "").strip()
    if len(titulo_limpo) < 6:
        return None
    client = session or requests
    params = {"lookfor": titulo_limpo, "type": "Title", "limit": 3, "field[]": ["title", "url", "id"]}
    resp = None
    for tentativa in range(max_retries):
        try:
            resp = client.get(BDTD_API, params=params, timeout=timeout)
            if resp.status_code == 200:
                break
            if resp.status_code in (429, 500, 502, 503, 504) and tentativa < max_retries - 1:
                sleep_fn(backoff_base * (2**tentativa))
                continue
            return None
        except requests.RequestException:
            if tentativa < max_retries - 1:
                sleep_fn(backoff_base * (2**tentativa))
                continue
            return None
    if resp is None or resp.status_code != 200:
        return None
    for rec in resp.json().get("records", []):
        rec_title = rec.get("title", "")
        if isinstance(rec_title, list):
            rec_title = rec_title[0] if rec_title else ""
        if similaridade_normalizada(titulo_limpo, str(rec_title)) < 0.88:
            continue
        urls = rec.get("url", [])
        for cand in (urls if isinstance(urls, list) else [urls]):
            u, tipo = classificar_url(str(cand))
            if u and tipo == "obra":
                return u
        if rec.get("id"):
            return f"https://bdtd.ibict.br/vufind/Record/{rec['id']}"
    return None
