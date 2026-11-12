"""Restricoes explicitas do cliente para ofertas da agenda, em horario local."""
from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AgendaPreferencia(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data_inicio: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    data_fim: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    turno: Literal["qualquer", "manha", "tarde"] = "qualquer"
    hora_inicio: Optional[str] = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    hora_fim: Optional[str] = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")

    @model_validator(mode="after")
    def validar_intervalos(self):
        if bool(self.data_inicio) != bool(self.data_fim):
            raise ValueError("Informe data_inicio e data_fim juntas.")
        if self.data_inicio:
            inicio, fim = date.fromisoformat(self.data_inicio), date.fromisoformat(self.data_fim)
            if not 0 <= (fim - inicio).days <= 30:
                raise ValueError("O periodo deve ter entre 1 e 31 dias, em ordem crescente.")
        if self.hora_fim and not self.hora_inicio:
            raise ValueError("Informe hora_inicio ao definir hora_fim.")
        inicio_min, fim_min = self.limites_horarios()
        if inicio_min >= fim_min:
            raise ValueError("O intervalo de horas deve ser crescente e compativel com o turno.")
        return self

    def permite_data(self, data_ref: date | str) -> bool:
        iso = data_ref.isoformat() if isinstance(data_ref, date) else data_ref
        return not self.data_inicio or self.data_inicio <= iso <= self.data_fim

    def limites_horarios(self) -> tuple[int, int]:
        inicio, fim = {"qualquer": (0, 24 * 60), "manha": (0, 12 * 60), "tarde": (12 * 60, 18 * 60)}[self.turno]
        if self.hora_inicio or self.hora_fim:
            def minutos(hora: str) -> int:
                hh, mm = hora.split(":")
                return int(hh) * 60 + int(mm)
            if self.hora_inicio:
                inicio = max(inicio, minutos(self.hora_inicio))
            if self.hora_fim:
                fim = min(fim, minutos(self.hora_fim))
        return inicio, fim
