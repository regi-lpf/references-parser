"""Contratos de dados tipados (Pydantic v2) para extrator e vitrine."""

from __future__ import annotations

import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ParseStage = Literal["capes", "apa", "abnt", "fallback"]
LinkSource = Literal["html", "bdtd", "manual", "none"]
THESIS_CATEGORIES = frozenset({"Mestrado", "Mestrado Profissional", "Doutorado", "Tese", "Dissertação"})


def normalizar_texto(texto: str | None) -> str:
    if not texto:
        return ""
    decomposed = unicodedata.normalize("NFD", str(texto))
    sem_acentos = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", sem_acentos).strip().lower()


class ListaConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lista_id: str
    titulo: str
    categoria_label: str
    input_html: str
    output_json: str
    pendencias_csv: str
    enriquecer_bdtd: bool = True


class RegistroBibliografico(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^ref_\d{4,}$")
    chave_dedup: str = Field(min_length=8, max_length=64)
    autor: str = ""
    autor_citacao: str = ""
    titulo: str = ""
    ano: int | None = None
    categoria: str = "Não classificado"
    veiculo_ou_ies: str = ""
    citacao_original: str
    link_obra: str | None = None
    link_lattes: str | None = None
    parse_stage: ParseStage
    link_source: LinkSource
    curado_humano: bool = False
    texto_busca: str = ""

    @model_validator(mode="after")
    def _gerar_texto_busca(self) -> RegistroBibliografico:
        partes = [self.titulo, self.autor, self.autor_citacao, str(self.ano or ""), self.categoria, self.veiculo_ou_ies]
        if self.parse_stage == "fallback" or not self.titulo:
            partes.append(self.citacao_original)
        self.texto_busca = normalizar_texto(" ".join(p for p in partes if p))
        return self


class VitrineOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = "1.0"
    lista_id: str
    titulo: str
    categoria_label: str
    gerado_em: str
    total: int
    registros: list[RegistroBibliografico]

    @model_validator(mode="after")
    def _validar_total(self) -> VitrineOutput:
        if self.total != len(self.registros):
            raise ValueError(f"total ({self.total}) != len(registros) ({len(self.registros)})")
        return self
