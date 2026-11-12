from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator


class LoteArquivoEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    nome: str = Field(min_length=1, max_length=180)
    tipo: Literal["audio", "exame"]
    tamanho: int = Field(gt=0, le=24_000_000)
    mime: str = Field(default="", max_length=150)


class LoteEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    transcricao: str = Field(default="", max_length=80000)
    consentimento: bool = False
    arquivos: list[LoteArquivoEntrada] = Field(max_length=10)

    @model_validator(mode="after")
    def limites(self):
        audios = [f for f in self.arquivos if f.tipo == "audio"]
        exames = [f for f in self.arquivos if f.tipo == "exame"]
        if len({f.id for f in self.arquivos}) != len(self.arquivos):
            raise ValueError("Cada arquivo precisa de um identificador distinto.")
        if len(audios) > 5 or len(exames) > 5:
            raise ValueError("Selecione até cinco áudios e cinco exames.")
        if any(f.tamanho > 10 * 1024 * 1024 for f in exames) or sum(f.tamanho for f in exames) > 20 * 1024 * 1024:
            raise ValueError("Cada exame admite 10 MB e o conjunto de exames admite 20 MB.")
        if not self.arquivos and not self.transcricao.strip():
            raise ValueError("Selecione arquivos ou informe uma transcrição.")
        return self


class RevisaoRacaBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    revisao_token: str = Field(pattern=r"^[0-9a-f]{64}$")
    arquivo_ids: list[UUID] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def arquivos_unicos(self):
        if len(set(self.arquivo_ids)) != len(self.arquivo_ids):
            raise ValueError("Selecione cada documento apenas uma vez.")
        return self


class RevisaoRacaEntrada(RevisaoRacaBase):
    confirmo_mesmo_paciente: Literal[True]
    confirmo_apenas_raca: Literal[True]
    consentimento: Literal[True]


class RevogacaoRevisaoRacaEntrada(RevisaoRacaBase):
    pass
