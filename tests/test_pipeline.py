"""Testes de idempotência, curadoria humana, cache BDTD e CSV de pendências."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from vitrine_bib.models import ListaConfig, VitrineOutput
from vitrine_bib.pipeline import processar_lista


class TestPipelineIdempotencia(unittest.TestCase):
    def _config(self) -> ListaConfig:
        return ListaConfig(
            lista_id="teste",
            titulo="Lista Teste",
            categoria_label="Grau",
            input_html="entrada.html",
            output_json="public/teste.json",
            pendencias_csv="data/pendencias/teste_pendencias.csv",
            enriquecer_bdtd=True,
        )

    def test_preserva_ids_ao_reordenar_protege_curados_e_reaproveita_bdtd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = self._config()

            html_inicial = """
            <ul>
              <li>SILVA, Ana. Tese sobre educação profissional. 10/05/2020 120 f. Doutorado em Educação Instituição de Ensino: UFSC, Florianópolis.</li>
              <li>SOUZA, Bruno. Dissertação sobre currículo integrado. 15/08/2021 90 f. Mestrado em Educação Instituição de Ensino: IFC, Blumenau.</li>
            </ul>
            """
            (root / "entrada.html").write_text(html_inicial, encoding="utf-8")

            chamadas_bdtd: list[str] = []

            def fake_bdtd(titulo: str) -> str | None:
                chamadas_bdtd.append(titulo)
                if "educação profissional" in titulo.lower():
                    return "https://repositorio.ufsc.br/handle/123/456"
                return None

            res1 = processar_lista(cfg, base_dir=root, bdtd_delay=0.0, bdtd_fn=fake_bdtd)
            self.assertEqual(res1.total_registros, 2)
            self.assertEqual(res1.novas_consultas_bdtd, 2)
            self.assertEqual(res1.pendencias, 1)
            self.assertTrue((root / cfg.pendencias_csv).exists())

            data1 = VitrineOutput.model_validate(
                json.loads((root / cfg.output_json).read_text(encoding="utf-8"))
            )
            id_ana = data1.registros[0].id
            id_bruno = data1.registros[1].id
            self.assertEqual(id_ana, "ref_0001")
            self.assertEqual(id_bruno, "ref_0002")
            self.assertEqual(data1.registros[0].link_source, "bdtd")

            # Marca Bruno como curado manualmente com link manual
            raw_json = json.loads((root / cfg.output_json).read_text(encoding="utf-8"))
            raw_json["registros"][1]["curado_humano"] = True
            raw_json["registros"][1]["titulo"] = "Título Curado Manualmente"
            raw_json["registros"][1]["link_obra"] = "https://exemplo.org/handle/manual/1"
            raw_json["registros"][1]["link_source"] = "manual"
            (root / cfg.output_json).write_text(json.dumps(raw_json, ensure_ascii=False), encoding="utf-8")

            # Reordena <li> e insere novo item no topo
            html_reordenado = """
            <ul>
              <li>COSTA, Carla. Novo trabalho inserido no topo. 01/02/2023 100 f. Mestrado em Educação Instituição de Ensino: IFSC, Florianópolis. Disponível em: <a href="https://repositorio.ifsc.edu.br/handle/123/999">link</a></li>
              <li>SOUZA, Bruno. Dissertação sobre currículo integrado. 15/08/2021 90 f. Mestrado em Educação Instituição de Ensino: IFC, Blumenau.</li>
              <li>SILVA, Ana. Tese sobre educação profissional. 10/05/2020 120 f. Doutorado em Educação Instituição de Ensino: UFSC, Florianópolis.</li>
            </ul>
            """
            (root / "entrada.html").write_text(html_reordenado, encoding="utf-8")

            chamadas_bdtd.clear()
            res2 = processar_lista(cfg, base_dir=root, bdtd_delay=0.0, bdtd_fn=fake_bdtd)
            # Nenhuma chamada BDTD repetida (Ana reaproveitou cache BDTD, Bruno foi protegido como curado, Carla já tinha link)
            self.assertEqual(chamadas_bdtd, [])
            self.assertEqual(res2.preservados_curados, 1)
            self.assertEqual(res2.reaproveitados_cache, 1)
            # Pendências zeraram -> CSV deve ter sido removido automaticamente
            self.assertEqual(res2.pendencias, 0)
            self.assertTrue(res2.csv_removido)
            self.assertFalse((root / cfg.pendencias_csv).exists())

            data2 = VitrineOutput.model_validate(
                json.loads((root / cfg.output_json).read_text(encoding="utf-8"))
            )
            por_id = {r.id: r for r in data2.registros}
            self.assertEqual(data2.registros[0].id, "ref_0003")  # Carla (nova)
            self.assertEqual(data2.registros[1].id, id_bruno)    # Bruno preservou ref_0002
            self.assertEqual(data2.registros[2].id, id_ana)      # Ana preservou ref_0001
            self.assertEqual(por_id[id_bruno].titulo, "Título Curado Manualmente")

            # Com forcar_curados=True, registro curado é reprocessado
            res3 = processar_lista(
                cfg,
                base_dir=root,
                offline=True,
                forcar_curados=True,
                bdtd_delay=0.0,
                bdtd_fn=fake_bdtd,
            )
            self.assertEqual(res3.preservados_curados, 0)
            data3 = VitrineOutput.model_validate(
                json.loads((root / cfg.output_json).read_text(encoding="utf-8"))
            )
            por_id3 = {r.id: r for r in data3.registros}
            self.assertNotEqual(por_id3[id_bruno].titulo, "Título Curado Manualmente")


if __name__ == "__main__":
    unittest.main()
