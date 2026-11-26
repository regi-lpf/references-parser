import argparse
import csv
from difflib import SequenceMatcher
import html
import json
import os
import re
import time
from urllib.parse import quote_plus, urlparse
from bs4 import BeautifulSoup
import requests

BDTD_API = "https://bdtd.ibict.br/vufind/api/v1/search"
PREPOSICOES = {
    "de",
    "da",
    "do",
    "das",
    "dos",
    "e",
    "em",
    "no",
    "na",
    "nos",
    "nas",
    "a",
    "o",
    "as",
    "os",
    "para",
    "por",
    "com",
}


# ---------------------------------------------------------
# 1. Camada de Ingestão (Unifica HTML <ul><li> e TXT puro)
# ---------------------------------------------------------
def classificar_url(url: str) -> tuple[str | None, str]:
    if not url:
        return None, "ausente"
    url = url.strip().rstrip(".,;)")
    parsed = urlparse(url)
    if not parsed.scheme.startswith("http"):
        return None, "invalida"

    path = parsed.path.strip("/")
    marcadores_profundos = (
        "handle/",
        "bitstream/",
        "jspui/",
        "tede/",
        "article/",
        "detalhes",
        "sucupira",
        "doi.org",
        "bdtd",
        "noticia/",
        ".pdf",
    )
    if (
        any(m in url.lower() for m in marcadores_profundos)
        or len(path.split("/")) >= 2
        or bool(parsed.query)
    ):
        return url, "link_direto_existente"

    if not path or (
        len(path.split("/")) == 1 and not any(c.isdigit() for c in path)
    ):
        return None, "rejeitada_homepage"

    return url, "link_existente_incerto"


def carregar_entradas_brutas(caminho: str) -> list[dict]:
    """Lê tanto arquivo .html (extraindo <li> e hrefs) quanto .txt linha a linha."""
    with open(caminho, "r", encoding="utf-8") as f:
        conteudo = f.read()

    # Detecta se é HTML pela presença de tags <li>
    if "<li" in conteudo.lower():
        soup = BeautifulSoup(conteudo, "html.parser")
        entradas = []
        for li in soup.find_all("li"):
            url_pub, url_lattes, status_url = None, None, "ausente"
            for a in li.find_all("a", href=True):
                href = a["href"].strip().rstrip(".,;)")
                if not href.startswith("http"):
                    continue
                if (
                    "lattes.cnpq.br" in href.lower()
                    or "escavador.com" in href.lower()
                ):
                    url_lattes = href
                elif not url_pub:
                    url_valida, st = classificar_url(href)
                    if url_valida:
                        url_pub, status_url = url_valida, st
                    elif st == "rejeitada_homepage" and status_url == "ausente":
                        status_url = st

                if a.get_text(strip=True).lower() in (
                    "link",
                    "acesse",
                    "aqui",
                ) or a.get_text(strip=True).startswith("http"):
                    a.decompose()

            texto = html.unescape(li.get_text(" ", strip=True))
            texto = re.sub(r"\s+", " ", texto).strip()
            texto = re.sub(
                r"\s*Disponível em:?\s*\.?$", "", texto, flags=re.IGNORECASE
            ).strip()
            if len(texto) >= 20:
                entradas.append({
                    "texto": texto,
                    "url_pub": url_pub,
                    "url_lattes": url_lattes,
                    "status_url": status_url,
                })
        return entradas

    # Fallback para arquivo TXT puro
    entradas = []
    for linha in conteudo.splitlines():
        linha = linha.strip()
        if not linha:
            continue
        match_url = re.search(r"(https?://[^\s<>\"']+)", linha)
        url_pub, status_url = None, "ausente"
        if match_url:
            url_bruta = match_url.group(1)
            linha = linha.replace(url_bruta, "").strip()
            url_pub, status_url = classificar_url(url_bruta)
        entradas.append({
            "texto": linha,
            "url_pub": url_pub,
            "url_lattes": None,
            "status_url": status_url,
        })
    return entradas


# ---------------------------------------------------------
# 2. Camada de Parsing Unificado (CAPES -> ABNT/APA)
# ---------------------------------------------------------
def formatar_nome_autor(autor_caps: str) -> str:
    if "," in autor_caps:
        sobrenome, prenome = [p.strip() for p in autor_caps.split(",", 1)]
        nome_completo = f"{prenome} {sobrenome}"
    else:
        nome_completo = autor_caps.strip()

    palavras = nome_completo.lower().split()
    return " ".join(
        p if (i > 0 and p in PREPOSICOES) else p.capitalize()
        for i, p in enumerate(palavras)
    )


def detectar_tipo(texto: str) -> str:
    t = texto.lower()
    if "doutorado" in t or "tese" in t:
        return "Doutorado"
    if "mestrado profissional" in t:
        return "Mestrado Profissional"
    if "mestrado" in t or "dissertação" in t:
        return "Mestrado"
    if " in." in t or " in:" in t or "org." in t:
        return "Capítulo de Livro"
    if "relatório" in t or "pós-doutoral" in t:
        return "Relatório de Pesquisa"
    if re.search(r"\b(v\.\s*\d+|n\.\s*\d+|doi:|issn)\b", t) or re.search(
        r"\(\d{4}\)", t
    ):
        return "Artigo em Periódico"
    if re.search(r"\d{2}/\d{2}/\d{4}", t):
        return "Notícia / Imprensa"
    return "Produção Bibliográfica"


def parse_registro(entrada: dict, ref_id: str) -> dict | None:
    texto = entrada["texto"]

    # Estágio 1: Padrão Sucupira/CAPES
    m_capes = re.match(
        r"^(?P<autor>[A-ZÀ-Ÿ][A-ZÀ-Ÿ\s'-]+,\s*[A-Za-zÀ-ÿ\s.'-]+?)\.\s*"
        r"(?P<titulo>.+?)[.'’\"]*\s+"
        r"(?P<data>\d{2}/\d{2}/\d{4})\s+"
        r"(?P<paginas>(?:\d+|undefined))\s*f\.\s+"
        r"(?P<grau_prog>.+?)\s+"
        r"Instituição de Ensino:\s*(?P<ies>.+?)"
        r"(?:\s+Biblioteca Depositária:\s*(?P<bib>.+?)\.?)?$",
        texto,
    )
    if m_capes:
        autor_bruto = m_capes.group("autor").strip()
        grau_prog = m_capes.group("grau_prog").strip()
        ies_raw = m_capes.group("ies").strip()
        return {
            "id": ref_id,
            "autor": formatar_nome_autor(autor_bruto),
            "autor_citacao": autor_bruto,
            "titulo": m_capes.group("titulo").strip(" .’'\""),
            "ano": int(m_capes.group("data").split("/")[-1]),
            "grau": (
                grau_prog.split(" em ")[0].strip()
                if " em " in grau_prog
                else grau_prog
            ),
            "ies": ies_raw.rsplit(",", 1)[0].strip() if "," in ies_raw else ies_raw,
            "url_publicacao": entrada["url_pub"],
            "url_lattes": entrada["url_lattes"],
            "origem_url": entrada["status_url"],
        }

    # Estágio 2: Padrão APA ("Sobrenome, I. (2020). Título. Revista...")
    m_apa = re.match(
        r"^(?P<autor>.+?)\s*\((?P<ano>19\d{2}|20\d{2})\)\.\s*(?P<titulo>[^.]+)\.\s*(?P<resto>.*)$",
        texto,
    )
    if m_apa:
        autor_bruto = m_apa.group("autor").strip(" .,")
        resto = m_apa.group("resto").strip(" .")
        return {
            "id": ref_id,
            "autor": autor_bruto,
            "autor_citacao": autor_bruto,
            "titulo": m_apa.group("titulo").strip(),
            "ano": int(m_apa.group("ano")),
            "grau": detectar_tipo(texto),
            "ies": resto[:140] + "..." if len(resto) > 140 else resto,
            "citacao_completa": texto,
            "url_publicacao": entrada["url_pub"],
            "url_lattes": entrada["url_lattes"],
            "origem_url": entrada["status_url"],
        }

    # Estágio 3: Padrão ABNT / Geral (autores em caixa alta ou institucional + título + ano)
    anos = re.findall(r"\b(19\d{2}|20\d{2})\b", texto)
    if anos:
        ano = int(anos[-1])
        m_abnt = re.match(
            r"^(?P<autor>(?:[A-ZÀ-Ÿ][A-Za-zÀ-ÿ'-]+,\s*(?:[A-ZÀ-Ÿ]\.\s*|[A-Za-zÀ-ÿ'-]+\s*)+;?\s*)+)\.\s+"
            r"(?P<titulo>[^.?!]+[?!]?)\.\s*(?P<resto>.*)$",
            texto,
        )
        if m_abnt:
            autor_bruto = m_abnt.group("autor").strip(" .;")
            titulo = m_abnt.group("titulo").strip()
            resto = m_abnt.group("resto").strip(" .")
        else:
            partes = [p.strip() for p in texto.split(". ") if p.strip()]
            autor_bruto = partes[0] if len(partes) >= 2 else "Autor não identificado"
            titulo = partes[1] if len(partes) >= 2 else texto
            resto = ". ".join(partes[2:]) if len(partes) >= 3 else ""

        return {
            "id": ref_id,
            "autor": autor_bruto,
            "autor_citacao": autor_bruto,
            "titulo": titulo,
            "ano": ano,
            "grau": detectar_tipo(texto),
            "ies": resto[:140] + "..." if len(resto) > 140 else resto,
            "citacao_completa": texto,
            "url_publicacao": entrada["url_pub"],
            "url_lattes": entrada["url_lattes"],
            "origem_url": entrada["status_url"],
        }

    return None


# ---------------------------------------------------------
# 3. Enriquecimento BDTD + Execução Incremental
# ---------------------------------------------------------
def buscar_na_bdtd(titulo: str) -> str | None:
    params = {
        "lookfor": titulo,
        "type": "Title",
        "limit": 3,
        "field[]": ["title", "url", "id"],
    }
    try:
        resp = requests.get(BDTD_API, params=params, timeout=12)
        if resp.status_code != 200:
            return None
        for rec in resp.json().get("records", []):
            sim = SequenceMatcher(
                None, titulo.lower(), rec.get("title", "").lower()
            ).ratio()
            if sim >= 0.88:
                urls = rec.get("url", [])
                if isinstance(urls, list) and urls:
                    return urls[0]
                if isinstance(urls, str) and urls.startswith("http"):
                    return urls
                if rec.get("id"):
                    return f"https://bdtd.ibict.br/vufind/Record/{rec['id']}"
    except requests.RequestException:
        return None
    return None


def main():
    parser = argparse.ArgumentParser(description="Pipeline unificado de referências LEME")
    parser.add_argument("-i", "--input", default="referencias_brutas.txt", help="Arquivo .html ou .txt")
    parser.add_argument("-o", "--output", default="referencias.json", help="JSON de saída")
    parser.add_argument("-c", "--csv", default="pendencias_revisao.csv", help="CSV de pendências")
    parser.add_argument("--prefix", default="ref", help="Prefixo dos IDs (ex: ref, prod, art)")
    parser.add_argument("--skip-bdtd", action="store_true", help="Não consultar API da BDTD")
    args = parser.parse_args()

    cache = {}
    if os.path.exists(args.output):
        with open(args.output, "r", encoding="utf-8") as f:
            cache = {item["id"]: item for item in json.load(f) if "id" in item}

    entradas = carregar_entradas_brutas(args.input)
    resultados, anomalias = [], []
    pulados, consultas_bdtd = 0, 0

    for idx, entrada in enumerate(entradas, start=1):
        ref_id = f"{args.prefix}_{idx:04d}"
        previo = cache.get(ref_id)

        if previo and previo.get("url_publicacao"):
            resultados.append(previo)
            pulados += 1
            continue

        item = previo if previo else parse_registro(entrada, ref_id)
        if not item:
            anomalias.append({"id": ref_id, "conteudo": entrada["texto"]})
            continue

        # Se a nova entrada HTML trouxe um link que antes não existia no cache
        if not item.get("url_publicacao") and entrada.get("url_pub"):
            item["url_publicacao"] = entrada["url_pub"]
            item["origem_url"] = entrada["status_url"]

        if (
            not item.get("url_publicacao")
            and not args.skip_bdtd
            and item.get("grau") in ("Doutorado", "Mestrado", "Mestrado Profissional")
        ):
            url_bdtd = buscar_na_bdtd(item["titulo"])
            consultas_bdtd += 1
            if url_bdtd:
                item["url_publicacao"] = url_bdtd
                item["origem_url"] = "bdtd_api"
            time.sleep(0.35)

        resultados.append(item)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(resultados, f, ensure_ascii=False, indent=2)

    with open(args.csv, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "status", "autor", "titulo", "ano", "busca_google"])
        for a in anomalias:
            writer.writerow([a["id"], "falha_parse", "", a["conteudo"], "", ""])
        for r in resultados:
            if not r.get("url_publicacao"):
                q = quote_plus(f'"{r["titulo"]}" "{r["autor"]}"')
                writer.writerow([
                    r["id"],
                    r["origem_url"],
                    r["autor"],
                    r["titulo"],
                    r["ano"],
                    f"https://www.google.com/search?q={q}",
                ])

    total_links = sum(1 for r in resultados if r.get("url_publicacao"))
    print(f"[{args.input}] Extraídos: {len(resultados)}/{len(entradas)} | Pulados (cache): {pulados} | Novas BDTD: {consultas_bdtd} | Com link: {total_links} | Anomalias: {len(anomalias)}")


if __name__ == "__main__":
    main()