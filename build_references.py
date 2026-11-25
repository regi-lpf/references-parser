import csv
from difflib import SequenceMatcher
import json
import os
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


def carregar_cache_existente(caminho_json: str) -> dict[str, dict]:
    """Carrega registros já processados em execuções anteriores indexados por ID."""
    if not os.path.exists(caminho_json):
        return {}
    try:
        with open(caminho_json, "r", encoding="utf-8") as f:
            dados = json.load(f)
        return {item["id"]: item for item in dados if "id" in item}
    except (json.JSONDecodeError, OSError):
        return {}


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

    if path or (
        len(path.split("/")) == 1 and not any(c.isdigit() for c in path)
    ):
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

    # Estágio 1: Padrão CAPES (aceita prenome em Title Case e falta de espaço após ponto do autor)
    padrao_capes = re.compile(
        r"^(?P<autor>[A-ZÀ-Ÿ][A-ZÀ-Ÿ\s'-]+,\s*[A-Za-zÀ-ÿ\s.'-]+?)\.\s*"
        r"(?P<titulo>.+?)[.'’\"]*\s+"
        r"(?P<data>\d{2}/\d{2}/\d{4})\s+"
        r"(?P<paginas>(?:\d+|undefined))\s*f\.\s+"
        r"(?P<grau_prog>.+?)\s+"
        r"Instituição de Ensino:\s*(?P<ies>.+?)"
        r"(?:\s+Biblioteca Depositária:\s*(?P<bib>.+?)\.?)?$"
    )

    m = padrao_capes.match(linha_sem_url)
    if m:
        autor_bruto = m.group("autor").strip()
        titulo = m.group("titulo").strip(" .’'\"")
        data = m.group("data")
        ano = int(data.split("/")[-1])
        grau_prog = m.group("grau_prog").strip()
        ies_raw = m.group("ies").strip()

        grau = (
            grau_prog.split(" em ")[0].strip()
            if " em " in grau_prog
            else grau_prog
        )
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

    # Estágio 2: Fallback para citações em formato ABNT livre
    padrao_abnt = re.compile(
        r"^(?P<autor>[A-ZÀ-Ÿ][A-ZÀ-Ÿ\s'-]+,\s*[A-Za-zÀ-ÿ\s.'-]+?)\.\s*"
        r"(?P<titulo>.+?)\.\s+"
        r"(?:\d{2}/\d{2}/)?(?P<ano>19\d{2}|20\d{2})\b.*?"
        r"(?P<grau>Tese|Dissertação|Mestrado|Doutorado)\b",
        re.IGNORECASE,
    )

    m2 = padrao_abnt.match(linha_sem_url)
    if m2:
        autor_bruto = m2.group("autor").strip()
        titulo = m2.group("titulo").strip(" .’'\"")
        ano = int(m2.group("ano"))
        grau_raw = m2.group("grau").lower()
        grau = "Doutorado" if grau_raw in ("tese", "doutorado") else "Mestrado"

        return {
            "id": f"ref_{idx:04d}",
            "autor": formatar_nome_autor(autor_bruto),
            "autor_citacao": autor_bruto,
            "titulo": titulo,
            "ano": ano,
            "data_defesa": str(ano),
            "grau": grau,
            "ies": "Não especificada (ABNT)",
            "url_publicacao": url_existente,
            "origem_url": status_url,
        }

    return None


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
                rec_id = rec.get("id")
                if rec_id:
                    return f"https://bdtd.ibict.br/vufind/Record/{rec_id}"
    except requests.RequestException:
        return None
    return None


def main():
    cache = carregar_cache_existente(OUTPUT_JSON)
    resultados = []
    anomalias = []
    pulados = 0
    novas_consultas_bdtd = 0

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        linhas = [l.strip() for l in f if l.strip()]

    print(
        f"Processando {len(linhas)} linhas (cache carregado: {len(cache)} registros)..."
    )

    for idx, linha in enumerate(linhas, start=1):
        ref_id = f"ref_{idx:04d}"
        registro_previo = cache.get(ref_id)

        # Se já existe no JSON e já tem URL verificada, pula sem reprocessar
        if registro_previo and registro_previo.get("url_publicacao"):
            resultados.append(registro_previo)
            pulados += 1
            continue

        # Caso contrário, faz o parse (ou reaproveita metadados prévios sem link)
        item = registro_previo if registro_previo else parse_linha_capes(linha, idx)
        if not item:
            anomalias.append({
                "linha_num": idx,
                "motivo": "falha_regex",
                "conteudo": linha,
            })
            continue

        # Consulta a BDTD apenas se ainda não houver link válido
        if not item.get("url_publicacao"):
            url_bdtd = buscar_na_bdtd(item["titulo"], item["ano"])
            novas_consultas_bdtd += 1
            if url_bdtd:
                item["url_publicacao"] = url_bdtd
                item["origem_url"] = "bdtd_api"
            time.sleep(0.35)

        resultados.append(item)

    # Salva JSON atualizado mantendo a ordem original
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(resultados, f, ensure_ascii=False, indent=2)

    # Regera CSV apenas com o que ainda está pendente
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
            if not r.get("url_publicacao"):
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

    total_links = sum(1 for r in resultados if r.get("url_publicacao"))
    print("\n--- Concluído ---")
    print(f"Pulados (já tinham link): {pulados}")
    print(f"Novas consultas BDTD realizadas: {novas_consultas_bdtd}")
    print(f"Total extraído no JSON: {len(resultados)}/{len(linhas)}")
    print(f"Total com link de publicação: {total_links}")
    print(f"Anomalias restantes: {len(anomalias)}")


if __name__ == "__main__":
    main()