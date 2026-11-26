"""Testes unitários de enriquecimento (BDTD similaridade/retry e LZString Lattes)."""

from __future__ import annotations

import json
import unittest
from urllib.parse import parse_qs, unquote, urlparse

from lzstring import LZString
import requests

from vitrine_bib.enrich import buscar_na_bdtd, gerar_url_lattes, similaridade_normalizada


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class _FakeSession:
    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.calls = 0

    def get(self, url: str, params=None, timeout: float = 8.0):
        self.calls += 1
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class TestEnrich(unittest.TestCase):
    def test_lzstring_roundtrip_e_url_lattes(self) -> None:
        url = gerar_url_lattes("José da Silva")
        self.assertIsNotNone(url)
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        self.assertEqual(parsed.netloc, "busca-cv-lattes.cnpq.br")
        self.assertEqual(qs["mode"], ["NOME"])
        self.assertEqual(qs["keyword"], ["José da Silva"])
        descomprimido = LZString().decompressFromEncodedURIComponent(unquote(qs["q"][0]))
        self.assertEqual(
            json.loads(descomprimido),
            {"modoBusca": "NOME", "keyword": "José da Silva", "orderBy": "nome"},
        )
        self.assertIsNone(gerar_url_lattes("MEC/SETEC"))

    def test_bdtd_limiar_similaridade_088(self) -> None:
        titulo = "A formação docente nos institutos federais de educação"
        self.assertGreaterEqual(similaridade_normalizada(titulo, "A Formacao Docente nos Institutos Federais de Educacao!"), 0.88)
        self.assertLess(similaridade_normalizada(titulo, "Outro estudo sobre agricultura familiar"), 0.88)

        sess_baixo = _FakeSession([_FakeResponse(200, {"records": [{"id": "r1", "title": "Química orgânica aplicada", "url": ["https://repositorio.ufsc.br/handle/1234/999"]}]})])
        self.assertIsNone(buscar_na_bdtd(titulo, session=sess_baixo, sleep_fn=lambda _: None))

        sess_alto = _FakeSession([_FakeResponse(200, {"records": [{"id": "r2", "title": "A formacao docente nos institutos federais de educacao", "url": ["https://repositorio.ufsc.br/handle/1234/888"]}]})])
        self.assertEqual(buscar_na_bdtd(titulo, session=sess_alto, sleep_fn=lambda _: None), "https://repositorio.ufsc.br/handle/1234/888")

    def test_bdtd_retry_backoff_em_erro_transitorio(self) -> None:
        delays: list[float] = []
        sess = _FakeSession([requests.Timeout("timeout"), _FakeResponse(503, {}), _FakeResponse(200, {"records": [{"id": "r3", "title": "Inclusão escolar na rede federal", "url": []}]})])
        url = buscar_na_bdtd("Inclusão escolar na rede federal", session=sess, backoff_base=0.1, sleep_fn=delays.append)
        self.assertEqual(url, "https://bdtd.ibict.br/vufind/Record/r3")
        self.assertEqual(sess.calls, 3)
        self.assertEqual(delays, [0.1, 0.2])


if __name__ == "__main__":
    unittest.main()
