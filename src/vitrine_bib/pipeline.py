"""Pipeline bibliográfico idempotente, auditoria CSV e CLI multilista."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import time
from urllib.parse import quote_plus

import requests

from vitrine_bib.enrich import buscar_na_bdtd, gerar_url_lattes
from vitrine_bib.ingest import carregar_html
from vitrine_bib.models import THESIS_CATEGORIES, ListaConfig, RegistroBibliografico, VitrineOutput, normalizar_texto
from vitrine_bib.parser import parse_entrada

LISTAS: dict[str, ListaConfig] = {
    "teses-dissertacoes": ListaConfig(
        lista_id="teses-dissertacoes",
        titulo="Teses e Dissertações",
        categoria_label="Grau",
        input_html="lista1.html",
        output_json="public/teses-dissertacoes.json",
        pendencias_csv="data/pendencias/teses-dissertacoes_pendencias.csv",
        enriquecer_bdtd=True,
    ),
    "producao-academica": ListaConfig(
        lista_id="producao-academica",
        titulo="Produção Acadêmica",
        categoria_label="Tipo",
        input_html="lista2.html",
        output_json="public/producao-academica.json",
        pendencias_csv="data/pendencias/producao-academica_pendencias.csv",
        enriquecer_bdtd=True,
    ),
    "documentos-oficiais": ListaConfig(
        lista_id="documentos-oficiais",
        titulo="Documentos Oficiais e Legislação",
        categoria_label="Tipo",
        input_html="lista3.html",
        output_json="public/documentos-oficiais.json",
        pendencias_csv="data/pendencias/documentos-oficiais_pendencias.csv",
        enriquecer_bdtd=False,
    ),
}


@dataclass(frozen=True)
class ResumoExecucao:
    lista_id: str
    total_registros: int
    estagios: dict[str, int]
    links_html: int
    links_bdtd: int
    sem_link: int
    reaproveitados_cache: int
    preservados_curados: int
    novas_consultas_bdtd: int
    pendencias: int
    csv_removido: bool


def _carregar_cache(output_json: Path) -> tuple[dict[str, dict], dict[tuple[str, str], dict], int]:
    por_dedup: dict[str, dict] = {}
    por_at: dict[tuple[str, str], dict] = {}
    max_num = 0
    if not output_json.exists():
        return por_dedup, por_at, 0

    raw = json.loads(output_json.read_text(encoding="utf-8"))
    itens = raw.get("registros", []) if isinstance(raw, dict) else raw
    for item in itens:
        if m := re.match(r"^ref_(\d+)$", item.get("id", "")):
            max_num = max(max_num, int(m.group(1)))
        if item.get("chave_dedup"):
            por_dedup[item["chave_dedup"]] = item
        na, nt = normalizar_texto(item.get("autor")), normalizar_texto(item.get("titulo"))
        if na and nt:
            por_at[(na, nt)] = item
    return por_dedup, por_at, max_num


def _atualizar_csv_pendencias(csv_path: Path, registros: list[RegistroBibliografico]) -> tuple[int, bool]:
    linhas: list[list[str]] = []
    for r in registros:
        motivos = [
            m for cond, m in (
                (r.parse_stage == "fallback", "parse_fallback"),
                (not r.autor.strip(), "autor_ausente"),
                (not r.titulo.strip(), "titulo_ausente"),
                (r.ano is None, "ano_ausente"),
                (r.categoria in THESIS_CATEGORIES and not r.link_obra, "tese_sem_link"),
            ) if cond
        ]
        if motivos:
            q = quote_plus(f'"{r.titulo}" "{r.autor}"'.strip())
            linhas.append([r.id, ",".join(motivos), r.parse_stage, r.categoria, r.autor, r.titulo, str(r.ano or ""), r.veiculo_ou_ies, f"https://www.google.com/search?q={q}"])
    if not linhas:
        if csv_path.exists():
            csv_path.unlink()
            return 0, True
        return 0, False
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "motivos", "parse_stage", "categoria", "autor", "titulo", "ano", "veiculo_ou_ies", "busca_google"])
        w.writerows(linhas)
    return len(linhas), False


def processar_lista(
    config: ListaConfig,
    *,
    base_dir: Path | None = None,
    offline: bool = False,
    forcar_curados: bool = False,
    bdtd_delay: float = 0.35,
    bdtd_fn=buscar_na_bdtd,
    sleep_fn=time.sleep,
) -> ResumoExecucao:
    root = base_dir or Path.cwd()
    output_path, csv_path = root / config.output_json, root / config.pendencias_csv
    cache_dedup, cache_at, max_num = _carregar_cache(output_path)
    entradas = carregar_html(root / config.input_html)

    next_num, usados = max_num + 1, set()
    registros: list[RegistroBibliografico] = []
    reaproveitados = curados = novas_bdtd = 0
    sess = requests.Session() if (not offline and config.enriquecer_bdtd and bdtd_fn is buscar_na_bdtd) else None
    try:
        for entrada in entradas:
            parsed = parse_entrada(entrada, config.lista_id)
            prev = cache_dedup.get(entrada.chave_dedup) or cache_at.get((normalizar_texto(parsed["autor"]), normalizar_texto(parsed["titulo"])))
            if prev and prev.get("id") and prev["id"] not in usados:
                ref_id = prev["id"]
            else:
                while f"ref_{next_num:04d}" in usados:
                    next_num += 1
                ref_id = f"ref_{next_num:04d}"
                next_num += 1
            usados.add(ref_id)

            if prev and prev.get("curado_humano") is True and not forcar_curados:
                registros.append(RegistroBibliografico.model_validate({**prev, "id": ref_id, "chave_dedup": prev.get("chave_dedup") or entrada.chave_dedup}))
                curados += 1
                continue

            link_obra, link_source = parsed["link_obra"], parsed["link_source"]
            if not link_obra and prev and (prev_link := prev.get("link_obra") or prev.get("url_publicacao")):
                link_obra = prev_link
                link_source = prev["link_source"] if prev.get("link_source") in ("html", "bdtd", "manual") else ("bdtd" if prev.get("origem_url") == "bdtd_api" else "html")
                reaproveitados += 1

            if not offline and config.enriquecer_bdtd and parsed["categoria"] in THESIS_CATEGORIES and not link_obra and parsed["titulo"]:
                if novas_bdtd > 0 and bdtd_delay > 0:
                    sleep_fn(bdtd_delay)
                url_bdtd = bdtd_fn(parsed["titulo"], session=sess) if bdtd_fn is buscar_na_bdtd else bdtd_fn(parsed["titulo"])
                novas_bdtd += 1
                if url_bdtd:
                    link_obra, link_source = url_bdtd, "bdtd"

            registros.append(RegistroBibliografico.model_validate({
                **parsed,
                "id": ref_id,
                "link_obra": link_obra,
                "link_lattes": parsed["link_lattes"] or gerar_url_lattes(parsed["autor"]),
                "link_source": link_source,
                "curado_humano": bool(prev.get("curado_humano", False)) if prev and not forcar_curados else False,
            }))
    finally:
        if sess:
            sess.close()

    saida = VitrineOutput.model_validate({
        "schema_version": "1.0", "lista_id": config.lista_id, "titulo": config.titulo, "categoria_label": config.categoria_label,
        "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"), "total": len(registros), "registros": [r.model_dump() for r in registros],
    })
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = output_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(saida.model_dump(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(output_path)

    qtd_pend, csv_rem = _atualizar_csv_pendencias(csv_path, registros)
    estagios = {k: sum(1 for r in registros if r.parse_stage == k) for k in ("capes", "apa", "abnt", "fallback")}
    return ResumoExecucao(
        config.lista_id, len(registros), estagios,
        sum(1 for r in registros if r.link_source == "html"),
        sum(1 for r in registros if r.link_source == "bdtd"),
        sum(1 for r in registros if r.link_source == "none"),
        reaproveitados, curados, novas_bdtd, qtd_pend, csv_rem,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="vitrine-bib", description="Extrator bibliográfico determinístico + BDTD/Lattes")
    ap.add_argument("--lista", default="todas", choices=[*LISTAS.keys(), "todas"])
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--forcar-curados", action="store_true")
    ap.add_argument("--bdtd-delay", type=float, default=0.35)
    ap.add_argument("--base-dir", type=Path, default=Path.cwd())
    args = ap.parse_args(argv)
    for cfg in (list(LISTAS.values()) if args.lista == "todas" else [LISTAS[args.lista]]):
        r = processar_lista(cfg, base_dir=args.base_dir, offline=args.offline, forcar_curados=args.forcar_curados, bdtd_delay=args.bdtd_delay)
        print(f"[{r.lista_id}] registros={r.total_registros} | estagios={r.estagios} | links(html={r.links_html}, bdtd={r.links_bdtd}, none={r.sem_link}) | cache={r.reaproveitados_cache} curados={r.preservados_curados} novas_bdtd={r.novas_consultas_bdtd} | pendencias={r.pendencias}" + (" (CSV removido)" if r.csv_removido else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
