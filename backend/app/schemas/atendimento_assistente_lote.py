from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.atendimento_assistente_lote_limites import (
    MAX_AUDIOS, MAX_AUDIO_BYTES, MAX_EXAMES, MAX_EXAME_BYTES, MAX_EXAMES_BYTES,
)


class LoteArquivoEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    nome: str = Field(min_length=1, max_length=180)
    tipo: Literal["audio", "exame"]
    tamanho: int = Field(gt=0, le=MAX_AUDIO_BYTES)
    mime: str = Field(default="", max_length=150)


class LoteEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    transcricao: str = Field(default="", max_length=80000)
    consentimento: bool = False
    modo: Literal["analise", "transcricao"] = "analise"
    arquivos: list[LoteArquivoEntrada] = Field(max_length=MAX_AUDIOS + MAX_EXAMES)

    @model_validator(mode="after")
    def limites(self):
        audios = [f for f in self.arquivos if f.tipo == "audio"]
        exames = [f for f in self.arquivos if f.tipo == "exame"]
        if len({f.id for f in self.arquivos}) != len(self.arquivos):
            raise ValueError("Cada arquivo precisa de um identificador distinto.")
        if len(audios) > MAX_AUDIOS or len(exames) > MAX_EXAMES:
            raise ValueError(f"Selecione até {MAX_AUDIOS} áudios e {MAX_EXAMES} exames.")
        if any(f.tamanho > MAX_EXAME_BYTES for f in exames) or sum(f.tamanho for f in exames) > MAX_EXAMES_BYTES:
            raise ValueError(f"Cada exame admite 10 MB e o conjunto de exames admite {MAX_EXAMES_BYTES // (1024 * 1024)} MB.")
        if self.modo == "transcricao" and (len(audios) != 1 or exames or self.transcricao.strip()):
            raise ValueError("Para somente transcrever, envie um áudio sem exames ou texto.")
        if not self.arquivos and not self.transcricao.strip():
            raise ValueError("Selecione arquivos ou informe uma transcrição.")
        return self


class RevisaoRacaBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    revisao_token: str = Field(pattern=r"^[0-9a-f]{64}$")
    arquivo_ids: list[UUID] = Field(min_length=1, max_length=MAX_EXAMES)

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
