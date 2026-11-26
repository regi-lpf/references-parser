"""Smoke test E2E com Playwright para index.html e fluxo loader -> widget Elementor."""

from __future__ import annotations

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import unittest

from vitrine_bib.models import VitrineOutput

ROOT_DIR = Path(__file__).resolve().parent.parent


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return


def _playwright_disponivel() -> tuple[bool, str]:
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except Exception as exc:
        return False, f"playwright não instalado: {exc}"
    return True, ""


class TestE2ESmoke(unittest.TestCase):
    def _fixture_output(self) -> dict:
        payload = {
            "schema_version": "1.0",
            "lista_id": "teses-dissertacoes",
            "titulo": "Vitrine Teste E2E",
            "categoria_label": "Grau",
            "gerado_em": "2026-11-26T00:00:00+00:00",
            "total": 3,
            "registros": [
                {
                    "id": "ref_0001",
                    "chave_dedup": "1111111111111111",
                    "autor": "Maria João da Silva",
                    "autor_citacao": "SILVA, Maria João da",
                    "titulo": "Educação Profissional e Inclusão Escolar",
                    "ano": 2022,
                    "categoria": "Doutorado",
                    "veiculo_ou_ies": "UFSC",
                    "citacao_original": "SILVA, Maria João da. Educação Profissional e Inclusão Escolar. 2022.",
                    "link_obra": "https://repositorio.ufsc.br/handle/123/1",
                    "link_lattes": "https://busca-cv-lattes.cnpq.br/busca?keyword=Maria&mode=NOME&q=abc",
                    "parse_stage": "capes",
                    "link_source": "html",
                    "curado_humano": False,
                },
                {
                    "id": "ref_0002",
                    "chave_dedup": "2222222222222222",
                    "autor": "Carlos Eduardo Souza",
                    "autor_citacao": "SOUZA, Carlos Eduardo",
                    "titulo": "Gestão Democrática na Rede Federal",
                    "ano": 2020,
                    "categoria": "Mestrado",
                    "veiculo_ou_ies": "IFC",
                    "citacao_original": "SOUZA, Carlos Eduardo. Gestão Democrática na Rede Federal. 2020.",
                    "link_obra": None,
                    "link_lattes": "https://busca-cv-lattes.cnpq.br/busca?keyword=Carlos&mode=NOME&q=def",
                    "parse_stage": "capes",
                    "link_source": "none",
                    "curado_humano": False,
                },
                {
                    "id": "ref_0003",
                    "chave_dedup": "3333333333333333",
                    "autor": "Ana Paula Pereira",
                    "autor_citacao": "PEREIRA, Ana Paula",
                    "titulo": "Currículo Integrado no Ensino Médio",
                    "ano": 2022,
                    "categoria": "Mestrado Profissional",
                    "veiculo_ou_ies": "IFSC",
                    "citacao_original": "PEREIRA, Ana Paula. Currículo Integrado no Ensino Médio. 2022.",
                    "link_obra": "https://repositorio.ifsc.edu.br/handle/123/3",
                    "link_lattes": None,
                    "parse_stage": "capes",
                    "link_source": "bdtd",
                    "curado_humano": False,
                },
            ],
        }
        validated = VitrineOutput.model_validate(payload)
        return validated.model_dump()

    def _preparar_servidor(self, tmp_dir: Path) -> tuple[ThreadingHTTPServer, str]:
        shutil.copy2(ROOT_DIR / "index.html", tmp_dir / "index.html")
        shutil.copytree(ROOT_DIR / "frontend", tmp_dir / "frontend")
        (tmp_dir / "public").mkdir()
        shutil.copy2(ROOT_DIR / "public" / "widget-elementor.html", tmp_dir / "public" / "widget-elementor.html")

        fixture = self._fixture_output()
        (tmp_dir / "public" / "teses-dissertacoes.json").write_text(
            json.dumps(fixture, ensure_ascii=False), encoding="utf-8"
        )
        prod_fixture = VitrineOutput.model_validate({
            "schema_version": "1.0",
            "lista_id": "producao-academica",
            "titulo": "Produção Acadêmica",
            "categoria_label": "Tipo",
            "gerado_em": "2026-11-26T00:00:00+00:00",
            "total": 1,
            "registros": [
                {
                    "id": "ref_0001",
                    "chave_dedup": "4444444444444444",
                    "autor": "Autor Artigo",
                    "autor_citacao": "AUTOR, A.",
                    "titulo": "Artigo Exemplo de Produção Acadêmica",
                    "ano": 2023,
                    "categoria": "Artigo",
                    "veiculo_ou_ies": "Revista EPT",
                    "citacao_original": "AUTOR, A. Artigo Exemplo de Produção Acadêmica. Revista EPT, 2023.",
                    "link_obra": "https://doi.org/10.1000/exemplo",
                    "link_lattes": None,
                    "parse_stage": "abnt",
                    "link_source": "html",
                    "curado_humano": False,
                }
            ],
        }).model_dump()
        (tmp_dir / "public" / "producao-academica.json").write_text(
            json.dumps(prod_fixture, ensure_ascii=False), encoding="utf-8"
        )

        # Página host simulando o snippet loader-elementor.html apontando para widget-elementor.html local
        loader_raw = (ROOT_DIR / "public" / "loader-elementor.html").read_text(encoding="utf-8")
        loader_local = (
            loader_raw
            .replace(
                "https://regi-lpf.github.io/references-parser/public/widget-elementor.html",
                "public/widget-elementor.html",
            )
            .replace(
                "https://regi-lpf.github.io/references-parser/public/teses-dissertacoes.json",
                "public/teses-dissertacoes.json",
            )
            .replace(
                'data-titulo="Teses e Dissertações"',
                'data-titulo="Acervo Via Loader" data-json-url-local="public/teses-dissertacoes.json"',
            )
        )
        host_html = (
            "<!DOCTYPE html><html lang='pt-BR'><head><meta charset='utf-8'></head><body>"
            f"{loader_local}"
            "</body></html>"
        )
        (tmp_dir / "host-loader.html").write_text(host_html, encoding="utf-8")

        handler = partial(_QuietHandler, directory=str(tmp_dir))
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        host, port = server.server_address
        return server, f"http://{host}:{port}"

    def _exercitar_pagina(self, page, url: str, expected_title: str) -> None:
        errors: list[str] = []
        page.on("pageerror", lambda exc: errors.append(f"pageerror: {exc}"))
        page.on("console", lambda msg: errors.append(f"console.{msg.type}: {msg.text}") if msg.type == "error" else None)

        page.goto(url, wait_until="networkidle")
        page.wait_for_selector("#vitrine-bib .vb-card")
        self.assertEqual(page.locator("#vb-title").inner_text().strip(), expected_title)
        self.assertEqual(page.locator("#vitrine-bib .vb-card").count(), 3)

        # Busca sem acento ("educacao" encontra "Educação")
        page.fill("#vb-search", "inclusao")
        page.wait_for_timeout(300)
        self.assertEqual(page.locator("#vitrine-bib .vb-card").count(), 1)

        page.click("#vb-clear")
        self.assertEqual(page.locator("#vitrine-bib .vb-card").count(), 3)

        # Filtro por Ano + Categoria
        page.select_option("#vb-filter-ano", "2022")
        self.assertEqual(page.locator("#vitrine-bib .vb-card").count(), 2)
        page.select_option("#vb-filter-categoria", "Mestrado Profissional")
        self.assertEqual(page.locator("#vitrine-bib .vb-card").count(), 1)

        page.click("#vb-clear")

        # Toggle "Apenas com texto disponível"
        page.check("#vb-only-available")
        self.assertEqual(page.locator("#vitrine-bib .vb-card").count(), 2)

        # Botão "Copiar citação"
        copy_btn = page.locator("#vitrine-bib button[data-copy-idx]").first
        copy_btn.click()
        page.locator("#vitrine-bib button[data-copy-idx].is-copied").first.wait_for(timeout=3000)
        self.assertEqual(copy_btn.inner_text().strip(), "Copiado!")

        self.assertEqual(errors, [])

    def test_smoke_index_e_loader_elementor(self) -> None:
        ok, reason = _playwright_disponivel()
        require_smoke = os.environ.get("REQUIRE_SMOKE") == "1"
        if not ok:
            if require_smoke:
                self.fail(f"REQUIRE_SMOKE=1 mas Playwright indisponível: {reason}")
            self.skipTest(reason)

        from playwright.sync_api import sync_playwright

        with tempfile.TemporaryDirectory() as tmp:
            server, base_url = self._preparar_servidor(Path(tmp))
            try:
                with sync_playwright() as p:
                    try:
                        browser = p.chromium.launch()
                    except Exception as exc:
                        if require_smoke:
                            self.fail(f"REQUIRE_SMOKE=1 mas Chromium falhou ao iniciar: {exc}")
                        self.skipTest(f"Chromium ausente: {exc}")
                    try:
                        context = browser.new_context()
                        page = context.new_page()
                        self._exercitar_pagina(page, f"{base_url}/index.html", "Teses e Dissertações")
                        page2 = context.new_page()
                        self._exercitar_pagina(page2, f"{base_url}/host-loader.html", "Acervo Via Loader")
                        # Troca de lista via seletor embutido no widget carregado pelo loader
                        page2.click('#vb-tabs button[data-vb-lista="producao-academica"]')
                        page2.wait_for_function(
                            "() => document.querySelector('#vitrine-bib .vb-card-title')?.textContent?.includes('Artigo Exemplo')"
                        )
                        self.assertEqual(page2.locator("#vb-title").text_content().strip(), "Produção Acadêmica")
                        self.assertEqual(page2.locator("#vb-categoria-label").text_content().strip(), "Tipo")
                        self.assertEqual(page2.locator("#vitrine-bib .vb-card").count(), 1)
                    finally:
                        browser.close()
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
