"""Empacotador e validador Elementor-safe da vitrine bibliográfica."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys

ROOT_DIR = Path(__file__).resolve().parent.parent
INDEX_PATH = ROOT_DIR / "index.html"
CSS_PATH = ROOT_DIR / "frontend" / "styles.css"
JS_PATH = ROOT_DIR / "frontend" / "app.js"
WIDGET_OUT = ROOT_DIR / "public" / "widget-elementor.html"
LOADER_OUT = ROOT_DIR / "public" / "loader-elementor.html"

DEFAULT_WIDGET_URL = "https://regi-lpf.github.io/references-parser/public/widget-elementor.html"
DEFAULT_JSON_URL = "https://regi-lpf.github.io/references-parser/public/teses-dissertacoes.json"

JS_RESERVED = frozenset({
    "if", "else", "for", "while", "do", "switch", "case", "break", "continue", "return",
    "throw", "try", "catch", "finally", "typeof", "instanceof", "new", "delete", "void",
    "in", "of", "function", "var", "let", "const", "true", "false", "null", "undefined",
    "this", "super", "class", "extends", "await", "async",
})
JS_GLOBALS = frozenset({
    "window", "document", "console", "navigator", "fetch", "Error", "Array", "Set", "Map",
    "Object", "String", "Number", "Boolean", "Math", "Date", "JSON", "Blob", "URL",
    "Promise", "RegExp", "encodeURIComponent", "decodeURIComponent", "setTimeout",
    "clearTimeout", "parseInt", "parseFloat", "isNaN",
})


def _strip_blank_lines(text: str) -> str:
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n") if line.strip()]
    return "\n".join(lines) + "\n"


def build_widget_html(index_html: str, css_text: str, js_text: str) -> str:
    m = re.search(r"(<section\s+id=\"vitrine-bib\"[\s\S]*?</section>)", index_html, re.I)
    if not m:
        raise ValueError('Container <section id="vitrine-bib"> não encontrado em index.html')
    sec = m.group(1)
    pos = sec.rfind("</section>")
    return _strip_blank_lines(f"{sec[:pos].rstrip()}\n<style>\n{css_text}\n</style>\n<script>\n{js_text}\n</script>\n</section>")


def build_loader_html(widget_url: str = DEFAULT_WIDGET_URL, json_url: str = DEFAULT_JSON_URL) -> str:
    return _strip_blank_lines(
        f'<div id="vitrine-bib-loader" data-widget-url="{widget_url}" data-mostrar-seletor="true" data-json-url="{json_url}" data-titulo="Teses e Dissertações" data-categoria-label="Grau">Carregando acervo bibliográfico...</div>\n'
        '<script>\n(function () {\n'
        '  var host = document.getElementById("vitrine-bib-loader");\n  if (!host) return;\n'
        '  fetch(host.getAttribute("data-widget-url"))\n'
        '    .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.text(); })\n'
        '    .then(function (html) {\n'
        '      var tpl = document.createElement("template");\n      tpl.innerHTML = html.trim();\n'
        '      var sec = tpl.content.querySelector("#vitrine-bib");\n      if (!sec) throw new Error("Widget inválido");\n'
        '      ["data-mostrar-seletor", "data-json-url", "data-json-url-local", "data-titulo", "data-categoria-label"].forEach(function (a) {\n'
        '        var v = host.getAttribute(a);\n        if (v) sec.setAttribute(a, v);\n      });\n'
        '      var scripts = Array.from(sec.querySelectorAll("script"));\n      scripts.forEach(function (s) { s.remove(); });\n'
        '      host.replaceWith(sec);\n'
        '      scripts.forEach(function (orig) { var sc = document.createElement("script"); sc.textContent = orig.textContent; sec.appendChild(sc); });\n'
        '    })\n    .catch(function () { host.textContent = "Não foi possível carregar o acervo bibliográfico."; });\n'
        '})();\n</script>'
    )


def check_css_scoping(css_text: str) -> list[str]:
    errors: list[str] = []
    cleaned = re.sub(r"/\*[\s\S]*?\*/", "", css_text)
    pos, n = 0, len(cleaned)
    while pos < n and (open_b := cleaned.find("{", pos)) != -1:
        header = cleaned[pos:open_b].strip()
        depth, cur = 1, open_b + 1
        while cur < n and depth > 0:
            depth += (cleaned[cur] == "{") - (cleaned[cur] == "}")
            cur += 1
        body = cleaned[open_b + 1 : cur - 1]
        if header.startswith(("@media", "@supports")):
            errors.extend(check_css_scoping(body))
        elif header and not header.startswith("@keyframes"):
            for sel in (s.strip() for s in header.split(",") if s.strip()):
                if not (sel == "#vitrine-bib" or sel.startswith(("#vitrine-bib ", "#vitrine-bib:", "#vitrine-bib.", "#vitrine-bib>"))):
                    errors.append(f"Seletor CSS fora do escopo #vitrine-bib: {sel!r}")
        pos = cur
    return errors


def check_bundle_invariants(html_text: str, label: str) -> list[str]:
    checks = [("\r" in html_text, "contém caractere CR (\\r)"), ("\n\n" in html_text, "contém linhas em branco (\\n\\n)"), ("backdrop-filter" in html_text.lower(), "contém backdrop-filter proibido no Elementor")]
    return [f"{label}: {msg}" for cond, msg in checks if cond]


def check_js_static_calls(js_text: str) -> list[str]:
    token_re = re.compile(r"//[^\n]*|/\*[\s\S]*?\*/|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`|(?<=[=(:,!&|?;\n])\s*/(?:\\.|\[(?:\\.|[^\]\\])*\]|[^/\n\\])+/[gimsuy]*")
    stripped = token_re.sub(" ", js_text)
    declared = set(JS_GLOBALS)
    declared.update(re.findall(r"\bfunction\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*\(", stripped))
    for params in re.findall(r"\bfunction(?:\s+[A-Za-z_$][A-Za-z0-9_$]*)?\s*\(([^)]*)\)", stripped):
        declared.update(p.strip() for p in params.split(",") if p.strip())
    declared.update(re.findall(r"\b(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\b", stripped))
    errors = {
        f"Chamada JS para identificador não declarado: {m.group(1)}()"
        for m in re.finditer(r"(?<![.\w$])([A-Za-z_$][A-Za-z0-9_$]*)\s*\(", stripped)
        if m.group(1) not in JS_RESERVED and m.group(1) not in declared and not re.search(r"\bfunction\s+$", stripped[max(0, m.start() - 12) : m.start()])
    }
    return sorted(errors)


def validate_all(*, index_html: str | None = None, css_text: str | None = None, js_text: str | None = None, widget_html: str | None = None, loader_html: str | None = None) -> list[str]:
    idx = index_html if index_html is not None else INDEX_PATH.read_text(encoding="utf-8")
    css = css_text if css_text is not None else CSS_PATH.read_text(encoding="utf-8")
    js = js_text if js_text is not None else JS_PATH.read_text(encoding="utf-8")
    w_act = widget_html if widget_html is not None else (WIDGET_OUT.read_text(encoding="utf-8") if WIDGET_OUT.exists() else "")
    l_act = loader_html if loader_html is not None else (LOADER_OUT.read_text(encoding="utf-8") if LOADER_OUT.exists() else "")

    errors = check_css_scoping(css) + check_js_static_calls(js) + check_bundle_invariants(w_act, "public/widget-elementor.html") + check_bundle_invariants(l_act, "public/loader-elementor.html")
    if "backdrop-filter" in css.lower():
        errors.append("frontend/styles.css: contém backdrop-filter")
    if "\\u0026" not in js or "\\u0026" not in w_act:
        errors.append("Escape HTML \\u0026 ausente")
    if m_style := re.search(r"<style>([\s\S]*?)</style>", w_act):
        errors.extend(check_css_scoping(m_style.group(1)))
    else:
        errors.append("public/widget-elementor.html: <style> ausente")
    if w_act != build_widget_html(idx, css, js):
        errors.append("Paridade falhou: public/widget-elementor.html diverge dos arquivos fonte")
    if l_act != build_loader_html():
        errors.append("Paridade falhou: public/loader-elementor.html diverge do gerador")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Empacotador e validador Elementor-safe")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if not args.check:
        WIDGET_OUT.parent.mkdir(parents=True, exist_ok=True)
        WIDGET_OUT.write_text(build_widget_html(INDEX_PATH.read_text(encoding="utf-8"), CSS_PATH.read_text(encoding="utf-8"), JS_PATH.read_text(encoding="utf-8")), encoding="utf-8")
        LOADER_OUT.write_text(build_loader_html(), encoding="utf-8")
    errors = validate_all()
    if errors:
        for err in errors:
            print(f"[ERRO] {err}", file=sys.stderr)
        return 1
    print("[OK] Bundle Elementor validado e em paridade.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
