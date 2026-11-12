from pydantic import BaseModel, Field, validator
from datetime import datetime
from typing import Optional, List

def parse_datetime(value):
    """Converte string ISO 8601 (com Z ou formato PostgreSQL) para datetime"""
    if isinstance(value, str):
        # Se termina com Z, converte para +00:00
        if value.endswith('Z'):
            value = value[:-1] + '+00:00'
        # Remove milisegundos (.000)
        if '.' in value:
            if '+' in value:
                dt_part, tz_part = value.rsplit('+', 1)
                if '.' in dt_part:
                    dt_part = dt_part.split('.')[0]
                value = f"{dt_part}+{tz_part}"
            else:
                value = value.split('.')[0]
        return datetime.fromisoformat(value)
    return value

class AgendamentoBase(BaseModel):
    paciente_id: Optional[int] = None
    tutor_id: Optional[int] = None
    clinica_id: Optional[int] = None
    servico_id: Optional[int] = None
    origem_atendimento: Optional[str] = "clinica_parceira"
    inicio: datetime
    fim: Optional[datetime] = None
    status: str = "Agendado"
    reserva_expira_em: Optional[datetime] = None
    observacoes: Optional[str] = None
    confirmar_conflito_deslocamento: bool = False
    confirmar_slot_reserva_expirada: bool = False
    confirmar_agenda_fechada: bool = False
    excecao_operacional_concedida: bool = False
    motivo_excecao_operacional: Optional[str] = None
    motivo_excecao_deslocamento: Optional[str] = None
    confirmar_sobreposicao: bool = False
    escopo_sobreposicao_confirmado: Optional[str] = Field(default=None, max_length=64)
    motivo_excecao_sobreposicao: Optional[str] = Field(default=None, max_length=1000)

    @validator('inicio', 'fim', 'reserva_expira_em', pre=True)
    def parse_dates(cls, v):
        return parse_datetime(v) if v else None

class AgendamentoCreate(AgendamentoBase):
    pedido_whatsapp_id: Optional[int] = Field(default=None, gt=0)
    pedido_whatsapp_versao: Optional[int] = Field(default=None, gt=0)
    pedido_whatsapp_divergencia_confirmada: bool = False

class AgendamentoUpdate(BaseModel):
    paciente_id: Optional[int] = None
    tutor_id: Optional[int] = None
    clinica_id: Optional[int] = None
    servico_id: Optional[int] = None
    origem_atendimento: Optional[str] = None
    inicio: Optional[datetime] = None
    fim: Optional[datetime] = None
    status: Optional[str] = None
    reserva_expira_em: Optional[datetime] = None
    observacoes: Optional[str] = None
    confirmar_conflito_deslocamento: Optional[bool] = None
    confirmar_agenda_fechada: Optional[bool] = None
    confirmar_slot_reserva_expirada: Optional[bool] = None
    excecao_operacional_concedida: Optional[bool] = None
    motivo_excecao_operacional: Optional[str] = None
    motivo_excecao_deslocamento: Optional[str] = None
    confirmar_sobreposicao: bool = False
    escopo_sobreposicao_confirmado: Optional[str] = Field(default=None, max_length=64)
    motivo_excecao_sobreposicao: Optional[str] = Field(default=None, max_length=1000)
    confirmar_alteracao_servico_hoje: Optional[bool] = None
    urgente_laudo: Optional[bool] = None

    @validator('inicio', 'fim', 'reserva_expira_em', pre=True)
    def parse_dates(cls, v):
        return parse_datetime(v) if v else None

class AgendamentoResponse(BaseModel):
    id: int
    paciente_id: Optional[int] = None
    tutor_id: Optional[int] = None
    clinica_id: Optional[int] = None
    servico_id: Optional[int] = None
    origem_atendimento: Optional[str] = None
    inicio: Optional[str] = None  # Retorna como string para evitar problemas de formato
    fim: Optional[str] = None  # Retorna como string
    status: str
    reserva_expira_em: Optional[str] = None
    excecao_sobreposicao: Optional[dict] = None
    excecao_agenda_fechada_ativa: bool = False
    observacoes: Optional[str] = None
    data: Optional[str] = None
    hora: Optional[str] = None
    paciente: Optional[str] = None
    tutor: Optional[str] = None
    telefone: Optional[str] = None
    servico: Optional[str] = None
    clinica: Optional[str] = None
    criado_por_nome: Optional[str] = None
    confirmado_por_nome: Optional[str] = None
    created_at: Optional[str] = None  # Retorna como string
    # Excecao de deslocamento concedida por admin. `ativa` ja considera o
    # escopo (horario/destino/servico): uma concessao obsoleta volta False.
    excecao_deslocamento_ativa: bool = False
    excecao_deslocamento_concedida_em: Optional[str] = None
    excecao_deslocamento_concedida_por_nome: Optional[str] = None
    excecao_deslocamento_motivo: Optional[str] = None

    class Config:
        from_attributes = True

class AgendamentoLista(BaseModel):
    total: int
    items: List[AgendamentoResponse]
    agenda_semanal: Optional[dict] = None
    agenda_feriados: Optional[list] = None
    agenda_excecoes: Optional[list] = None
