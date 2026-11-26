"""Testes unitários de ingestão DOM e parsing em cascata."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from vitrine_bib.ingest import EntradaBruta, carregar_html, classificar_url
from vitrine_bib.models import RegistroBibliografico
from vitrine_bib.parser import formatar_nome_autor, parse_entrada


class TestIngest(unittest.TestCase):
    def test_classificar_url_obra_vs_lattes_vs_homepage(self) -> None:
        self.assertEqual(
            classificar_url("https://repositorio.ufscar.br/handle/ufscar/13222."),
            ("https://repositorio.ufscar.br/handle/ufscar/13222", "obra"),
        )
        self.assertEqual(
            classificar_url("http://lattes.cnpq.br/1234567890123456"),
            ("http://lattes.cnpq.br/1234567890123456", "lattes"),
        )
        self.assertEqual(
            classificar_url("http://www.2018.reditec.org.br"),
            (None, "rejeitada_homepage"),
        )
        self.assertEqual(
            classificar_url("https://portal.mec.gov.br/index.html"),
            (None, "rejeitada_homepage"),
        )
        self.assertEqual(
            classificar_url("http://portal.mec.gov.br/rede-e-tec-brasil"),
            ("http://portal.mec.gov.br/rede-e-tec-brasil", "obra"),
        )

    def test_carregar_html_separa_links_e_descarta_homepage_e_vazios(self) -> None:
        html_doc = """
        <ul>
          <li>SILVA, João da. Tese exemplo. 10/03/2020 120 f. Doutorado em Educação Instituição de Ensino: UFSC, Florianópolis.
            Disponível em: <a href="https://repositorio.ufsc.br/handle/12345/6789.">link</a>
            e <a href="http://lattes.cnpq.br/9988776655443322">Lattes</a>
          </li>
          <li>AUTORA, Maria. Artigo com homepage. Revista X, v. 1, n. 2, 2021.
            Disponível em: <a href="https://exemplo.org/">link</a>
          </li>
          <li>   </li>
        </ul>
        """
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "lista.html"
            p.write_text(html_doc, encoding="utf-8")
            entradas = carregar_html(p)

        self.assertEqual(len(entradas), 2)
        self.assertEqual(entradas[0].link_obra, "https://repositorio.ufsc.br/handle/12345/6789")
        self.assertEqual(entradas[0].link_lattes, "http://lattes.cnpq.br/9988776655443322")
        self.assertIsNone(entradas[1].link_obra)
        self.assertTrue(entradas[1].url_rejeitada_homepage)
        self.assertNotIn("Disponível em", entradas[1].texto_limpo)


class TestParserCascade(unittest.TestCase):
    def _entrada(self, texto: str, link_obra: str | None = None) -> EntradaBruta:
        return EntradaBruta(
            texto_limpo=texto,
            chave_dedup="abcdef0123456789",
            link_obra=link_obra,
            link_lattes=None,
        )

    def test_estagio_1_capes(self) -> None:
        txt = (
            "AGUIAR, JOSUE ESTEVES DE. O PAPEL DA BIBLIOTECA NA FORMAÇÃO PARA O TRABALHO: "
            "um estudo no CEFET/MG' 20/07/2021 117 f. Mestrado Profissional em EDUCAÇÃO PROFISSIONAL "
            "Instituição de Ensino: INSTITUTO FEDERAL DO SUDESTE DE MINAS GERAIS, Vitória "
            "Biblioteca Depositária: Biblioteca Jofre Moreira."
        )
        res = parse_entrada(self._entrada(txt), "teses-dissertacoes")
        self.assertEqual(res["parse_stage"], "capes")
        self.assertEqual(res["autor"], "Josue Esteves de Aguiar")
        self.assertEqual(res["ano"], 2021)
        self.assertEqual(res["categoria"], "Mestrado Profissional")
        self.assertIn("INSTITUTO FEDERAL", res["veiculo_ou_ies"])

    def test_estagio_2_apa(self) -> None:
        txt = (
            "Alves Monteiro, C. M. ., & Leandro Plácido, R. (2020). "
            "O ACOLHIMENTO NAS PRÁTICAS EDUCACIONAIS INCLUSIVAS DA EPT. Educação Em Foco, 25(3)."
        )
        res = parse_entrada(
            self._entrada(txt, "https://doi.org/10.22195/2447-524620202532903"),
            "producao-academica",
        )
        self.assertEqual(res["parse_stage"], "apa")
        self.assertEqual(res["ano"], 2020)
        self.assertEqual(res["categoria"], "Artigo")
        self.assertIn("O ACOLHIMENTO", res["titulo"])
        self.assertIn("Educação Em Foco", res["veiculo_ou_ies"])

    def test_estagio_3_abnt_artigo_capitulo_e_legislacao(self) -> None:
        artigo = (
            "ALVES, L. M. S.; PLÁCIDO, R. L. Retalhos de experiências exitosas em Educação Profissional. "
            "Debates em Educação, v. 11, n. 24, p. 564–585, 2019. DOI: 10.28998/2175-6600"
        )
        res_art = parse_entrada(self._entrada(artigo), "producao-academica")
        self.assertEqual(res_art["parse_stage"], "abnt")
        self.assertEqual(res_art["ano"], 2019)
        self.assertEqual(res_art["categoria"], "Artigo")

        capitulo = (
            "AGUIAR, Luiz Edmundo Vargas de; PACHECO, Eliezer Moreira. "
            "Os Institutos Federais como política pública. p. 13 a 35. "
            "IN. ANJOS, Malyta Brandão dos; RÔSAS, Giselle. Org. As políticas públicas. Natal: IFRN, 2017."
        )
        res_cap = parse_entrada(self._entrada(capitulo), "producao-academica")
        self.assertEqual(res_cap["parse_stage"], "abnt")
        self.assertEqual(res_cap["ano"], 2017)
        self.assertEqual(res_cap["categoria"], "Capítulo de livro")

        lei = "BRASIL. Constituição Política do Império do Brasil, de 25 de março de 1824. Carta de Lei de 25 de Março de 1824."
        res_lei = parse_entrada(self._entrada(lei), "documentos-oficiais")
        self.assertEqual(res_lei["parse_stage"], "abnt")
        self.assertEqual(res_lei["ano"], 1824)
        self.assertEqual(res_lei["categoria"], "Legislação")

    def test_estagio_4_fallback_seguro_e_texto_busca_normalizado(self) -> None:
        txt = "Texto completamente fora de padrão sem vírgula ou estrutura conhecida"
        res = parse_entrada(self._entrada(txt), "producao-academica")
        self.assertEqual(res["parse_stage"], "fallback")
        self.assertEqual(res["citacao_original"], txt)

        reg = RegistroBibliografico.model_validate({"id": "ref_0001", **res})
        self.assertIn("completamente fora de padrao", reg.texto_busca)

    def test_formatar_nome_autor(self) -> None:
        self.assertEqual(formatar_nome_autor("SILVA, MARIA DAS DORES"), "Maria das Dores Silva")
        self.assertEqual(formatar_nome_autor("MEC/SETEC"), "MEC/SETEC")

    def test_regressao_auditoria_multi_autor_org_lei_e_brasil_pessoal(self) -> None:
        from vitrine_bib.enrich import gerar_url_lattes

        # Sobrenome BRASIL com prenome é pessoa física e gera Lattes
        self.assertIsNotNone(gerar_url_lattes("Jorge Eduardo Mendonca Brasil"))

        # Multi-autor não vaza sobrenome final para o título
        r1 = parse_entrada(
            self._entrada("CARLOS, N. L.; CAVALCANTE, I.; MEDEIROS NETA, O. A educação na ditadura. Revista X, v. 1, 2018."),
            "producao-academica",
        )
        self.assertEqual(r1["autor"], "N. L. Carlos; I. Cavalcante; O. Medeiros Neta")
        self.assertTrue(r1["titulo"].startswith("A educação na ditadura"))

        r2 = parse_entrada(
            self._entrada("CARDOSO, D. dos S., e REIS, A. R. da S., Educação Profissional: Desafios. In: III CONEDU, 2016."),
            "producao-academica",
        )
        self.assertEqual(r2["parse_stage"], "abnt")
        self.assertIn("Cardoso", r2["autor"])
        self.assertEqual(r2["categoria"], "Anais de evento")

        # Capítulo com (Org.) após In. não engole título como autor
        r3 = parse_entrada(
            self._entrada("FRIGOTTO, Gaudêncio. Indeterminação de identidade. In. FRIGOTTO, Gaudêncio (Org.). Institutos Federais. Rio: UERJ, 2018."),
            "producao-academica",
        )
        self.assertEqual(r3["autor"], "Gaudêncio Frigotto")
        self.assertEqual(r3["categoria"], "Capítulo de livro")

        # Lei e documento MEC/SETEC não caem em Artigo
        r4 = parse_entrada(self._entrada("BRASIL. Lei Nº 9.394, de 20 de dezembro de 1996. LDB."), "documentos-oficiais")
        self.assertEqual(r4["categoria"], "Legislação")
        r5 = parse_entrada(self._entrada("MEC/SETEC. Centenário da Rede Federal de Educação Profissional."), "documentos-oficiais")
        self.assertEqual(r5["categoria"], "Documento oficial")

    def test_deduplicacao_html_mescla_links(self) -> None:
        html_dup = """
        <ul>
          <li>AUTOR, Teste. Título duplicado idêntico no HTML. 10/01/2020 80 f. Mestrado em Educação Instituição de Ensino: UFSC, Florianópolis.</li>
          <li>AUTOR, Teste. Título duplicado idêntico no HTML. 10/01/2020 80 f. Mestrado em Educação Instituição de Ensino: UFSC, Florianópolis. <a href="https://repositorio.ufsc.br/handle/1/2">link</a></li>
        </ul>
        """
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "dup.html"
            p.write_text(html_dup, encoding="utf-8")
            entradas = carregar_html(p)
        self.assertEqual(len(entradas), 1)
        self.assertEqual(entradas[0].link_obra, "https://repositorio.ufsc.br/handle/1/2")


if __name__ == "__main__":
    unittest.main()
