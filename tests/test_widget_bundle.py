"""Testes do empacotador e validador Elementor-safe (build_widget.py)."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR / "frontend") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "frontend"))

import build_widget  # noqa: E402


class TestWidgetBundle(unittest.TestCase):
    def test_artefatos_public_passam_em_check(self) -> None:
        errors = build_widget.validate_all()
        self.assertEqual(errors, [])

    def test_rejeita_css_fora_do_escopo(self) -> None:
        errs = build_widget.check_css_scoping("body { color: red; }\n#vitrine-bib .ok { color: blue; }")
        self.assertTrue(any("body" in e for e in errs))

    def test_rejeita_linhas_em_branco_cr_e_backdrop_filter(self) -> None:
        errs = build_widget.check_bundle_invariants(
            "<section id=\"vitrine-bib\">\r\n\nbackdrop-filter: blur(4px);</section>",
            "teste.html",
        )
        self.assertEqual(len(errs), 3)

    def test_rejeita_chamada_js_indefinida(self) -> None:
        errs = build_widget.check_js_static_calls(
            "function ok(a) { return String(a); }\nnaoExiste(123);"
        )
        self.assertEqual(errs, ["Chamada JS para identificador não declarado: naoExiste()"])

    def test_app_js_sem_chamadas_indefinidas(self) -> None:
        js_text = (ROOT_DIR / "frontend" / "app.js").read_text(encoding="utf-8")
        self.assertEqual(build_widget.check_js_static_calls(js_text), [])
        self.assertIn("\\u0026", js_text)


if __name__ == "__main__":
    unittest.main()
