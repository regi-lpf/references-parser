# Vitrine Bibliográfica LEME (`vitrine-bib`)

Extrator bibliográfico determinístico em Python (`>= 3.12`, `uv`) + vitrine web estática empacotada para WordPress/Elementor sem backend nem plugins.

## Estrutura do Projeto

- `src/vitrine_bib/`:
  - `models.py`: contratos Pydantic v2 (`RegistroBibliografico`, `VitrineOutput`, `ListaConfig`) e normalização.
  - `ingest.py`: ingestão DOM via `BeautifulSoup`, extração de `href`, separação `link_obra` vs. `link_lattes` e descarte de homepages genéricas.
  - `parser.py`: cascata determinística offline (`capes` → `apa` → `abnt` → `fallback`).
  - `enrich.py`: consulta seletiva à BDTD (similaridade `>= 0.88`, retry com backoff exponencial) e URL direta de busca no `busca-cv-lattes.cnpq.br` (`lzstring`).
  - `pipeline.py`: catálogo das listas, idempotência (`ref_XXXX`), proteção de `curado_humano: true`, auditoria CSV em `data/pendencias/` e CLI `vitrine-bib`.
- `frontend/`:
  - `styles.css`: CSS 100% escopado em `#vitrine-bib` (sem `backdrop-filter`).
  - `app.js`: vitrine client-side vanilla JS (busca sem acento com debounce, filtros combináveis, paginação, cópia de citação, exportação JSON e CSV UTF-8 BOM `;`).
  - `build_widget.py`: empacotador e validador `--check` gerando `public/widget-elementor.html` e `public/loader-elementor.html`.
- `public/`: JSONs estáticos validados + `widget-elementor.html` + `loader-elementor.html`.
- `data/pendencias/`: CSVs `<lista>_pendencias.csv` (removidos automaticamente ao zerar).
- `tests/`: testes unitários (`unittest`), validação estática do bundle e smoke E2E (`playwright`).

## Comandos

```bash
# Processar todas as listas offline (usando cache do JSON anterior)
uv run vitrine-bib --lista todas --offline

# Processar uma lista específica consultando a BDTD
uv run vitrine-bib --lista teses-dissertacoes

# Reprocessar inclusive registros marcados com curado_humano=true
uv run vitrine-bib --lista todas --offline --forcar-curados

# Empacotar e validar o bundle Elementor
uv run python frontend/build_widget.py
uv run python frontend/build_widget.py --check

# Executar testes unitários e smoke E2E
uv run python -m unittest discover -s tests -v
```

## Uso no WordPress / Elementor

Cole o conteúdo de `public/loader-elementor.html` em um bloco **HTML** do Elementor e ajuste apenas `data-json-url`, `data-titulo` e `data-categoria-label` por página.
