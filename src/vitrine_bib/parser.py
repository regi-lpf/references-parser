"""Parser bibliográfico determinístico em cascata: CAPES -> APA -> ABNT -> fallback."""

from __future__ import annotations

import re

from vitrine_bib.ingest import EntradaBruta
from vitrine_bib.models import normalizar_texto

_PREPOSICOES = frozenset({"de", "da", "do", "das", "dos", "e", "em", "no", "na", "nos", "nas", "a", "o", "as", "os", "para", "por", "com"})
_INST_EXPLICITO = ("conselho", "ministerio", "secretaria", "associacao", "assembleia", "instituto", "universidade", "fundacao", "governo", "confederacao")
_INST_PREFIXOS = ("brasil", "mec", "alesc", "acirs", "cgu", "cne", "conif", "concefet", "coneaf", "cedup", "diario", "ibge", "inep", "tcu", "capes", "cnpq", "ocde", "unesco", *_INST_EXPLICITO)

_RE_CAPES = re.compile(
    r"^(?:\d+\.\s+)?(?P<autor>[A-ZÀ-Ÿ][A-ZÀ-Ÿ\s'’-]+,\s*[A-Za-zÀ-ÿ\s.'’-]+?)(?:\.(?!\s*(?:DA|DE|DO|DAS|DOS)\.)\s*|\s+(?=[“\"']))"
    r"(?P<titulo>.+?)[.'’\"”]*\s+(?P<data>\d{2}/\d{2}/\d{4})\s+(?:\d+|undefined)\s*f\.\s+(?P<grau>.+?)\s+"
    r"Institui[çc][ãa]o\s+de\s+Ensino:\s*(?P<ies>.+?)(?:\s+Biblioteca\s+Deposit[áa]ria:\s*.+)?$",
    re.IGNORECASE,
)
_RE_APA = re.compile(r"^(?P<autor>.+?)\s*\((?P<ano>(?:18|19|20)\d{2})[a-z]?\)\s*\.?\s*(?P<resto>.+)$")
_RE_ANO = re.compile(r"\b((?:18|19|20)\d{2})\b")


def eh_autor_institucional(autor: str | None) -> bool:
    norm = normalizar_texto(autor)
    if not norm:
        return True
    if "," in (autor or "") and not any(t in norm for t in _INST_EXPLICITO):
        return False
    if any(t in norm for t in _INST_EXPLICITO):
        return True
    if any(norm == p or norm.startswith((f"{p}.", f"{p}/", f"{p} ")) for p in _INST_PREFIXOS):
        return True
    limpo = (autor or "").strip().rstrip(".")
    return "," not in limpo and limpo.isupper() and len(limpo.split()) <= 6


def formatar_nome_autor(autor_bruto: str) -> str:
    limpo = re.sub(r"\s+", " ", autor_bruto).strip().rstrip(".,;")
    if not limpo or eh_autor_institucional(limpo):
        return limpo
    partes = [p.strip() for p in re.split(r"\s*;\s*|\s+&\s+|,\s+e\s+", limpo) if p.strip()]
    formatados: list[str] = []
    for p in partes:
        p = re.sub(r"\s*\((?:org|orgs|coor|coord|ed|eds)\.?\)|,?\s*et\.?\s*al\.?", "", p, flags=re.IGNORECASE).strip(" .")
        if not p or eh_autor_institucional(p):
            if p:
                formatados.append(p)
            continue
        nome = f"{p.split(',', 1)[1].strip()} {p.split(',', 1)[0].strip()}" if "," in p else p
        nome = re.sub(r"([A-Za-zÀ-ÿ]\.)(?=[A-Za-zÀ-ÿ])", r"\1 ", nome)
        palavras = [
            (w[0].upper() + ".") if re.fullmatch(r"[A-Za-zÀ-ÿ]\.?", w) else (w.lower() if i > 0 and w.lower() in _PREPOSICOES else w.lower().capitalize())
            for i, w in enumerate(nome.split())
        ]
        formatados.append(" ".join(palavras))
    return "; ".join(formatados)


def detectar_categoria(texto: str, lista_id: str, link_obra: str | None = None) -> str:
    low, url_low = normalizar_texto(texto), (link_obra or "").lower()
    if "mestrado profissional" in low:
        return "Mestrado Profissional"
    if re.search(r"\b(tese|doutorado)\b", low):
        return "Doutorado"
    if re.search(r"\b(dissertacao|mestrado)\b", low):
        return "Mestrado"
    if re.search(r"\b(constituicao|decreto-lei|decreto|lei\s+n[º°o.]?|portaria|resolucao|parecer|medida provisoria|instrucao normativa)\b", low):
        return "Legislação"
    if re.search(r"\b(relatorio|prestacao de contas|indicadores de gestao)\b", low):
        return "Relatório"
    if re.search(r"\b(apresentacao|slides|ppt)\b", low):
        return "Apresentação"
    if "noticia/" in url_low or re.search(r"\b(noticia|reportagem)\b", low):
        return "Notícia"
    if re.search(r"\b(?:IN|In)[.:]\s|\b(?:IN|In)\s+[A-ZÀ-Ÿ]", texto):
        return "Anais de evento" if re.search(r"\b(anais|conedu|congresso(?!\s+nacional)|simposio|seminario|coloquio)\b", low) else "Capítulo de livro"
    if re.search(r"\b(anais|conedu|congresso(?!\s+nacional)|simposio|seminario|coloquio)\b", low):
        return "Anais de evento"
    if "doi.org/" in url_low or re.search(r"\bv\.\s*\d+|\bn\.\s*\d+|\bdoi\s*:|\bissn\b|\brevista\b|\bcadernos?\b|\bdebates em educacao\b|\bvivencias\b|\beducacao em foco\b|\btrabalho & educacao\b|\beducacao unisinos\b|\bmetodologias e aprendizado\b|\blinhas criticas\b|\bsemina\b|\bretratos da escola\b", low):
        return "Artigo"
    if re.search(r"\b\d+\s*p\.\b|\beditora\b|\b\d+\.\s*ed\b", low):
        return "Livro"
    return "Documento oficial" if lista_id == "documentos-oficiais" else "Publicação"


def _separar_titulo_e_resto(corpo: str) -> tuple[str, str]:
    m_marc = re.search(r"(?:\.\s*|\s+)(?=(?:IN[.:]\s|In[.:]\s|In\s+[A-ZÀ-Ÿ]|Disserta[çc][ãa]o\b|Tese\b|Relat[óo]rio\b|\d{2}/\d{2}/(?:18|19|20)\d{2}))", corpo)
    if m_marc and m_marc.start() >= 5:
        return corpo[: m_marc.start()].strip(" .’'\"”"), corpo[m_marc.start() :].lstrip(" .")
    m = re.search(r"([.?!])\s+(?=[A-ZÀ-Ÿ0-9\[])", corpo)
    if m and m.start() >= 4:
        fim = m.end(1) if m.group(1) != "." else m.start()
        return corpo[:fim].strip(" .’'\"”"), corpo[m.end() :].strip()
    return corpo.strip(" .’'\"”"), ""


def _extrair_ano(resto: str, texto: str) -> int | None:
    m = _RE_ANO.findall(resto)
    if m:
        return int(m[-1])
    sem_int = re.sub(r"\(\s*(?:18|19|20)\d{2}\s*[-–]\s*(?:18|19|20)\d{2}\s*\)", " ", texto)
    m2 = _RE_ANO.findall(sem_int) or _RE_ANO.findall(texto)
    return int(m2[-1]) if m2 else None


def _parse_abnt(texto: str, lista_id: str, link_obra: str | None) -> dict | None:
    limpo = re.sub(r"^\d+\.\s+", "", texto)
    last_semi_author = r"[A-Za-zÀ-Ÿ][A-Za-zÀ-ÿ\s'’-]{1,45},\s*(?:(?:(?:[A-Za-zÀ-Ÿ]\.|de|da|do|das|dos)\s*)+(?:\.\s*)?|[^.;()]{1,45}?(?:\((?:org|orgs|coor|coord|ed|eds)\.?\))?\.)"
    m = (
        re.match(rf"^(?P<autor>(?:[^;]{{3,75}};\s*)+{last_semi_author})\s+(?P<corpo>(?:[A-ZÀ-Ÿ\[][a-zà-ÿA-ZÀ-Ÿ0-9]|O\s|A\s).+)$", limpo, re.I)
        or re.match(r"^(?P<autor>[A-ZÀ-Ÿ][A-ZÀ-Ÿ\s'’-]+,\s*[^,;]{1,35},\s*e\s+[A-ZÀ-Ÿ][A-ZÀ-Ÿ\s'’-]+,\s*[^,;]{1,35})[.,]\s+(?P<corpo>.+)$", limpo, re.I)
        or re.match(r"^(?P<autor>[A-ZÀ-Ÿ][A-Za-zÀ-ÿ.,'’\s-]{2,55}?(?:\((?:org|orgs|coor|coord|ed|eds)\.?\)|,?\s*et\.?\s*al\.?))[.,]?\s+(?P<corpo>.+)$", limpo, re.I)
        or re.match(r"^(?P<autor>[A-ZÀ-Ÿ][A-ZÀ-Ÿ\s/()-]{2,85}(?:\.\s*(?:Secretaria|Minist[ée]rio|Associa[çc][ãa]o|Assembleia)[^.]{3,90}){0,2})\.\s+(?P<corpo>.+)$", limpo)
        or re.match(r"^(?P<autor>[A-ZÀ-Ÿ][A-ZÀ-Ÿ\s'’-]{1,50},\s*(?:(?:[A-ZÀ-Ÿ]\.\s*)+(?:(?:de|da|do|das|dos)\.?\s*(?:[A-ZÀ-Ÿ]\.\s*)*)?|[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\s'’-]{1,60}))[.,]?\s+(?P<corpo>(?:[A-ZÀ-Ÿ\[][a-zà-ÿA-ZÀ-Ÿ0-9]|O\s|A\s).+)$", limpo)
    )
    if not m or len(m.group("autor")) > 220 or re.search(r"\bIn[.:]?\s", m.group("autor")):
        return None
    autor_raw, corpo = m.group("autor").strip(" .,"), m.group("corpo").strip()
    titulo, resto = _separar_titulo_e_resto(corpo)
    if len(autor_raw) < 2 or len(titulo) < 4:
        return None
    veiculo = re.sub(r"\s*(?:Acesso\s+em|DOI)\s*:.*$", "", resto, flags=re.I).strip(" .,-–")
    return {
        "autor": formatar_nome_autor(autor_raw), "autor_citacao": autor_raw, "titulo": titulo,
        "ano": _extrair_ano(resto, limpo), "categoria": detectar_categoria(limpo, lista_id, link_obra),
        "veiculo_ou_ies": veiculo[:220], "parse_stage": "abnt",
    }


def parse_entrada(entrada: EntradaBruta, lista_id: str) -> dict:
    t = entrada.texto_limpo
    parsed: dict | None = None
    if m := _RE_CAPES.match(t):
        grau = m.group("grau").split(" em ")[0].strip()
        ies = m.group("ies").rsplit(",", 1)[0].strip()
        parsed = {
            "autor": formatar_nome_autor(m.group("autor")), "autor_citacao": m.group("autor").strip(),
            "titulo": m.group("titulo").strip(" .’'\"”“"), "ano": int(m.group("data").split("/")[-1]),
            "categoria": "Mestrado Profissional" if "profissional" in grau.lower() else ("Doutorado" if "doutor" in grau.lower() else "Mestrado"),
            "veiculo_ou_ies": ies, "parse_stage": "capes",
        }
    elif m := _RE_APA.match(t):
        autor_raw = m.group("autor").strip(" .,")
        titulo, resto = _separar_titulo_e_resto(m.group("resto").strip())
        if len(autor_raw) >= 2 and len(titulo) >= 3:
            parsed = {
                "autor": formatar_nome_autor(autor_raw), "autor_citacao": autor_raw, "titulo": titulo,
                "ano": int(m.group("ano")), "categoria": detectar_categoria(t, lista_id, entrada.link_obra),
                "veiculo_ou_ies": re.sub(r"\s*DOI\s*:.*$", "", resto, flags=re.I).strip(" .")[:220], "parse_stage": "apa",
            }
    if not parsed:
        parsed = _parse_abnt(t, lista_id, entrada.link_obra)
    if not parsed:
        parsed = {"autor": "", "autor_citacao": "", "titulo": t[:180], "ano": _extrair_ano("", t), "categoria": "Não classificado", "veiculo_ou_ies": "", "parse_stage": "fallback"}
    return {**parsed, "citacao_original": t, "chave_dedup": entrada.chave_dedup, "link_obra": entrada.link_obra, "link_lattes": entrada.link_lattes, "link_source": "html" if entrada.link_obra else "none"}
