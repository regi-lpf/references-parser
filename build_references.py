import csv
from difflib import SequenceMatcher
import json
import re
import time
from urllib.parse import quote_plus, urlparse
import requests

# Configurações
INPUT_FILE = "referencias_brutas.txt"
OUTPUT_JSON = "referencias.json"
OUTPUT_CSV = "pendencias_revisao.csv"
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


def formatar_nome_autor(autor_caps: str) -> str:
    """Converte 'SOBRENOME, NOME DO MEIO' para 'Nome do Meio Sobrenome'."""
    if "," in autor_caps:
        sobrenome, prenome = [p.strip() for p in autor_caps.split(",", 1)]
        nome_completo = f"{prenome} {sobrenome}"
    else:
        nome_completo = autor_caps.strip()

    palavras = nome_completo.lower().split()
    formatadas = [
        p if (i > 0 and p in PREPOSICOES) else p.capitalize()
        for i, p in enumerate(palavras)
    ]
    return " ".join(formatadas)


def classificar_url(url: str) -> tuple[str | None, str]:
    """Distingue links profundos (handle, pdf, tede) de homepages genéricas."""
    if not url:
        return None, "ausente"

    url = url.strip().rstrip(".,;)")
    parsed = urlparse(url)
    if not parsed.scheme.startswith("http"):
        return None, "invalida"

    path = parsed.path.strip("/")
    query = parsed.query

    # Sinais fortes de link direto para documento/registro
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
        ".pdf",
    )
    if (
        any(m in url.lower() for m in marcadores_profundos)
        or len(path.split("/")) >= 2
        or bool(query)
    ):
        return url, "link_direto_existente"

    # Se o path é vazio ou tem apenas 1 segmento curto sem número (ex: /ppge), trata como homepage
    if not path or (
        len(path.split("/")) == 1 and not any(c.isdigit() for c in path)
    ):
        return None, "rejeitada_homepage"

    return url, "link_existente_incerto"


def extrair_url_da_linha(linha: str) -> tuple[str, str | None, str]:
    """Remove qualquer URL embutida na linha antes do parsing textual e a classifica."""
    match_url = re.search(r"(https?://[^\s<>\"']+)", linha)
    if not match_url:
        return linha, None, "ausente"

    url_bruta = match_url.group(1)
    linha_limpa = linha.replace(url_bruta, "").strip()
    url_valida, status = classificar_url(url_bruta)
    return linha_limpa, url_valida, status


def parse_linha_capes(linha: str, idx: int) -> dict | None:
    linha_sem_url, url_existente, status_url = extrair_url_da_linha(linha)

    # Padrão principal da exportação Sucupira/CAPES
    padrao = re.compile(
        r"^(?P<autor>[A-ZÀ-Ÿ\s,'-]+?)\.\s+"
        r"(?P<titulo>.+?)[.'’\"]*\s+"
        r"(?P<data>\d{2}/\d{2}/\d{4})\s+"
        r"(?P<paginas>(?:\d+|undefined))\s*f\.\s+"
        r"(?P<grau_prog>.+?)\s+"
        r"Instituição de Ensino:\s*(?P<ies>.+?)"
        r"(?:\s+Biblioteca Depositária:\s*(?P<bib>.+?)\.?)?$"
    )

    m = padrao.match(linha_sem_url)
    if not m:
        return None

    autor_bruto = m.group("autor").strip()
    titulo = m.group("titulo").strip(" .’'\"")
    data = m.group("data")
    ano = int(data.split("/")[-1])
    grau_prog = m.group("grau_prog").strip()
    ies_raw = m.group("ies").strip()

    # Separa Grau (ex: Doutorado / Mestrado Profissional) de Programa
    grau = (
        grau_prog.split(" em ")[0].strip() if " em " in grau_prog else grau_prog
    )
    # Remove cidade após a última vírgula da IES, se houver
    ies = ies_raw.rsplit(",", 1)[0].strip() if "," in ies_raw else ies_raw

    return {
        "id": f"ref_{idx:04d}",
        "autor": formatar_nome_autor(autor_bruto),
        "autor_citacao": autor_bruto,
        "titulo": titulo,
        "ano": ano,
        "data_defesa": data,
        "grau": grau,
        "ies": ies,
        "url_publicacao": url_existente,
        "origem_url": status_url,
    }


def similaridade(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def buscar_na_bdtd(titulo: str, ano: int) -> str | None:
    """Consulta a API pública da BDTD pelo título e valida por similaridade."""
    params = {
        "lookfor": titulo,
        "type": "Title",
        "limit": 3,
        "field[]": ["title", "publishDate", "url", "id"],
    }
    try:
        resp = requests.get(BDTD_API, params=params, timeout=12)
        if resp.status_code != 200:
            return None
        records = resp.json().get("records", [])
        for rec in records:
            rec_title = rec.get("title", "")
            if similaridade(titulo, rec_title) >= 0.88:
                urls = rec.get("url", [])
                if isinstance(urls, list) and urls:
                    return urls[0]
                if isinstance(urls, str) and urls.startswith("http"):
                    return urls
                # Fallback: página do registro na própria BDTD
                rec_id = rec.get("id")
                if rec_id:
                    return f"https://bdtd.ibict.br/vufind/Record/{rec_id}"
    except requests.RequestException:
        return None
    return None


def main():
    resultados = []
    anomalias = []

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        linhas = [l.strip() for l in f if l.strip()]

    print(f"Processando {len(linhas)} linhas...")

    for idx, linha in enumerate(linhas, start=1):
        item = parse_linha_capes(linha, idx)
        if not item:
            anomalias.append({
                "linha_num": idx,
                "motivo": "falha_regex",
                "conteudo": linha,
            })
            continue

        # Se não havia link profundo válido na lista original, consulta a BDTD
        if not item["url_publicacao"]:
            url_bdtd = buscar_na_bdtd(item["titulo"], item["ano"])
            if url_bdtd:
                item["url_publicacao"] = url_bdtd
                item["origem_url"] = "bdtd_api"
            time.sleep(0.35)  # Respeita rate limit da API pública

        resultados.append(item)

        if idx % 50 == 0:
            encontrados = sum(1 for r in resultados if r["url_publicacao"])
            print(
                f"[{idx}/{len(linhas)}] Parseados: {len(resultados)} | Com link: {encontrados}"
            )

    # Salva JSON final para o GitHub / Elementor
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(resultados, f, ensure_ascii=False, indent=2)

    # Salva CSV de pendências e anomalias para revisão futura
    with open(OUTPUT_CSV, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "id",
            "status",
            "autor",
            "titulo",
            "ano",
            "ies",
            "busca_rapida_google",
        ])
        for a in anomalias:
            writer.writerow([
                f"linha_{a['linha_num']}",
                a["motivo"],
                "",
                a["conteudo"],
                "",
                "",
                "",
            ])
        for r in resultados:
            if not r["url_publicacao"]:
                q = quote_plus(f'"{r["titulo"]}" "{r["autor"]}"')
                writer.writerow([
                    r["id"],
                    r["origem_url"],
                    r["autor"],
                    r["titulo"],
                    r["ano"],
                    r["ies"],
                    f"https://www.google.com/search?q={q}",
                ])

    total_links = sum(1 for r in resultados if r["url_publicacao"])
    print("\n--- Concluído ---")
    print(f"Total extraído: {len(resultados)}/{len(linhas)}")
    print(f"Com link de publicação: {total_links}")
    print(f"Anomalias de parsing: {len(anomalias)}")


if __name__ == "__main__":
    main()