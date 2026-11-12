import asyncio
import hashlib
import json
import logging
import math
import os
import re
import secrets
import unicodedata
from functools import lru_cache
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from queue import Empty
from types import SimpleNamespace
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, exists, func, inspect, or_, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.api.v1.endpoints.tutores import GeocodeEnderecoPayload, geocode_endereco_tutor
from app.db.database import get_db
from app.services.agenda_sobreposicao import (
    assinatura as assinatura_sobreposicao,
    ler_concessao as ler_concessao_sobreposicao,
    validar_pedido as validar_pedido_sobreposicao,
    validar_conflitos as validar_conflitos_sobreposicao,
)
from app.models.agendamento import Agendamento
from app.models.agenda_bloqueio import AgendaBloqueio
from app.models.paciente import Paciente
from app.models.clinica import Clinica
from app.models.configuracao import Configuracao, ConfiguracaoUsuario
from app.models.auditoria_evento import AuditoriaEvento
from app.models.servico import Servico
from app.models.ordem_servico import OrdemServico
from app.models.laudo import Laudo
from app.models.user import User
from app.models.tutor import Tutor
from app.schemas.agenda_preferencia import AgendaPreferencia
from app.schemas.agendamento import (
    AgendamentoCreate,
    AgendamentoLista,
    AgendamentoResponse,
    AgendamentoUpdate,
)
from app.core.agenda_config import (
    DEFAULT_AGENDA_SEMANAL,
    carregar_agenda_excecoes,
    carregar_agenda_feriados,
    carregar_agenda_semanal,
    obter_excecao_data,
    obter_feriado,
    validar_horario_agenda,
)
from app.core.agenda_route_rules import carregar_agenda_rota_regras
from app.core.agenda_realtime import agenda_realtime_manager
from app.core.config import settings
from app.core.security import get_current_user
from app.core.agenda_permissions import usuario_pode_excluir_agendamento
from app.services.logistica_service import (
    estimar_deslocamento,
    normalizar_perfil,
    obter_duracao_deslocamento,
    obter_duracao_deslocamento_entidades,
)
from app.services.agenda_regional_transition import avaliar_transicao_regional
from app.services.geocoding_service import GeocodingError, geocodificar_endereco_google
from app.services.google_maps_cost_control import GoogleMapsCostBlocked, block_cache_only_lookup, cache_only_operation
from app.services.precos_service import calcular_preco_servico, calcular_precos_servicos_em_lote, to_decimal
from app.services.auditoria_service import registrar_auditoria
from app.services.push_notifications import (
    send_agenda_push_notification,
    send_financeiro_push_notification,
)
from app.services.push_scheduler_service import schedule_pending_os_payment_reminder

router = APIRouter()
logger = logging.getLogger(__name__)
# Horario de Brasilia (UTC-3). Evita dependencia de tzdata no Windows local.
LOCAL_TZ = timezone(timedelta(hours=-3))
AGENDA_STATUS_PERMITIDOS = ["Agendado", "Reservado", "Confirmado", "Em atendimento", "Realizado", "Cancelado", "Faltou", "Expirado"]
AGENDA_STATUS_PRE_AGENDADOS = {"Agendado", "Reservado", "Confirmado"}
AGENDA_STATUS_BLOQUEIAM_SLOT = {"Agendado", "Reservado", "Confirmado", "Em atendimento"}
AGENDA_STATUS_NAO_ANCORA = {"Cancelado", "Faltou", "Expirado"}
ORIGENS_ATENDIMENTO_PERMITIDAS = {"clinica_parceira", "domiciliar"}
ORIGEM_ATENDIMENTO_PADRAO = "clinica_parceira"
ORIGEM_ATENDIMENTO_DOMICILIAR = "domiciliar"
MIN_MARGEM_SEGURA_DESLOCAMENTO_MIN = 5
MAX_DESLOCAMENTO_TRECHO_VIZINHO_MIN = 45
# Janela operacional da excecao de ancora, independente da grade visual/de busca.
JANELA_OPERACIONAL_ADJACENCIA_ANCORA_MIN = 30
# Reabilitacao de reserva expirada: a clinica volta a pedir o mesmo horario
# depois do vencimento e o slot segue livre, entao a reserva ganha um novo
# prazo ate a chegada dos dados do paciente.
PRAZO_REABILITACAO_RESERVA_HORAS_PADRAO = 3.0
PRAZO_REABILITACAO_RESERVA_HORAS_MIN = 0.5
PRAZO_REABILITACAO_RESERVA_HORAS_MAX = 72.0
MARGEM_MINIMA_PRAZO_RESERVA_MIN = 5
AGENDA_WRITE_LOCK_KEY = 24052301
ASSISTENTE_BUSCA_PROGRESSIVA_MAX_DIAS = 30
ASSISTENTE_BUSCA_DIA_VAZIO_EXTRA_MAX_DIAS = 7
ASSISTENTE_HIERARQUIA_MAX_DATAS = 3
ASSISTENTE_HIERARQUIA_MAX_ITENS_POR_DATA = 2
ASSISTENTE_AGENDA_TOKEN_ENV = "ASSISTENTE_AGENDA_TOKEN"
ASSISTENTE_AGENDA_MAX_WINDOW_ENV = "ASSISTENTE_AGENDA_MAX_WINDOW_DAYS"
ASSISTENTE_AGENDA_DEFAULT_WINDOW_DAYS = 7
ASSISTENTE_AGENDA_DEFAULT_MAX_WINDOW_DAYS = 14
ASSISTENTE_AGENDA_HARD_MAX_WINDOW_DAYS = 31
AGENDA_RELACIONADOS_MAX_IDS = 100
DIAS_SEMANA_PT = [
    "segunda-feira",
    "terca-feira",
    "quarta-feira",
    "quinta-feira",
    "sexta-feira",
    "sabado",
    "domingo",
]


def _parse_agendamento_ids_param(value: str) -> list[int]:
    tokens = str(value or "").split(",")
    if not tokens or any(not token.strip() for token in tokens):
        raise HTTPException(status_code=400, detail="Informe agendamento_ids separados por virgula.")

    ids: list[int] = []
    vistos: set[int] = set()
    for token in tokens:
        normalizado = token.strip()
        if not normalizado.isdigit():
            raise HTTPException(status_code=400, detail="agendamento_ids deve conter apenas inteiros positivos.")
        agendamento_id = int(normalizado)
        if agendamento_id <= 0:
            raise HTTPException(status_code=400, detail="agendamento_ids deve conter apenas inteiros positivos.")
        if agendamento_id in vistos:
            continue
        vistos.add(agendamento_id)
        ids.append(agendamento_id)

    if len(ids) > AGENDA_RELACIONADOS_MAX_IDS:
        raise HTTPException(
            status_code=400,
            detail=f"agendamento_ids aceita no maximo {AGENDA_RELACIONADOS_MAX_IDS} IDs unicos.",
        )
    return ids


def _usuario_tem_papel(usuario: Any, papel: str) -> bool:
    metodo = getattr(usuario, "tem_papel", None)
    if callable(metodo):
        try:
            return bool(metodo(papel))
        except Exception:
            return False
    return False


def _listar_bloqueios_ativos(db: Session) -> list[AgendaBloqueio]:
    cache_key = "_agenda_bloqueios_table_available"
    available = db.info.get(cache_key)
    if available is None:
        # A sessao ja retém uma conexao; inspecionar o Engine pediria outra
        # ao pool e poderia bloquear a propria requisicao sob concorrencia.
        available = "agenda_bloqueios" in inspect(db.connection()).get_table_names()
        db.info[cache_key] = available
    if not available:
        return []
    return db.query(AgendaBloqueio).filter(AgendaBloqueio.ativo.is_(True)).all()


def _ensure_agendamento_workflow_columns(db: Session) -> None:
    """Compatibilidade legada executada no startup, nunca no caminho HTTP."""
    if db.info.get("_agenda_workflow_columns_checked"):
        return

    bind = db.get_bind()
    insp = inspect(bind)
    if "agendamentos" not in insp.get_table_names():
        db.info["_agenda_workflow_columns_checked"] = True
        return

    colunas = {col["name"] for col in insp.get_columns("agendamentos")}
    alteracoes: dict[str, str] = {
        "excecao_sobreposicao": 'ALTER TABLE "agendamentos" ADD COLUMN excecao_sobreposicao TEXT',
        "tutor_id": 'ALTER TABLE "agendamentos" ADD COLUMN tutor_id INTEGER',
        "origem_atendimento": 'ALTER TABLE "agendamentos" ADD COLUMN origem_atendimento VARCHAR(32) DEFAULT \'clinica_parceira\'',
        "reserva_expira_em": 'ALTER TABLE "agendamentos" ADD COLUMN reserva_expira_em TIMESTAMP',
        "excecao_deslocamento_concedida_em": 'ALTER TABLE "agendamentos" ADD COLUMN excecao_deslocamento_concedida_em TIMESTAMP',
        "excecao_deslocamento_concedida_por_id": 'ALTER TABLE "agendamentos" ADD COLUMN excecao_deslocamento_concedida_por_id INTEGER',
        "excecao_deslocamento_concedida_por_nome": 'ALTER TABLE "agendamentos" ADD COLUMN excecao_deslocamento_concedida_por_nome VARCHAR(255)',
        "excecao_deslocamento_motivo": 'ALTER TABLE "agendamentos" ADD COLUMN excecao_deslocamento_motivo TEXT',
        "excecao_deslocamento_escopo": 'ALTER TABLE "agendamentos" ADD COLUMN excecao_deslocamento_escopo VARCHAR(64)',
        "excecao_agenda_fechada_escopo": 'ALTER TABLE "agendamentos" ADD COLUMN excecao_agenda_fechada_escopo VARCHAR(100)',
    }

    faltantes = [sql for coluna, sql in alteracoes.items() if coluna not in colunas]
    if not faltantes:
        db.info["_agenda_workflow_columns_checked"] = True
        return

    for sql in faltantes:
        db.execute(text(sql))
    db.execute(
        text(
            "UPDATE agendamentos SET origem_atendimento = 'clinica_parceira' "
            "WHERE origem_atendimento IS NULL OR TRIM(origem_atendimento) = ''"
        )
    )
    db.commit()
    db.info["_agenda_workflow_columns_checked"] = True


def _normalizar_origem_atendimento(value: Optional[str]) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ORIGEM_ATENDIMENTO_PADRAO
    aliases = {
        "clinica": ORIGEM_ATENDIMENTO_PADRAO,
        "clinica_parceira": ORIGEM_ATENDIMENTO_PADRAO,
        "parceira": ORIGEM_ATENDIMENTO_PADRAO,
        "domiciliar": ORIGEM_ATENDIMENTO_DOMICILIAR,
    }
    origem = aliases.get(raw, raw)
    if origem not in ORIGENS_ATENDIMENTO_PERMITIDAS:
        raise HTTPException(
            status_code=422,
            detail="Origem de atendimento invalida. Use clinica_parceira ou domiciliar.",
        )
    return origem


def _resolver_tutor_agendamento(db: Session, agendamento: Agendamento) -> Optional[Tutor]:
    tutor_id = int(getattr(agendamento, "tutor_id", 0) or 0)
    if tutor_id > 0:
        tutor = db.query(Tutor).filter(Tutor.id == tutor_id).first()
        if tutor:
            return tutor

    paciente_id = int(getattr(agendamento, "paciente_id", 0) or 0)
    if paciente_id <= 0:
        return None
    paciente = db.query(Paciente).filter(Paciente.id == paciente_id).first()
    if not paciente or not paciente.tutor_id:
        return None
    tutor = db.query(Tutor).filter(Tutor.id == paciente.tutor_id).first()
    if tutor and tutor_id <= 0:
        agendamento.tutor_id = tutor.id
    return tutor


def _resolver_tutor_id_relacionado(
    agendamento: Agendamento,
    tutor_id_relacionado: Optional[int] = None,
) -> Optional[int]:
    try:
        tutor_id_atual = int(getattr(agendamento, "tutor_id", 0) or 0)
    except (TypeError, ValueError):
        tutor_id_atual = 0
    if tutor_id_atual > 0:
        return tutor_id_atual

    try:
        tutor_id_fallback = int(tutor_id_relacionado or 0)
    except (TypeError, ValueError):
        tutor_id_fallback = 0
    if tutor_id_fallback > 0:
        agendamento.tutor_id = tutor_id_fallback
        return tutor_id_fallback
    return None


class SugestaoHorarioPayload(BaseModel):
    preferencia: Optional[AgendaPreferencia] = None
    data: str = Field(..., description="Data no formato YYYY-MM-DD")
    origem_atendimento: Literal["clinica_parceira", "domiciliar"] = Field(default=ORIGEM_ATENDIMENTO_PADRAO)
    clinica_id: Optional[int] = Field(default=None, ge=1)
    tutor_id: Optional[int] = Field(default=None, ge=1)
    servico_id: Optional[int] = Field(default=None, ge=1)
    duracao_minutos: Optional[int] = Field(default=None, ge=5, le=720)
    intervalo_minutos: int = Field(default=15, ge=5, le=120)
    limite: int = Field(default=8, ge=1, le=50)
    perfil_deslocamento: str = Field(default="comercial")
    ignorar_agendamento_id: Optional[int] = Field(default=None, ge=1)


class OportunidadesDiaPayload(BaseModel):
    data: str
    servico_id: Optional[int] = Field(default=None, ge=1)
    limite: Optional[int] = Field(default=20, ge=1, le=50)


class ValidarOfertaAssistentePayload(BaseModel):
    inicio: str = Field(..., description="Inicio exato da oferta em horario local, YYYY-MM-DD HH:mm")
    origem_atendimento: Literal["clinica_parceira", "domiciliar"] = Field(default=ORIGEM_ATENDIMENTO_PADRAO)
    clinica_id: Optional[int] = Field(default=None, ge=1)
    tutor_id: Optional[int] = Field(default=None, ge=1)
    servico_id: Optional[int] = Field(default=None, ge=1)
    duracao_minutos: Optional[int] = Field(default=None, ge=5, le=720)
    perfil_deslocamento: str = Field(default="comercial")
    ignorar_agendamento_id: Optional[int] = Field(default=None, ge=1)


class SugestaoProximidadePayload(BaseModel):
    preferencia: Optional[AgendaPreferencia] = None
    origem_atendimento: Literal["clinica_parceira", "domiciliar"] = Field(default=ORIGEM_ATENDIMENTO_PADRAO)
    clinica_id: Optional[int] = Field(default=None, ge=1)
    tutor_id: Optional[int] = Field(default=None, ge=1)
    data: Optional[str] = Field(default=None, description="Data no formato YYYY-MM-DD")
    data_contato: Optional[str] = Field(default=None, description="Data do contato no formato YYYY-MM-DD")
    servico_id: Optional[int] = Field(default=None, ge=1)
    duracao_minutos: Optional[int] = Field(default=None, ge=5, le=720)
    intervalo_minutos: int = Field(default=30, ge=5, le=120)
    limite_sugestoes_operacionais: int = Field(default=8, ge=1, le=50)
    perfil_deslocamento: str = Field(default="comercial")
    limite_minutos: int = Field(default=25, ge=1, le=180)
    ignorar_agendamento_id: Optional[int] = Field(default=None, ge=1)
    incluir_mesma_clinica: bool = Field(default=True)
    janela_dias_proximidade: int = Field(default=7, ge=0, le=30)


class AssistenteEncerramentoPayload(BaseModel):
    tipo: Literal["solicitacao_excecao", "encerramento_sem_agendamento"] = Field(...)
    motivo: str = Field(..., min_length=5, max_length=1200)
    origem_atendimento: Optional[Literal["clinica_parceira", "domiciliar"]] = Field(default=None)
    clinica_id: Optional[int] = Field(default=None, ge=1)
    tutor_id: Optional[int] = Field(default=None, ge=1)
    servico_id: Optional[int] = Field(default=None, ge=1)
    data_referencia: Optional[str] = Field(default=None, description="Data no formato YYYY-MM-DD")
    data_contato: Optional[str] = Field(default=None, description="Data do primeiro contato no formato YYYY-MM-DD")
    contexto: Optional[dict[str, Any]] = Field(default=None)


class AssistenteOfertaPayload(BaseModel):
    preferencia: Optional[AgendaPreferencia] = None
    origem_atendimento: Literal["clinica_parceira", "domiciliar"] = Field(default=ORIGEM_ATENDIMENTO_PADRAO)
    clinica_id: Optional[int] = Field(default=None, ge=1)
    tutor_id: Optional[int] = Field(default=None, ge=1)
    data: Optional[str] = Field(default=None, description="Data no formato YYYY-MM-DD")
    data_contato: Optional[str] = Field(default=None, description="Data do contato no formato YYYY-MM-DD")
    servico_id: Optional[int] = Field(default=None, ge=1)
    duracao_minutos: Optional[int] = Field(default=None, ge=5, le=720)
    intervalo_minutos: int = Field(default=30, ge=5, le=120)
    limite: int = Field(default=8, ge=1, le=50)
    perfil_deslocamento: str = Field(default="comercial")
    limite_minutos: int = Field(default=25, ge=1, le=180)
    ignorar_agendamento_id: Optional[int] = Field(default=None, ge=1)
    incluir_mesma_clinica: bool = Field(default=True)
    janela_dias_proximidade: int = Field(default=7, ge=0, le=30)


class ReabilitarReservaPayload(BaseModel):
    prazo_confirmacao_horas: Optional[float] = Field(
        default=None,
        ge=PRAZO_REABILITACAO_RESERVA_HORAS_MIN,
        le=PRAZO_REABILITACAO_RESERVA_HORAS_MAX,
        description="Novo prazo de confirmacao em horas contadas de agora (padrao 3h).",
    )
    reserva_expira_em: Optional[datetime] = Field(
        default=None,
        description="Prazo exato de confirmacao; quando informado, ignora prazo_confirmacao_horas.",
    )
    confirmar_slot_reserva_expirada: bool = Field(default=False)
    confirmar_conflito_deslocamento: bool = Field(default=False)
    motivo_excecao_deslocamento: Optional[str] = Field(
        default=None,
        description="Motivo registrado ao conceder a excecao de conflito de rota.",
    )


def _parse_hora_hhmm(value: Optional[str], fallback: str) -> str:
    raw = str(value or "").strip()
    if len(raw) != 5 or raw[2] != ":":
        return fallback

    hh = raw[:2]
    mm = raw[3:]
    if not (hh.isdigit() and mm.isdigit()):
        return fallback

    hora = int(hh)
    minuto = int(mm)
    if hora < 0 or hora > 23 or minuto < 0 or minuto > 59:
        return fallback
    return f"{hora:02d}:{minuto:02d}"


def _hora_para_minutos(value: str) -> int:
    hh, mm = value.split(":")
    return int(hh) * 60 + int(mm)


def _combine_date_hhmm(data_ref: date, hora_hhmm: str) -> datetime:
    hh, mm = hora_hhmm.split(":")
    return datetime(
        data_ref.year,
        data_ref.month,
        data_ref.day,
        int(hh),
        int(mm),
        0,
        0,
    )


def _minutos_entre(inicio: datetime, fim: datetime) -> int:
    return int((fim - inicio).total_seconds() // 60)


def _arredondar_para_proximo_slot(data_hora: datetime, intervalo_minutos: int) -> datetime:
    intervalo = max(1, int(intervalo_minutos))
    base = data_hora.replace(second=0, microsecond=0)
    total_min = (base.hour * 60) + base.minute
    resto = total_min % intervalo
    if resto == 0:
        return base
    total_ajustado = total_min + (intervalo - resto)
    inicio_dia = base.replace(hour=0, minute=0, second=0, microsecond=0)
    return inicio_dia + timedelta(minutes=total_ajustado)


def _obter_duracao_deslocamento_cacheado(
    db: Session,
    *,
    origem_clinica_id: Optional[int],
    destino_clinica_id: Optional[int],
    perfil: str,
    permitir_estimativa_fallback: bool = True,
    cache: Optional[dict[tuple[int, int, str, bool], tuple[int, str]]] = None,
    commit_cache: bool = True,
) -> tuple[int, str]:
    perfil_norm = normalizar_perfil(perfil)
    chave = (
        int(origem_clinica_id or 0),
        int(destino_clinica_id or 0),
        perfil_norm,
        bool(permitir_estimativa_fallback),
    )
    if isinstance(cache, dict) and chave in cache:
        return cache[chave]

    resultado = obter_duracao_deslocamento(
        db,
        origem_clinica_id=origem_clinica_id,
        destino_clinica_id=destino_clinica_id,
        perfil=perfil_norm,
        permitir_estimativa_fallback=permitir_estimativa_fallback,
        commit_cache=commit_cache,
    )
    if isinstance(cache, dict):
        cache[chave] = resultado
    return resultado


def _nome_clinica_legivel(nome: Optional[str], fallback: str = "destino nao informado") -> str:
    valor = str(nome or "").strip()
    return valor or fallback


def _formatar_data_com_semana_pt(data_iso: Optional[str]) -> str:
    raw = str(data_iso or "").strip()
    if not raw:
        return "data nao informada"
    try:
        data_ref = datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return raw
    return f"{raw} ({DIAS_SEMANA_PT[data_ref.weekday()]})"


def _frase_deslocamento_entre_clinicas(origem: str, destino: str, duracao_min: int) -> str:
    origem_nome = _nome_clinica_legivel(origem)
    destino_nome = _nome_clinica_legivel(destino)
    if origem_nome.casefold() == destino_nome.casefold():
        return f"Deslocamento local em {origem_nome}: {duracao_min} min."
    return f"Deslocamento entre {origem_nome} e {destino_nome} de {duracao_min} min."


def _detalhar_deslocamento_por_clinicas(
    *,
    clinica_destino: Optional[str],
    clinica_anterior: Optional[str],
    clinica_posterior: Optional[str],
    duracao_anterior_min: Optional[int],
    duracao_posterior_min: Optional[int],
    total_min: Optional[int],
    ha_agendamento_anterior: bool,
    ha_agendamento_posterior: bool,
    trecho_anterior_desconsiderado: bool = False,
    trecho_posterior_desconsiderado: bool = False,
    duracao_anterior_real_min: Optional[int] = None,
    duracao_posterior_real_min: Optional[int] = None,
) -> str:
    destino_nome = _nome_clinica_legivel(clinica_destino)
    anterior_nome = _nome_clinica_legivel(clinica_anterior)
    posterior_nome = _nome_clinica_legivel(clinica_posterior)
    anterior_min = max(0, int(duracao_anterior_min or 0))
    posterior_min = max(0, int(duracao_posterior_min or 0))
    total = max(0, int(total_min or 0))

    partes = []
    if ha_agendamento_anterior:
        if trecho_anterior_desconsiderado:
            anterior_real = max(0, int(duracao_anterior_real_min or anterior_min))
            partes.append(
                f"Trecho anterior entre {anterior_nome} e {destino_nome} desconsiderado "
                "pela regra de encaixe adjacente a agendamento ja registrado "
                f"(deslocamento real: {anterior_real} min)."
            )
        else:
            partes.append(_frase_deslocamento_entre_clinicas(anterior_nome, destino_nome, anterior_min))
    else:
        partes.append("Nao ha agendamentos anteriores ainda.")

    if ha_agendamento_posterior:
        if trecho_posterior_desconsiderado:
            posterior_real = max(0, int(duracao_posterior_real_min or posterior_min))
            partes.append(
                f"Trecho posterior entre {destino_nome} e {posterior_nome} desconsiderado "
                "pela regra de encaixe adjacente a agendamento ja registrado "
                f"(deslocamento real: {posterior_real} min)."
            )
        else:
            partes.append(_frase_deslocamento_entre_clinicas(destino_nome, posterior_nome, posterior_min))
    else:
        partes.append("Nao ha agendamentos posteriores ainda.")

    partes.append(f"Total estimado de deslocamento: {total} min.")
    return " ".join(partes)


def _nome_clinica_por_id(db: Session, clinica_id: Optional[int]) -> str:
    if not clinica_id:
        return "Clinica nao informada"
    clinica = db.query(Clinica).filter(Clinica.id == int(clinica_id)).first()
    if clinica and clinica.nome:
        return str(clinica.nome).strip()
    return f"Clinica #{int(clinica_id)}"


def _nome_tutor_por_id(db: Session, tutor_id: Optional[int]) -> str:
    if not tutor_id:
        return "Tutor nao informado"
    tutor = db.query(Tutor).filter(Tutor.id == int(tutor_id)).first()
    if tutor and tutor.nome:
        return str(tutor.nome).strip()
    return f"Tutor #{int(tutor_id)}"


def _clinica_tem_localizacao_confiavel(clinica: Optional[Clinica]) -> bool:
    if not clinica:
        return False
    if clinica.latitude is None or clinica.longitude is None:
        return False
    try:
        lat = float(clinica.latitude)
        lng = float(clinica.longitude)
    except (TypeError, ValueError):
        return False
    if not math.isfinite(lat) or not math.isfinite(lng):
        return False
    if lat < -90.0 or lat > 90.0 or lng < -180.0 or lng > 180.0:
        return False
    if abs(lat) < 0.000001 and abs(lng) < 0.000001:
        return False
    return True


def _assert_clinica_georreferenciada(clinica: Optional[Clinica], *, contexto: str) -> None:
    if clinica is None:
        raise HTTPException(status_code=404, detail="Clinica nao encontrada.")
    if _clinica_tem_localizacao_confiavel(clinica):
        return
    raise HTTPException(
        status_code=422,
        detail=(
            f"Nao foi possivel {contexto} porque a clinica selecionada ainda nao possui "
            "endereco georreferenciado pela API Google. Atualize o cadastro da clinica antes de continuar."
        ),
    )


def _tutor_tem_endereco_preenchido(tutor: Optional[Tutor]) -> bool:
    if not tutor:
        return False
    return all(
        str(valor or "").strip()
        for valor in [tutor.endereco, tutor.numero, tutor.cidade, tutor.estado]
    )


def _tutor_tem_localizacao_confiavel(tutor: Optional[Tutor]) -> bool:
    if not tutor:
        return False
    if not _tutor_tem_endereco_preenchido(tutor):
        return False
    if tutor.latitude is None or tutor.longitude is None:
        return False
    try:
        lat = float(tutor.latitude)
        lng = float(tutor.longitude)
    except (TypeError, ValueError):
        return False
    if not math.isfinite(lat) or not math.isfinite(lng):
        return False
    if lat < -90.0 or lat > 90.0 or lng < -180.0 or lng > 180.0:
        return False
    if abs(lat) < 0.000001 and abs(lng) < 0.000001:
        return False
    return True


def _assert_tutor_georreferenciado(tutor: Optional[Tutor], *, contexto: str) -> None:
    if tutor is None:
        raise HTTPException(status_code=422, detail="Selecione um tutor valido para o atendimento domiciliar.")
    if _tutor_tem_localizacao_confiavel(tutor):
        return
    raise HTTPException(
        status_code=422,
        detail=(
            f"Nao foi possivel {contexto} porque o tutor selecionado ainda nao possui "
            "endereco georreferenciado pela API Google. Atualize o cadastro do tutor antes de continuar."
        ),
    )


def _criar_destino_operacional_clinica(
    clinica: Optional[Clinica],
    *,
    fallback_nome: Optional[str] = None,
) -> dict[str, Any]:
    clinica_id = int(getattr(clinica, "id", 0) or 0) if clinica is not None else 0
    nome = str(getattr(clinica, "nome", None) or fallback_nome or "").strip()
    if not nome:
        nome = f"Clinica #{clinica_id}" if clinica_id > 0 else "Clinica nao informada"
    return {
        "tipo": ORIGEM_ATENDIMENTO_PADRAO,
        "entity_id": clinica_id or None,
        "clinica_id": clinica_id or None,
        "tutor_id": None,
        "nome": nome,
        "label": nome,
        "latitude": getattr(clinica, "latitude", None) if clinica is not None else None,
        "longitude": getattr(clinica, "longitude", None) if clinica is not None else None,
        "place_id": getattr(clinica, "place_id", None) if clinica is not None else None,
        "endereco": getattr(clinica, "endereco", None) if clinica is not None else None,
        "numero": getattr(clinica, "numero", None) if clinica is not None else None,
        "complemento": getattr(clinica, "complemento", None) if clinica is not None else None,
        "bairro": getattr(clinica, "bairro", None) if clinica is not None else None,
        "cidade": getattr(clinica, "cidade", None) if clinica is not None else None,
        "estado": getattr(clinica, "estado", None) if clinica is not None else None,
        "cep": getattr(clinica, "cep", None) if clinica is not None else None,
        "geocode_at": getattr(clinica, "geocode_at", None) if clinica is not None else None,
        "localizacao_confiavel": _clinica_tem_localizacao_confiavel(clinica),
        "obj": clinica,
    }


def _criar_destino_operacional_tutor(
    tutor: Optional[Tutor],
    *,
    fallback_nome: Optional[str] = None,
) -> dict[str, Any]:
    tutor_id = int(getattr(tutor, "id", 0) or 0) if tutor is not None else 0
    nome_tutor = str(getattr(tutor, "nome", None) or fallback_nome or "").strip()
    if not nome_tutor:
        nome_tutor = f"Tutor #{tutor_id}" if tutor_id > 0 else "Tutor nao informado"
    label = f"Domicilio de {nome_tutor}" if nome_tutor != "Tutor nao informado" else "Atendimento domiciliar"
    return {
        "tipo": ORIGEM_ATENDIMENTO_DOMICILIAR,
        "entity_id": tutor_id or None,
        "clinica_id": None,
        "tutor_id": tutor_id or None,
        "nome": nome_tutor,
        "label": label,
        "latitude": getattr(tutor, "latitude", None) if tutor is not None else None,
        "longitude": getattr(tutor, "longitude", None) if tutor is not None else None,
        "place_id": getattr(tutor, "place_id", None) if tutor is not None else None,
        "endereco": getattr(tutor, "endereco", None) if tutor is not None else None,
        "numero": getattr(tutor, "numero", None) if tutor is not None else None,
        "complemento": getattr(tutor, "complemento", None) if tutor is not None else None,
        "bairro": getattr(tutor, "bairro", None) if tutor is not None else None,
        "cidade": getattr(tutor, "cidade", None) if tutor is not None else None,
        "estado": getattr(tutor, "estado", None) if tutor is not None else None,
        "cep": getattr(tutor, "cep", None) if tutor is not None else None,
        "geocode_at": getattr(tutor, "updated_at", None) if tutor is not None else None,
        "localizacao_confiavel": _tutor_tem_localizacao_confiavel(tutor),
        "obj": tutor,
    }


def _rotulo_destino_operacional(destino: Optional[dict[str, Any]], fallback: str = "Destino nao informado") -> str:
    if isinstance(destino, dict):
        label = str(destino.get("label") or destino.get("nome") or "").strip()
        if label:
            return label
        if str(destino.get("tipo") or "").strip() == ORIGEM_ATENDIMENTO_DOMICILIAR:
            return "Atendimento domiciliar"
    return fallback


def _destinos_operacionais_mesma_referencia(
    origem: Optional[dict[str, Any]],
    destino: Optional[dict[str, Any]],
) -> bool:
    if not isinstance(origem, dict) or not isinstance(destino, dict):
        return False
    if str(origem.get("tipo") or "").strip() != str(destino.get("tipo") or "").strip():
        return False
    origem_id = int(origem.get("entity_id") or 0)
    destino_id = int(destino.get("entity_id") or 0)
    return origem_id > 0 and origem_id == destino_id


def _adaptar_destino_operacional_para_logistica(destino: Optional[dict[str, Any]]) -> Optional[SimpleNamespace]:
    if not isinstance(destino, dict):
        return None
    lat = destino.get("latitude")
    lng = destino.get("longitude")
    if lat is None or lng is None:
        return None
    entity_id = int(destino.get("entity_id") or 0)
    tipo = str(destino.get("tipo") or "").strip() or ORIGEM_ATENDIMENTO_PADRAO
    adapter_id = entity_id if tipo == ORIGEM_ATENDIMENTO_PADRAO else (-entity_id if entity_id > 0 else -1)
    return SimpleNamespace(
        id=adapter_id,
        nome=destino.get("nome"),
        latitude=lat,
        longitude=lng,
        place_id=destino.get("place_id"),
        endereco=destino.get("endereco"),
        numero=destino.get("numero"),
        complemento=destino.get("complemento"),
        bairro=destino.get("bairro"),
        cidade=destino.get("cidade"),
        estado=destino.get("estado"),
        cep=destino.get("cep"),
        geocode_at=destino.get("geocode_at"),
    )


def _tempo_estimado_destino_operacional_ate_base_min(
    destino: Optional[dict[str, Any]],
    *,
    base_lat: Optional[float],
    base_lng: Optional[float],
    perfil_deslocamento: str = "comercial",
) -> Optional[int]:
    destino_adaptado = _adaptar_destino_operacional_para_logistica(destino)
    if destino_adaptado is None:
        return None
    return _tempo_estimado_clinica_ate_base_min(
        destino_adaptado,
        base_lat=base_lat,
        base_lng=base_lng,
        perfil_deslocamento=perfil_deslocamento,
    )


def _destinos_operacionais_mesma_regiao(
    destino_a: Optional[dict[str, Any]],
    destino_b: Optional[dict[str, Any]],
) -> bool:
    if _destinos_operacionais_mesma_referencia(destino_a, destino_b):
        return True
    origem = _adaptar_destino_operacional_para_logistica(destino_a)
    destino = _adaptar_destino_operacional_para_logistica(destino_b)
    if origem is None or destino is None:
        return False
    return _clinicas_mesma_regiao_operacional(origem, destino)


def _resolver_destino_operacional_payload(
    db: Session,
    *,
    origem_atendimento: Optional[str],
    clinica_id: Optional[int],
    tutor_id: Optional[int],
    contexto: str,
) -> dict[str, Any]:
    origem = _normalizar_origem_atendimento(origem_atendimento)
    if origem == ORIGEM_ATENDIMENTO_DOMICILIAR:
        tutor = db.query(Tutor).filter(Tutor.id == int(tutor_id or 0)).first() if tutor_id else None
        _assert_tutor_georreferenciado(tutor, contexto=contexto)
        return _criar_destino_operacional_tutor(tutor)

    clinica = db.query(Clinica).filter(Clinica.id == int(clinica_id or 0)).first() if clinica_id else None
    _assert_clinica_georreferenciada(clinica, contexto=contexto)
    return _criar_destino_operacional_clinica(clinica)


def _obter_duracao_deslocamento_operacional(
    db: Session,
    *,
    origem: Optional[dict[str, Any]],
    destino: Optional[dict[str, Any]],
    perfil: str,
    cache_clinicas: Optional[dict[tuple[int, int, str, bool], tuple[int, str]]] = None,
    cache_operacional: Optional[dict[tuple[str, int, str, int, str], tuple[int, str]]] = None,
    cache_google: Optional[dict] = None,
    commit_cache: bool = True,
) -> tuple[int, str]:
    if not isinstance(origem, dict) or not isinstance(destino, dict):
        return 0, "indefinido"
    if _destinos_operacionais_mesma_referencia(origem, destino):
        return 0, "mesmo_destino"

    perfil_norm = normalizar_perfil(perfil)
    origem_tipo = str(origem.get("tipo") or "").strip() or ORIGEM_ATENDIMENTO_PADRAO
    destino_tipo = str(destino.get("tipo") or "").strip() or ORIGEM_ATENDIMENTO_PADRAO
    origem_entity_id = int(origem.get("entity_id") or 0)
    destino_entity_id = int(destino.get("entity_id") or 0)

    if (
        origem_tipo == ORIGEM_ATENDIMENTO_PADRAO
        and destino_tipo == ORIGEM_ATENDIMENTO_PADRAO
        and origem_entity_id > 0
        and destino_entity_id > 0
    ):
        return _obter_duracao_deslocamento_cacheado(
            db,
            origem_clinica_id=origem_entity_id,
            destino_clinica_id=destino_entity_id,
            perfil=perfil_norm,
            permitir_estimativa_fallback=True,
            cache=cache_clinicas,
            commit_cache=commit_cache,
        )

    chave = (origem_tipo, origem_entity_id, destino_tipo, destino_entity_id, perfil_norm)
    if isinstance(cache_operacional, dict) and chave in cache_operacional:
        return cache_operacional[chave]

    origem_adaptado = _adaptar_destino_operacional_para_logistica(origem)
    destino_adaptado = _adaptar_destino_operacional_para_logistica(destino)
    if origem_adaptado is None or destino_adaptado is None:
        resultado = (0, "indefinido")
    else:
        duracao_min, fonte = obter_duracao_deslocamento_entidades(
            db,
            origem=origem_adaptado,
            destino=destino_adaptado,
            perfil=perfil_norm,
            permitir_estimativa_fallback=True,
            google_cache=cache_google,
            commit_cache=commit_cache,
        )
        resultado = (max(0, int(duracao_min or 0)), str(fonte or "indefinido"))

    if isinstance(cache_operacional, dict):
        cache_operacional[chave] = resultado
    return resultado


def _resolver_destino_operacional_agendamento(
    db: Session,
    agendamento: Agendamento,
    *,
    cache_clinicas: Optional[dict[int, Optional[Clinica]]] = None,
    cache_tutores: Optional[dict[int, Optional[Tutor]]] = None,
    cache_pacientes: Optional[dict[int, Optional[Paciente]]] = None,
) -> dict[str, Any]:
    origem = _normalizar_origem_atendimento(getattr(agendamento, "origem_atendimento", None))
    clinicas_cache = cache_clinicas if isinstance(cache_clinicas, dict) else {}
    tutores_cache = cache_tutores if isinstance(cache_tutores, dict) else {}
    pacientes_cache = cache_pacientes if isinstance(cache_pacientes, dict) else {}

    def _get_clinica(cid: Optional[int]) -> Optional[Clinica]:
        clinica_id = int(cid or 0)
        if clinica_id <= 0:
            return None
        if clinica_id not in clinicas_cache:
            clinicas_cache[clinica_id] = db.query(Clinica).filter(Clinica.id == clinica_id).first()
        return clinicas_cache[clinica_id]

    def _get_tutor(tid: Optional[int]) -> Optional[Tutor]:
        tutor_id = int(tid or 0)
        if tutor_id <= 0:
            return None
        if tutor_id not in tutores_cache:
            tutores_cache[tutor_id] = db.query(Tutor).filter(Tutor.id == tutor_id).first()
        return tutores_cache[tutor_id]

    def _get_paciente(pid: Optional[int]) -> Optional[Paciente]:
        paciente_id = int(pid or 0)
        if paciente_id <= 0:
            return None
        if paciente_id not in pacientes_cache:
            pacientes_cache[paciente_id] = db.query(Paciente).filter(Paciente.id == paciente_id).first()
        return pacientes_cache[paciente_id]

    if origem == ORIGEM_ATENDIMENTO_DOMICILIAR:
        tutor = _get_tutor(getattr(agendamento, "tutor_id", None))
        if tutor is None:
            paciente = _get_paciente(getattr(agendamento, "paciente_id", None))
            tutor = _get_tutor(getattr(paciente, "tutor_id", None))
        return _criar_destino_operacional_tutor(tutor, fallback_nome=getattr(agendamento, "tutor", None))

    clinica = _get_clinica(getattr(agendamento, "clinica_id", None))
    return _criar_destino_operacional_clinica(clinica, fallback_nome=getattr(agendamento, "clinica", None))


def _validar_regras_origem_agendamento(
    db: Session,
    agendamento: Agendamento,
    *,
    contexto: str,
) -> str:
    origem = _normalizar_origem_atendimento(getattr(agendamento, "origem_atendimento", None))
    agendamento.origem_atendimento = origem

    tutor = _resolver_tutor_agendamento(db, agendamento)
    if getattr(agendamento, "tutor_id", None):
        from app.services.tutor_identidade_service import exigir_tutor_utilizavel
        tutor = exigir_tutor_utilizavel(db, agendamento.tutor_id)
    if tutor and not getattr(agendamento, "tutor_id", None):
        agendamento.tutor_id = tutor.id

    if origem == ORIGEM_ATENDIMENTO_DOMICILIAR:
        agendamento.clinica_id = None
        _assert_tutor_georreferenciado(tutor, contexto=contexto)
    else:
        if agendamento.clinica_id:
            clinica_agendamento = db.query(Clinica).filter(Clinica.id == agendamento.clinica_id).first()
            _assert_clinica_georreferenciada(clinica_agendamento, contexto=contexto)

    return origem


def _rotulo_clinica_agendamento(
    agendamento: Agendamento,
    clinica_nome: Optional[str] = None,
) -> str:
    nome = str(clinica_nome or getattr(agendamento, "clinica", None) or "").strip()
    if nome:
        return nome
    origem = _normalizar_origem_atendimento(getattr(agendamento, "origem_atendimento", None))
    if origem == ORIGEM_ATENDIMENTO_DOMICILIAR:
        return "Atendimento domiciliar"
    return ""


def _hora_hhmm_para_minutos(value: Optional[str], fallback: int = 16 * 60) -> int:
    raw = str(value or "").strip()
    if len(raw) != 5 or raw[2] != ":":
        return fallback
    hh = raw[:2]
    mm = raw[3:]
    if not (hh.isdigit() and mm.isdigit()):
        return fallback
    hora = int(hh)
    minuto = int(mm)
    if hora < 0 or hora > 23 or minuto < 0 or minuto > 59:
        return fallback
    return (hora * 60) + minuto


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    raio_terra_km = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return raio_terra_km * c


def _normalizar_localidade(value: Optional[str]) -> str:
    raw = str(value or "").strip().casefold()
    if not raw:
        return ""
    sem_acentos = unicodedata.normalize("NFKD", raw)
    sem_acentos = sem_acentos.encode("ascii", "ignore").decode("ascii")
    sem_pontuacao = re.sub(r"[^a-z0-9]+", " ", sem_acentos)
    return re.sub(r"\s+", " ", sem_pontuacao).strip()


def _status_conta_como_ancora(status_value: Optional[str]) -> bool:
    status = str(status_value or "").strip() or "Agendado"
    return status not in AGENDA_STATUS_NAO_ANCORA


def _clinicas_mesma_regiao_operacional(
    clinica_a: Optional[Clinica],
    clinica_b: Optional[Clinica],
    *,
    max_cluster_km: float = 18.0,
) -> bool:
    if clinica_a is None or clinica_b is None:
        return False

    cidade_a = _normalizar_localidade(getattr(clinica_a, "cidade", None))
    cidade_b = _normalizar_localidade(getattr(clinica_b, "cidade", None))
    uf_a = _normalizar_localidade(getattr(clinica_a, "estado", None))
    uf_b = _normalizar_localidade(getattr(clinica_b, "estado", None))

    if cidade_a and cidade_b and cidade_a == cidade_b:
        if uf_a and uf_b and uf_a != uf_b:
            return False
        return True

    if _clinica_tem_localizacao_confiavel(clinica_a) and _clinica_tem_localizacao_confiavel(clinica_b):
        try:
            lat_a = float(clinica_a.latitude)
            lng_a = float(clinica_a.longitude)
            lat_b = float(clinica_b.latitude)
            lng_b = float(clinica_b.longitude)
        except (TypeError, ValueError):
            return False
        return _haversine_km(lat_a, lng_a, lat_b, lng_b) <= float(max_cluster_km)

    return False


def _tempo_estimado_clinica_ate_base_min(
    clinica: Optional[Clinica],
    *,
    base_lat: Optional[float],
    base_lng: Optional[float],
    perfil_deslocamento: str = "comercial",
) -> Optional[int]:
    if clinica is None:
        return None
    if base_lat is None or base_lng is None:
        return None
    if clinica.latitude is None or clinica.longitude is None:
        return None

    try:
        lat_clinica = float(clinica.latitude)
        lng_clinica = float(clinica.longitude)
        lat_base = float(base_lat)
        lng_base = float(base_lng)
    except (TypeError, ValueError):
        return None

    if not (
        math.isfinite(lat_clinica)
        and math.isfinite(lng_clinica)
        and math.isfinite(lat_base)
        and math.isfinite(lng_base)
    ):
        return None

    distancia_km = _haversine_km(lat_clinica, lng_clinica, lat_base, lng_base)
    perfil_norm = normalizar_perfil(perfil_deslocamento)
    velocidade_media_kmh = 26.0 if perfil_norm == "comercial" else 32.0
    buffer_min = 8 if perfil_norm == "comercial" else 5
    minutos = int(round((distancia_km / max(1.0, velocidade_media_kmh)) * 60.0))
    return max(1, minutos + buffer_min)


def _obter_regras_rota_agenda(db: Session) -> dict:
    config = db.query(Configuracao).first()
    if not config:
        return carregar_agenda_rota_regras(None)
    return carregar_agenda_rota_regras(getattr(config, "agenda_rota_regras", None))


def _endereco_base_primeira_saida(base_cfg: dict[str, Any]) -> str:
    endereco = str(base_cfg.get("address") or "").strip()
    cep = str(base_cfg.get("zip_code") or "").strip()
    return ", ".join(parte for parte in (endereco, f"CEP {cep}" if cep else "", "Brasil") if parte)


@lru_cache(maxsize=32)
def _geocodificar_base_primeira_saida(endereco_completo: str):
    # A base e pequena e estavel. O cache por endereco evita geocoding repetido
    # entre requisicoes, sem persistir coordenadas deduzidas na configuracao.
    return geocodificar_endereco_google(endereco_completo, settings.GOOGLE_MAPS_API_KEY)


def _obter_deslocamento_primeira_saida(
    db: Session,
    *,
    destino: dict[str, Any],
    base_cfg: dict[str, Any],
    perfil: str,
) -> tuple[Optional[int], str]:
    """Estima o trajeto casa→primeiro destino usando uma rota de rua do Google."""
    destino_adaptado = _adaptar_destino_operacional_para_logistica(destino)
    if destino_adaptado is None or not bool(destino.get("localizacao_confiavel")):
        return None, "destino_sem_localizacao"

    endereco = _endereco_base_primeira_saida(base_cfg)
    if not str(base_cfg.get("address") or "").strip():
        return None, "base_sem_endereco"
    perfil_norm = normalizar_perfil(perfil)
    chave = (
        endereco,
        base_cfg.get("lat"),
        base_cfg.get("lng"),
        destino.get("tipo"),
        destino.get("entity_id"),
        destino.get("latitude"),
        destino.get("longitude"),
        destino.get("place_id"),
        perfil_norm,
    )
    cache = db.info.setdefault("_agenda_primeira_saida_deslocamento", {})
    if chave in cache:
        # This per-session cache has no timestamp or durable freshness proof.
        # Cache-only policy cannot treat it as a validated stored route.
        if cache_only_operation():
            block_cache_only_lookup()
        return cache[chave]

    try:
        lat = float(base_cfg.get("lat"))
        lng = float(base_cfg.get("lng"))
        coordenadas_validas = (
            math.isfinite(lat) and math.isfinite(lng)
            and -90 <= lat <= 90 and -180 <= lng <= 180
            and not (abs(lat) < 0.000001 and abs(lng) < 0.000001)
        )
    except (TypeError, ValueError):
        lat = lng = None
        coordenadas_validas = False

    place_id = None
    cidade_base = "Fortaleza" if "fortaleza" in _normalizar_localidade(endereco) else ""
    estado_base = "CE" if cidade_base else ""
    permitir_google = bool(
        getattr(settings, "LOGISTICA_ALLOW_LIVE_GOOGLE_LOOKUPS_ON_READ", False)
        and str(settings.GOOGLE_MAPS_API_KEY or "").strip()
    )
    if not coordenadas_validas:
        if not permitir_google:
            resultado = (None, "base_sem_coordenadas")
            cache[chave] = resultado
            return resultado
        try:
            geocode = _geocodificar_base_primeira_saida(endereco)
            lat = float(geocode.latitude)
            lng = float(geocode.longitude)
            if not (
                math.isfinite(lat) and math.isfinite(lng)
                and -90 <= lat <= 90 and -180 <= lng <= 180
                and not (abs(lat) < 0.000001 and abs(lng) < 0.000001)
            ):
                raise ValueError("Coordenadas invalidas")
            # Um resultado de outra cidade/UF para a residencia confirmada
            # poderia tornar o primeiro trajeto perigosamente curto.
            if cidade_base and _normalizar_localidade(geocode.cidade) != _normalizar_localidade(cidade_base):
                raise ValueError("Municipio da base divergente")
            if estado_base and str(geocode.estado or "").strip().upper() != estado_base:
                raise ValueError("UF da base divergente")
            place_id = str(geocode.place_id or "").strip() or None
            cidade_base = str(geocode.cidade or cidade_base).strip()
            estado_base = str(geocode.estado or estado_base).strip()
        except (GeocodingError, TypeError, ValueError):
            resultado = (None, "base_geocode_indisponivel")
            cache[chave] = resultado
            return resultado

    origem = SimpleNamespace(
        id=-2147483647,
        nome="Casa (base operacional)",
        latitude=lat,
        longitude=lng,
        place_id=place_id,
        endereco=endereco,
        numero=None,
        complemento=None,
        bairro=None,
        cidade=cidade_base,
        estado=estado_base,
        cep=str(base_cfg.get("zip_code") or "").strip(),
        geocode_at=None,
    )
    try:
        _distancia_km, duracao_min, fonte = estimar_deslocamento(
            origem,
            destino_adaptado,
            perfil=perfil_norm,
            permitir_google_lookup=permitir_google,
        )
    except GoogleMapsCostBlocked:
        # Preserve the actionable cost/consent failure; never synthesize a route
        # or hide this as ordinary lack of availability.
        raise
    except Exception:
        resultado = (None, "rota_indisponivel")
        cache[chave] = resultado
        return resultado
    fonte = str(fonte or "indefinido")
    # Haversine e distancia em linha reta e pode subestimar vias/engarrafamentos.
    # Para a primeira chegada nao converta essa heuristica em oferta segura.
    if not fonte.startswith("google_") or int(duracao_min or 0) <= 0:
        resultado = (None, "rota_indisponivel")
    else:
        resultado = (int(duracao_min), fonte)
    cache[chave] = resultado
    return resultado


def _avaliar_primeira_saida(
    db: Session,
    *,
    inicio: datetime,
    destino: dict[str, Any],
    agendamentos_dia: list[dict],
    regras_rota: dict[str, Any],
    perfil: str,
    agora_local: Optional[datetime] = None,
    abertura_agenda: Optional[datetime] = None,
) -> Optional[dict[str, Any]]:
    """Devolve limite de chegada quando o candidato sera o primeiro compromisso ativo do dia."""
    if any(
        isinstance(item.get("inicio"), datetime)
        and item["inicio"] < inicio
        and _status_conta_como_ancora(item.get("status"))
        for item in agendamentos_dia
    ):
        return None

    agora = agora_local or datetime.now(LOCAL_TZ).replace(tzinfo=None)
    if inicio.date() < agora.date():
        return None
    base_cfg = regras_rota.get("base") if isinstance(regras_rota.get("base"), dict) else {}
    thresholds = regras_rota.get("thresholds") if isinstance(regras_rota.get("thresholds"), dict) else {}
    route_policy = regras_rota.get("route_policy") if isinstance(regras_rota.get("route_policy"), dict) else {}
    duracao_min, fonte = _obter_deslocamento_primeira_saida(
        db, destino=destino, base_cfg=base_cfg, perfil=perfil,
    )
    municipio = _normalizar_localidade(destino.get("cidade"))
    estado = _normalizar_localidade(destino.get("estado"))
    # Cadastros legados podem guardar "Caucaia - CE" no campo cidade.
    if municipio.endswith(" ce"):
        municipio = municipio[:-3].strip()
    elif municipio.endswith(" ceara"):
        municipio = municipio[:-6].strip()
    if estado and estado not in {"ce", "ceara"}:
        municipio = ""
    pisos = route_policy.get("first_appointment_city_floors")
    piso_hhmm = pisos.get(municipio) if isinstance(pisos, dict) else None
    piso_dt = (
        _combine_date_hhmm(inicio.date(), piso_hhmm)
        if isinstance(piso_hhmm, str) and re.fullmatch(r"\d{2}:\d{2}", piso_hhmm)
        else None
    )
    if duracao_min is None:
        return {
            "viavel": False,
            "tempo_deslocamento_base_min": None,
            "fonte_deslocamento_base": fonte,
            "inicio_minimo_primeira_saida": None,
            "piso_municipio": piso_hhmm,
        }

    abertura = abertura_agenda
    if abertura is None:
        abertura, _fim, _motivo = _obter_janela_funcionamento_data(db, inicio.date().isoformat())
    if abertura is None:
        # Para excecoes administrativas em dia fechado, use a abertura-padrao
        # como ponto de partida; o deslocamento continua obrigatorio.
        abertura = inicio.replace(hour=8, minute=0, second=0, microsecond=0)
    margem = max(0, int(thresholds.get("safe_margin_min", MIN_MARGEM_SEGURA_DESLOCAMENTO_MIN)))
    minimo = abertura + timedelta(minutes=duracao_min + margem)
    if inicio.date() == agora.date():
        minimo = max(minimo, agora + timedelta(minutes=duracao_min + margem))
    if piso_dt is not None:
        minimo = max(minimo, piso_dt)
    if minimo.second or minimo.microsecond:
        minimo = minimo.replace(second=0, microsecond=0) + timedelta(minutes=1)
    return {
        "viavel": inicio >= minimo,
        "tempo_deslocamento_base_min": duracao_min,
        "fonte_deslocamento_base": fonte,
        "inicio_minimo_primeira_saida": minimo.strftime("%Y-%m-%d %H:%M"),
        "piso_municipio": piso_hhmm,
    }


def _exigir_primeira_saida_viavel(avaliacao: Optional[dict[str, Any]]) -> None:
    if avaliacao is None or bool(avaliacao.get("viavel")):
        return
    minimo = avaliacao.get("inicio_minimo_primeira_saida")
    mensagem = (
        f"O primeiro atendimento deste dia so pode comecar a partir de {minimo[-5:]}, "
        "considerando a saida de casa, o deslocamento e a margem segura."
        if isinstance(minimo, str) and len(minimo) >= 5
        else "Nao foi possivel consultar uma rota confiavel de casa ate o primeiro atendimento. Tente novamente; se persistir, revise os enderecos e a configuracao de rotas."
    )
    raise HTTPException(
        status_code=409,
        detail={
            "codigo": "PRIMEIRA_SAIDA_INVIAVEL",
            "mensagem": mensagem,
            "inicio_minimo_primeira_saida": minimo,
            "tempo_deslocamento_base_min": avaliacao.get("tempo_deslocamento_base_min"),
            "fonte_deslocamento_base": avaliacao.get("fonte_deslocamento_base"),
            "confirmavel": True,
        },
    )


def _obter_max_window_assistente_agenda() -> int:
    raw = str(
        os.getenv(ASSISTENTE_AGENDA_MAX_WINDOW_ENV)
        or getattr(settings, ASSISTENTE_AGENDA_MAX_WINDOW_ENV, "")
        or ""
    ).strip()
    try:
        value = int(raw) if raw else ASSISTENTE_AGENDA_DEFAULT_MAX_WINDOW_DAYS
    except ValueError:
        value = ASSISTENTE_AGENDA_DEFAULT_MAX_WINDOW_DAYS
    return max(1, min(ASSISTENTE_AGENDA_HARD_MAX_WINDOW_DAYS, value))


def _validar_acesso_assistente_agenda(request: Request) -> None:
    expected = str(
        os.getenv(ASSISTENTE_AGENDA_TOKEN_ENV)
        or getattr(settings, ASSISTENTE_AGENDA_TOKEN_ENV, "")
        or ""
    ).strip()
    if len(expected) < 20:
        raise HTTPException(
            status_code=403,
            detail="Integracao read-only do assistente de agenda desabilitada.",
        )

    headers = getattr(request, "headers", {}) or {}
    provided = str(headers.get("x-assistente-agenda-token") or "").strip()
    auth_header = str(headers.get("authorization") or "").strip()
    if not provided and auth_header.lower().startswith("bearer "):
        provided = auth_header[7:].strip()

    if not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=403, detail="Token do assistente de agenda invalido.")


def _parse_data_assistente_agenda(value: Optional[str], *, field_label: str, default: date) -> date:
    raw = str(value or "").strip()
    if not raw:
        return default
    data_iso = _extract_date_filter(raw)
    if not data_iso:
        raise HTTPException(status_code=422, detail=f"{field_label} invalida. Use YYYY-MM-DD.")
    try:
        return datetime.strptime(data_iso, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=422, detail=f"{field_label} invalida. Use YYYY-MM-DD.")


def _resolver_periodo_assistente_agenda(
    data_inicio: Optional[str],
    data_fim: Optional[str],
) -> tuple[str, str, int]:
    hoje = datetime.now(LOCAL_TZ).date()
    inicio_ref = _parse_data_assistente_agenda(
        data_inicio,
        field_label="Data inicial",
        default=hoje,
    )
    fim_padrao = inicio_ref + timedelta(days=ASSISTENTE_AGENDA_DEFAULT_WINDOW_DAYS)
    fim_ref = _parse_data_assistente_agenda(
        data_fim,
        field_label="Data final",
        default=fim_padrao,
    )
    if fim_ref < inicio_ref:
        raise HTTPException(status_code=422, detail="Data final nao pode ser anterior a data inicial.")

    total_dias = (fim_ref - inicio_ref).days + 1
    max_dias = _obter_max_window_assistente_agenda()
    if total_dias > max_dias:
        raise HTTPException(
            status_code=422,
            detail=f"Janela maxima para assistente de agenda e de {max_dias} dias.",
        )

    return inicio_ref.isoformat(), fim_ref.isoformat(), total_dias


def _contar_agendamentos_clinica_30d(
    db: Session,
    *,
    clinica_id: int,
    data_ref_iso: str,
) -> int:
    try:
        data_ref = datetime.strptime(data_ref_iso, "%Y-%m-%d").date()
    except ValueError:
        data_ref = datetime.now(LOCAL_TZ).date()
    inicio = (data_ref - timedelta(days=30)).isoformat()
    fim = data_ref.isoformat()
    count = (
        db.query(Agendamento.id)
        .filter(Agendamento.clinica_id == clinica_id)
        .filter(Agendamento.status != "Cancelado")
        .filter(func.date(Agendamento.inicio) >= inicio)
        .filter(func.date(Agendamento.inicio) <= fim)
        .count()
    )
    return int(count or 0)


def _existe_ancora_proxima_no_dia(
    db: Session,
    *,
    clinica_id: int,
    data_iso: str,
    limite_minutos: int,
    perfil_deslocamento: str,
    agendamento_id_excluir: Optional[int] = None,
) -> bool:
    if limite_minutos <= 0:
        return False
    janela_inicio, janela_fim, _motivo = _obter_janela_funcionamento_data(db, data_iso)
    if janela_inicio is None or janela_fim is None:
        return False

    agendamentos_dia = _listar_agendamentos_ativos_do_dia(
        db,
        data_iso,
        agendamento_id_excluir=agendamento_id_excluir,
    )
    agendamentos_dia = _filtrar_agendamentos_por_janela_funcionamento(
        db,
        agendamentos_dia,
        cache_janelas={data_iso: (janela_inicio, janela_fim, None)},
    )
    clinica_ref = db.query(Clinica).filter(Clinica.id == clinica_id).first()
    clinicas_cache: dict[int, Optional[Clinica]] = {}
    ancoras_mesma_cidade = 0

    def _get_clinica_cached(cid: int) -> Optional[Clinica]:
        if cid not in clinicas_cache:
            clinicas_cache[cid] = db.query(Clinica).filter(Clinica.id == cid).first()
        return clinicas_cache[cid]

    cache_duracoes: dict[tuple[int, int, str, bool], tuple[int, str]] = {}
    perfil_norm = normalizar_perfil(perfil_deslocamento)
    for item in agendamentos_dia:
        status_item = (str(item.get("status") or "").strip() or "Agendado")
        if not _status_conta_como_ancora(status_item):
            continue
        clinica_item_id = int(item.get("clinica_id") or 0)
        if clinica_item_id <= 0:
            continue
        if clinica_item_id == clinica_id:
            return True
        duracao_min, _fonte = _obter_duracao_deslocamento_cacheado(
            db,
            origem_clinica_id=clinica_id,
            destino_clinica_id=clinica_item_id,
                perfil=perfil_norm,
                permitir_estimativa_fallback=True,
                cache=cache_duracoes,
            )
        if duracao_min > 0 and duracao_min <= limite_minutos:
            return True
        if duracao_min <= 0:
            clinica_item = _get_clinica_cached(clinica_item_id)
            if not _clinicas_mesma_regiao_operacional(clinica_ref, clinica_item):
                continue
            ancoras_mesma_cidade += 1
            if ancoras_mesma_cidade >= 1:
                # Fallback operacional: se a matriz ainda nao tem duracoes, mas existe
                # ancora valida na mesma cidade/UF para D+2, libera a ancoragem.
                return True
    return False


def _clinicas_mesma_cidade_uf(
    db: Session,
    *,
    clinica_a_id: int,
    clinica_b_id: int,
    cache: Optional[dict[int, Optional[Clinica]]] = None,
) -> bool:
    clinicas_cache = cache if isinstance(cache, dict) else {}

    def _get_clinica(cid: int) -> Optional[Clinica]:
        if cid not in clinicas_cache:
            clinicas_cache[cid] = db.query(Clinica).filter(Clinica.id == cid).first()
        return clinicas_cache[cid]

    clinica_a = _get_clinica(int(clinica_a_id or 0))
    clinica_b = _get_clinica(int(clinica_b_id or 0))
    return _clinicas_mesma_regiao_operacional(clinica_a, clinica_b)


def _classificar_politica_oferta(
    db: Session,
    *,
    clinica_id: int,
    data_contato_iso: str,
    perfil_deslocamento: str,
    regras_rota: dict,
    agendamento_id_excluir: Optional[int] = None,
    preferencia: Optional[AgendaPreferencia] = None,
) -> dict[str, Any]:
    thresholds = regras_rota.get("thresholds") if isinstance(regras_rota.get("thresholds"), dict) else {}
    offer_policy = regras_rota.get("offer_policy") if isinstance(regras_rota.get("offer_policy"), dict) else {}
    base_cfg = regras_rota.get("base") if isinstance(regras_rota.get("base"), dict) else {}

    limite_ancora = int(thresholds.get("nearby_anchor_max_travel_min") or 20)
    limite_distante = int(thresholds.get("distant_clinic_min_travel_from_base_min") or 35)
    limite_baixa_frequencia = int(thresholds.get("low_frequency_max_bookings_30d") or 3)
    try:
        data_contato_ref = datetime.strptime(data_contato_iso, "%Y-%m-%d").date()
    except ValueError:
        data_contato_ref = datetime.now(LOCAL_TZ).date()
    data_d0 = data_contato_ref.isoformat()
    data_d2 = (data_contato_ref + timedelta(days=2)).isoformat()
    data_d3 = (data_contato_ref + timedelta(days=3)).isoformat()

    dias_padrao = [int(item) for item in list(offer_policy.get("default_first_offer_days_ahead") or [2])]
    dias_distantes = [
        int(item) for item in list(offer_policy.get("distant_low_frequency_first_offer_days_ahead") or [3, 4])
    ]
    permitir_d2_ancora = bool(offer_policy.get("allow_d2_if_anchor_exists", True))

    clinica = db.query(Clinica).filter(Clinica.id == clinica_id).first()
    clinic_name = str(getattr(clinica, "nome", "") or "").strip()
    clinic_name_norm = clinic_name.casefold()
    tempo_base_min = _tempo_estimado_clinica_ate_base_min(
        clinica,
        base_lat=base_cfg.get("lat"),
        base_lng=base_cfg.get("lng"),
        perfil_deslocamento=perfil_deslocamento,
    )
    distante_base = tempo_base_min is not None and tempo_base_min >= limite_distante
    qtd_30d = _contar_agendamentos_clinica_30d(
        db,
        clinica_id=clinica_id,
        data_ref_iso=data_contato_iso,
    )
    baixa_frequencia = qtd_30d <= limite_baixa_frequencia
    if tempo_base_min is None and baixa_frequencia and permitir_d2_ancora:
        # Sem base geocodificada, adota regra conservadora para clinicas de baixa frequencia:
        # D+2 so e priorizado quando houver ancora realmente proxima.
        distante_base = True
    base_proxima = tempo_base_min is not None and tempo_base_min < limite_distante

    dias_preferenciais = dias_padrao or [2]
    ancora_d0 = False
    ancora_d2 = False
    ancora_d3 = False
    sem_agendamentos_d0 = False
    prioridade_d0_aplicada = False
    override_aplicado = None
    override_ancora_obrigatoria = False

    def _ancora_no_periodo(data_iso: str) -> bool:
        # Only evaluate anchors that can participate in this requested period.
        # Otherwise a missing D+2/D+3 route could consume a confirmation whose
        # envelope correctly covers only today's offers.
        if preferencia and not preferencia.permite_data(data_iso):
            return False
        return _existe_ancora_proxima_no_dia(
            db, clinica_id=clinica_id, data_iso=data_iso,
            limite_minutos=limite_ancora, perfil_deslocamento=perfil_deslocamento,
            agendamento_id_excluir=agendamento_id_excluir,
        )

    if distante_base and baixa_frequencia:
        dias_preferenciais = dias_distantes or dias_preferenciais
        if permitir_d2_ancora:
            ancora_d2 = _ancora_no_periodo(data_d2)
            if ancora_d2:
                dias_preferenciais = [2]

    if base_proxima:
        agendamentos_d0 = _listar_agendamentos_ativos_do_dia(
            db,
            data_d0,
            agendamento_id_excluir=agendamento_id_excluir,
        )
        agendamentos_d0 = _filtrar_agendamentos_por_janela_funcionamento(db, agendamentos_d0)
        sem_agendamentos_d0 = len(agendamentos_d0) == 0
        if not sem_agendamentos_d0:
            ancora_d0 = _ancora_no_periodo(data_d0)
        if not ancora_d2:
            ancora_d2 = _ancora_no_periodo(data_d2)
        ancora_d3 = _ancora_no_periodo(data_d3)
        if (ancora_d0 or sem_agendamentos_d0) and (not ancora_d2 and not ancora_d3):
            dias_preferenciais = [0]
            prioridade_d0_aplicada = True

    overrides_cfg = regras_rota.get("clinic_overrides") if isinstance(regras_rota.get("clinic_overrides"), list) else []
    for override in overrides_cfg:
        if not isinstance(override, dict):
            continue
        override_name = str(override.get("clinic_name") or "").strip().casefold()
        if not override_name:
            continue
        if override_name != clinic_name_norm:
            continue
        override_dias = [
            int(item)
            for item in list(override.get("force_days_ahead") or [])
            if str(item).strip().isdigit()
        ]
        override_dias = [dia for dia in override_dias if 0 <= dia <= 30]
        if override_dias:
            dias_preferenciais = sorted(set(override_dias))
        override_ancora_obrigatoria = bool(override.get("prefer_only_when_anchor_exists", False))
        override_aplicado = {
            "clinic_name": clinic_name,
            "force_days_ahead": dias_preferenciais,
            "prefer_only_when_anchor_exists": override_ancora_obrigatoria,
            "notes": str(override.get("notes") or "").strip(),
        }
        break

    if override_ancora_obrigatoria and 2 in dias_preferenciais:
        data_d2 = (datetime.strptime(data_contato_iso, "%Y-%m-%d").date() + timedelta(days=2)).isoformat()
        if not ancora_d2:
            ancora_d2 = _ancora_no_periodo(data_d2)
        if not ancora_d2:
            dias_preferenciais = [dia for dia in dias_preferenciais if dia != 2]
            if not dias_preferenciais:
                dias_preferenciais = dias_distantes or dias_padrao or [2]

    dias_preferenciais = sorted(set(int(dia) for dia in dias_preferenciais if 0 <= int(dia) <= 30))

    return {
        "dias_preferenciais": dias_preferenciais,
        "distante_base": bool(distante_base),
        "base_proxima": bool(base_proxima),
        "baixa_frequencia": bool(baixa_frequencia),
        "agendamentos_30d": int(qtd_30d),
        "tempo_base_estimado_min": tempo_base_min,
        "ancora_d0": bool(ancora_d0),
        "ancora_d2": bool(ancora_d2),
        "ancora_d3": bool(ancora_d3),
        "sem_agendamentos_d0": bool(sem_agendamentos_d0),
        "prioridade_d0_aplicada": bool(prioridade_d0_aplicada),
        "override_aplicado": override_aplicado,
    }


def _obter_janela_funcionamento_data(
    db: Session,
    data_iso: str,
) -> tuple[Optional[datetime], Optional[datetime], Optional[str]]:
    try:
        data_ref = datetime.strptime(data_iso, "%Y-%m-%d").date()
    except ValueError:
        return None, None, "Data invalida. Use o formato YYYY-MM-DD."

    agenda_semanal, agenda_feriados, agenda_excecoes = _obter_regras_agenda(db)

    excecao = obter_excecao_data(data_ref, agenda_excecoes)
    if excecao is not None:
        if not bool(excecao.get("ativo", False)):
            motivo = str(excecao.get("motivo") or "").strip()
            detalhe = f" ({motivo})" if motivo else ""
            return None, None, f"Agenda fechada por excecao de data{detalhe}."
        hora_inicio = _parse_hora_hhmm(str(excecao.get("inicio") or ""), "08:00")
        hora_fim = _parse_hora_hhmm(str(excecao.get("fim") or ""), "18:00")
    else:
        feriado = obter_feriado(data_ref, agenda_feriados)
        if feriado:
            descricao = str(feriado.get("descricao") or "").strip()
            detalhe = f" ({descricao})" if descricao else ""
            return None, None, f"Agenda fechada em feriado{detalhe}."

        dia_key = str(data_ref.isoweekday())
        dia_cfg = agenda_semanal.get(dia_key) or DEFAULT_AGENDA_SEMANAL[dia_key]
        if not bool(dia_cfg.get("ativo", False)):
            return None, None, "Agenda fechada para este dia."
        fallback_dia = DEFAULT_AGENDA_SEMANAL.get(dia_key, {"inicio": "08:00", "fim": "14:00"})
        hora_inicio = _parse_hora_hhmm(str(dia_cfg.get("inicio") or ""), str(fallback_dia["inicio"]))
        hora_fim = _parse_hora_hhmm(str(dia_cfg.get("fim") or ""), str(fallback_dia["fim"]))

    if _hora_para_minutos(hora_inicio) >= _hora_para_minutos(hora_fim):
        return None, None, "Configuracao de agenda invalida para esta data."

    inicio = _combine_date_hhmm(data_ref, hora_inicio)
    fim = _combine_date_hhmm(data_ref, hora_fim)
    return inicio, fim, None


def _listar_agendamentos_ativos_periodo(
    db: Session,
    data_inicio_iso: str,
    data_fim_iso: str,
    *,
    agendamento_id_excluir: Optional[int] = None,
) -> list[dict]:
    data_sem_vazio = func.nullif(func.trim(Agendamento.data), "")
    query = (
        db.query(Agendamento)
        .filter(Agendamento.status.notin_(["Cancelado", "Expirado"]))
        .filter(
            or_(
                and_(
                    data_sem_vazio.isnot(None),
                    data_sem_vazio >= data_inicio_iso,
                    data_sem_vazio <= data_fim_iso,
                ),
                and_(
                    func.date(Agendamento.inicio) >= data_inicio_iso,
                    func.date(Agendamento.inicio) <= data_fim_iso,
                ),
            )
        )
    )
    if agendamento_id_excluir is not None:
        query = query.filter(Agendamento.id != agendamento_id_excluir)

    cache_clinicas: dict[int, Optional[Clinica]] = {}
    cache_tutores: dict[int, Optional[Tutor]] = {}
    cache_pacientes: dict[int, Optional[Paciente]] = {}
    registros: list[dict] = []
    for item in query.order_by(Agendamento.inicio.asc(), Agendamento.id.asc()).all():
        if _status_efetivo_agendamento(item) == "Expirado":
            continue
        inicio_dt, fim_dt = _intervalo_local_agendamento(item)
        if inicio_dt is None:
            continue

        if fim_dt is None or fim_dt <= inicio_dt:
            fim_dt = inicio_dt + timedelta(minutes=30)

        destino_operacional = _resolver_destino_operacional_agendamento(
            db,
            item,
            cache_clinicas=cache_clinicas,
            cache_tutores=cache_tutores,
            cache_pacientes=cache_pacientes,
        )

        registros.append(
            {
                "id": item.id,
                "inicio": inicio_dt,
                "fim": fim_dt,
                "origem_atendimento": _normalizar_origem_atendimento(getattr(item, "origem_atendimento", None)),
                "clinica_id": item.clinica_id,
                "clinica_nome": (str(item.clinica or "").strip() or None),
                "tutor_id": getattr(item, "tutor_id", None),
                "servico_id": item.servico_id,
                "status": item.status,
                "destino_operacional": destino_operacional,
                "destino_operacional_label": _rotulo_destino_operacional(destino_operacional),
            }
        )

    return registros


def _listar_agendamentos_ativos_do_dia(
    db: Session,
    data_iso: str,
    *,
    agendamento_id_excluir: Optional[int] = None,
) -> list[dict]:
    return _listar_agendamentos_ativos_periodo(
        db,
        data_iso,
        data_iso,
        agendamento_id_excluir=agendamento_id_excluir,
    )


def _obter_janela_funcionamento_cacheada(
    db: Session,
    data_iso: str,
    *,
    cache_janelas: Optional[dict[str, tuple[Optional[datetime], Optional[datetime], Optional[str]]]] = None,
) -> tuple[Optional[datetime], Optional[datetime], Optional[str]]:
    if cache_janelas is not None and data_iso in cache_janelas:
        return cache_janelas[data_iso]
    janela = _obter_janela_funcionamento_data(db, data_iso)
    if cache_janelas is not None:
        cache_janelas[data_iso] = janela
    return janela


def _filtrar_agendamentos_por_janela_funcionamento(
    db: Session,
    agendamentos: list[dict],
    *,
    cache_janelas: Optional[dict[str, tuple[Optional[datetime], Optional[datetime], Optional[str]]]] = None,
) -> list[dict]:
    filtrados: list[dict] = []
    for item in agendamentos:
        inicio_item = item.get("inicio")
        fim_item = item.get("fim")
        if not isinstance(inicio_item, datetime):
            continue
        if not isinstance(fim_item, datetime) or fim_item <= inicio_item:
            fim_item = inicio_item + timedelta(minutes=30)
        data_item_iso = inicio_item.date().isoformat()
        janela_inicio, janela_fim, _motivo = _obter_janela_funcionamento_cacheada(
            db,
            data_item_iso,
            cache_janelas=cache_janelas,
        )
        if janela_inicio is None or janela_fim is None:
            continue
        # Ignora legados fora da janela operacional ativa para evitar ancoras invalidas.
        if inicio_item < janela_inicio or fim_item > janela_fim:
            continue
        filtrados.append(item)
    return filtrados


def _obter_vizinhos_horario(
    agendamentos_dia: list[dict],
    inicio: datetime,
    fim: datetime,
) -> tuple[Optional[dict], Optional[dict]]:
    anterior = None
    proximo = None

    for item in agendamentos_dia:
        if item["fim"] <= inicio:
            anterior = item
            continue
        if item["inicio"] >= fim:
            proximo = item
            break
    return anterior, proximo


def _folga_cobre_deslocamento(
    folga_min: Optional[int],
    duracao_min: int,
    *,
    margem_min: int = 0,
) -> bool:
    if folga_min is None:
        return False
    return int(folga_min) >= int(duracao_min) + max(0, int(margem_min))


def _folga_necessaria_entre_destinos(
    origem: Optional[dict[str, Any]],
    destino: Optional[dict[str, Any]],
    *,
    deslocamento_min: int,
    margem_segura_min: int,
    transicao_mesmo_local_min: int,
    ancora_adjacente: bool,
) -> int:
    if _destinos_operacionais_mesma_referencia(origem, destino):
        return max(0, transicao_mesmo_local_min)
    return max(0, deslocamento_min) + (0 if ancora_adjacente else max(0, margem_segura_min))


def _janela_preferencia(
    preferencia: Optional[AgendaPreferencia],
    inicio: datetime,
    fim: datetime,
) -> tuple[Optional[datetime], Optional[datetime]]:
    if preferencia is None:
        return inicio, fim
    if not preferencia.permite_data(inicio.date()):
        return None, None
    minuto_inicio, minuto_fim = preferencia.limites_horarios()
    meia_noite = inicio.replace(hour=0, minute=0, second=0, microsecond=0)
    inicio_restrito = max(inicio, meia_noite + timedelta(minutes=minuto_inicio))
    fim_restrito = min(fim, meia_noite + timedelta(minutes=minuto_fim))
    if inicio_restrito >= fim_restrito:
        return None, None
    return inicio_restrito, fim_restrito


def _vizinho_e_ancora_adjacente(
    vizinho: Optional[dict],
    destino_vizinho: Optional[dict[str, Any]],
    *,
    duracao_deslocamento_min: int,
    folga_min: Optional[int],
    limite_ancora_min: int,
    margem_segura_min: int,
) -> bool:
    if not isinstance(vizinho, dict) or not isinstance(destino_vizinho, dict):
        return False
    if not _status_conta_como_ancora(vizinho.get("status")):
        return False
    if not bool(destino_vizinho.get("localizacao_confiavel")):
        return False

    duracao = max(0, int(duracao_deslocamento_min or 0))
    if limite_ancora_min > 0 and duracao > int(limite_ancora_min):
        return False
    if not _folga_cobre_deslocamento(folga_min, duracao):
        return False

    # A mesma janela estreita vale na oferta e na escrita. Mudar a grade de
    # exibicao/busca nunca amplia uma excecao de rota.
    janela_adjacencia = JANELA_OPERACIONAL_ADJACENCIA_ANCORA_MIN + max(0, int(margem_segura_min))
    if janela_adjacencia > 0 and int(folga_min or 0) > janela_adjacencia:
        return False
    return True


def _marcar_slots_adjacentes_ancora(
    sugestoes: list[dict[str, Any]],
    ancoras_mesma_clinica: list[dict[str, Any]],
    *,
    margem_segura_min: int,
) -> None:
    # Here the margin is the configured transition at the same location.
    for sugestao in sugestoes:
        if isinstance(sugestao, dict):
            sugestao["adjacente_ancora"] = False
            sugestao["adjacencia_tipo"] = None

    if not sugestoes or not ancoras_mesma_clinica:
        return

    sugestoes_ordenadas: list[tuple[int, datetime, datetime]] = []
    for idx, sugestao in enumerate(sugestoes):
        if not isinstance(sugestao, dict):
            continue
        inicio_sugestao = _to_local_naive(_coerce_datetime(sugestao.get("inicio")))
        fim_sugestao = _to_local_naive(_coerce_datetime(sugestao.get("fim")))
        if inicio_sugestao is None or fim_sugestao is None:
            continue
        sugestoes_ordenadas.append((idx, inicio_sugestao, fim_sugestao))

    if not sugestoes_ordenadas:
        return

    sugestoes_ordenadas.sort(key=lambda item: item[1])
    marcacoes: dict[int, str] = {}

    for ancora in sorted(
        ancoras_mesma_clinica,
        key=lambda item: _to_local_naive(_coerce_datetime(item.get("inicio"))) or datetime.min,
    ):
        inicio_ancora = _to_local_naive(_coerce_datetime(ancora.get("inicio")))
        fim_ancora = _to_local_naive(_coerce_datetime(ancora.get("fim")))
        if inicio_ancora is None or fim_ancora is None:
            continue

        liberacao_ancora = fim_ancora + timedelta(minutes=max(0, int(margem_segura_min)))

        candidato_apos = next(
            (idx for idx, inicio_sugestao, _fim_sugestao in sugestoes_ordenadas if inicio_sugestao >= liberacao_ancora),
            None,
        )
        if candidato_apos is not None:
            marcacoes[candidato_apos] = "apos_ancora"

        for idx, _inicio_sugestao, fim_sugestao in reversed(sugestoes_ordenadas):
            if fim_sugestao <= inicio_ancora - timedelta(minutes=max(0, int(margem_segura_min))):
                marcacoes.setdefault(idx, "antes_ancora")
                break

    for idx, tipo in marcacoes.items():
        if idx < 0 or idx >= len(sugestoes):
            continue
        sugestao = sugestoes[idx]
        if not isinstance(sugestao, dict):
            continue
        sugestao["adjacente_ancora"] = True
        sugestao["adjacencia_tipo"] = tipo


def _classificar_panorama_data_assistente(resposta_panorama: Optional[dict[str, Any]]) -> str:
    if not isinstance(resposta_panorama, dict):
        return "sem_oferta"

    items = resposta_panorama.get("items")
    items_lista = items if isinstance(items, list) else []
    if not items_lista:
        return "sem_oferta"

    tem_ancora_mesma_clinica = bool(resposta_panorama.get("tem_ancora_mesma_clinica_no_dia"))
    if tem_ancora_mesma_clinica and any(
        bool(item.get("adjacente_ancora")) for item in items_lista if isinstance(item, dict)
    ):
        return "ancora"

    if not bool(resposta_panorama.get("tem_agendamentos_no_dia")):
        return "data_vazia"

    return "operacional"


def _selecionar_items_hierarquia_data_assistente(
    resposta_panorama: Optional[dict[str, Any]],
    *,
    categoria: str,
) -> list[dict[str, Any]]:
    if not isinstance(resposta_panorama, dict):
        return []

    items = resposta_panorama.get("items")
    items_lista = [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []
    if categoria == "ancora":
        adjacentes = [item for item in items_lista if bool(item.get("adjacente_ancora"))]
        if adjacentes:
            return adjacentes
    return items_lista


EXCECAO_DESLOCAMENTO_MOTIVO_PADRAO = "Excecao de conflito de rota confirmada por admin."

EXCECAO_DESLOCAMENTO_CAMPOS = (
    "excecao_deslocamento_concedida_em",
    "excecao_deslocamento_concedida_por_id",
    "excecao_deslocamento_concedida_por_nome",
    "excecao_deslocamento_motivo",
    "excecao_deslocamento_escopo",
)


def _fingerprint_escopo_deslocamento(agendamento: Agendamento) -> str:
    """Assinatura da rota aprovada quando o admin concedeu a excecao.

    A excecao vale para aquele trecho de rota especifico, nao para o
    agendamento em geral: se horario, destino (clinica ou endereco do
    domiciliar) ou servico mudarem, a assinatura muda e a excecao persistida
    para de ser aplicada, para nao mascarar um conflito de rota novo.

    Paciente e tutor entram na assinatura apenas no domiciliar, onde definem o
    endereco de destino. Em clinica parceira eles nao afetam a rota - e uma
    reserva costuma receber esses dados depois da concessao, no fluxo normal de
    confirmacao tardia, que nao deve invalidar a excecao.
    """
    inicio = _to_local_naive(_coerce_datetime(getattr(agendamento, "inicio", None)))
    fim = _to_local_naive(_coerce_datetime(getattr(agendamento, "fim", None)))
    origem = str(getattr(agendamento, "origem_atendimento", "") or "").strip().lower()
    origem = origem or ORIGEM_ATENDIMENTO_PADRAO
    partes = [
        inicio.isoformat(timespec="minutes") if inicio else "-",
        fim.isoformat(timespec="minutes") if fim else "-",
        str(int(getattr(agendamento, "clinica_id", 0) or 0)),
        str(int(getattr(agendamento, "servico_id", 0) or 0)),
        origem,
    ]
    if origem == ORIGEM_ATENDIMENTO_DOMICILIAR:
        partes.extend(
            [
                str(int(getattr(agendamento, "paciente_id", 0) or 0)),
                str(int(getattr(agendamento, "tutor_id", 0) or 0)),
            ]
        )
    return hashlib.sha256("|".join(partes).encode("utf-8")).hexdigest()


def _excecao_deslocamento_ativa(agendamento: Agendamento) -> bool:
    """True quando existe excecao concedida e ainda valida para a rota atual."""
    concedida_em = _coerce_datetime(getattr(agendamento, "excecao_deslocamento_concedida_em", None))
    escopo = str(getattr(agendamento, "excecao_deslocamento_escopo", "") or "").strip()
    if concedida_em is None or not escopo:
        return False
    return escopo == _fingerprint_escopo_deslocamento(agendamento)


def _conceder_excecao_deslocamento(
    agendamento: Agendamento,
    *,
    current_user: User,
    motivo: str = "",
) -> None:
    agendamento.excecao_deslocamento_concedida_em = datetime.now()
    agendamento.excecao_deslocamento_concedida_por_id = getattr(current_user, "id", None)
    agendamento.excecao_deslocamento_concedida_por_nome = getattr(current_user, "nome", None)
    agendamento.excecao_deslocamento_motivo = (
        str(motivo or "").strip() or EXCECAO_DESLOCAMENTO_MOTIVO_PADRAO
    )
    agendamento.excecao_deslocamento_escopo = _fingerprint_escopo_deslocamento(agendamento)


def _limpar_excecao_deslocamento(agendamento: Agendamento) -> bool:
    if not any(getattr(agendamento, campo, None) for campo in EXCECAO_DESLOCAMENTO_CAMPOS):
        return False
    for campo in EXCECAO_DESLOCAMENTO_CAMPOS:
        setattr(agendamento, campo, None)
    return True


def _descartar_excecao_deslocamento_obsoleta(agendamento: Agendamento) -> bool:
    """Zera a concessao quando a rota aprovada nao existe mais."""
    escopo = str(getattr(agendamento, "excecao_deslocamento_escopo", "") or "").strip()
    if not escopo or escopo == _fingerprint_escopo_deslocamento(agendamento):
        return False
    return _limpar_excecao_deslocamento(agendamento)


def _registrar_auditoria_excecao_deslocamento(
    *,
    db: Session,
    current_user: User,
    request: Optional[Request],
    agendamento: Agendamento,
    bypass: dict,
    acao_operacional: str,
) -> None:
    """Registra concessao/reuso da excecao de rota na trilha de auditoria."""
    origem = str(bypass.get("origem") or "")
    if origem not in {"confirmacao_admin", "excecao_persistida"}:
        return
    related = _fetch_related_names(db, agendamento)
    contexto = _contexto_agendamento_auditoria(agendamento, related)
    concedida_em = _coerce_datetime(getattr(agendamento, "excecao_deslocamento_concedida_em", None))
    if origem == "confirmacao_admin":
        acao = "AGENDA_EXCECAO_DESLOCAMENTO_CONCEDIDA"
        descricao = (
            f"Excecao de conflito de rota concedida por admin em '{acao_operacional}' - "
            f"{_descricao_contexto_agendamento(contexto)}"
        )
    else:
        acao = "AGENDA_EXCECAO_DESLOCAMENTO_APLICADA"
        descricao = (
            f"Excecao de conflito de rota previamente concedida aplicada em '{acao_operacional}' - "
            f"{_descricao_contexto_agendamento(contexto)}"
        )
    registrar_auditoria(
        current_user=current_user,
        modulo="agenda",
        entidade="agendamento",
        entidade_id=agendamento.id,
        acao=acao,
        descricao=descricao,
        detalhes={
            "agendamento_id": agendamento.id,
            "acao_operacional": acao_operacional,
            "bloqueio_ignorado": bypass.get("bloqueio"),
            "origem_excecao": origem,
            "motivo": getattr(agendamento, "excecao_deslocamento_motivo", None),
            "concedida_em": concedida_em.isoformat() if concedida_em else None,
            "concedida_por_nome": getattr(agendamento, "excecao_deslocamento_concedida_por_nome", None),
            "clinica_id": agendamento.clinica_id,
            "servico_id": agendamento.servico_id,
            "contexto_agendamento": contexto,
        },
        request=request,
    )


def _capturar_baseline_regional_agendamento(
    db: Session,
    inicio: Any,
) -> Optional[list[dict]]:
    """Snapshot the target day before a writer mutates its ORM appointment.

    A later SELECT can return the already changed identity-map object, even
    without autoflush. The route dictionaries must therefore be captured first.
    Disabled policy never queries the day's appointments for this snapshot.
    """
    regras = _obter_regras_rota_agenda(db)
    if not (regras.get("route_policy") or {}).get("regional_transition_enabled"):
        return None
    inicio_local = _to_local_naive(_coerce_datetime(inicio))
    if inicio_local is None:
        return None
    return _listar_agendamentos_ativos_do_dia(db, inicio_local.date().isoformat())


def _validar_deslocamento_agendamento(
    db: Session,
    agendamento: Agendamento,
    *,
    agendamento_id_excluir: Optional[int] = None,
    perfil_deslocamento: str = "comercial",
    confirmar_conflito_deslocamento: bool = False,
    validar_primeira_saida: bool = True,
    commit_cache: bool = False,
    baseline_regional: Optional[list[dict]] = None,
) -> Optional[dict[str, str]]:
    """Bloqueia conflitos de rota, salvo excecao confirmada agora ou persistida.

    Retorna `None` quando nao havia conflito a ignorar. Quando um bloqueio foi
    ignorado, devolve `{"origem": ..., "bloqueio": ...}` para o chamador
    persistir a concessao (`confirmacao_admin`) ou registrar o reuso de uma
    excecao ja concedida (`excecao_persistida`).
    """
    status_atual = (str(agendamento.status or "").strip() or "Agendado")
    if status_atual == "Cancelado":
        return None

    excecao_persistida = _excecao_deslocamento_ativa(agendamento)
    if confirmar_conflito_deslocamento:
        origem_excecao = "confirmacao_admin"
    elif excecao_persistida:
        origem_excecao = "excecao_persistida"
    else:
        origem_excecao = ""
    ignorar_conflito = bool(origem_excecao)

    inicio_dt = _to_local_naive(_coerce_datetime(agendamento.inicio))
    if inicio_dt is None:
        raise HTTPException(status_code=422, detail="Horario de inicio invalido para validar deslocamento.")

    fim_dt = _to_local_naive(_coerce_datetime(agendamento.fim))
    if fim_dt is None or fim_dt <= inicio_dt:
        fim_dt = inicio_dt + timedelta(minutes=30)

    data_iso = inicio_dt.date().isoformat()
    agendamentos_dia = _listar_agendamentos_ativos_do_dia(
        db,
        data_iso,
        agendamento_id_excluir=agendamento_id_excluir,
    )
    anterior, proximo = _obter_vizinhos_horario(agendamentos_dia, inicio_dt, fim_dt)
    perfil_norm = normalizar_perfil(perfil_deslocamento)
    regras_rota = _obter_regras_rota_agenda(db)
    thresholds = regras_rota.get("thresholds") if isinstance(regras_rota.get("thresholds"), dict) else {}
    route_policy = regras_rota.get("route_policy") if isinstance(regras_rota.get("route_policy"), dict) else {}
    limite_desvio_insercao = int(thresholds.get("max_insertion_detour_min") or 25)
    margem_segura_min = int(thresholds.get("safe_margin_min", MIN_MARGEM_SEGURA_DESLOCAMENTO_MIN))
    transicao_mesmo_local_min = int(thresholds.get("same_location_transition_min", 5))
    limite_trecho_vizinho_min = int(
        thresholds.get("max_neighbor_travel_min", MAX_DESLOCAMENTO_TRECHO_VIZINHO_MIN)
    )
    bloquear_ineficiencia = bool(route_policy.get("reject_clear_inefficiency", True))
    cache_clinicas: dict[int, Optional[Clinica]] = {}
    cache_tutores: dict[int, Optional[Tutor]] = {}
    cache_pacientes: dict[int, Optional[Paciente]] = {}
    cache_duracoes_clinicas: dict[tuple[int, int, str, bool], tuple[int, str]] = {}
    cache_duracoes_operacionais: dict[tuple[str, int, str, int, str], tuple[int, str]] = {}
    cache_google: dict = {}
    duracao_prev = 0
    folga_prev = None
    fonte_prev = "indefinido"
    destino_anterior_nome = None
    duracao_next = 0
    folga_next = None
    fonte_next = "indefinido"
    destino_proximo_nome = None
    destino_anterior = None
    destino_proximo = None

    destino_atual = _resolver_destino_operacional_agendamento(
        db,
        agendamento,
        cache_clinicas=cache_clinicas,
        cache_tutores=cache_tutores,
        cache_pacientes=cache_pacientes,
    )
    destino_atual_nome = _rotulo_destino_operacional(destino_atual)
    destino_atual_confiavel = bool(destino_atual.get("localizacao_confiavel"))

    primeira_saida_ignorada = False
    if validar_primeira_saida and status_atual not in AGENDA_STATUS_NAO_ANCORA:
        primeira_saida = _avaliar_primeira_saida(
            db,
            inicio=inicio_dt,
            destino=destino_atual,
            agendamentos_dia=agendamentos_dia,
            regras_rota=regras_rota,
            perfil=perfil_norm,
        )
        if primeira_saida is not None and not primeira_saida.get("viavel") and ignorar_conflito:
            primeira_saida_ignorada = True
        else:
            _exigir_primeira_saida_viavel(primeira_saida)

    if anterior:
        destino_anterior = anterior.get("destino_operacional") if isinstance(anterior, dict) else None
        if isinstance(destino_anterior, dict) and ((destino_atual_confiavel and bool(destino_anterior.get("localizacao_confiavel"))) or _destinos_operacionais_mesma_referencia(destino_anterior, destino_atual)):
            duracao_prev, fonte_prev = _obter_duracao_deslocamento_operacional(
                db,
                origem=destino_anterior,
                destino=destino_atual,
                perfil=perfil_norm,
                cache_clinicas=cache_duracoes_clinicas,
                cache_operacional=cache_duracoes_operacionais,
                cache_google=cache_google,
                commit_cache=commit_cache,
            )
            folga_prev = _minutos_entre(anterior["fim"], inicio_dt)
            destino_anterior_nome = _rotulo_destino_operacional(destino_anterior)

    if proximo:
        destino_proximo = proximo.get("destino_operacional") if isinstance(proximo, dict) else None
        if isinstance(destino_proximo, dict) and ((destino_atual_confiavel and bool(destino_proximo.get("localizacao_confiavel"))) or _destinos_operacionais_mesma_referencia(destino_atual, destino_proximo)):
            duracao_next, fonte_next = _obter_duracao_deslocamento_operacional(
                db,
                origem=destino_atual,
                destino=destino_proximo,
                perfil=perfil_norm,
                cache_clinicas=cache_duracoes_clinicas,
                cache_operacional=cache_duracoes_operacionais,
                cache_google=cache_google,
                commit_cache=commit_cache,
            )
            folga_next = _minutos_entre(fim_dt, proximo["inicio"])
            destino_proximo_nome = _rotulo_destino_operacional(destino_proximo)

    baseline_avaliacao = baseline_regional if baseline_regional is not None else agendamentos_dia
    if baseline_regional is None and route_policy.get("regional_transition_enabled") and agendamento_id_excluir:
        baseline_avaliacao = _listar_agendamentos_ativos_do_dia(db, data_iso)
    regional = avaliar_transicao_regional(
        baseline_avaliacao,
        {"id": agendamento_id_excluir, "inicio": inicio_dt, "fim": fim_dt,
         "status": status_atual, "destino_operacional": destino_atual},
        regras_rota=regras_rota,
        agendamento_id_excluir=agendamento_id_excluir,
        resolver_deslocamento=lambda origem, destino: _obter_duracao_deslocamento_operacional(
            db, origem=origem, destino=destino, perfil=perfil_norm,
            cache_clinicas=cache_duracoes_clinicas, cache_operacional=cache_duracoes_operacionais,
            cache_google=cache_google, commit_cache=commit_cache,
        ),
    )
    if regional is not None and not regional.permitida:
        if ignorar_conflito:
            return {"origem": origem_excecao, "bloqueio": regional.codigo}
        raise HTTPException(status_code=409, detail={
            "codigo": "CONFLITO_DESLOCAMENTO", "motivo_regional": regional.codigo,
            "mensagem": "A rota permite uma transicao de ate 50 minutos no dia, com pelo menos 15 minutos de margem. Revise a viagem, a folga e as demais transicoes.",
            "confirmavel": False, "transicao_regional": regional.as_dict(),
        })
    regional_prev = bool(regional and regional.trecho_anterior and regional.trecho_anterior.longo)
    regional_next = bool(regional and regional.trecho_proximo and regional.trecho_proximo.longo)

    ancora_anterior_adjacente = _vizinho_e_ancora_adjacente(
        anterior,
        destino_anterior,
        duracao_deslocamento_min=duracao_prev,
        folga_min=folga_prev,
        limite_ancora_min=int(thresholds.get("nearby_anchor_max_travel_min") or 20),
        margem_segura_min=margem_segura_min,
    )
    ancora_proxima_adjacente = _vizinho_e_ancora_adjacente(
        proximo,
        destino_proximo,
        duracao_deslocamento_min=duracao_next,
        folga_min=folga_next,
        limite_ancora_min=int(thresholds.get("nearby_anchor_max_travel_min") or 20),
        margem_segura_min=margem_segura_min,
    )
    relaxar_limite_prev_por_ancora = regional_prev or (
        regional is None
        and limite_trecho_vizinho_min > 0
        and duracao_prev > limite_trecho_vizinho_min
        and ancora_proxima_adjacente
        and _folga_cobre_deslocamento(folga_prev, duracao_prev, margem_min=margem_segura_min)
    )
    relaxar_limite_next_por_ancora = regional_next or (
        regional is None
        and limite_trecho_vizinho_min > 0
        and duracao_next > limite_trecho_vizinho_min
        and ancora_anterior_adjacente
        and _folga_cobre_deslocamento(folga_next, duracao_next, margem_min=margem_segura_min)
    )

    if limite_trecho_vizinho_min > 0 and duracao_prev > limite_trecho_vizinho_min and not relaxar_limite_prev_por_ancora:
        if ignorar_conflito:
            return {"origem": origem_excecao, "bloqueio": "limite_trecho_anterior"}
        raise HTTPException(
            status_code=409,
            detail={
                "codigo": "CONFLITO_DESLOCAMENTO",
                "mensagem": (
                    f"O tempo de deslocamento entre {destino_anterior_nome} e {destino_atual_nome} "
                    f"e de aproximadamente {duracao_prev} minutos e excede o limite operacional "
                    f"de {limite_trecho_vizinho_min} minutos para um trecho da rota. "
                    "Ajuste o horario ou revise o destino do atendimento."
                ),
                "origem_clinica": destino_anterior_nome,
                "destino_clinica": destino_atual_nome,
                "origem_operacional": destino_anterior_nome,
                "destino_operacional": destino_atual_nome,
                "duracao_min": int(duracao_prev),
                "limite_trecho_vizinho_min": int(limite_trecho_vizinho_min),
                "fonte": fonte_prev,
                "confirmavel": False,
            },
        )
    mesmo_local_prev = _destinos_operacionais_mesma_referencia(destino_anterior, destino_atual)
    folga_necessaria_prev = _folga_necessaria_entre_destinos(
        destino_anterior, destino_atual, deslocamento_min=duracao_prev,
        margem_segura_min=margem_segura_min, transicao_mesmo_local_min=transicao_mesmo_local_min,
        ancora_adjacente=ancora_anterior_adjacente,
    )
    if regional_prev:
        folga_necessaria_prev = duracao_prev + regional.margem_min
    if mesmo_local_prev and folga_prev < folga_necessaria_prev:
        if ignorar_conflito:
            return {"origem": origem_excecao, "bloqueio": "transicao_mesmo_local_prev"}
        raise HTTPException(status_code=409, detail={
            "codigo": "CONFLITO_DESLOCAMENTO",
            "mensagem": f"Reserve {transicao_mesmo_local_min} minutos de transicao entre atendimentos no mesmo local.",
            "duracao_min": 0, "folga_min": max(0, int(folga_prev)),
            "same_location_transition_min": transicao_mesmo_local_min,
            "folga_necessaria_min": folga_necessaria_prev, "confirmavel": False,
        })
    if duracao_prev > 0 and folga_prev < folga_necessaria_prev:
        if ignorar_conflito:
            return {"origem": origem_excecao, "bloqueio": "folga_anterior"}
        raise HTTPException(
            status_code=409,
            detail={
                "codigo": "CONFLITO_DESLOCAMENTO",
                "mensagem": (
                    f"O tempo de deslocamento entre {destino_anterior_nome} e {destino_atual_nome} "
                    f"e de aproximadamente {duracao_prev} minutos. "
                    f"Disponivel: {max(0, folga_prev)} minutos. "
                    f"Necessario com margem segura: {folga_necessaria_prev} minutos "
                    f"({duracao_prev} min de deslocamento + {0 if ancora_anterior_adjacente else margem_segura_min} min de margem). "
                    "Ajuste o horario ou revise o destino do atendimento."
                ),
                "origem_clinica": destino_anterior_nome,
                "destino_clinica": destino_atual_nome,
                "origem_operacional": destino_anterior_nome,
                "destino_operacional": destino_atual_nome,
                "duracao_min": int(duracao_prev),
                "folga_min": max(0, int(folga_prev)),
                "margem_segura_min": int(0 if ancora_anterior_adjacente else margem_segura_min),
                "folga_necessaria_min": int(folga_necessaria_prev),
                "fonte": fonte_prev,
                "confirmavel": False,
            },
        )

    if limite_trecho_vizinho_min > 0 and duracao_next > limite_trecho_vizinho_min and not relaxar_limite_next_por_ancora:
        if ignorar_conflito:
            return {"origem": origem_excecao, "bloqueio": "limite_trecho_proximo"}
        raise HTTPException(
            status_code=409,
            detail={
                "codigo": "CONFLITO_DESLOCAMENTO",
                "mensagem": (
                    f"O tempo de deslocamento entre {destino_atual_nome} e {destino_proximo_nome} "
                    f"e de aproximadamente {duracao_next} minutos e excede o limite operacional "
                    f"de {limite_trecho_vizinho_min} minutos para um trecho da rota. "
                    "Ajuste o horario ou revise o destino do atendimento."
                ),
                "origem_clinica": destino_atual_nome,
                "destino_clinica": destino_proximo_nome,
                "origem_operacional": destino_atual_nome,
                "destino_operacional": destino_proximo_nome,
                "duracao_min": int(duracao_next),
                "limite_trecho_vizinho_min": int(limite_trecho_vizinho_min),
                "fonte": fonte_next,
                "confirmavel": False,
            },
        )
    mesmo_local_next = _destinos_operacionais_mesma_referencia(destino_atual, destino_proximo)
    folga_necessaria_next = _folga_necessaria_entre_destinos(
        destino_atual, destino_proximo, deslocamento_min=duracao_next,
        margem_segura_min=margem_segura_min, transicao_mesmo_local_min=transicao_mesmo_local_min,
        ancora_adjacente=ancora_proxima_adjacente,
    )
    if regional_next:
        folga_necessaria_next = duracao_next + regional.margem_min
    if mesmo_local_next and folga_next < folga_necessaria_next:
        if ignorar_conflito:
            return {"origem": origem_excecao, "bloqueio": "transicao_mesmo_local_next"}
        raise HTTPException(status_code=409, detail={
            "codigo": "CONFLITO_DESLOCAMENTO",
            "mensagem": f"Reserve {transicao_mesmo_local_min} minutos de transicao entre atendimentos no mesmo local.",
            "duracao_min": 0, "folga_min": max(0, int(folga_next)),
            "same_location_transition_min": transicao_mesmo_local_min,
            "folga_necessaria_min": folga_necessaria_next, "confirmavel": False,
        })
    if duracao_next > 0 and folga_next < folga_necessaria_next:
        if ignorar_conflito:
            return {"origem": origem_excecao, "bloqueio": "folga_proximo"}
        raise HTTPException(
            status_code=409,
            detail={
                "codigo": "CONFLITO_DESLOCAMENTO",
                "mensagem": (
                    f"O tempo de deslocamento entre {destino_atual_nome} e {destino_proximo_nome} "
                    f"e de aproximadamente {duracao_next} minutos. "
                    f"Disponivel: {max(0, folga_next)} minutos. "
                    f"Necessario com margem segura: {folga_necessaria_next} minutos "
                    f"({duracao_next} min de deslocamento + {0 if ancora_proxima_adjacente else margem_segura_min} min de margem). "
                    "Ajuste o horario ou revise o destino do atendimento."
                ),
                "origem_clinica": destino_atual_nome,
                "destino_clinica": destino_proximo_nome,
                "origem_operacional": destino_atual_nome,
                "destino_operacional": destino_proximo_nome,
                "duracao_min": int(duracao_next),
                "folga_min": max(0, int(folga_next)),
                "margem_segura_min": int(0 if ancora_proxima_adjacente else margem_segura_min),
                "folga_necessaria_min": int(folga_necessaria_next),
                "fonte": fonte_next,
                "confirmavel": False,
            },
        )

    if (
        bloquear_ineficiencia
        and limite_desvio_insercao > 0
        and anterior
        and proximo
        and duracao_prev > 0
        and duracao_next > 0
        and (regional is not None or not (relaxar_limite_prev_por_ancora or relaxar_limite_next_por_ancora))
    ):
        destino_anterior = anterior.get("destino_operacional") if isinstance(anterior, dict) else None
        destino_proximo = proximo.get("destino_operacional") if isinstance(proximo, dict) else None
        duracao_direta, fonte_direta = _obter_duracao_deslocamento_operacional(
            db,
            origem=destino_anterior,
            destino=destino_proximo,
            perfil=perfil_norm,
            cache_clinicas=cache_duracoes_clinicas,
            cache_operacional=cache_duracoes_operacionais,
            cache_google=cache_google,
            commit_cache=commit_cache,
        )
        if duracao_direta > 0:
            duracao_via_novo = int(duracao_prev + duracao_next)
            desvio_insercao = max(0, int(duracao_via_novo - duracao_direta))
            if desvio_insercao > limite_desvio_insercao:
                if ignorar_conflito:
                    return {"origem": origem_excecao, "bloqueio": "desvio_insercao"}
                origem = destino_anterior_nome or _rotulo_destino_operacional(destino_anterior)
                destino = destino_proximo_nome or _rotulo_destino_operacional(destino_proximo)
                raise HTTPException(
                    status_code=409,
                    detail={
                        "codigo": "CONFLITO_DESLOCAMENTO",
                        "mensagem": (
                            f"A insercao de {destino_atual_nome} entre {origem} e {destino} "
                            f"gera desvio estimado de {desvio_insercao} minutos "
                            f"(limite: {limite_desvio_insercao} minutos). "
                            "Ajuste o horario ou revise o destino do atendimento."
                        ),
                        "origem_clinica": origem,
                        "destino_clinica": destino,
                        "origem_operacional": origem,
                        "destino_operacional": destino,
                        "clinica_inserida": destino_atual_nome,
                        "destino_inserido": destino_atual_nome,
                        "desvio_insercao_min": desvio_insercao,
                        "limite_desvio_min": limite_desvio_insercao,
                        "duracao_direta_min": int(duracao_direta),
                        "duracao_via_insercao_min": duracao_via_novo,
                        "fonte": fonte_direta,
                        "confirmavel": False,
                    },
                )

    if primeira_saida_ignorada:
        return {"origem": origem_excecao, "bloqueio": "PRIMEIRA_SAIDA_INVIAVEL"}


def _notificar_agenda_update(
    db: Session,
    action: str,
    agendamento_id: int,
    data: Optional[dict] = None,
    actor_user_id: Optional[int] = None,
) -> None:
    try:
        agenda_realtime_manager.publish(action=action, agendamento_id=agendamento_id, data=data)
    except Exception as exc:
        print(f"[agenda-realtime] Falha ao publicar evento: {exc}")

    try:
        send_agenda_push_notification(
            db,
            action=action,
            agendamento_id=agendamento_id,
            data=data,
            actor_user_id=actor_user_id,
        )
    except Exception as exc:
        print(f"[agenda-push] Falha ao enviar notificacao push: {exc}")


def _texto_realtime(value: Optional[object]) -> str:
    return str(value or "").strip()


def _montar_payload_realtime(
    *,
    agendamento: Optional[Agendamento] = None,
    related: Optional[dict] = None,
    usuario: Optional[User] = None,
    base: Optional[dict] = None,
) -> dict:
    payload = dict(base or {})

    if agendamento is not None:
        tutor_id_relacionado = _resolver_tutor_id_relacionado(
            agendamento,
            (related or {}).get("tutor_id_relacionado") if isinstance(related, dict) else None,
        )
        payload.setdefault("status", agendamento.status)
        payload.setdefault("data", agendamento.data)
        payload.setdefault("hora", agendamento.hora)
        payload.setdefault("paciente_id", agendamento.paciente_id)
        payload.setdefault("tutor_id", tutor_id_relacionado)
        payload.setdefault("clinica_id", agendamento.clinica_id)
        payload.setdefault("servico_id", agendamento.servico_id)
        payload.setdefault("origem_atendimento", _normalizar_origem_atendimento(getattr(agendamento, "origem_atendimento", None)))

    rel = related or {}
    paciente_nome = _texto_realtime(rel.get("paciente_nome")) or _texto_realtime(getattr(agendamento, "paciente", None))
    clinica_nome = _texto_realtime(rel.get("clinica_nome")) or _texto_realtime(getattr(agendamento, "clinica", None))
    servico_nome = _texto_realtime(rel.get("servico_nome")) or _texto_realtime(getattr(agendamento, "servico", None))

    if paciente_nome:
        payload["paciente_nome"] = paciente_nome
        payload.setdefault("paciente", paciente_nome)
    if clinica_nome:
        payload["clinica_nome"] = clinica_nome
        payload.setdefault("clinica", clinica_nome)
    if servico_nome:
        payload["servico_nome"] = servico_nome
        payload.setdefault("servico", servico_nome)

    if usuario is not None:
        nome_usuario = _texto_realtime(usuario.nome)
        if nome_usuario:
            payload["usuario_nome"] = nome_usuario
            payload.setdefault("usuario", nome_usuario)
        if getattr(usuario, "id", None) is not None:
            payload["usuario_id"] = usuario.id

    return payload


def _parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None

    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"

    # Compatibilidade com bancos legados que armazenam offset como +00/-03 (sem minutos).
    if len(raw) > 10:
        sufixo = raw[10:]
        if not re.search(r"[+-]\d{2}:\d{2}$", sufixo):
            match_hhmm = re.search(r"([+-]\d{2})(\d{2})$", sufixo)
            if match_hhmm:
                sufixo = sufixo[: match_hhmm.start()] + f"{match_hhmm.group(1)}:{match_hhmm.group(2)}"
            else:
                match_hh = re.search(r"([+-]\d{2})$", sufixo)
                if match_hh:
                    sufixo = sufixo[: match_hh.start()] + f"{match_hh.group(1)}:00"
            raw = raw[:10] + sufixo

    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _to_local_naive(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(LOCAL_TZ).replace(tzinfo=None)


def _to_local_aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        # Interpreta datetimes sem timezone como horario local de Brasilia.
        return value.replace(tzinfo=LOCAL_TZ)
    return value.astimezone(LOCAL_TZ)


def _extract_date_filter(value: Optional[str]) -> Optional[str]:
    if not value:
        return None

    parsed = _parse_iso_datetime(value)
    if parsed is not None:
        return parsed.date().isoformat()

    # Fallback para valores no formato YYYY-MM-DD...
    candidate = value.strip().split("T", 1)[0].split(" ", 1)[0]
    if len(candidate) == 10:
        return candidate
    return None


def _coerce_datetime(value) -> Optional[datetime]:
    if isinstance(value, datetime):
        return _to_local_aware(value)
    if isinstance(value, str):
        parsed = _parse_iso_datetime(value.replace(" ", "T", 1))
        return _to_local_aware(parsed)
    return None


def _coerce_hora_hhmm(value: Optional[str]) -> Optional[str]:
    raw = str(value or "").strip()
    if not raw:
        return None
    match = re.match(r"^(\d{2}):(\d{2})", raw)
    if not match:
        return None
    hh = int(match.group(1))
    mm = int(match.group(2))
    if hh < 0 or hh > 23 or mm < 0 or mm > 59:
        return None
    return f"{hh:02d}:{mm:02d}"


def _coerce_data_iso(value: Optional[str]) -> Optional[str]:
    raw = str(value or "").strip()
    if not raw:
        return None
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return None
    return raw


def _intervalo_local_agendamento(
    item: Agendamento,
    *,
    fallback_duracao_min: int = 30,
) -> tuple[Optional[datetime], Optional[datetime]]:
    inicio_ref = _to_local_naive(_coerce_datetime(item.inicio))
    fim_ref = _to_local_naive(_coerce_datetime(item.fim))

    duracao_min = max(1, int(fallback_duracao_min or 30))
    if inicio_ref is not None and fim_ref is not None and fim_ref > inicio_ref:
        duracao_min = max(1, int((fim_ref - inicio_ref).total_seconds() // 60))

    data_iso = _coerce_data_iso(getattr(item, "data", None))
    hora_hhmm = _coerce_hora_hhmm(getattr(item, "hora", None))
    if data_iso and hora_hhmm:
        try:
            inicio_normalizado = datetime.strptime(f"{data_iso} {hora_hhmm}", "%Y-%m-%d %H:%M")
            fim_normalizado = inicio_normalizado + timedelta(minutes=duracao_min)
            return inicio_normalizado, fim_normalizado
        except ValueError:
            pass

    if inicio_ref is None:
        return None, None
    if fim_ref is None or fim_ref <= inicio_ref:
        fim_ref = inicio_ref + timedelta(minutes=duracao_min)
    return inicio_ref, fim_ref


def _normalize_text_filter(value: Optional[str]) -> Optional[str]:
    raw = " ".join(str(value or "").split())
    return raw.strip() or None


def _build_contains_pattern(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )
    return f"%{escaped}%"


def _fill_data_hora_from_inicio(agendamento: Agendamento) -> None:
    inicio_dt = _coerce_datetime(agendamento.inicio)
    if inicio_dt is None:
        return
    agendamento.data = inicio_dt.strftime("%Y-%m-%d")
    agendamento.hora = inicio_dt.strftime("%H:%M")


def _apply_service_duration_if_needed(
    db: Session,
    agendamento: Agendamento,
    *,
    force_from_service: bool = False,
) -> None:
    inicio_dt = _coerce_datetime(agendamento.inicio)
    if inicio_dt is None:
        return

    fim_dt = _coerce_datetime(agendamento.fim)

    if agendamento.servico_id:
        servico = db.query(Servico).filter(Servico.id == agendamento.servico_id).first()
        if servico and servico.duracao_minutos and servico.duracao_minutos > 0:
            agendamento.fim = inicio_dt + timedelta(minutes=int(servico.duracao_minutos))
            return
        if force_from_service:
            agendamento.fim = inicio_dt + timedelta(minutes=30)
            return

    if fim_dt is not None and fim_dt > inicio_dt:
        return

    agendamento.fim = inicio_dt + timedelta(minutes=30)


def _resolver_duracao_servico(
    db: Session,
    *,
    servico_id: Optional[int],
    fallback_minutos: int = 30,
) -> int:
    fallback = max(5, int(fallback_minutos or 30))
    if not servico_id:
        return fallback

    servico = db.query(Servico).filter(Servico.id == servico_id).first()
    if not servico:
        raise HTTPException(status_code=404, detail="Servico nao encontrado.")

    duracao = int(servico.duracao_minutos or 0)
    if duracao <= 0:
        return fallback
    return max(5, duracao)


def _obter_regras_agenda(db: Session) -> tuple[dict, list, list]:
    # A Agenda não usa os binários de documentos contidos na mesma linha.
    # Projeção escalar também evita reutilizar uma entidade ORM desatualizada.
    config = db.query(
        Configuracao.agenda_semanal,
        Configuracao.agenda_feriados,
        Configuracao.agenda_excecoes,
    ).first()
    if not config:
        return carregar_agenda_semanal(None), carregar_agenda_feriados(None), carregar_agenda_excecoes(None)

    return (
        carregar_agenda_semanal(getattr(config, "agenda_semanal", None)),
        carregar_agenda_feriados(getattr(config, "agenda_feriados", None)),
        carregar_agenda_excecoes(getattr(config, "agenda_excecoes", None)),
    )


def _expirar_reservas_vencidas(db: Session) -> int:
    agora_local = datetime.now(LOCAL_TZ).replace(tzinfo=None)
    reservas = (
        db.query(Agendamento)
        .filter(Agendamento.status == "Reservado")
        .filter(Agendamento.reserva_expira_em.isnot(None))
        .all()
    )
    expiradas = 0
    for reserva in reservas:
        prazo_local = _to_local_naive(_coerce_datetime(reserva.reserva_expira_em))
        if prazo_local is None or prazo_local > agora_local:
            continue
        reserva.status = "Expirado"
        reserva.atualizado_em = datetime.now()
        reserva.updated_at = datetime.now()
        expiradas += 1
    if expiradas:
        db.flush()
    return expiradas


def _calcular_prazo_reabilitacao_reserva(
    agendamento: Agendamento,
    *,
    horas: Optional[float] = None,
    prazo_explicito: Optional[datetime] = None,
) -> tuple[datetime, bool]:
    """Resolve o novo prazo de confirmacao ao reabilitar uma reserva expirada.

    Devolve o prazo em horario local (naive, como o resto do modulo persiste) e
    se ele precisou ser encurtado para terminar antes do horario reservado.
    """
    agora_local = datetime.now(LOCAL_TZ).replace(tzinfo=None, second=0, microsecond=0)
    inicio_local = _to_local_naive(_coerce_datetime(agendamento.inicio))
    if inicio_local is None:
        raise HTTPException(
            status_code=422,
            detail="Horario de inicio invalido para reabilitar a reserva.",
        )

    limite_local = (
        inicio_local - timedelta(minutes=MARGEM_MINIMA_PRAZO_RESERVA_MIN)
    ).replace(second=0, microsecond=0)
    if limite_local <= agora_local:
        raise HTTPException(
            status_code=409,
            detail=(
                "Este horario esta proximo demais (ou ja passou) para uma nova reserva. "
                "Agende direto com os dados do paciente ou escolha outro horario."
            ),
        )

    if prazo_explicito is not None:
        prazo_local = _to_local_naive(_coerce_datetime(prazo_explicito))
        if prazo_local is None:
            raise HTTPException(status_code=422, detail="Prazo de confirmacao invalido.")
        return prazo_local.replace(second=0, microsecond=0), False

    horas_pedidas = horas if horas is not None else PRAZO_REABILITACAO_RESERVA_HORAS_PADRAO
    prazo_local = (agora_local + timedelta(hours=float(horas_pedidas))).replace(
        second=0, microsecond=0
    )
    if prazo_local <= limite_local:
        return prazo_local, False
    return limite_local, True


def _status_efetivo_agendamento(agendamento: Agendamento) -> str:
    status_atual = str(agendamento.status or "").strip() or "Agendado"
    if status_atual != "Reservado":
        return status_atual
    prazo_local = _to_local_naive(_coerce_datetime(getattr(agendamento, "reserva_expira_em", None)))
    if prazo_local is None:
        return status_atual
    agora_local = datetime.now(LOCAL_TZ).replace(tzinfo=None)
    return "Expirado" if prazo_local <= agora_local else status_atual


def _validar_prazo_reserva(agendamento: Agendamento) -> None:
    if str(agendamento.status or "").strip() != "Reservado":
        return
    prazo = _to_local_naive(_coerce_datetime(getattr(agendamento, "reserva_expira_em", None)))
    if prazo is None:
        return
    inicio = _to_local_naive(_coerce_datetime(agendamento.inicio))
    agora_local = datetime.now(LOCAL_TZ).replace(tzinfo=None)
    if prazo <= agora_local:
        raise HTTPException(status_code=422, detail="O prazo de confirmacao da reserva deve estar no futuro.")
    if inicio is not None and prazo >= inicio:
        raise HTTPException(
            status_code=422,
            detail="O prazo de confirmacao deve ser anterior ao horario reservado.",
        )


def _exigir_confirmacao_reativacao_reserva_expirada(
    *,
    status_anterior: str,
    status_novo: str,
    confirmado: bool,
) -> bool:
    tentativa_status_ativo = (
        status_anterior == "Expirado"
        and status_novo in AGENDA_STATUS_BLOQUEIAM_SLOT
    )
    if tentativa_status_ativo and status_novo != "Agendado":
        raise HTTPException(
            status_code=409,
            detail=(
                "Para reativar uma reserva expirada, use 'Reabilitar reserva' "
                "(segura o horario com um novo prazo de confirmacao) ou altere "
                "primeiro o status para Agendado."
            ),
        )
    reativando = tentativa_status_ativo and status_novo == "Agendado"
    if reativando and not confirmado:
        raise HTTPException(
            status_code=409,
            detail={
                "codigo": "CONFIRMACAO_REATIVACAO_RESERVA_EXPIRADA",
                "mensagem": (
                    "Esta reserva expirou. Se o cliente confirmou depois do prazo, "
                    "confirme a reativacao para o mesmo cliente. O horario sera agendado "
                    "somente se o slot ainda estiver livre."
                ),
                "confirmavel": True,
            },
        )
    return reativando


def _motivo_agenda_fechada_confirmavel(mensagem: str) -> bool:
    texto = str(mensagem or "").strip()
    return texto.startswith(
        (
            "Agenda fechada",
            "Horario fora do funcionamento da agenda",
            "Horario fora da excecao desta data",
        )
    )


def _escopo_excecao_agenda_fechada(agendamento: Agendamento) -> str:
    inicio = _to_local_naive(_coerce_datetime(agendamento.inicio))
    fim = _to_local_naive(_coerce_datetime(agendamento.fim))
    return f"{inicio.isoformat() if inicio else ''}|{fim.isoformat() if fim else ''}"


def _excecao_agenda_fechada_ativa(agendamento: Agendamento) -> bool:
    escopo = getattr(agendamento, "excecao_agenda_fechada_escopo", None)
    return bool(escopo and escopo == _escopo_excecao_agenda_fechada(agendamento))


def _validar_agendamento_no_funcionamento(
    db: Session,
    agendamento: Agendamento,
    *,
    permitir_excecao_agenda_fechada: bool = False,
) -> Optional[str]:
    inicio_dt = _coerce_datetime(agendamento.inicio)
    if inicio_dt is None:
        raise HTTPException(status_code=422, detail="Horario de inicio invalido.")

    fim_dt = _coerce_datetime(agendamento.fim)
    if fim_dt is None:
        fim_dt = inicio_dt + timedelta(minutes=30)

    inicio_local = _to_local_naive(inicio_dt)
    fim_local = _to_local_naive(fim_dt)
    if inicio_local is None or fim_local is None:
        raise HTTPException(status_code=422, detail="Nao foi possivel validar o horario informado.")

    agenda_semanal, agenda_feriados, agenda_excecoes = _obter_regras_agenda(db)
    valido, mensagem = validar_horario_agenda(
        inicio_local=inicio_local,
        fim_local=fim_local,
        agenda_semanal=agenda_semanal,
        agenda_feriados=agenda_feriados,
        agenda_excecoes=agenda_excecoes,
    )
    if not valido:
        if permitir_excecao_agenda_fechada and _motivo_agenda_fechada_confirmavel(mensagem):
            return mensagem
        raise HTTPException(status_code=422, detail=mensagem)
    return None


def _escopo_sobreposicao(item: Agendamento) -> str:
    inicio = _to_local_naive(_coerce_datetime(item.inicio))
    fim = _to_local_naive(_coerce_datetime(item.fim))
    return assinatura_sobreposicao({
        "rota": _fingerprint_escopo_deslocamento(item),
        "inicio": inicio.isoformat() if inicio else None,
        "fim": fim.isoformat() if fim else None,
    })


def _validar_slot_disponivel(
    db: Session,
    agendamento: Agendamento,
    *,
    agendamento_id_excluir: Optional[int] = None,
    confirmar_slot_reserva_expirada: bool = False,
    detalhar_sobreposicao: bool = False,
    **confirmacao_sobreposicao,
) -> list[Agendamento]:
    _expirar_reservas_vencidas(db)
    status_atual = (str(agendamento.status or "").strip() or "Agendado")
    if status_atual not in AGENDA_STATUS_BLOQUEIAM_SLOT:
        return []

    inicio_local, fim_local = _intervalo_local_agendamento(agendamento)
    if inicio_local is None:
        raise HTTPException(status_code=422, detail="Horario de inicio invalido para validar disponibilidade.")
    if fim_local is None:
        raise HTTPException(status_code=422, detail="Nao foi possivel validar disponibilidade do horario informado.")

    if fim_local <= inicio_local:
        raise HTTPException(status_code=422, detail="Horario final invalido para validar disponibilidade.")

    for bloqueio in _listar_bloqueios_ativos(db):
        bloqueio_inicio = _to_local_naive(_coerce_datetime(bloqueio.inicio))
        bloqueio_fim = _to_local_naive(_coerce_datetime(bloqueio.fim))
        if bloqueio_inicio is None or bloqueio_fim is None:
            continue
        if inicio_local < bloqueio_fim and fim_local > bloqueio_inicio:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Horario indisponivel: o slot esta bloqueado "
                    f"de {bloqueio_inicio.strftime('%d/%m/%Y %H:%M')} a "
                    f"{bloqueio_fim.strftime('%d/%m/%Y %H:%M')} "
                    f"({str(bloqueio.motivo or 'bloqueio administrativo')})."
                ),
            )

    data_referencia = inicio_local.date().isoformat()
    data_sem_vazio = func.nullif(func.trim(Agendamento.data), "")

    query_expiradas = (
        db.query(Agendamento)
        .filter(Agendamento.status == "Expirado")
        .filter(
            or_(
                data_sem_vazio == data_referencia,
                and_(
                    data_sem_vazio.is_(None),
                    func.date(Agendamento.inicio) == data_referencia,
                ),
            )
        )
    )
    if agendamento_id_excluir is not None:
        query_expiradas = query_expiradas.filter(Agendamento.id != agendamento_id_excluir)

    reservas_expiradas_sobrepostas: list[Agendamento] = []
    for expirada in query_expiradas.all():
        inicio_expirada, fim_expirada = _intervalo_local_agendamento(expirada)
        if inicio_expirada is None or fim_expirada is None:
            continue
        if inicio_local < fim_expirada and fim_local > inicio_expirada:
            reservas_expiradas_sobrepostas.append(expirada)

    query = (
        db.query(Agendamento)
        .filter(Agendamento.status.in_(AGENDA_STATUS_BLOQUEIAM_SLOT))
        .filter(
            or_(
                data_sem_vazio == data_referencia,
                and_(
                    Agendamento.inicio < _to_local_aware(fim_local),
                    Agendamento.fim > _to_local_aware(inicio_local),
                ),
                and_(
                    data_sem_vazio.is_(None),
                    func.date(Agendamento.inicio) == data_referencia,
                ),
            )
        )
    )
    if agendamento_id_excluir is not None:
        query = query.filter(Agendamento.id != agendamento_id_excluir)

    escopo = _escopo_sobreposicao(agendamento)
    assinatura_candidato = (
        assinatura_sobreposicao({"id": agendamento.id, "escopo": escopo})
        if agendamento.id is not None else None
    )
    conflitos_sobreposicao = []
    for existente in query.all():
        inicio_existente_local, fim_existente_local = _intervalo_local_agendamento(existente)
        if inicio_existente_local is None:
            continue
        if fim_existente_local is None:
            continue

        sobrepoe = inicio_local < fim_existente_local and fim_local > inicio_existente_local
        if not sobrepoe:
            continue

        escopo_existente = _escopo_sobreposicao(existente)
        concessao_existente = ler_concessao_sobreposicao(existente)
        conflitos_sobreposicao.append({
            "id": existente.id,
            "paciente": str(existente.paciente or "").strip(),
            "inicio": inicio_existente_local.isoformat(),
            "fim": fim_existente_local.isoformat(),
            "assinatura": assinatura_sobreposicao({
                "id": existente.id, "escopo": escopo_existente,
            }),
            # O atendimento original também pode seguir no mesmo horário.
            "autorizado_pelo_existente": (
                assinatura_candidato is not None
                and concessao_existente.get("escopo") == escopo_existente
                and assinatura_candidato in concessao_existente.get("conflitos", [])
            ),
        })

    try:
        validar_conflitos_sobreposicao(
            agendamento, escopo, conflitos_sobreposicao,
            **confirmacao_sobreposicao,
        )
    except HTTPException as exc:
        # PATCH de status/reabilitacao e clientes legados conservam mensagem
        # textual. POST/PUT retornam o contrato de revisao para admin.
        if not detalhar_sobreposicao and exc.status_code == 409 and isinstance(exc.detail, dict):
            raise HTTPException(409, exc.detail["mensagem"]) from exc
        raise

    if reservas_expiradas_sobrepostas and not confirmar_slot_reserva_expirada:
        reservas_detalhes = []
        for expirada in reservas_expiradas_sobrepostas:
            inicio_expirada, fim_expirada = _intervalo_local_agendamento(expirada)
            related_expirada = _fetch_related_names(db, expirada)
            prazo_expirado = _to_local_naive(
                _coerce_datetime(getattr(expirada, "reserva_expira_em", None))
            )
            reservas_detalhes.append(
                {
                    "id": expirada.id,
                    "clinica": related_expirada.get("clinica_nome") or expirada.clinica or "Clinica nao informada",
                    "paciente": related_expirada.get("paciente_nome") or expirada.paciente or "Pendente",
                    "tutor": related_expirada.get("tutor_nome") or expirada.tutor or "Pendente",
                    "telefone": related_expirada.get("tutor_telefone") or expirada.telefone or "",
                    "inicio": inicio_expirada.isoformat() if inicio_expirada else None,
                    "fim": fim_expirada.isoformat() if fim_expirada else None,
                    "reserva_expira_em": prazo_expirado.isoformat() if prazo_expirado else None,
                }
            )
        raise HTTPException(
            status_code=409,
            detail={
                "codigo": "CONFIRMACAO_SLOT_RESERVA_EXPIRADA",
                "mensagem": (
                    "Este horario teve uma reserva expirada. Antes de reutiliza-lo, "
                    "revise as mensagens do WhatsApp e confirme que a clinica nao enviou "
                    "os dados do tutor ou do pet apos o vencimento."
                ),
                "confirmavel": True,
                "reservas_expiradas": reservas_detalhes,
            },
        )

    return reservas_expiradas_sobrepostas


def _is_slot_overlap_db_error(exc: Exception) -> bool:
    original = getattr(exc, "orig", None)
    sqlstate = str(
        getattr(original, "sqlstate", None)
        or getattr(original, "pgcode", None)
        or ""
    ).strip()
    if sqlstate == "23P01":
        return True
    return "ex_agendamentos_slot_ativo" in str(exc).lower()


def _commit_agenda_write(db: Session) -> None:
    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        if _is_slot_overlap_db_error(exc):
            raise HTTPException(
                status_code=409,
                detail="Horario indisponivel: ja existe atendimento sobreposto neste slot.",
            ) from exc
        raise HTTPException(
            status_code=500,
            detail="Erro ao salvar agendamento no banco de dados.",
        ) from exc


def _adquirir_lock_escrita_agenda(db: Session) -> None:
    if db.info.get("_agenda_write_lock"):
        return

    bind = db.get_bind()
    dialect_name = str(getattr(getattr(bind, "dialect", None), "name", "")).lower()

    if dialect_name == "sqlite":
        # Em SQLite, BEGIN IMMEDIATE antecipa o lock de escrita e evita corrida
        # entre duas transacoes que validam slot ao mesmo tempo.
        if not db.in_transaction():
            db.execute(text("BEGIN IMMEDIATE"))
    elif dialect_name in {"postgres", "postgresql"}:
        db.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": AGENDA_WRITE_LOCK_KEY})
    else:
        (
            db.query(Configuracao)
            .order_by(Configuracao.id.asc())
            .with_for_update()
            .first()
        )

    db.info["_agenda_write_lock"] = True


def _fetch_related_names(db: Session, agendamento: Agendamento) -> dict:
    paciente_nome = None
    tutor_nome = None
    tutor_telefone = None
    tutor_id_relacionado = None
    clinica_nome = None
    servico_nome = None

    tutor = None
    if agendamento.paciente_id:
        paciente = db.query(Paciente).filter(Paciente.id == agendamento.paciente_id).first()
        if paciente:
            paciente_nome = paciente.nome
            if paciente.tutor_id:
                tutor_id_relacionado = int(paciente.tutor_id)
                tutor = db.query(Tutor).filter(Tutor.id == paciente.tutor_id).first()
                if tutor:
                    tutor_id_relacionado = tutor.id
                    agendamento.tutor_id = _resolver_tutor_id_relacionado(agendamento, tutor.id)
                    tutor_nome = tutor.nome
                    tutor_telefone = tutor.telefone

    if tutor is None:
        tutor = _resolver_tutor_agendamento(db, agendamento)
        if tutor:
            tutor_id_relacionado = tutor.id
            tutor_nome = tutor.nome
            tutor_telefone = tutor.telefone

    if agendamento.clinica_id:
        clinica = db.query(Clinica).filter(Clinica.id == agendamento.clinica_id).first()
        if clinica:
            clinica_nome = clinica.nome

    if agendamento.servico_id:
        servico = db.query(Servico).filter(Servico.id == agendamento.servico_id).first()
        if servico:
            servico_nome = servico.nome

    return {
        "paciente_nome": paciente_nome,
        "tutor_nome": tutor_nome,
        "tutor_telefone": tutor_telefone,
        "tutor_id_relacionado": _resolver_tutor_id_relacionado(agendamento, tutor_id_relacionado),
        "clinica_nome": clinica_nome,
        "servico_nome": servico_nome,
    }


def _sync_denormalized_fields(agendamento: Agendamento, related: dict) -> None:
    paciente_nome = related.get("paciente_nome")
    tutor_nome = related.get("tutor_nome")
    tutor_telefone = related.get("tutor_telefone")
    clinica_nome = related.get("clinica_nome")
    servico_nome = related.get("servico_nome")

    if paciente_nome:
        agendamento.paciente = paciente_nome
    if tutor_nome:
        agendamento.tutor = tutor_nome
    if tutor_telefone:
        agendamento.telefone = tutor_telefone
    origem = _normalizar_origem_atendimento(getattr(agendamento, "origem_atendimento", None))

    if clinica_nome:
        agendamento.clinica = clinica_nome
    elif origem == ORIGEM_ATENDIMENTO_DOMICILIAR:
        agendamento.clinica = "Atendimento domiciliar"
    if servico_nome:
        agendamento.servico = servico_nome


def _contexto_agendamento_auditoria(agendamento: Agendamento, related: Optional[dict] = None) -> dict[str, str]:
    rel = related or {}

    data = str(agendamento.data or "").strip()
    hora = str(agendamento.hora or "").strip()
    if not data or not hora:
        inicio = _to_local_naive(_coerce_datetime(agendamento.inicio))
        if inicio is not None:
            if not data:
                data = inicio.strftime("%Y-%m-%d")
            if not hora:
                hora = inicio.strftime("%H:%M")

    paciente = (str(rel.get("paciente_nome") or agendamento.paciente or "").strip() or "Nao informado")
    tutor = (str(rel.get("tutor_nome") or agendamento.tutor or "").strip() or "Nao informado")
    origem = _normalizar_origem_atendimento(getattr(agendamento, "origem_atendimento", None))
    clinica_padrao = "Atendimento domiciliar" if origem == ORIGEM_ATENDIMENTO_DOMICILIAR else "Nao informada"
    clinica = (str(rel.get("clinica_nome") or agendamento.clinica or "").strip() or clinica_padrao)

    return {
        "data": data or "-",
        "hora": hora or "-",
        "clinica": clinica,
        "animal": paciente,
        "tutor": tutor,
    }


def _descricao_contexto_agendamento(contexto: dict[str, str]) -> str:
    return (
        f"{contexto.get('data', '-')} {contexto.get('hora', '-')}"
        f" | Clinica: {contexto.get('clinica', 'Nao informada')}"
        f" | Animal: {contexto.get('animal', 'Nao informado')}"
        f" | Tutor: {contexto.get('tutor', 'Nao informado')}"
    )


def _registrar_auditoria_excecao_operacional_concedida(
    *,
    db: Session,
    current_user: User,
    request: Request,
    agendamento: Agendamento,
    related: Optional[dict],
    motivo: str,
) -> None:
    contexto = _contexto_agendamento_auditoria(agendamento, related)
    registrar_auditoria(
        current_user=current_user,
        modulo="agenda",
        entidade="assistente_agendamento",
        entidade_id=agendamento.id,
        acao="ASSISTENTE_AGENDA_EXCECAO_CONCEDIDA",
        descricao=(
            "Excecao operacional concedida por admin para concluir agendamento manual - "
            f"{_descricao_contexto_agendamento(contexto)}"
        ),
        detalhes={
            "motivo": motivo,
            "perfil_usuario": "admin",
            "agendamento_id": agendamento.id,
            "clinica_id": agendamento.clinica_id,
            "servico_id": agendamento.servico_id,
            "contexto_agendamento": contexto,
        },
        request=request,
    )


def _registrar_evento_funil_assistente(
    *,
    current_user: User,
    request: Optional[Request],
    evento: str,
    detalhes: Optional[dict[str, Any]] = None,
) -> None:
    registrar_auditoria(
        current_user=current_user,
        modulo="agenda",
        entidade="assistente_agendamento",
        acao=evento,
        descricao=f"Evento de funil do assistente: {evento}.",
        detalhes=detalhes or {},
        request=request,
    )


def _parse_detalhes_auditoria(raw: Optional[str]) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _extrair_data_evento_local(value: Any) -> Optional[str]:
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return dt.astimezone(LOCAL_TZ).date().isoformat()
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(LOCAL_TZ).date().isoformat()


def _validar_paciente_tutor_para_status(
    db: Session,
    agendamento: Agendamento,
    *,
    status_destino: Optional[str] = None,
    related: Optional[dict] = None,
) -> None:
    status_alvo = (status_destino or agendamento.status or "").strip() or "Agendado"
    if status_alvo in {"Reservado", "Cancelado"}:
        return

    rel = related or _fetch_related_names(db, agendamento)
    paciente_id_valido = bool(agendamento.paciente_id)
    paciente_nome = str(rel.get("paciente_nome") or agendamento.paciente or "").strip()
    tutor_nome = str(rel.get("tutor_nome") or agendamento.tutor or "").strip()

    if not paciente_id_valido or not paciente_nome:
        raise HTTPException(
            status_code=422,
            detail="Para este status, o campo paciente deve estar preenchido.",
        )

    if not tutor_nome:
        raise HTTPException(
            status_code=422,
            detail="Para este status, o campo tutor deve estar preenchido.",
        )


def _normalizar_status_agendamento(status_value: Optional[str], fallback: str = "Agendado") -> str:
    status_norm = (status_value or fallback or "Agendado").strip() or "Agendado"
    if status_norm not in AGENDA_STATUS_PERMITIDOS:
        raise HTTPException(
            status_code=400,
            detail=f"Status invalido. Use: {', '.join(AGENDA_STATUS_PERMITIDOS)}",
        )
    return status_norm


def _serialize_agendamento(
    agendamento: Agendamento,
    *,
    paciente_nome: Optional[str] = None,
    tutor_nome: Optional[str] = None,
    tutor_telefone: Optional[str] = None,
    tutor_id_relacionado: Optional[int] = None,
    clinica_nome: Optional[str] = None,
    servico_nome: Optional[str] = None,
) -> dict:
    inicio_dt = _coerce_datetime(agendamento.inicio)
    fim_dt = _coerce_datetime(agendamento.fim)
    reserva_expira_dt = _coerce_datetime(getattr(agendamento, "reserva_expira_em", None))
    excecao_deslocamento_em = _coerce_datetime(
        getattr(agendamento, "excecao_deslocamento_concedida_em", None)
    )
    tutor_id_resolvido = _resolver_tutor_id_relacionado(agendamento, tutor_id_relacionado)

    data = agendamento.data
    hora = agendamento.hora
    if inicio_dt is not None:
        if not data:
            data = inicio_dt.strftime("%Y-%m-%d")
        if not hora:
            hora = inicio_dt.strftime("%H:%M")

    return {
        "id": agendamento.id,
        "paciente_id": agendamento.paciente_id,
        "tutor_id": tutor_id_resolvido,
        "clinica_id": agendamento.clinica_id,
        "servico_id": agendamento.servico_id,
        "origem_atendimento": _normalizar_origem_atendimento(getattr(agendamento, "origem_atendimento", None)),
        "inicio": inicio_dt.strftime("%Y-%m-%d %H:%M:%S") if inicio_dt else None,
        "fim": fim_dt.strftime("%Y-%m-%d %H:%M:%S") if fim_dt else None,
        "status": _status_efetivo_agendamento(agendamento),
        "reserva_expira_em": reserva_expira_dt.isoformat() if reserva_expira_dt else None,
        "excecao_agenda_fechada_ativa": _excecao_agenda_fechada_ativa(agendamento),
        "observacoes": agendamento.observacoes,
        "data": data,
        "hora": hora,
        "paciente": paciente_nome or agendamento.paciente or "Paciente nao informado",
        "tutor": tutor_nome or agendamento.tutor or "Tutor nao informado",
        "telefone": tutor_telefone or agendamento.telefone or "",
        "servico": servico_nome or agendamento.servico or "",
        "clinica": clinica_nome or agendamento.clinica or (
            "Atendimento domiciliar"
            if _normalizar_origem_atendimento(getattr(agendamento, "origem_atendimento", None)) == ORIGEM_ATENDIMENTO_DOMICILIAR
            else "Clinica nao informada"
        ),
        "criado_por_nome": agendamento.criado_por_nome,
        "confirmado_por_nome": agendamento.confirmado_por_nome,
        "created_at": str(agendamento.created_at) if agendamento.created_at else None,
        "excecao_sobreposicao": ler_concessao_sobreposicao(agendamento) or None,
        "excecao_deslocamento_ativa": _excecao_deslocamento_ativa(agendamento),
        "excecao_deslocamento_concedida_em": (
            excecao_deslocamento_em.isoformat() if excecao_deslocamento_em else None
        ),
        "excecao_deslocamento_concedida_por_nome": getattr(
            agendamento, "excecao_deslocamento_concedida_por_nome", None
        ),
        "excecao_deslocamento_motivo": getattr(agendamento, "excecao_deslocamento_motivo", None),
    }


def _query_agendamentos_com_relacionados(db: Session):
    return (
        db.query(
            Agendamento,
            Paciente.nome.label("paciente_nome"),
            Clinica.nome.label("clinica_nome"),
            Servico.nome.label("servico_nome"),
            Tutor.nome.label("tutor_nome"),
            Tutor.telefone.label("tutor_telefone"),
            func.coalesce(Agendamento.tutor_id, Paciente.tutor_id).label("tutor_id_relacionado"),
        )
        .outerjoin(Paciente, Agendamento.paciente_id == Paciente.id)
        .outerjoin(Clinica, Agendamento.clinica_id == Clinica.id)
        .outerjoin(Servico, Agendamento.servico_id == Servico.id)
        .outerjoin(
            Tutor,
            or_(
                Paciente.tutor_id == Tutor.id,
                and_(Paciente.id.is_(None), Agendamento.tutor_id == Tutor.id),
            ),
        )
    )


def _primeiro_nome_paciente_assistente(
    agendamento: Agendamento,
    *,
    paciente_nome: Optional[str] = None,
) -> Optional[str]:
    raw = " ".join(str(paciente_nome or agendamento.paciente or "").split())
    if not raw:
        return None
    return raw.split(" ", 1)[0]


def _serialize_agendamento_assistente_readonly(
    agendamento: Agendamento,
    *,
    paciente_nome: Optional[str] = None,
    clinica_nome: Optional[str] = None,
    servico_nome: Optional[str] = None,
    incluir_paciente: bool = False,
) -> dict[str, Any]:
    inicio_dt, fim_dt = _intervalo_local_agendamento(agendamento)
    data = str(agendamento.data or "").strip()
    hora = str(agendamento.hora or "").strip()
    if inicio_dt is not None:
        if not data:
            data = inicio_dt.date().isoformat()
        if not hora:
            hora = inicio_dt.strftime("%H:%M")

    duracao_minutos = None
    if inicio_dt is not None and fim_dt is not None and fim_dt > inicio_dt:
        duracao_minutos = int((fim_dt - inicio_dt).total_seconds() // 60)

    item: dict[str, Any] = {
        "agendamento_id": agendamento.id,
        "data": data or None,
        "inicio": hora or (inicio_dt.strftime("%H:%M") if inicio_dt else None),
        "fim": fim_dt.strftime("%H:%M") if fim_dt else None,
        "duracao_minutos": duracao_minutos,
        "status": agendamento.status,
        "conta_como_ancora": _status_conta_como_ancora(agendamento.status),
        "clinica": {
            "id": agendamento.clinica_id,
            "nome": clinica_nome or agendamento.clinica or "Clinica nao informada",
        },
        "servico": {
            "id": agendamento.servico_id,
            "nome": servico_nome or agendamento.servico or "",
        },
    }
    if incluir_paciente:
        item["paciente_primeiro_nome"] = _primeiro_nome_paciente_assistente(
            agendamento,
            paciente_nome=paciente_nome,
        )
    return item


def _incrementar_resumo_assistente(bucket: dict[str, int], key: Optional[Any]) -> None:
    key_txt = str(key or "nao_informado").strip() or "nao_informado"
    bucket[key_txt] = int(bucket.get(key_txt, 0)) + 1


def _clinicas_ativas_assistente(db: Session) -> list[dict[str, Any]]:
    clinicas = (
        db.query(Clinica)
        .filter(Clinica.ativo == True)  # noqa: E712
        .order_by(Clinica.nome.asc(), Clinica.id.asc())
        .all()
    )
    return [
        {
            "id": clinica.id,
            "nome": clinica.nome,
            "cidade": clinica.cidade,
            "estado": clinica.estado,
            "regiao_operacional": clinica.regiao_operacional,
        }
        for clinica in clinicas
    ]


def _servicos_ativos_assistente(db: Session) -> list[dict[str, Any]]:
    servicos = (
        db.query(Servico)
        .filter(Servico.ativo == True)  # noqa: E712
        .order_by(Servico.nome.asc(), Servico.id.asc())
        .all()
    )
    return [
        {
            "id": servico.id,
            "nome": servico.nome,
            "duracao_minutos": servico.duracao_minutos,
        }
        for servico in servicos
    ]


def _status_operacional_assistente(status_value: Optional[Any]) -> str:
    status_txt = str(status_value or "").strip().casefold()
    if status_txt in {"agendado", "reservado", "confirmado"}:
        return "aguardando"
    if status_txt == "em atendimento":
        return "em_atendimento"
    if status_txt in {"realizado", "concluido", "concluído"}:
        return "finalizado"
    if status_txt == "cancelado":
        return "cancelado"
    if status_txt == "faltou":
        return "faltou"
    return "outro"


def _datas_periodo_assistente(inicio_iso: str, fim_iso: str) -> list[str]:
    try:
        inicio_ref = datetime.strptime(inicio_iso, "%Y-%m-%d").date()
        fim_ref = datetime.strptime(fim_iso, "%Y-%m-%d").date()
    except ValueError:
        return []
    total = max(0, (fim_ref - inicio_ref).days)
    return [(inicio_ref + timedelta(days=offset)).isoformat() for offset in range(total + 1)]


def _merge_intervalos_assistente(intervalos: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    ordenados = sorted(
        [(inicio, fim) for inicio, fim in intervalos if fim > inicio],
        key=lambda item: item[0],
    )
    merged: list[tuple[datetime, datetime]] = []
    for inicio, fim in ordenados:
        if not merged or inicio > merged[-1][1]:
            merged.append((inicio, fim))
            continue
        merged[-1] = (merged[-1][0], max(merged[-1][1], fim))
    return merged


def _resumir_operacional_dia_assistente(
    db: Session,
    *,
    data_iso: str,
    agendamentos_periodo: list[dict],
    agora_local: datetime,
    min_slot_minutos: int = 30,
) -> dict[str, Any]:
    janela_inicio, janela_fim, motivo_fechado = _obter_janela_funcionamento_data(db, data_iso)
    agendamentos_dia = [
        item
        for item in agendamentos_periodo
        if isinstance(item.get("inicio"), datetime) and item["inicio"].date().isoformat() == data_iso
    ]
    agendamentos_dia.sort(key=lambda item: (item["inicio"], item.get("id") or 0))

    fila_status = {
        "aguardando": 0,
        "em_atendimento": 0,
        "finalizado": 0,
        "cancelado": 0,
        "faltou": 0,
        "outro": 0,
    }
    pendencias = {
        "sem_confirmacao": 0,
        "sem_clinica": 0,
        "sem_servico": 0,
        "sem_horario_fim": 0,
    }
    atrasos: list[dict[str, Any]] = []
    conflitos: list[dict[str, Any]] = []
    por_clinica: dict[str, int] = {}
    intervalos_ocupados: list[tuple[datetime, datetime]] = []
    anterior: Optional[dict] = None

    for item in agendamentos_dia:
        inicio_item = item.get("inicio")
        fim_item = item.get("fim")
        if not isinstance(inicio_item, datetime):
            continue
        if not isinstance(fim_item, datetime) or fim_item <= inicio_item:
            fim_item = inicio_item + timedelta(minutes=30)
            pendencias["sem_horario_fim"] += 1

        status_item = str(item.get("status") or "").strip() or "Agendado"
        status_operacional = _status_operacional_assistente(status_item)
        fila_status[status_operacional] = int(fila_status.get(status_operacional, 0)) + 1
        _incrementar_resumo_assistente(por_clinica, item.get("clinica_nome"))
        if status_item in {"Agendado", "Reservado"}:
            pendencias["sem_confirmacao"] += 1
        if not item.get("clinica_id"):
            pendencias["sem_clinica"] += 1
        if not item.get("servico_id"):
            pendencias["sem_servico"] += 1

        if status_item not in AGENDA_STATUS_NAO_ANCORA:
            intervalos_ocupados.append((inicio_item, fim_item))
            if (
                inicio_item.date() == agora_local.date()
                and inicio_item < agora_local
                and status_item in {"Agendado", "Reservado", "Confirmado"}
            ):
                atrasos.append(
                    {
                        "agendamento_id": item.get("id"),
                        "status": status_item,
                        "inicio": inicio_item.strftime("%H:%M"),
                        "clinica": item.get("clinica_nome") or "Clinica nao informada",
                        "minutos_desde_inicio": max(0, _minutos_entre(inicio_item, agora_local)),
                    }
                )

        if anterior:
            anterior_fim = anterior.get("fim")
            if isinstance(anterior_fim, datetime) and inicio_item < anterior_fim:
                conflitos.append(
                    {
                        "tipo": "sobreposicao",
                        "agendamento_id": item.get("id"),
                        "agendamento_anterior_id": anterior.get("id"),
                        "inicio": inicio_item.strftime("%H:%M"),
                        "fim_anterior": anterior_fim.strftime("%H:%M"),
                    }
                )
            if not isinstance(anterior_fim, datetime) or fim_item > anterior_fim:
                anterior = {**item, "fim": fim_item}
        else:
            anterior = {**item, "fim": fim_item}

    vagas: list[dict[str, Any]] = []
    minutos_janela = 0
    minutos_ocupados = 0
    if janela_inicio is not None and janela_fim is not None:
        minutos_janela = max(0, _minutos_entre(janela_inicio, janela_fim))
        intervalos_clipped = [
            (max(inicio, janela_inicio), min(fim, janela_fim))
            for inicio, fim in intervalos_ocupados
            if fim > janela_inicio and inicio < janela_fim
        ]
        intervalos_merged = _merge_intervalos_assistente(intervalos_clipped)
        minutos_ocupados = sum(max(0, _minutos_entre(inicio, fim)) for inicio, fim in intervalos_merged)

        cursor = janela_inicio
        for inicio_ocupado, fim_ocupado in intervalos_merged:
            if inicio_ocupado > cursor:
                duracao_livre = _minutos_entre(cursor, inicio_ocupado)
                if duracao_livre >= min_slot_minutos:
                    vagas.append(
                        {
                            "inicio": cursor.strftime("%H:%M"),
                            "fim": inicio_ocupado.strftime("%H:%M"),
                            "duracao_minutos": duracao_livre,
                        }
                    )
            if fim_ocupado > cursor:
                cursor = fim_ocupado
        if cursor < janela_fim:
            duracao_livre = _minutos_entre(cursor, janela_fim)
            if duracao_livre >= min_slot_minutos:
                vagas.append(
                    {
                        "inicio": cursor.strftime("%H:%M"),
                        "fim": janela_fim.strftime("%H:%M"),
                        "duracao_minutos": duracao_livre,
                    }
                )

    ocupacao_percentual = 0
    if minutos_janela > 0:
        ocupacao_percentual = round(min(100.0, minutos_ocupados / minutos_janela * 100), 1)

    gargalos: list[dict[str, Any]] = []
    if conflitos:
        gargalos.append({"tipo": "conflito_horario", "severidade": "alta", "total": len(conflitos)})
    if atrasos:
        gargalos.append({"tipo": "atraso_operacional", "severidade": "media", "total": len(atrasos)})
    if ocupacao_percentual >= 85:
        gargalos.append({"tipo": "ocupacao_alta", "severidade": "media", "ocupacao_percentual": ocupacao_percentual})
    if not vagas and janela_inicio is not None:
        gargalos.append({"tipo": "sem_vagas_livres", "severidade": "media"})

    return {
        "data": data_iso,
        "janela": (
            {
                "inicio": janela_inicio.strftime("%H:%M"),
                "fim": janela_fim.strftime("%H:%M"),
                "minutos": minutos_janela,
            }
            if janela_inicio is not None and janela_fim is not None
            else {"fechada": True, "motivo": motivo_fechado or "Agenda fechada."}
        ),
        "fila_status": fila_status,
        "total_agendamentos_ativos": len(agendamentos_dia),
        "por_clinica": por_clinica,
        "ocupacao": {
            "minutos_ocupados": minutos_ocupados,
            "percentual": ocupacao_percentual,
        },
        "vagas_livres": vagas[:12],
        "vagas_livres_truncado": len(vagas) > 12,
        "atrasos": atrasos[:20],
        "conflitos": conflitos[:20],
        "pendencias": pendencias,
        "gargalos": gargalos,
    }


def _gerar_contexto_operacional_assistente(
    db: Session,
    *,
    data_inicio_iso: str,
    data_fim_iso: str,
) -> dict[str, Any]:
    datas = _datas_periodo_assistente(data_inicio_iso, data_fim_iso)
    agora_local = datetime.now(LOCAL_TZ).replace(tzinfo=None)
    agendamentos_periodo = _listar_agendamentos_ativos_periodo(
        db,
        data_inicio_iso,
        data_fim_iso,
    )
    dias = [
        _resumir_operacional_dia_assistente(
            db,
            data_iso=data_iso,
            agendamentos_periodo=agendamentos_periodo,
            agora_local=agora_local,
        )
        for data_iso in datas
    ]
    return {
        "gerado_em": datetime.now(LOCAL_TZ).isoformat(),
        "modo": "read_only_sanitizado",
        "totais": {
            "agendamentos_ativos": sum(int(dia.get("total_agendamentos_ativos") or 0) for dia in dias),
            "conflitos": sum(len(dia.get("conflitos") or []) for dia in dias),
            "atrasos": sum(len(dia.get("atrasos") or []) for dia in dias),
            "dias_com_gargalo": sum(1 for dia in dias if dia.get("gargalos")),
            "vagas_livres": sum(len(dia.get("vagas_livres") or []) for dia in dias),
        },
        "dias": dias,
        "orientacao_nox": [
            "Use fila_status para responder sobre andamento do dia.",
            "Use vagas_livres como candidatos iniciais; antes de orientar agendamento, considere regras de rota e assistente guiado.",
            "Use conflitos, atrasos, pendencias e gargalos para priorizar atencao humana.",
            "Nao trate vagas_livres como confirmacao automatica de agendamento.",
        ],
    }


def _aplicar_filtros_lista_agenda(
    query,
    *,
    data_inicio: Optional[str],
    data_fim: Optional[str],
    status: Optional[str],
    origem_atendimento: Optional[str],
    clinica_id: Optional[int],
    servico_id: Optional[int],
    paciente_id: Optional[int],
    paciente_nome: Optional[str],
    tutor_nome: Optional[str],
    clinica_nome: Optional[str],
    servico_nome: Optional[str],
):
    # Filtra por coluna data (YYYY-MM-DD) para evitar drift de timezone entre navegador e servidor.
    data_inicio_filtro = _extract_date_filter(data_inicio)
    data_fim_filtro = _extract_date_filter(data_fim)
    if data_inicio_filtro:
        query = query.filter(Agendamento.data >= data_inicio_filtro)
    if data_fim_filtro:
        query = query.filter(Agendamento.data <= data_fim_filtro)
    if status == "Expirado":
        query = query.filter(
            or_(
                Agendamento.status == "Expirado",
                and_(
                    Agendamento.status == "Reservado",
                    Agendamento.reserva_expira_em.isnot(None),
                    Agendamento.reserva_expira_em <= func.now(),
                ),
            )
        )
    elif status == "Reservado":
        query = query.filter(Agendamento.status == "Reservado").filter(
            or_(
                Agendamento.reserva_expira_em.is_(None),
                Agendamento.reserva_expira_em > func.now(),
            )
        )
    elif status:
        query = query.filter(Agendamento.status == status)
    if origem_atendimento and str(origem_atendimento).strip().lower() != "todos":
        origem_normalizada = _normalizar_origem_atendimento(origem_atendimento)
        query = query.filter(Agendamento.origem_atendimento == origem_normalizada)
    if clinica_id:
        query = query.filter(Agendamento.clinica_id == clinica_id)
    if servico_id:
        query = query.filter(Agendamento.servico_id == servico_id)
    if paciente_id:
        query = query.filter(Agendamento.paciente_id == paciente_id)

    paciente_nome_filtro = _normalize_text_filter(paciente_nome)
    if paciente_nome_filtro:
        pattern = _build_contains_pattern(paciente_nome_filtro)
        query = query.filter(
            or_(
                Agendamento.paciente.ilike(pattern, escape="\\"),
                exists().where(Paciente.id == Agendamento.paciente_id).where(
                    Paciente.nome.ilike(pattern, escape="\\")
                ),
            )
        )

    tutor_nome_filtro = _normalize_text_filter(tutor_nome)
    if tutor_nome_filtro:
        pattern = _build_contains_pattern(tutor_nome_filtro)
        query = query.filter(
            or_(
                Agendamento.tutor.ilike(pattern, escape="\\"),
                exists()
                .where(Paciente.id == Agendamento.paciente_id)
                .where(Paciente.tutor_id == Tutor.id)
                .where(Tutor.nome.ilike(pattern, escape="\\")),
            )
        )

    clinica_nome_filtro = _normalize_text_filter(clinica_nome)
    if clinica_nome_filtro:
        pattern = _build_contains_pattern(clinica_nome_filtro)
        query = query.filter(
            or_(
                Agendamento.clinica.ilike(pattern, escape="\\"),
                exists().where(Clinica.id == Agendamento.clinica_id).where(
                    Clinica.nome.ilike(pattern, escape="\\")
                ),
            )
        )

    servico_nome_filtro = _normalize_text_filter(servico_nome)
    if servico_nome_filtro:
        pattern = _build_contains_pattern(servico_nome_filtro)
        query = query.filter(
            or_(
                Agendamento.servico.ilike(pattern, escape="\\"),
                exists().where(Servico.id == Agendamento.servico_id).where(
                    Servico.nome.ilike(pattern, escape="\\")
                ),
            )
        )

    return query


@router.get("", response_model=AgendamentoLista)
def listar_agendamentos(
    data_inicio: Optional[str] = None,
    data_fim: Optional[str] = None,
    status: Optional[str] = None,
    origem_atendimento: Optional[str] = None,
    clinica_id: Optional[int] = None,
    servico_id: Optional[int] = None,
    paciente_id: Optional[int] = None,
    paciente_nome: Optional[str] = None,
    tutor_nome: Optional[str] = None,
    clinica_nome: Optional[str] = None,
    servico_nome: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Lista agendamentos com filtros e nomes dos relacionados"""
    query_ids = _aplicar_filtros_lista_agenda(
        db.query(Agendamento.id),
        data_inicio=data_inicio,
        data_fim=data_fim,
        status=status,
        origem_atendimento=origem_atendimento,
        clinica_id=clinica_id,
        servico_id=servico_id,
        paciente_id=paciente_id,
        paciente_nome=paciente_nome,
        tutor_nome=tutor_nome,
        clinica_nome=clinica_nome,
        servico_nome=servico_nome,
    )

    total = query_ids.order_by(None).count()
    ids_paginados = [
        row[0]
        for row in query_ids.order_by(Agendamento.inicio.asc(), Agendamento.id.asc()).offset(skip).limit(limit).all()
    ]

    results = []
    if ids_paginados:
        results = (
            _query_agendamentos_com_relacionados(db)
            .filter(Agendamento.id.in_(ids_paginados))
            .order_by(Agendamento.inicio.asc(), Agendamento.id.asc())
            .all()
        )

    items = [
        _serialize_agendamento(
            ag,
            paciente_nome=paciente_nome,
            clinica_nome=clinica_nome,
            servico_nome=servico_nome,
            tutor_nome=tutor_nome,
            tutor_telefone=tutor_telefone,
            tutor_id_relacionado=tutor_id_relacionado,
        )
        for ag, paciente_nome, clinica_nome, servico_nome, tutor_nome, tutor_telefone, tutor_id_relacionado in results
    ]

    agenda_semanal, agenda_feriados, agenda_excecoes = _obter_regras_agenda(db)

    return {
        "total": total,
        "items": items,
        "agenda_semanal": agenda_semanal,
        "agenda_feriados": agenda_feriados,
        "agenda_excecoes": agenda_excecoes,
    }


def _serialize_endereco_relacionado(entidade: Any) -> dict[str, Any]:
    return {
        "id": entidade.id,
        "nome": entidade.nome,
        "endereco": entidade.endereco,
        "numero": entidade.numero,
        "bairro": entidade.bairro,
        "cidade": entidade.cidade,
        "estado": entidade.estado,
        "cep": entidade.cep,
        "latitude": entidade.latitude,
        "longitude": entidade.longitude,
        "endereco_normalizado": entidade.endereco_normalizado,
    }


@router.get("/relacionados", response_model=dict)
def listar_relacionados_agenda(
    agendamento_ids: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retorna apenas os resumos relacionados ao lote visivel da Agenda."""
    del current_user
    ids_solicitados = _parse_agendamento_ids_param(agendamento_ids)

    relacoes = (
        db.query(
            Agendamento.id.label("agendamento_id"),
            Agendamento.clinica_id.label("clinica_id"),
            func.coalesce(Agendamento.tutor_id, Paciente.tutor_id).label("tutor_id"),
        )
        .outerjoin(Paciente, Paciente.id == Agendamento.paciente_id)
        .filter(Agendamento.id.in_(ids_solicitados))
        .all()
    )
    ids_validos = sorted({int(item.agendamento_id) for item in relacoes})
    if not ids_validos:
        return {
            "agendamento_ids": [],
            "laudos": [],
            "ordens_servico": [],
            "clinicas": [],
            "tutores": [],
        }

    laudos_rows = (
        db.query(
            Laudo.id,
            Laudo.agendamento_id,
            Laudo.paciente_id,
            Laudo.tipo,
            Laudo.status,
            Laudo.titulo,
        )
        .filter(Laudo.agendamento_id.in_(ids_validos))
        .all()
    )
    laudos_por_chave: dict[tuple[int, str], dict[str, Any]] = {}
    for laudo in laudos_rows:
        agendamento_id = int(laudo.agendamento_id)
        tipo = str(laudo.tipo or "")
        if not tipo:
            continue
        chave = (agendamento_id, tipo)
        anterior = laudos_por_chave.get(chave)
        if anterior is None or int(laudo.id) > int(anterior["id"]):
            laudos_por_chave[chave] = {
                "id": int(laudo.id),
                "agendamento_id": agendamento_id,
                "paciente_id": int(laudo.paciente_id),
                "tipo": tipo,
                "status": str(laudo.status or ""),
                "titulo": str(laudo.titulo or f"Laudo {laudo.id}"),
            }

    ordens_rows = (
        db.query(
            OrdemServico.id,
            OrdemServico.agendamento_id,
            OrdemServico.numero_os,
            OrdemServico.status,
            OrdemServico.valor_servico,
            OrdemServico.desconto,
            OrdemServico.valor_final,
        )
        .filter(OrdemServico.agendamento_id.in_(ids_validos))
        .all()
    )
    ordens_por_agendamento: dict[int, dict[str, Any]] = {}
    for ordem in ordens_rows:
        agendamento_id = int(ordem.agendamento_id)
        anterior = ordens_por_agendamento.get(agendamento_id)
        if anterior is None or int(ordem.id) > int(anterior["id"]):
            ordens_por_agendamento[agendamento_id] = {
                "id": int(ordem.id),
                "agendamento_id": agendamento_id,
                "numero_os": str(ordem.numero_os or ""),
                "status": str(ordem.status or ""),
                "valor_servico": float(ordem.valor_servico or 0),
                "desconto": float(ordem.desconto or 0),
                "valor_final": float(ordem.valor_final or 0),
            }

    ids_clinica = sorted(
        {
            int(item.clinica_id)
            for item in relacoes
            if item.clinica_id is not None and int(item.clinica_id) > 0
        }
    )
    ids_tutor = sorted(
        {
            int(item.tutor_id)
            for item in relacoes
            if item.tutor_id is not None and int(item.tutor_id) > 0
        }
    )
    clinicas = db.query(Clinica).filter(Clinica.id.in_(ids_clinica)).all() if ids_clinica else []
    tutores = db.query(Tutor).filter(Tutor.id.in_(ids_tutor)).all() if ids_tutor else []

    return {
        "agendamento_ids": ids_validos,
        "laudos": sorted(
            laudos_por_chave.values(),
            key=lambda item: (item["agendamento_id"], item["tipo"], item["id"]),
        ),
        "ordens_servico": sorted(
            ordens_por_agendamento.values(),
            key=lambda item: (item["agendamento_id"], item["id"]),
        ),
        "clinicas": sorted(
            (_serialize_endereco_relacionado(clinica) for clinica in clinicas),
            key=lambda item: item["id"],
        ),
        "tutores": sorted(
            (_serialize_endereco_relacionado(tutor) for tutor in tutores),
            key=lambda item: item["id"],
        ),
    }


def _calcular_previsoes_agendamentos_em_lote(
    db: Session,
    agendamentos: list[Agendamento],
) -> dict[int, Decimal]:
    """Calcula previsoes da Agenda sem repetir consultas de precificacao por item."""
    previsoes = {int(agendamento.id): Decimal("0.00") for agendamento in agendamentos}
    chaves_por_agendamento: dict[int, tuple[int | None, int, str]] = {}

    for agendamento in agendamentos:
        origem = _normalizar_origem_atendimento(getattr(agendamento, "origem_atendimento", None))
        if not agendamento.servico_id:
            continue
        if origem != ORIGEM_ATENDIMENTO_DOMICILIAR and not agendamento.clinica_id:
            continue

        try:
            servico_id = int(agendamento.servico_id)
            clinica_id = int(agendamento.clinica_id) if agendamento.clinica_id else None
        except (TypeError, ValueError):
            continue
        chaves_por_agendamento[int(agendamento.id)] = (clinica_id, servico_id, origem)

    if not chaves_por_agendamento:
        return previsoes

    try:
        precos = calcular_precos_servicos_em_lote(
            db,
            chaves_por_agendamento.values(),
            tipo_horario="comercial",
            usar_preco_clinica=True,
        )
    except Exception:
        logger.exception("Resumo financeiro da agenda falhou ao carregar precificacao em lote")
        return previsoes

    for agendamento_id, chave in chaves_por_agendamento.items():
        previsoes[agendamento_id] = to_decimal(precos.get(chave))

    return previsoes


@router.get("/resumo-financeiro")
def resumo_financeiro_agenda(
    data: Optional[str] = None,
    data_inicio: Optional[str] = None,
    data_fim: Optional[str] = None,
    origem_atendimento: Optional[str] = None,
    clinica_id: Optional[int] = None,
    servico_id: Optional[int] = None,
    paciente_id: Optional[int] = None,
    paciente_nome: Optional[str] = None,
    tutor_nome: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Resumo financeiro da agenda para admin (realizado x agendado)."""
    if not current_user.tem_papel("admin"):
        raise HTTPException(status_code=403, detail="Apenas administradores podem acessar este resumo.")

    if data:
        inicio = _extract_date_filter(data)
        fim = inicio
    else:
        inicio = _extract_date_filter(data_inicio)
        fim = _extract_date_filter(data_fim)

    if not inicio:
        hoje = datetime.now(LOCAL_TZ).date().isoformat()
        inicio = hoje
    if not fim:
        fim = inicio

    query_agendamentos = _aplicar_filtros_lista_agenda(
        db.query(Agendamento),
        data_inicio=inicio,
        data_fim=fim,
        status=None,
        origem_atendimento=origem_atendimento,
        clinica_id=clinica_id,
        servico_id=servico_id,
        paciente_id=paciente_id,
        paciente_nome=paciente_nome,
        tutor_nome=tutor_nome,
        clinica_nome=None,
        servico_nome=None,
    )
    agendamentos = query_agendamentos.all()

    ids_agendamento = [ag.id for ag in agendamentos]
    mapa_os: dict[int, OrdemServico] = {}
    if ids_agendamento:
        ordens = (
            db.query(OrdemServico)
            .filter(
                OrdemServico.agendamento_id.in_(ids_agendamento),
                OrdemServico.status != "Cancelado",
            )
            .order_by(OrdemServico.id.desc())
            .all()
        )
        for os_data in ordens:
            if os_data.agendamento_id not in mapa_os:
                mapa_os[os_data.agendamento_id] = os_data

    agendamentos_sem_valor_na_os = [
        agendamento
        for agendamento in agendamentos
        if not (
            mapa_os.get(agendamento.id)
            and mapa_os[agendamento.id].valor_final is not None
        )
    ]
    previsoes_por_agendamento = _calcular_previsoes_agendamentos_em_lote(
        db,
        agendamentos_sem_valor_na_os,
    )

    valor_realizado = Decimal("0.00")
    valor_agendado = Decimal("0.00")
    qtd_realizados = 0
    qtd_agendados = 0

    for ag in agendamentos:
        os_vinculada = mapa_os.get(ag.id)
        valor_base = (
            to_decimal(os_vinculada.valor_final)
            if os_vinculada and os_vinculada.valor_final is not None
            else previsoes_por_agendamento.get(int(ag.id), Decimal("0.00"))
        )

        if ag.status == "Realizado":
            qtd_realizados += 1
            valor_realizado += valor_base
        elif ag.status in ("Agendado", "Reservado", "Confirmado", "Em atendimento"):
            qtd_agendados += 1
            valor_agendado += valor_base

    return {
        "data_inicio": inicio,
        "data_fim": fim,
        "qtd_realizados": qtd_realizados,
        "qtd_agendados": qtd_agendados,
        "valor_realizado": float(valor_realizado),
        "valor_agendado": float(valor_agendado),
    }


@router.get("/configuracao")
def obter_configuracao_agenda(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Retorna regras de funcionamento da agenda para qualquer usuario com acesso ao modulo Agenda.
    Evita depender de permissao do modulo Configuracoes apenas para ler horario de funcionamento.
    """
    config = db.query(Configuracao).first()
    agenda_semanal, agenda_feriados, agenda_excecoes = _obter_regras_agenda(db)
    agenda_rota_regras = _obter_regras_rota_agenda(db)

    return {
        "horario_comercial_inicio": getattr(config, "horario_comercial_inicio", "08:00") if config else "08:00",
        "horario_comercial_fim": getattr(config, "horario_comercial_fim", "18:00") if config else "18:00",
        "dias_trabalho": getattr(config, "dias_trabalho", "1,2,3,4,5") if config else "1,2,3,4,5",
        "agenda_semanal": agenda_semanal,
        "agenda_feriados": agenda_feriados,
        "agenda_excecoes": agenda_excecoes,
        "agenda_rota_regras": agenda_rota_regras,
    }


@router.get("/assistente/contexto")
def obter_contexto_assistente_agenda_readonly(
    request: Request,
    data_inicio: Optional[str] = None,
    data_fim: Optional[str] = None,
    status: Optional[str] = None,
    clinica_id: Optional[int] = None,
    servico_id: Optional[int] = None,
    incluir_paciente: bool = False,
    limit: int = 200,
    db: Session = Depends(get_db),
):
    """
    Contexto minimo e read-only da agenda para assistentes externos autorizados.

    A rota usa token dedicado e nao retorna telefone, tutor, observacoes, laudos,
    financeiro nem dados completos de paciente. Serve para o assistente entender
    disponibilidade, ancoras e regras operacionais sem ganhar capacidade de escrita.
    """
    _validar_acesso_assistente_agenda(request)
    if status and status not in AGENDA_STATUS_PERMITIDOS:
        raise HTTPException(
            status_code=422,
            detail=f"Status invalido. Use: {', '.join(AGENDA_STATUS_PERMITIDOS)}",
        )

    inicio, fim, total_dias = _resolver_periodo_assistente_agenda(data_inicio, data_fim)
    limit_eff = max(1, min(500, int(limit or 200)))

    query_ids = _aplicar_filtros_lista_agenda(
        db.query(Agendamento.id),
        data_inicio=inicio,
        data_fim=fim,
        status=status,
        origem_atendimento=None,
        clinica_id=clinica_id,
        servico_id=servico_id,
        paciente_id=None,
        paciente_nome=None,
        tutor_nome=None,
        clinica_nome=None,
        servico_nome=None,
    )
    total = query_ids.order_by(None).count()
    ids_paginados = [
        row[0]
        for row in query_ids.order_by(Agendamento.inicio.asc(), Agendamento.id.asc())
        .limit(limit_eff)
        .all()
    ]

    rows = []
    if ids_paginados:
        rows = (
            _query_agendamentos_com_relacionados(db)
            .filter(Agendamento.id.in_(ids_paginados))
            .order_by(Agendamento.inicio.asc(), Agendamento.id.asc())
            .all()
        )

    items: list[dict[str, Any]] = []
    por_data: dict[str, int] = {}
    por_status: dict[str, int] = {}
    por_clinica: dict[str, int] = {}
    for agendamento, paciente_nome, clinica_nome, servico_nome, _tutor_nome, _tutor_telefone, _tutor_id_relacionado in rows:
        item = _serialize_agendamento_assistente_readonly(
            agendamento,
            paciente_nome=paciente_nome,
            clinica_nome=clinica_nome,
            servico_nome=servico_nome,
            incluir_paciente=incluir_paciente,
        )
        items.append(item)
        _incrementar_resumo_assistente(por_data, item.get("data"))
        _incrementar_resumo_assistente(por_status, item.get("status"))
        clinica_item = item.get("clinica") if isinstance(item.get("clinica"), dict) else {}
        _incrementar_resumo_assistente(por_clinica, clinica_item.get("nome"))

    agenda_semanal, agenda_feriados, agenda_excecoes = _obter_regras_agenda(db)
    agenda_rota_regras = _obter_regras_rota_agenda(db)

    return {
        "ok": True,
        "contrato": {
            "modo": "read_only",
            "escopo": "agenda_operacional",
            "janela_maxima_dias": _obter_max_window_assistente_agenda(),
            "dados_excluidos": [
                "telefone",
                "tutor",
                "observacoes",
                "laudos",
                "financeiro",
                "dados_completos_paciente",
            ],
            "acoes_permitidas": [
                "consultar_ocupacao",
                "explicar_regras",
                "preparar_sugestoes",
                "pedir_confirmacao_humana",
            ],
            "acoes_bloqueadas": [
                "criar_agendamento",
                "editar_agendamento",
                "cancelar_agendamento",
                "consultar_contato_do_tutor",
            ],
        },
        "periodo": {
            "data_inicio": inicio,
            "data_fim": fim,
            "total_dias": total_dias,
        },
        "agenda": {
            "total": total,
            "limit": limit_eff,
            "truncado": total > len(items),
            "items": items,
            "resumo": {
                "por_data": por_data,
                "por_status": por_status,
                "por_clinica": por_clinica,
            },
        },
        "operacional": _gerar_contexto_operacional_assistente(
            db,
            data_inicio_iso=inicio,
            data_fim_iso=fim,
        ),
        "catalogos": {
            "clinicas_ativas": _clinicas_ativas_assistente(db),
            "servicos_ativos": _servicos_ativos_assistente(db),
        },
        "regras": {
            "fonte": "configuracoes",
            "status_permitidos": AGENDA_STATUS_PERMITIDOS,
            "status_que_contam_como_ancora": [
                status_item
                for status_item in AGENDA_STATUS_PERMITIDOS
                if _status_conta_como_ancora(status_item)
            ],
            "agenda_semanal": agenda_semanal,
            "agenda_feriados": agenda_feriados,
            "agenda_excecoes": agenda_excecoes,
            "agenda_rota_regras": agenda_rota_regras,
        },
        "assistente_guiado": {
            "regra_geral": (
                "Use as mesmas regras de janela operacional, feriados, excecoes, "
                "ancoras por clinica e politica de oferta por rota/frequencia antes "
                "de sugerir horarios."
            ),
            "referencias_backend": {
                "orquestrador_ofertas": "POST /api/v1/agenda/assistente/ofertas",
                "sugestao_proximidade": "POST /api/v1/agenda/sugestao-proximidade",
                "panorama_horarios": "POST /api/v1/agenda/sugestoes-horario",
                "encerramento_sem_agendamento": "POST /api/v1/agenda/assistente/encerramento",
            },
            "orientacao_operacional": [
                "Nunca confirme agendamento sozinho; apresente sugestoes e peca validacao humana.",
                "Priorize slots aderentes a rota e frequencia configuradas.",
                "Quando nao houver oferta aderente, registre a necessidade de excecao ou encaminhe para humano.",
                "Nao use dados pessoais fora do minimo necessario para localizar ocupacao da agenda.",
            ],
        },
    }


@router.get("/hoje", response_model=AgendamentoLista)
def agendamentos_hoje(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Lista agendamentos de hoje"""
    hoje_str = datetime.now().strftime("%Y-%m-%d")
    results = (
        _query_agendamentos_com_relacionados(db)
        .filter(Agendamento.data == hoje_str)
        .order_by(Agendamento.inicio.asc(), Agendamento.id.asc())
        .all()
    )
    items = [
        _serialize_agendamento(
            agendamento,
            paciente_nome=paciente_nome,
            clinica_nome=clinica_nome,
            servico_nome=servico_nome,
            tutor_nome=tutor_nome,
            tutor_telefone=tutor_telefone,
            tutor_id_relacionado=tutor_id_relacionado,
        )
        for agendamento, paciente_nome, clinica_nome, servico_nome, tutor_nome, tutor_telefone, tutor_id_relacionado in results
    ]
    return {"total": len(items), "items": items}


@router.get("/stream")
async def stream_agenda(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Canal SSE para atualizacao em tempo real da agenda."""
    # FastAPI 0.104 encerra dependencias yield somente depois do body. O canal
    # pode ficar aberto indefinidamente, mas so precisa do ID ja autorizado.
    user_id = current_user.id
    await asyncio.to_thread(db.close)
    subscriber = agenda_realtime_manager.subscribe()

    async def event_generator():
        connected_payload = {
            "type": "connected",
            "module": "agenda",
            "user_id": user_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            yield f"event: connected\ndata: {json.dumps(connected_payload, ensure_ascii=False)}\n\n"
            while True:
                if await request.is_disconnected():
                    break

                try:
                    payload = await asyncio.to_thread(subscriber.get, True, 15)
                    yield f"event: agenda_update\ndata: {payload}\n\n"
                except Empty:
                    # keep-alive
                    yield "event: ping\ndata: {}\n\n"
        finally:
            agenda_realtime_manager.unsubscribe(subscriber)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        # Desconexao durante o envio pode suspender o generator no yield.
        background=BackgroundTask(agenda_realtime_manager.unsubscribe, subscriber),
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/geocode-endereco-tutor")
def geocode_tutor_para_agendamento(
    payload: GeocodeEnderecoPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # A single address entered inside Agenda is part of scheduling. Its own
    # registered action permits one confirmed Geocoding unit, never a batch.
    if not all(str(getattr(payload, field) or "").strip() for field in ("endereco", "numero", "cidade", "estado")):
        raise HTTPException(status_code=422, detail="Preencha endereço, número, cidade e UF para localizar o tutor na Agenda.")
    return geocode_endereco_tutor(payload, db=db, current_user=current_user)


@router.post("/oportunidades-dia")
def listar_oportunidades_dia(
    payload: OportunidadesDiaPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.agenda_day_opportunities import buscar_oportunidades_dia
    return buscar_oportunidades_dia(payload, db, current_user)


@router.post("/sugestoes-horario")
def sugerir_horarios_agenda(
    payload: SugestaoHorarioPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _sugerir_horarios_agenda(payload, db, current_user)


def _sugerir_horarios_agenda(payload, db, current_user, *, resolver_viagem=None, contexto_dia=None):
    """Sugere horarios operacionais considerando conflito de agenda e deslocamento entre destinos operacionais."""
    data_iso = _extract_date_filter(payload.data)
    if not data_iso:
        raise HTTPException(status_code=422, detail="Data invalida. Use o formato YYYY-MM-DD.")
    origem_atendimento = _normalizar_origem_atendimento(payload.origem_atendimento)
    hoje_local_iso = datetime.now(LOCAL_TZ).date().isoformat()
    if data_iso < hoje_local_iso:
        return {
            "ok": True,
            "data": data_iso,
            "clinica_id": payload.clinica_id,
            "tutor_id": payload.tutor_id,
            "origem_atendimento": origem_atendimento,
            "duracao_minutos": max(5, int(payload.duracao_minutos or 30)),
            "perfil_deslocamento": normalizar_perfil(payload.perfil_deslocamento),
            "motivo": "Nao sugerimos horarios para datas passadas. Selecione hoje ou uma data futura.",
            "total_encontrados": 0,
            "items": [],
        }

    contexto_dia = contexto_dia or {}
    destino_base = contexto_dia.get("destinos", {}).get(payload.clinica_id) or _resolver_destino_operacional_payload(
        db,
        origem_atendimento=origem_atendimento,
        clinica_id=payload.clinica_id,
        tutor_id=payload.tutor_id,
        contexto="sugerir horarios",
    )
    regras_rota = contexto_dia.get("regras") or _obter_regras_rota_agenda(db)
    thresholds = regras_rota.get("thresholds") if isinstance(regras_rota.get("thresholds"), dict) else {}
    route_policy = regras_rota.get("route_policy") if isinstance(regras_rota.get("route_policy"), dict) else {}
    base_cfg = regras_rota.get("base") if isinstance(regras_rota.get("base"), dict) else {}

    duracao_minutos = int(payload.duracao_minutos or 0)
    duracao_fallback = max(5, duracao_minutos if duracao_minutos > 0 else 30)
    # Fonte de verdade: quando houver servico selecionado, usa sempre a duracao cadastrada.
    duracao_minutos = contexto_dia.get("duracao_minutos") or _resolver_duracao_servico(
        db,
        servico_id=payload.servico_id,
        fallback_minutos=duracao_fallback,
    )

    janela_inicio, janela_fim, motivo_fechado = contexto_dia.get("janela") or _obter_janela_funcionamento_data(db, data_iso)
    if janela_inicio is None or janela_fim is None:
        return {
            "ok": True,
            "data": data_iso,
            "clinica_id": payload.clinica_id,
            "tutor_id": payload.tutor_id,
            "origem_atendimento": origem_atendimento,
            "duracao_minutos": duracao_minutos,
            "perfil_deslocamento": normalizar_perfil(payload.perfil_deslocamento),
            "motivo": motivo_fechado or "Sem janela valida para sugerir horarios.",
            "total_encontrados": 0,
            "items": [],
        }

    agendamentos_dia_todos = contexto_dia.get("agendamentos")
    if agendamentos_dia_todos is None:
        agendamentos_dia_todos = _listar_agendamentos_ativos_do_dia(
            db,
            data_iso,
            agendamento_id_excluir=payload.ignorar_agendamento_id,
        )
    agendamentos_dia = _filtrar_agendamentos_por_janela_funcionamento(
        db,
        agendamentos_dia_todos,
        cache_janelas={data_iso: (janela_inicio, janela_fim, None)},
    )
    # Keep all operational neighbours, even outside the requested turn/window.
    abertura_agenda = janela_inicio
    janela_inicio, janela_fim = _janela_preferencia(payload.preferencia, janela_inicio, janela_fim)
    if janela_inicio is None or janela_fim is None:
        return {"ok": True, "data": data_iso, "items": [], "total_encontrados": 0,
                "motivo": "Nenhum horario dentro da preferencia informada.",
                "duracao_minutos": duracao_minutos}

    bloqueios_dia: list[tuple[datetime, datetime]] = []
    for bloqueio in contexto_dia.get("bloqueios", []) if "bloqueios" in contexto_dia else _listar_bloqueios_ativos(db):
        bloqueio_inicio = _to_local_naive(_coerce_datetime(bloqueio.inicio))
        bloqueio_fim = _to_local_naive(_coerce_datetime(bloqueio.fim))
        if bloqueio_inicio is None or bloqueio_fim is None:
            continue
        if bloqueio_inicio.date().isoformat() <= data_iso <= bloqueio_fim.date().isoformat():
            bloqueios_dia.append((bloqueio_inicio, bloqueio_fim))
    perfil_norm = normalizar_perfil(payload.perfil_deslocamento)
    intervalo_minutos = max(5, int(payload.intervalo_minutos))
    margem_segura_min = int(thresholds.get("safe_margin_min", MIN_MARGEM_SEGURA_DESLOCAMENTO_MIN))
    limite_trecho_vizinho_min = int(
        thresholds.get("max_neighbor_travel_min", MAX_DESLOCAMENTO_TRECHO_VIZINHO_MIN)
    )
    transicao_mesmo_local_min = int(thresholds.get("same_location_transition_min", 5))
    ancoras_mesmo_destino = sorted(
        [
            item
            for item in agendamentos_dia
            if _destinos_operacionais_mesma_referencia(item.get("destino_operacional"), destino_base)
            and _status_conta_como_ancora(item.get("status"))
            and isinstance(item.get("inicio"), datetime)
            and isinstance(item.get("fim"), datetime)
        ],
        key=lambda item: item["inicio"],
    )
    ancoras_mesma_clinica = [
        item for item in ancoras_mesmo_destino
        if item["inicio"] < janela_fim and item["fim"] > janela_inicio
    ]
    limite_desvio_insercao = int(thresholds.get("max_insertion_detour_min") or 25)
    limite_proximo_base_min = int(thresholds.get("nearby_anchor_max_travel_min") or 20)
    janela_fim_rota_min = _hora_hhmm_para_minutos(
        route_policy.get("end_of_route_window_start"),
        fallback=16 * 60,
    )
    preferir_base_fim_rota = bool(route_policy.get("prefer_near_base_at_end_of_route", True))
    bonus_base_score = abs(int(route_policy.get("bonus_near_base_score") or 15))
    penalty_far_score = int(route_policy.get("penalty_far_base_score") or 10)
    bloquear_ineficiencia = bool(route_policy.get("reject_clear_inefficiency", True))
    tempo_ate_base_min = _tempo_estimado_destino_operacional_ate_base_min(
        destino_base,
        base_lat=base_cfg.get("lat"),
        base_lng=base_cfg.get("lng"),
        perfil_deslocamento=perfil_norm,
    )
    cache_duracoes_clinicas: dict[tuple[int, int, str, bool], tuple[int, str]] = {}
    cache_duracoes_operacionais: dict[tuple[str, int, str, int, str], tuple[int, str]] = {}
    cache_google: dict = {}
    resolver_viagem = resolver_viagem or _obter_duracao_deslocamento_operacional
    cache_regional: dict = contexto_dia.setdefault("cache_regional", {})
    baseline_regional = agendamentos_dia_todos
    if route_policy.get("regional_transition_enabled") and payload.ignorar_agendamento_id:
        baseline_regional = _listar_agendamentos_ativos_do_dia(db, data_iso)

    sugestoes: list[dict] = []
    # Cache-only resolvers may know a later direction even if this slot's is missing.
    teve_rota_sem_estimativa = False
    primeira_saida_sem_estimativa = False
    primeiro_inicio_viavel: Optional[str] = None
    inicio_minimo = janela_inicio
    cursor_grade = janela_inicio
    agora_local = datetime.now(LOCAL_TZ).replace(tzinfo=None)
    if janela_inicio.date() == agora_local.date():
        # A borda exata so precisa respeitar a antecedencia real. O arredondamento
        # vale apenas para candidatos regulares da grade.
        lead_time_min = max(1, margem_segura_min)
        inicio_minimo = max(janela_inicio, agora_local + timedelta(minutes=lead_time_min))
        cursor_grade = max(janela_inicio, _arredondar_para_proximo_slot(inicio_minimo, intervalo_minutos))
    # Ate 288 inicios de grade/dia e duas bordas por atendimento no mesmo local.
    candidatos = set()
    while cursor_grade < janela_fim:
        candidatos.add(cursor_grade)
        cursor_grade += timedelta(minutes=intervalo_minutos)
    for ancora in ancoras_mesmo_destino:
        candidatos.add(ancora["fim"] + timedelta(minutes=transicao_mesmo_local_min))
        candidatos.add(ancora["inicio"] - timedelta(minutes=duracao_minutos + transicao_mesmo_local_min))
    candidatos.add(janela_fim - timedelta(minutes=duracao_minutos))
    for inicio_candidato in sorted(candidato for candidato in candidatos if inicio_minimo <= candidato < janela_fim):
        fim_candidato = inicio_candidato + timedelta(minutes=duracao_minutos)
        if fim_candidato > janela_fim:
            break

        conflita = any(
            inicio_candidato < item["fim"] and fim_candidato > item["inicio"]
            for item in agendamentos_dia_todos
        )
        conflita = conflita or any(
            inicio_candidato < bloqueio_fim and fim_candidato > bloqueio_inicio
            for bloqueio_inicio, bloqueio_fim in bloqueios_dia
        )
        if conflita:
            continue

        if contexto_dia.get("somente_cache"):
            # Completing an anchored day must never trigger a base lookup,
            # including malformed/overnight legacy intervals.
            if not any(_status_conta_como_ancora(item.get("status")) and item["inicio"] < inicio_candidato
                       for item in agendamentos_dia_todos):
                continue
            primeira_saida = None
        else:
            primeira_saida = _avaliar_primeira_saida(
                db,
                inicio=inicio_candidato,
                destino=destino_base,
                agendamentos_dia=agendamentos_dia_todos,
                regras_rota=regras_rota,
                perfil=perfil_norm,
                agora_local=agora_local,
                abertura_agenda=abertura_agenda,
            )
        if primeira_saida is not None and not primeira_saida["viavel"]:
            primeira_saida_sem_estimativa = primeira_saida_sem_estimativa or primeira_saida["tempo_deslocamento_base_min"] is None
            minimo_primeira_saida = primeira_saida.get("inicio_minimo_primeira_saida")
            if isinstance(minimo_primeira_saida, str):
                primeiro_inicio_viavel = minimo_primeira_saida
            continue

        # Para validar deslocamento operacional, os vizinhos devem considerar toda a agenda ativa do dia.
        # Isso evita ofertar slots que "cabem" na janela configurada, mas conflitam com atendimentos
        # reais registrados fora da janela (legado/excecoes operacionais).
        anterior, proximo = _obter_vizinhos_horario(agendamentos_dia_todos, inicio_candidato, fim_candidato)

        tempo_prev = 0
        tempo_next = 0
        folga_prev = None
        folga_next = None
        fonte_prev = "indefinido"
        fonte_next = "indefinido"
        destino_anterior = anterior.get("destino_operacional") if isinstance(anterior, dict) else None
        destino_proximo = proximo.get("destino_operacional") if isinstance(proximo, dict) else None
        relaxar_limite_prev_por_ancora = False
        relaxar_limite_next_por_ancora = False
        ancora_anterior_adjacente = False
        ancora_proxima_adjacente = False

        if isinstance(destino_anterior, dict) and (bool(destino_anterior.get("localizacao_confiavel")) or _destinos_operacionais_mesma_referencia(destino_anterior, destino_base)):
            tempo_prev, fonte_prev = resolver_viagem(
                db,
                origem=destino_anterior,
                destino=destino_base,
                perfil=perfil_norm,
                cache_clinicas=cache_duracoes_clinicas,
                cache_operacional=cache_duracoes_operacionais,
                cache_google=cache_google,
            )
            if tempo_prev is None:
                teve_rota_sem_estimativa = True
                continue
            folga_prev = _minutos_entre(anterior["fim"], inicio_candidato)

        if isinstance(destino_proximo, dict) and (bool(destino_proximo.get("localizacao_confiavel")) or _destinos_operacionais_mesma_referencia(destino_base, destino_proximo)):
            tempo_next, fonte_next = resolver_viagem(
                db,
                origem=destino_base,
                destino=destino_proximo,
                perfil=perfil_norm,
                cache_clinicas=cache_duracoes_clinicas,
                cache_operacional=cache_duracoes_operacionais,
                cache_google=cache_google,
            )
            if tempo_next is None:
                teve_rota_sem_estimativa = True
                continue
            folga_next = _minutos_entre(fim_candidato, proximo["inicio"])

        regional = avaliar_transicao_regional(
            baseline_regional,
            {"id": payload.ignorar_agendamento_id, "inicio": inicio_candidato, "fim": fim_candidato,
             "status": "Agendado", "destino_operacional": destino_base},
            regras_rota=regras_rota,
            agendamento_id_excluir=payload.ignorar_agendamento_id,
            cache_deslocamentos=cache_regional,
            resolver_deslocamento=lambda origem, destino: resolver_viagem(
                db, origem=origem, destino=destino, perfil=perfil_norm,
                cache_clinicas=cache_duracoes_clinicas, cache_operacional=cache_duracoes_operacionais,
                cache_google=cache_google,
            ),
        )
        if regional is not None and not regional.permitida:
            if regional.codigo == "TRANSICAO_REGIONAL_ROTA_NAO_CONFIAVEL":
                teve_rota_sem_estimativa = True
            continue
        regional_prev = bool(regional and regional.trecho_anterior and regional.trecho_anterior.longo)
        regional_next = bool(regional and regional.trecho_proximo and regional.trecho_proximo.longo)

        ancora_anterior_adjacente = _vizinho_e_ancora_adjacente(
            anterior,
            destino_anterior,
            duracao_deslocamento_min=tempo_prev,
            folga_min=folga_prev,
            limite_ancora_min=limite_proximo_base_min,
            margem_segura_min=margem_segura_min,
        )
        ancora_proxima_adjacente = _vizinho_e_ancora_adjacente(
            proximo,
            destino_proximo,
            duracao_deslocamento_min=tempo_next,
            folga_min=folga_next,
            limite_ancora_min=limite_proximo_base_min,
            margem_segura_min=margem_segura_min,
        )
        relaxar_limite_prev_por_ancora = regional_prev or (
            regional is None
            and limite_trecho_vizinho_min > 0
            and tempo_prev > limite_trecho_vizinho_min
            and ancora_proxima_adjacente
            and _folga_cobre_deslocamento(folga_prev, tempo_prev, margem_min=margem_segura_min)
        )
        relaxar_limite_next_por_ancora = regional_next or (
            regional is None
            and limite_trecho_vizinho_min > 0
            and tempo_next > limite_trecho_vizinho_min
            and ancora_anterior_adjacente
            and _folga_cobre_deslocamento(folga_next, tempo_next, margem_min=margem_segura_min)
        )

        if (
            limite_trecho_vizinho_min > 0
            and tempo_prev > limite_trecho_vizinho_min
            and not relaxar_limite_prev_por_ancora
        ):
            continue
        mesmo_local_prev = _destinos_operacionais_mesma_referencia(destino_anterior, destino_base)
        folga_necessaria_prev = _folga_necessaria_entre_destinos(
            destino_anterior, destino_base, deslocamento_min=tempo_prev,
            margem_segura_min=margem_segura_min, transicao_mesmo_local_min=transicao_mesmo_local_min,
            ancora_adjacente=ancora_anterior_adjacente,
        )
        if regional_prev:
            folga_necessaria_prev = tempo_prev + regional.margem_min
        if (tempo_prev > 0 or mesmo_local_prev) and folga_prev < folga_necessaria_prev:
            continue

        if (
            limite_trecho_vizinho_min > 0
            and tempo_next > limite_trecho_vizinho_min
            and not relaxar_limite_next_por_ancora
        ):
            continue
        mesmo_local_next = _destinos_operacionais_mesma_referencia(destino_base, destino_proximo)
        folga_necessaria_next = _folga_necessaria_entre_destinos(
            destino_base, destino_proximo, deslocamento_min=tempo_next,
            margem_segura_min=margem_segura_min, transicao_mesmo_local_min=transicao_mesmo_local_min,
            ancora_adjacente=ancora_proxima_adjacente,
        )
        if regional_next:
            folga_necessaria_next = tempo_next + regional.margem_min
        if (tempo_next > 0 or mesmo_local_next) and folga_next < folga_necessaria_next:
            continue

        if (
            bloquear_ineficiencia
            and limite_desvio_insercao > 0
            and isinstance(destino_anterior, dict)
            and isinstance(destino_proximo, dict)
            and tempo_prev > 0
            and tempo_next > 0
            and (regional is not None or not (relaxar_limite_prev_por_ancora or relaxar_limite_next_por_ancora))
        ):
            duracao_direta, _fonte_direta = resolver_viagem(
                db,
                origem=destino_anterior,
                destino=destino_proximo,
                perfil=perfil_norm,
                cache_clinicas=cache_duracoes_clinicas,
                cache_operacional=cache_duracoes_operacionais,
                cache_google=cache_google,
            )
            if duracao_direta is None:
                teve_rota_sem_estimativa = True
                continue
            if duracao_direta > 0:
                desvio_insercao = max(0, int((tempo_prev + tempo_next) - duracao_direta))
                if desvio_insercao > limite_desvio_insercao:
                    continue

        tempo_prev_contabilizado = 0 if relaxar_limite_prev_por_ancora and regional is None else tempo_prev
        tempo_next_contabilizado = 0 if relaxar_limite_next_por_ancora and regional is None else tempo_next
        margem_prev = (folga_prev - tempo_prev) if folga_prev is not None else None
        margem_next = (folga_next - tempo_next) if folga_next is not None else None
        ociosidade_min = max(0, margem_prev or 0) + max(0, margem_next or 0)
        folgas_ancoras_adjacentes = []
        if ancora_anterior_adjacente and folga_prev is not None:
            folgas_ancoras_adjacentes.append(max(0, int(folga_prev)))
        if ancora_proxima_adjacente and folga_next is not None:
            folgas_ancoras_adjacentes.append(max(0, int(folga_next)))
        folga_ancora_adjacente_min = min(folgas_ancoras_adjacentes) if folgas_ancoras_adjacentes else None

        # Compact either side of the actual neighbouring booking, with equal priority.
        esperas_mesmo_local = []
        if mesmo_local_prev and folga_prev is not None:
            esperas_mesmo_local.append(max(0, folga_prev - transicao_mesmo_local_min))
        if mesmo_local_next and folga_next is not None:
            esperas_mesmo_local.append(max(0, folga_next - transicao_mesmo_local_min))
        preferencia_ancora_ordem = 0 if esperas_mesmo_local else 1
        espera_ancora_min = min(esperas_mesmo_local) if esperas_mesmo_local else 999999

        risco = 0
        if margem_prev is not None and margem_prev < (transicao_mesmo_local_min if mesmo_local_prev else margem_segura_min):
            risco += 1
        if margem_next is not None and margem_next < (transicao_mesmo_local_min if mesmo_local_next else margem_segura_min):
            risco += 1

        tempo_deslocamento_total = tempo_prev_contabilizado + tempo_next_contabilizado
        score = round((tempo_deslocamento_total * 1.0) + (ociosidade_min * 0.2) + (risco * 20.0), 2)
        horario_min = (inicio_candidato.hour * 60) + inicio_candidato.minute
        fim_rota = horario_min >= janela_fim_rota_min
        ajuste_base_score = 0
        if preferir_base_fim_rota and fim_rota and tempo_ate_base_min is not None:
            if tempo_ate_base_min <= limite_proximo_base_min:
                ajuste_base_score -= bonus_base_score
            else:
                ajuste_base_score += penalty_far_score
        score = round(score + ajuste_base_score, 2)

        sugestoes.append(
            {
                "inicio": inicio_candidato.strftime("%Y-%m-%d %H:%M"),
                "fim": fim_candidato.strftime("%Y-%m-%d %H:%M"),
                "score": score,
                "transicao_regional": regional.as_dict() if regional else None,
                "risco": risco,
                "preferencia_ancora_ordem": preferencia_ancora_ordem,
                "espera_ancora_min": espera_ancora_min if preferencia_ancora_ordem == 0 else None,
                "preferencia_ancora_adjacente_ordem": 0 if folga_ancora_adjacente_min is not None else 1,
                "folga_ancora_adjacente_min": folga_ancora_adjacente_min,
                "fim_rota": bool(fim_rota),
                "tempo_ate_base_min": tempo_ate_base_min,
                "ajuste_base_score": ajuste_base_score,
                "tempo_deslocamento_total_min": tempo_deslocamento_total,
                "tempo_deslocamento_base_min": primeira_saida["tempo_deslocamento_base_min"] if primeira_saida else None,
                "fonte_deslocamento_base": primeira_saida["fonte_deslocamento_base"] if primeira_saida else None,
                "inicio_minimo_primeira_saida": primeira_saida["inicio_minimo_primeira_saida"] if primeira_saida else None,
                "origem_primeira_saida": "base_operacional" if primeira_saida else None,
                "ociosidade_min": ociosidade_min,
                "destino_operacional": _rotulo_destino_operacional(destino_base),
                "destino_operacional_tipo": destino_base.get("tipo"),
                "anterior": (
                    {
                        "agendamento_id": anterior.get("id"),
                        "clinica_id": anterior.get("clinica_id"),
                        "tutor_id": anterior.get("tutor_id"),
                        "tipo": (destino_anterior or {}).get("tipo"),
                        "clinica": _rotulo_destino_operacional(destino_anterior),
                        "fim": anterior["fim"].strftime("%Y-%m-%d %H:%M"),
                        "duracao_deslocamento_min": tempo_prev,
                        "duracao_deslocamento_contabilizada_min": tempo_prev_contabilizado,
                        "folga_min": folga_prev,
                        "margem_min": margem_prev,
                        "fonte": fonte_prev,
                        "ancora_adjacente": bool(ancora_anterior_adjacente),
                        "trecho_desconsiderado_ancora_adjacente": bool(relaxar_limite_prev_por_ancora and regional is None),
                        "margem_segura_relaxada_ancora_adjacente": bool(ancora_anterior_adjacente and not regional_prev),
                    }
                    if anterior
                    else None
                ),
                "proximo": (
                    {
                        "agendamento_id": proximo.get("id"),
                        "clinica_id": proximo.get("clinica_id"),
                        "tutor_id": proximo.get("tutor_id"),
                        "tipo": (destino_proximo or {}).get("tipo"),
                        "clinica": _rotulo_destino_operacional(destino_proximo),
                        "inicio": proximo["inicio"].strftime("%Y-%m-%d %H:%M"),
                        "duracao_deslocamento_min": tempo_next,
                        "duracao_deslocamento_contabilizada_min": tempo_next_contabilizado,
                        "folga_min": folga_next,
                        "margem_min": margem_next,
                        "fonte": fonte_next,
                        "ancora_adjacente": bool(ancora_proxima_adjacente),
                        "trecho_desconsiderado_ancora_adjacente": bool(relaxar_limite_next_por_ancora and regional is None),
                        "margem_segura_relaxada_ancora_adjacente": bool(ancora_proxima_adjacente and not regional_next),
                    }
                    if proximo
                    else None
                ),
            }
        )


    sugestoes.sort(
        key=lambda item: (
            int(item.get("preferencia_ancora_ordem", 1)),
            (
                int(item.get("espera_ancora_min"))
                if item.get("espera_ancora_min") is not None
                else 999999
            ),
            int(item.get("preferencia_ancora_adjacente_ordem", 1)),
            (
                int(item.get("folga_ancora_adjacente_min"))
                if item.get("folga_ancora_adjacente_min") is not None
                else 999999
            ),
            item["score"],
            item["risco"],
            item["inicio"],
        )
    )
    _marcar_slots_adjacentes_ancora(
        sugestoes,
        ancoras_mesma_clinica,
        margem_segura_min=transicao_mesmo_local_min,
    )
    limite = max(1, min(50, int(payload.limite)))
    top_items = sugestoes[:limite]
    motivo_sem_item = None
    if not top_items and primeira_saida_sem_estimativa:
        motivo_sem_item = "Nao foi possivel consultar uma rota confiavel de casa ate o primeiro atendimento. Tente novamente; se persistir, revise os enderecos e a configuracao de rotas."
    if not top_items and primeiro_inicio_viavel:
        motivo_sem_item = (
            f"O primeiro atendimento neste destino so pode comecar a partir de {primeiro_inicio_viavel[-5:]}, "
            "considerando a saida de casa e o deslocamento."
        )
    if not top_items and data_iso == agora_local.date().isoformat():
        motivo_sem_item = motivo_sem_item or "Nao ha horarios futuros disponiveis para hoje dentro da janela da agenda."

    return {
        "ok": True,
        "data": data_iso,
        "clinica_id": payload.clinica_id,
        "tutor_id": payload.tutor_id,
        "origem_atendimento": origem_atendimento,
        "destino_operacional": _rotulo_destino_operacional(destino_base),
        "duracao_minutos": duracao_minutos,
        "perfil_deslocamento": perfil_norm,
        "intervalo_minutos": intervalo_minutos,
        "regras_aplicadas": {
            "regional_transition_enabled": bool(route_policy.get("regional_transition_enabled")),
            "regional_transition_max_travel_min": route_policy.get("regional_transition_max_travel_min", 50),
            "regional_transition_margin_min": route_policy.get("regional_transition_margin_min", 15),
            "safe_margin_min": margem_segura_min,
            "same_location_transition_min": transicao_mesmo_local_min,
            "max_neighbor_travel_min": limite_trecho_vizinho_min,
            "max_insertion_detour_min": limite_desvio_insercao,
            "nearby_anchor_max_travel_min": limite_proximo_base_min,
            "end_of_route_window_start": route_policy.get("end_of_route_window_start", "16:00"),
            "prefer_near_base_at_end_of_route": preferir_base_fim_rota,
            "tempo_ate_base_min": tempo_ate_base_min,
        },
        "janela": {
            "inicio": janela_inicio.strftime("%Y-%m-%d %H:%M"),
            "fim": janela_fim.strftime("%Y-%m-%d %H:%M"),
        },
        "motivo": motivo_sem_item,
        "total_agendamentos_no_dia": len(agendamentos_dia_todos),
        "tem_agendamentos_no_dia": bool(agendamentos_dia_todos),
        "total_ancoras_mesma_clinica": len(ancoras_mesma_clinica),
        "tem_ancora_mesma_clinica_no_dia": bool(ancoras_mesma_clinica),
        "total_encontrados": len(sugestoes),
        "teve_rota_sem_estimativa": teve_rota_sem_estimativa,
        "items": top_items,
    }


@router.post("/assistente/validar-oferta")
def validar_oferta_assistente_agenda(
    payload: ValidarOfertaAssistentePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Revalida o horario exato quando o cliente aceita uma oferta exibida anteriormente."""
    inicio_aware = _coerce_datetime(payload.inicio)
    inicio = _to_local_naive(inicio_aware)
    if inicio is None:
        raise HTTPException(status_code=422, detail="Inicio invalido. Use YYYY-MM-DD HH:mm.")
    agora = datetime.now(LOCAL_TZ).replace(tzinfo=None)
    if inicio <= agora:
        return {
            "ok": True, "valido": False, "codigo": "HORARIO_PASSADO",
            "mensagem": "O horario desta oferta ja passou. Solicite uma nova sugestao.",
            "inicio_minimo_primeira_saida": None,
        }

    duracao = _resolver_duracao_servico(
        db,
        servico_id=payload.servico_id,
        fallback_minutos=max(5, int(payload.duracao_minutos or 30)),
    )
    fim = inicio + timedelta(minutes=duracao)
    candidato = Agendamento(
        inicio=inicio_aware,
        fim=fim.replace(tzinfo=LOCAL_TZ),
        data=inicio.date().isoformat(),
        hora=inicio.strftime("%H:%M"),
        status="Agendado",
        origem_atendimento=payload.origem_atendimento,
        clinica_id=payload.clinica_id,
        tutor_id=payload.tutor_id,
        servico_id=payload.servico_id,
    )
    try:
        _validar_regras_origem_agendamento(db, candidato, contexto="validar a oferta")
        _validar_agendamento_no_funcionamento(db, candidato)
        ocupados = _listar_agendamentos_ativos_do_dia(
            db,
            inicio.date().isoformat(),
            agendamento_id_excluir=payload.ignorar_agendamento_id,
        )
        if any(inicio < item["fim"] and fim > item["inicio"] for item in ocupados):
            return {
                "ok": True, "valido": False, "codigo": "HORARIO_INDISPONIVEL",
                "mensagem": "Este horario foi ocupado. Solicite uma nova sugestao.",
                "inicio_minimo_primeira_saida": None,
            }
        for bloqueio in _listar_bloqueios_ativos(db):
            bloqueio_inicio = _to_local_naive(_coerce_datetime(bloqueio.inicio))
            bloqueio_fim = _to_local_naive(_coerce_datetime(bloqueio.fim))
            if bloqueio_inicio is not None and bloqueio_fim is not None and inicio < bloqueio_fim and fim > bloqueio_inicio:
                return {
                    "ok": True, "valido": False, "codigo": "HORARIO_BLOQUEADO",
                    "mensagem": "Este horario esta bloqueado. Solicite uma nova sugestao.",
                    "inicio_minimo_primeira_saida": None,
                }
        _validar_deslocamento_agendamento(
            db,
            candidato,
            agendamento_id_excluir=payload.ignorar_agendamento_id,
            perfil_deslocamento=payload.perfil_deslocamento,
            # This endpoint has no pending appointment write. Preserve cache
            # persistence for this read-only validation; writers keep False.
            commit_cache=True,
        )
    except GoogleMapsCostBlocked:
        raise
    except HTTPException as exc:
        detalhe = exc.detail if isinstance(exc.detail, dict) else {"mensagem": str(exc.detail)}
        return {
            "ok": True,
            "valido": False,
            "codigo": str(detalhe.get("codigo") or "OFERTA_INVIAVEL"),
            "mensagem": str(detalhe.get("mensagem") or "Esta oferta nao esta mais disponivel."),
            "inicio_minimo_primeira_saida": detalhe.get("inicio_minimo_primeira_saida"),
        }
    return {"ok": True, "valido": True, "inicio_minimo_primeira_saida": None}


@router.post("/sugestao-proximidade")
def sugerir_agendamento_proximo(
    payload: SugestaoProximidadePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Sugere aproveitamento de agenda existente proximo ao destino operacional selecionado."""
    origem_atendimento = _normalizar_origem_atendimento(payload.origem_atendimento)
    destino_base = _resolver_destino_operacional_payload(
        db,
        origem_atendimento=origem_atendimento,
        clinica_id=payload.clinica_id,
        tutor_id=payload.tutor_id,
        contexto="consultar sugestoes de proximidade",
    )
    destino_operacional_nome = _rotulo_destino_operacional(destino_base)
    regras_rota = _obter_regras_rota_agenda(db)
    thresholds = regras_rota.get("thresholds") if isinstance(regras_rota.get("thresholds"), dict) else {}
    limite_proximidade_default = int(thresholds.get("nearby_anchor_max_travel_min") or 20)

    data_iso = _extract_date_filter(payload.data) if payload.data else datetime.now().strftime("%Y-%m-%d")
    if not data_iso:
        raise HTTPException(status_code=422, detail="Data invalida. Use o formato YYYY-MM-DD.")
    hoje_local_iso = datetime.now(LOCAL_TZ).date().isoformat()
    if data_iso < hoje_local_iso:
        return {
            "ok": True,
            "data": data_iso,
            "clinica_id": payload.clinica_id,
            "tutor_id": payload.tutor_id,
            "origem_atendimento": origem_atendimento,
            "destino_operacional": destino_operacional_nome,
            "sugerir": False,
            "limite_minutos": limite_proximidade_default,
            "itens_ignorados_janela": 0,
            "politica_oferta": {
                "data_contato": None,
                "datas_preferenciais": [],
            },
            "mensagem": "Nao sugerimos horarios para datas passadas. Selecione hoje ou uma data futura.",
            "item": None,
        }

    data_contato_iso = (
        _extract_date_filter(payload.data_contato)
        if payload.data_contato
        else datetime.now(LOCAL_TZ).date().isoformat()
    )
    if not data_contato_iso:
        data_contato_iso = datetime.now(LOCAL_TZ).date().isoformat()
    try:
        data_contato_ref = datetime.strptime(data_contato_iso, "%Y-%m-%d").date()
    except ValueError:
        data_contato_ref = datetime.now(LOCAL_TZ).date()

    data_ref = datetime.strptime(data_iso, "%Y-%m-%d").date()
    agora_local = datetime.now(LOCAL_TZ).replace(tzinfo=None)
    janela_dias = int(payload.janela_dias_proximidade or 7)
    limite_minutos_payload = int(payload.limite_minutos or 0)
    limite_minutos = limite_minutos_payload
    if limite_minutos_payload == 25:
        limite_minutos = limite_proximidade_default
    if limite_minutos <= 0:
        limite_minutos = limite_proximidade_default

    if origem_atendimento == ORIGEM_ATENDIMENTO_PADRAO and payload.clinica_id:
        politica_oferta = _classificar_politica_oferta(
            db,
            clinica_id=payload.clinica_id,
            data_contato_iso=data_contato_iso,
            perfil_deslocamento=payload.perfil_deslocamento,
            regras_rota=regras_rota,
            agendamento_id_excluir=payload.ignorar_agendamento_id,
            preferencia=payload.preferencia,
        )
    else:
        politica_oferta = {
            "dias_preferenciais": [],
            "distante_base": False,
            "base_proxima": False,
            "baixa_frequencia": False,
            "agendamentos_30d": 0,
            "tempo_base_estimado_min": _tempo_estimado_destino_operacional_ate_base_min(
                destino_base,
                base_lat=(regras_rota.get("base") or {}).get("lat") if isinstance(regras_rota.get("base"), dict) else None,
                base_lng=(regras_rota.get("base") or {}).get("lng") if isinstance(regras_rota.get("base"), dict) else None,
                perfil_deslocamento=payload.perfil_deslocamento,
            ),
            "ancora_d0": False,
            "ancora_d2": False,
            "ancora_d3": False,
            "override": None,
            "override_ancora_obrigatoria": False,
            "prioridade_d0_aplicada": False,
            "sem_agendamentos_d0": False,
        }
    datas_preferenciais = [
        (
            datetime.strptime(data_contato_iso, "%Y-%m-%d").date() + timedelta(days=int(dia))
        ).isoformat()
        for dia in politica_oferta.get("dias_preferenciais", [])
    ]
    datas_preferenciais_dt = [
        datetime.strptime(data_item, "%Y-%m-%d").date() for data_item in datas_preferenciais
    ]
    datas_preferenciais_set = set(datas_preferenciais)
    politica_distante_baixa = bool(politica_oferta.get("distante_base")) and bool(
        politica_oferta.get("baixa_frequencia")
    )
    exigir_data_preferencial = (politica_distante_baixa and not bool(politica_oferta.get("ancora_d2"))
                               and not (payload.preferencia and payload.preferencia.data_inicio))

    data_inicio_busca = (data_ref - timedelta(days=janela_dias)).strftime("%Y-%m-%d")
    data_fim_busca = (data_ref + timedelta(days=janela_dias)).strftime("%Y-%m-%d")

    if payload.preferencia and payload.preferencia.data_inicio:
        data_inicio_busca = payload.preferencia.data_inicio
        data_fim_busca = payload.preferencia.data_fim

    agendamentos_periodo = _listar_agendamentos_ativos_periodo(
        db,
        data_inicio_busca,
        data_fim_busca,
        agendamento_id_excluir=payload.ignorar_agendamento_id,
    )
    total_agendamentos_periodo = len(agendamentos_periodo)
    agendamentos_periodo = _filtrar_agendamentos_por_janela_funcionamento(
        db,
        agendamentos_periodo,
    )
    itens_ignorados_janela = max(0, total_agendamentos_periodo - len(agendamentos_periodo))
    cache_clinicas: dict[int, Optional[Clinica]] = {}
    cache_slots_operacionais_por_data: dict[str, list[dict[str, Any]]] = {}
    melhor_item: Optional[dict] = None
    melhor_tempo: Optional[int] = None
    melhor_rank = None

    def _obter_slots_operacionais_data(data_busca_iso: str) -> list[dict[str, Any]]:
        if data_busca_iso in cache_slots_operacionais_por_data:
            return cache_slots_operacionais_por_data[data_busca_iso]

        payload_sugestoes = SugestaoHorarioPayload(
            preferencia=payload.preferencia,
            data=data_busca_iso,
            origem_atendimento=origem_atendimento,
            clinica_id=payload.clinica_id,
            tutor_id=payload.tutor_id,
            servico_id=payload.servico_id,
            duracao_minutos=payload.duracao_minutos,
            intervalo_minutos=payload.intervalo_minutos,
            limite=payload.limite_sugestoes_operacionais,
            perfil_deslocamento=payload.perfil_deslocamento,
            ignorar_agendamento_id=payload.ignorar_agendamento_id,
        )
        resposta_sugestoes = sugerir_horarios_agenda(
            payload=payload_sugestoes,
            db=db,
            current_user=current_user,
        )
        slots = resposta_sugestoes.get("items") if isinstance(resposta_sugestoes, dict) else None
        slots_lista = slots if isinstance(slots, list) else []
        cache_slots_operacionais_por_data[data_busca_iso] = slots_lista
        return slots_lista

    def _slot_referencia_ancora(slot: dict[str, Any], agendamento_id_ancora: int) -> bool:
        if agendamento_id_ancora <= 0:
            return False
        anterior = slot.get("anterior") if isinstance(slot, dict) else None
        proximo = slot.get("proximo") if isinstance(slot, dict) else None
        anterior_id = int((anterior or {}).get("agendamento_id") or 0)
        proximo_id = int((proximo or {}).get("agendamento_id") or 0)
        return anterior_id == agendamento_id_ancora or proximo_id == agendamento_id_ancora

    def _slot_usa_encaixe_adjacente_excepcional(slot: dict[str, Any], agendamento_id_ancora: int) -> bool:
        if agendamento_id_ancora <= 0 or not isinstance(slot, dict):
            return False
        anterior = slot.get("anterior") if isinstance(slot.get("anterior"), dict) else {}
        proximo = slot.get("proximo") if isinstance(slot.get("proximo"), dict) else {}
        anterior_id = int((anterior or {}).get("agendamento_id") or 0)
        proximo_id = int((proximo or {}).get("agendamento_id") or 0)
        if proximo_id == agendamento_id_ancora and bool(
            (anterior or {}).get("trecho_desconsiderado_ancora_adjacente")
        ):
            return True
        if anterior_id == agendamento_id_ancora and bool(
            (proximo or {}).get("trecho_desconsiderado_ancora_adjacente")
        ):
            return True
        return False

    for item in agendamentos_periodo:
        inicio_item = item.get("inicio")
        if inicio_item is None:
            continue

        status_item = (str(item.get("status") or "").strip() or "Agendado")
        if not _status_conta_como_ancora(status_item):
            continue

        # Nao sugerir ancora em horario passado, inclusive quando a data-base for hoje.
        # Isso evita mensagens contraditorias (proximidade sugerindo slot ja vencido).
        if inicio_item < agora_local:
            continue

        data_item_iso = inicio_item.date().isoformat()
        if payload.preferencia and not payload.preferencia.permite_data(data_item_iso):
            continue
        if exigir_data_preferencial and data_item_iso not in datas_preferenciais_set and data_item_iso != data_iso:
            continue

        slots_operacionais_data = _obter_slots_operacionais_data(data_item_iso)
        if not slots_operacionais_data:
            continue

        agendamento_ancora_id = int(item.get("id") or 0)
        if agendamento_ancora_id > 0:
            possui_slot_aderente = any(
                _slot_referencia_ancora(slot, agendamento_ancora_id) for slot in slots_operacionais_data
            )
            if not possui_slot_aderente:
                continue

        destino_item = item.get("destino_operacional") if isinstance(item, dict) else None
        clinica_item_id = int(item.get("clinica_id") or 0)
        if not isinstance(destino_item, dict):
            continue
        if _destinos_operacionais_mesma_referencia(destino_item, destino_base) and not payload.incluir_mesma_clinica:
            continue

        slots_aderentes = (
            [slot for slot in slots_operacionais_data if _slot_referencia_ancora(slot, agendamento_ancora_id)]
            if agendamento_ancora_id > 0
            else list(slots_operacionais_data)
        )
        if exigir_data_preferencial and data_item_iso not in datas_preferenciais_set:
            slots_aderentes = [
                slot
                for slot in slots_aderentes
                if _slot_usa_encaixe_adjacente_excepcional(slot, agendamento_ancora_id)
            ]
        if not slots_aderentes:
            continue

        for slot in slots_aderentes:
            if not isinstance(slot, dict):
                continue

            inicio_slot_raw = str(slot.get("inicio") or "").strip()
            fim_slot_raw = str(slot.get("fim") or "").strip()
            if not inicio_slot_raw:
                continue

            try:
                inicio_slot = datetime.strptime(inicio_slot_raw, "%Y-%m-%d %H:%M")
            except ValueError:
                continue

            data_slot_iso = inicio_slot.strftime("%Y-%m-%d")
            if exigir_data_preferencial and data_slot_iso not in datas_preferenciais_set and data_slot_iso != data_iso:
                continue
            if inicio_slot < agora_local:
                continue

            anterior_slot = slot.get("anterior") if isinstance(slot.get("anterior"), dict) else {}
            proximo_slot = slot.get("proximo") if isinstance(slot.get("proximo"), dict) else {}
            clinica_anterior_nome = str((anterior_slot or {}).get("clinica") or "").strip()
            clinica_posterior_nome = str((proximo_slot or {}).get("clinica") or "").strip()
            ha_agendamento_anterior = bool((anterior_slot or {}).get("agendamento_id") or clinica_anterior_nome)
            ha_agendamento_posterior = bool((proximo_slot or {}).get("agendamento_id") or clinica_posterior_nome)
            duracao_anterior_real = max(0, int((anterior_slot or {}).get("duracao_deslocamento_min") or 0))
            duracao_proximo_real = max(0, int((proximo_slot or {}).get("duracao_deslocamento_min") or 0))
            duracao_anterior = max(
                0,
                int((anterior_slot or {}).get("duracao_deslocamento_contabilizada_min", duracao_anterior_real) or 0),
            )
            duracao_proximo = max(
                0,
                int((proximo_slot or {}).get("duracao_deslocamento_contabilizada_min", duracao_proximo_real) or 0),
            )
            duracao_total = duracao_anterior + duracao_proximo

            if duracao_total <= 0:
                # Fallback para manter compatibilidade com payloads antigos sem vizinhos detalhados.
                duracao_total = max(0, int(slot.get("tempo_deslocamento_total_min") or 0))

            fonte_anterior = str((anterior_slot or {}).get("fonte") or "").strip()
            fonte_proximo = str((proximo_slot or {}).get("fonte") or "").strip()
            if duracao_anterior > 0 and duracao_proximo > 0:
                fonte = f"anterior:{fonte_anterior or 'indefinido'}|proximo:{fonte_proximo or 'indefinido'}"
            elif duracao_anterior > 0:
                fonte = f"anterior:{fonte_anterior or 'indefinido'}"
            elif duracao_proximo > 0:
                fonte = f"proximo:{fonte_proximo or 'indefinido'}"
            else:
                if _destinos_operacionais_mesma_referencia(destino_item, destino_base):
                    fonte = "mesmo_destino"
                elif (
                    origem_atendimento == ORIGEM_ATENDIMENTO_PADRAO
                    and clinica_item_id > 0
                    and payload.clinica_id
                    and _clinicas_mesma_cidade_uf(
                        db,
                        clinica_a_id=payload.clinica_id,
                        clinica_b_id=clinica_item_id,
                        cache=cache_clinicas,
                    )
                ):
                    fonte = "fallback_mesma_cidade"
                elif _destinos_operacionais_mesma_regiao(destino_base, destino_item):
                    fonte = "fallback_mesma_cidade"
                else:
                    fonte = "sem_vizinhos"

            folgas_ancora = []
            if int((anterior_slot or {}).get("agendamento_id") or 0) == agendamento_ancora_id:
                folgas_ancora.append(max(0, int((anterior_slot or {}).get("folga_min") or 0)))
            if int((proximo_slot or {}).get("agendamento_id") or 0) == agendamento_ancora_id:
                folgas_ancora.append(max(0, int((proximo_slot or {}).get("folga_min") or 0)))
            folga_ancora_min = min(folgas_ancora) if folgas_ancora else 999999

            rank = (
                int(duracao_total),
                int(folga_ancora_min),
                abs((inicio_slot.date() - data_ref).days),
                0 if data_slot_iso in datas_preferenciais_set else 1,
                (
                    min(abs((inicio_slot.date() - data_pref).days) for data_pref in datas_preferenciais_dt)
                    if datas_preferenciais_dt
                    else 0
                ),
                inicio_slot,
                int(item.get("id") or 0),
            )
            if melhor_rank is None or rank < melhor_rank:
                melhor_rank = rank
                melhor_tempo = int(duracao_total)
                melhor_item = {
                    "agendamento_id": item.get("id"),
                    "clinica_id": clinica_item_id or None,
                    "tutor_id": item.get("tutor_id"),
                    "clinica": _rotulo_destino_operacional(destino_item),
                    "data": data_slot_iso,
                    "inicio": inicio_slot.strftime("%H:%M"),
                    "fim": fim_slot_raw.split(" ")[1] if " " in fim_slot_raw else (fim_slot_raw or None),
                    "duracao_deslocamento_min": duracao_total,
                    "tempo_deslocamento_total_min": duracao_total,
                    "duracao_deslocamento_anterior_min": duracao_anterior,
                    "duracao_deslocamento_proximo_min": duracao_proximo,
                    "duracao_deslocamento_anterior_real_min": duracao_anterior_real,
                    "duracao_deslocamento_proximo_real_min": duracao_proximo_real,
                    "trecho_anterior_desconsiderado_ancora_adjacente": bool(
                        (anterior_slot or {}).get("trecho_desconsiderado_ancora_adjacente")
                    ),
                    "trecho_proximo_desconsiderado_ancora_adjacente": bool(
                        (proximo_slot or {}).get("trecho_desconsiderado_ancora_adjacente")
                    ),
                    "clinica_destino": destino_operacional_nome,
                    "destino_operacional": destino_operacional_nome,
                    "destino_operacional_tipo": origem_atendimento,
                    "clinica_anterior": clinica_anterior_nome or None,
                    "clinica_posterior": clinica_posterior_nome or None,
                    "ha_agendamento_anterior": ha_agendamento_anterior,
                    "ha_agendamento_posterior": ha_agendamento_posterior,
                    "fonte_deslocamento": fonte,
                    "status": status_item,
                    "data_preferencial": data_slot_iso in datas_preferenciais_set,
                }

    if melhor_item is None or melhor_tempo is None:
        mensagem_base = "Nao encontramos agenda proxima para sugestao automatica dentro da janela configurada."
        if politica_distante_baixa and datas_preferenciais:
            dias_relativos = ", ".join(
                [
                    f"D+{(datetime.strptime(item, '%Y-%m-%d').date() - data_contato_ref).days}"
                    for item in datas_preferenciais
                ]
            )
            if dias_relativos:
                mensagem_base = (
                    f"{mensagem_base} Politica da clinica: priorizar {dias_relativos} e usar D+2 apenas com atendimento proximo."
                )
        if itens_ignorados_janela > 0:
            mensagem_base = (
                f"{mensagem_base} {itens_ignorados_janela} agendamento(s) foram ignorados por estarem "
                "fora da janela operacional ou em data fechada."
            )
        return {
            "ok": True,
            "data": data_iso,
            "clinica_id": payload.clinica_id,
            "tutor_id": payload.tutor_id,
            "origem_atendimento": origem_atendimento,
            "destino_operacional": destino_operacional_nome,
            "sugerir": False,
            "limite_minutos": limite_minutos,
            "itens_ignorados_janela": itens_ignorados_janela,
            "politica_oferta": {
                **politica_oferta,
                "data_contato": data_contato_iso,
                "datas_preferenciais": datas_preferenciais,
            },
            "mensagem": mensagem_base,
            "item": None,
        }

    if melhor_tempo > limite_minutos:
        data_item = str(melhor_item.get("data") or data_iso)
        data_item_legivel = _formatar_data_com_semana_pt(data_item)
        detalhe_deslocamento = _detalhar_deslocamento_por_clinicas(
            clinica_destino=melhor_item.get("clinica_destino") or clinica_destino_nome,
            clinica_anterior=melhor_item.get("clinica_anterior"),
            clinica_posterior=melhor_item.get("clinica_posterior"),
            duracao_anterior_min=melhor_item.get("duracao_deslocamento_anterior_min"),
            duracao_posterior_min=melhor_item.get("duracao_deslocamento_proximo_min"),
            total_min=melhor_tempo,
            ha_agendamento_anterior=bool(melhor_item.get("ha_agendamento_anterior")),
            ha_agendamento_posterior=bool(melhor_item.get("ha_agendamento_posterior")),
            trecho_anterior_desconsiderado=bool(
                melhor_item.get("trecho_anterior_desconsiderado_ancora_adjacente")
            ),
            trecho_posterior_desconsiderado=bool(
                melhor_item.get("trecho_proximo_desconsiderado_ancora_adjacente")
            ),
            duracao_anterior_real_min=melhor_item.get("duracao_deslocamento_anterior_real_min"),
            duracao_posterior_real_min=melhor_item.get("duracao_deslocamento_proximo_real_min"),
        )
        mensagem_limite = (
            f"Opcao mais proxima encontrada na data {data_item_legivel} as {melhor_item.get('inicio')} "
            f"proximo ao atendimento em {_nome_clinica_legivel(melhor_item.get('clinica'))}. "
            f"{detalhe_deslocamento} O deslocamento total estimado ({melhor_tempo} min) "
            f"esta acima do limite configurado de {limite_minutos} min."
        )
        return {
            "ok": True,
            "data": data_iso,
            "clinica_id": payload.clinica_id,
            "tutor_id": payload.tutor_id,
            "origem_atendimento": origem_atendimento,
            "destino_operacional": destino_operacional_nome,
            "sugerir": False,
            "limite_minutos": limite_minutos,
            "itens_ignorados_janela": itens_ignorados_janela,
            "politica_oferta": {
                **politica_oferta,
                "data_contato": data_contato_iso,
                "datas_preferenciais": datas_preferenciais,
            },
            "mensagem": mensagem_limite,
            "item": None,
            "item_rejeitado": melhor_item,
            "acima_do_limite": True,
        }

    data_item = str(melhor_item.get("data") or data_iso)
    data_item_legivel = _formatar_data_com_semana_pt(data_item)
    detalhe_deslocamento = _detalhar_deslocamento_por_clinicas(
        clinica_destino=melhor_item.get("clinica_destino") or clinica_destino_nome,
        clinica_anterior=melhor_item.get("clinica_anterior"),
        clinica_posterior=melhor_item.get("clinica_posterior"),
        duracao_anterior_min=melhor_item.get("duracao_deslocamento_anterior_min"),
        duracao_posterior_min=melhor_item.get("duracao_deslocamento_proximo_min"),
        total_min=melhor_tempo,
        ha_agendamento_anterior=bool(melhor_item.get("ha_agendamento_anterior")),
        ha_agendamento_posterior=bool(melhor_item.get("ha_agendamento_posterior")),
        trecho_anterior_desconsiderado=bool(
            melhor_item.get("trecho_anterior_desconsiderado_ancora_adjacente")
        ),
        trecho_posterior_desconsiderado=bool(
            melhor_item.get("trecho_proximo_desconsiderado_ancora_adjacente")
        ),
        duracao_anterior_real_min=melhor_item.get("duracao_deslocamento_anterior_real_min"),
        duracao_posterior_real_min=melhor_item.get("duracao_deslocamento_proximo_real_min"),
    )
    if _nome_clinica_legivel(melhor_item.get("clinica")) == _nome_clinica_legivel(destino_operacional_nome):
        mensagem = (
            f"Encontramos horario livre na data {data_item_legivel} as {melhor_item['inicio']} "
            f"no destino {_nome_clinica_legivel(melhor_item.get('clinica_destino') or destino_operacional_nome)}. "
            f"{detalhe_deslocamento} "
            "Sugira esse horario para o cliente e confirme a disponibilidade."
        )
    else:
        mensagem = (
            f"Encontramos horario livre na data {data_item_legivel} as {melhor_item['inicio']} "
            f"proximo ao atendimento em {_nome_clinica_legivel(melhor_item.get('clinica'))}. "
            f"{detalhe_deslocamento} "
            "Sugira esse horario para o cliente e confirme a disponibilidade."
        )
    if politica_oferta.get("distante_base") and politica_oferta.get("baixa_frequencia"):
        dias_txt = ", ".join([f"D+{int(dia)}" for dia in politica_oferta.get("dias_preferenciais", [])])
        if dias_txt:
            mensagem = (
                f"{mensagem} Politica recomendada para este destino: priorizar {dias_txt} "
                "quando nao houver atendimento proximo em D+2."
            )
    if datas_preferenciais and not bool(melhor_item.get("data_preferencial")):
        mensagem = (
            f"{mensagem} Observacao: o horario sugerido ficou fora das datas preferenciais "
            f"({', '.join(datas_preferenciais)})."
        )
    return {
        "ok": True,
        "data": data_iso,
        "clinica_id": payload.clinica_id,
        "tutor_id": payload.tutor_id,
        "origem_atendimento": origem_atendimento,
        "destino_operacional": destino_operacional_nome,
        "sugerir": True,
        "limite_minutos": limite_minutos,
        "itens_ignorados_janela": itens_ignorados_janela,
        "politica_oferta": {
            **politica_oferta,
            "data_contato": data_contato_iso,
            "datas_preferenciais": datas_preferenciais,
        },
        "mensagem": mensagem,
        "item": melhor_item,
    }


@router.post("/assistente/ofertas")
def orquestrar_ofertas_assistente(
    payload: AssistenteOfertaPayload,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Orquestra politica de oferta + sugestao de proximidade + panorama de horarios em resposta unica."""
    origem_atendimento = _normalizar_origem_atendimento(payload.origem_atendimento)
    data_referencia = _extract_date_filter(payload.data) if payload.data else datetime.now(LOCAL_TZ).date().isoformat()
    if not data_referencia:
        raise HTTPException(status_code=422, detail="Data invalida. Use o formato YYYY-MM-DD.")
    try:
        data_referencia_ref = datetime.strptime(data_referencia, "%Y-%m-%d").date()
    except ValueError:
        data_referencia_ref = datetime.now(LOCAL_TZ).date()
    data_contato = (
        _extract_date_filter(payload.data_contato)
        if payload.data_contato
        else datetime.now(LOCAL_TZ).date().isoformat()
    )
    if not data_contato:
        data_contato = datetime.now(LOCAL_TZ).date().isoformat()

    resposta_proximidade = sugerir_agendamento_proximo(
        payload=SugestaoProximidadePayload(
            preferencia=payload.preferencia,
            origem_atendimento=origem_atendimento,
            clinica_id=payload.clinica_id,
            tutor_id=payload.tutor_id,
            data=data_referencia,
            data_contato=data_contato,
            servico_id=payload.servico_id,
            duracao_minutos=payload.duracao_minutos,
            intervalo_minutos=payload.intervalo_minutos,
            limite_sugestoes_operacionais=payload.limite,
            perfil_deslocamento=payload.perfil_deslocamento,
            limite_minutos=payload.limite_minutos,
            ignorar_agendamento_id=payload.ignorar_agendamento_id,
            incluir_mesma_clinica=payload.incluir_mesma_clinica,
            janela_dias_proximidade=payload.janela_dias_proximidade,
        ),
        db=db,
        current_user=current_user,
    )

    politica_oferta = (
        resposta_proximidade.get("politica_oferta")
        if isinstance(resposta_proximidade, dict) and isinstance(resposta_proximidade.get("politica_oferta"), dict)
        else {}
    )
    data_proximidade = (
        str(((resposta_proximidade or {}).get("item") or {}).get("data") or "").strip()
        if isinstance(resposta_proximidade, dict)
        else ""
    )
    datas_preferenciais = [
        str(item).strip()
        for item in (politica_oferta.get("datas_preferenciais") or [])
        if isinstance(item, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", item.strip())
    ]
    politica_distante_baixa = bool(politica_oferta.get("distante_base")) and bool(politica_oferta.get("baixa_frequencia"))
    sugestao_proximidade_aderente = bool((resposta_proximidade or {}).get("sugerir")) and bool(data_proximidade)

    data_base = data_referencia
    origem_data_automatica = "manual"
    candidatos_data_base: list[tuple[str, str]] = []
    datas_tentadas_panorama: list[str] = []

    def _adicionar_candidato_data(data_candidata: Optional[str], origem: str) -> None:
        data_txt = str(data_candidata or "").strip()
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", data_txt):
            return
        if payload.preferencia and not payload.preferencia.permite_data(data_txt):
            return
        if any(data_txt == data_existente for data_existente, _ in candidatos_data_base):
            return
        candidatos_data_base.append((data_txt, origem))

    periodo_explicito = bool(payload.preferencia and payload.preferencia.data_inicio)
    if periodo_explicito:
        cursor_preferencia = date.fromisoformat(payload.preferencia.data_inicio)
        fim_preferencia = date.fromisoformat(payload.preferencia.data_fim)
        while cursor_preferencia <= fim_preferencia:
            _adicionar_candidato_data(cursor_preferencia.isoformat(), "preferencia")
            cursor_preferencia += timedelta(days=1)
    elif politica_distante_baixa and datas_preferenciais:
        if sugestao_proximidade_aderente:
            _adicionar_candidato_data(data_proximidade, "proximidade")
        for data_preferencial in datas_preferenciais:
            _adicionar_candidato_data(data_preferencial, "politica")
        _adicionar_candidato_data(data_referencia, "manual")
    elif sugestao_proximidade_aderente:
        _adicionar_candidato_data(data_proximidade, "proximidade")
        _adicionar_candidato_data(data_referencia, "manual")
    else:
        _adicionar_candidato_data(data_referencia, "manual")

    if not candidatos_data_base:
        _adicionar_candidato_data(data_referencia, "manual")

    resposta_panorama = {"ok": True, "items": [], "motivo": "", "itens_ignorados_janela": 0}
    panoramas_consultados: list[dict[str, Any]] = []
    cache_panorama_por_data: dict[str, dict[str, Any]] = {}
    limite_total = max(1, min(50, int(payload.limite)))

    def _consultar_panorama_data(data_candidata: str, origem_candidata: str) -> dict[str, Any]:
        nonlocal resposta_panorama
        if data_candidata in cache_panorama_por_data:
            return cache_panorama_por_data[data_candidata]

        resposta_tentativa = sugerir_horarios_agenda(
            payload=SugestaoHorarioPayload(
                preferencia=payload.preferencia,
                data=data_candidata,
                origem_atendimento=origem_atendimento,
                clinica_id=payload.clinica_id,
                tutor_id=payload.tutor_id,
                servico_id=payload.servico_id,
                duracao_minutos=payload.duracao_minutos,
                intervalo_minutos=payload.intervalo_minutos,
                limite=payload.limite,
                perfil_deslocamento=payload.perfil_deslocamento,
                ignorar_agendamento_id=payload.ignorar_agendamento_id,
            ),
            db=db,
            current_user=current_user,
        )
        datas_tentadas_panorama.append(data_candidata)
        resposta_panorama = resposta_tentativa if isinstance(resposta_tentativa, dict) else resposta_panorama
        categoria = _classificar_panorama_data_assistente(resposta_panorama)
        registro = {
            "data": data_candidata,
            "origem": origem_candidata,
            "categoria": categoria,
            "resposta": resposta_panorama,
            "items_hierarquia": _selecionar_items_hierarquia_data_assistente(
                resposta_panorama,
                categoria=categoria,
            ),
        }
        cache_panorama_por_data[data_candidata] = registro
        panoramas_consultados.append(registro)
        return registro

    def _selecionar_datas_hierarquia() -> list[dict[str, Any]]:
        selecoes: list[dict[str, Any]] = []
        datas_escolhidas: set[str] = set()

        def _adicionar_registros(categoria_alvo: str, limite_categoria: int) -> None:
            if limite_categoria <= 0:
                return
            adicionados = 0
            for registro in panoramas_consultados:
                if registro.get("categoria") != categoria_alvo:
                    continue
                data_registro = str(registro.get("data") or "").strip()
                if not data_registro or data_registro in datas_escolhidas:
                    continue
                items_hierarquia = registro.get("items_hierarquia")
                if not isinstance(items_hierarquia, list) or not items_hierarquia:
                    continue
                selecoes.append(registro)
                datas_escolhidas.add(data_registro)
                adicionados += 1
                if adicionados >= limite_categoria or len(selecoes) >= ASSISTENTE_HIERARQUIA_MAX_DATAS:
                    break

        possui_data_vazia_disponivel = any(
            registro.get("categoria") == "data_vazia"
            and isinstance(registro.get("items_hierarquia"), list)
            and bool(registro.get("items_hierarquia"))
            for registro in panoramas_consultados
        )

        _adicionar_registros("ancora", 2)
        vagas_restantes = max(0, ASSISTENTE_HIERARQUIA_MAX_DATAS - len(selecoes))
        reserva_data_vazia = 1 if possui_data_vazia_disponivel and vagas_restantes > 0 else 0
        limite_operacional = max(0, vagas_restantes - reserva_data_vazia)
        if limite_operacional > 0:
            _adicionar_registros("operacional", limite_operacional)
        _adicionar_registros("data_vazia", 1)
        if len(selecoes) < ASSISTENTE_HIERARQUIA_MAX_DATAS:
            _adicionar_registros("operacional", ASSISTENTE_HIERARQUIA_MAX_DATAS)
        return selecoes[:ASSISTENTE_HIERARQUIA_MAX_DATAS]

    for data_candidata, origem_candidata in candidatos_data_base:
        _consultar_panorama_data(data_candidata, origem_candidata)

    selecoes_hierarquia = _selecionar_datas_hierarquia()
    hoje_local_ref = datetime.now(LOCAL_TZ).date()
    datas_tentadas_set = set(datas_tentadas_panorama)
    if not periodo_explicito and data_referencia_ref >= hoje_local_ref:
        datas_candidatas_ref: list[date] = []
        for data_candidata, _origem in candidatos_data_base:
            try:
                datas_candidatas_ref.append(datetime.strptime(data_candidata, "%Y-%m-%d").date())
            except ValueError:
                continue

        data_cursor = max(datas_candidatas_ref) if datas_candidatas_ref else data_referencia_ref
        data_inicio_intervalo = min(datas_candidatas_ref) if datas_candidatas_ref else data_referencia_ref
        if data_inicio_intervalo < data_cursor:
            data_intervalo = data_inicio_intervalo
            while data_intervalo <= data_cursor:
                data_intervalo_iso = data_intervalo.isoformat()
                if data_intervalo_iso not in datas_tentadas_set:
                    _consultar_panorama_data(data_intervalo_iso, "intervalo_candidatos")
                    datas_tentadas_set.add(data_intervalo_iso)
                data_intervalo = data_intervalo + timedelta(days=1)
            selecoes_hierarquia = _selecionar_datas_hierarquia()

        dias_busca_progressiva = 0

        while len(selecoes_hierarquia) < 2 and dias_busca_progressiva < ASSISTENTE_BUSCA_PROGRESSIVA_MAX_DIAS:
            dias_busca_progressiva += 1
            data_cursor = data_cursor + timedelta(days=1)
            data_cursor_iso = data_cursor.isoformat()
            if data_cursor_iso in datas_tentadas_set:
                continue

            _consultar_panorama_data(data_cursor_iso, "progressao_dias")
            datas_tentadas_set.add(data_cursor_iso)
            selecoes_hierarquia = _selecionar_datas_hierarquia()

        possui_data_vazia = any(item.get("categoria") == "data_vazia" for item in selecoes_hierarquia)
        dias_busca_vazio = 0
        while (
            len(selecoes_hierarquia) < ASSISTENTE_HIERARQUIA_MAX_DATAS
            and not possui_data_vazia
            and dias_busca_progressiva < ASSISTENTE_BUSCA_PROGRESSIVA_MAX_DIAS
            and dias_busca_vazio < ASSISTENTE_BUSCA_DIA_VAZIO_EXTRA_MAX_DIAS
        ):
            dias_busca_progressiva += 1
            dias_busca_vazio += 1
            data_cursor = data_cursor + timedelta(days=1)
            data_cursor_iso = data_cursor.isoformat()
            if data_cursor_iso in datas_tentadas_set:
                continue

            _consultar_panorama_data(data_cursor_iso, "progressao_dias")
            datas_tentadas_set.add(data_cursor_iso)
            selecoes_hierarquia = _selecionar_datas_hierarquia()
            possui_data_vazia = any(item.get("categoria") == "data_vazia" for item in selecoes_hierarquia)

    if selecoes_hierarquia:
        data_base = str(selecoes_hierarquia[0].get("data") or data_referencia)
        origem_data_automatica = str(selecoes_hierarquia[0].get("origem") or "manual")

    if origem_data_automatica == "proximidade":
        prefixo_mensagem = "Sugestoes calculadas automaticamente com base no agendamento proximo."
    elif origem_data_automatica == "politica":
        prefixo_mensagem = "Sugestoes calculadas automaticamente conforme politica de oferta (rota/frequencia)."
    elif origem_data_automatica == "progressao_dias":
        prefixo_mensagem = "Sugestoes calculadas automaticamente apos busca progressiva nos dias seguintes."
    else:
        prefixo_mensagem = ""

    items_panorama: list[dict[str, Any]] = []
    datas_hierarquizadas: list[dict[str, Any]] = []
    resposta_panorama_base = resposta_panorama
    itens_ignorados_janela_total = 0
    if selecoes_hierarquia:
        resposta_panorama_base = (
            selecoes_hierarquia[0].get("resposta")
            if isinstance(selecoes_hierarquia[0].get("resposta"), dict)
            else resposta_panorama
        )
        restante_total = limite_total
        for ordem, registro in enumerate(selecoes_hierarquia, start=1):
            if restante_total <= 0:
                break
            resposta_registro = registro.get("resposta")
            if isinstance(resposta_registro, dict):
                itens_ignorados_janela_total += int(resposta_registro.get("itens_ignorados_janela") or 0)
            items_hierarquia = registro.get("items_hierarquia")
            items_lista = items_hierarquia if isinstance(items_hierarquia, list) else []
            limite_data = min(ASSISTENTE_HIERARQUIA_MAX_ITENS_POR_DATA, restante_total)
            selecionados_data: list[dict[str, Any]] = []
            for item in items_lista[:limite_data]:
                if not isinstance(item, dict):
                    continue
                item_saida = dict(item)
                item_saida["hierarquia_data_ordem"] = ordem
                item_saida["hierarquia_data_categoria"] = registro.get("categoria")
                item_saida["hierarquia_data_origem"] = registro.get("origem")
                item_saida["hierarquia_data"] = registro.get("data")
                items_panorama.append(item_saida)
                selecionados_data.append(item_saida)
                restante_total -= 1
                if restante_total <= 0:
                    break
            datas_hierarquizadas.append(
                {
                    "ordem": ordem,
                    "data": registro.get("data"),
                    "categoria": registro.get("categoria"),
                    "origem": registro.get("origem"),
                    "total_itens": len(selecionados_data),
                }
            )

        resposta_panorama = dict(resposta_panorama_base) if isinstance(resposta_panorama_base, dict) else {"ok": True}
        resposta_panorama["data"] = data_base
        resposta_panorama["items"] = items_panorama
        resposta_panorama["total_encontrados"] = len(items_panorama)
        resposta_panorama["itens_ignorados_janela"] = itens_ignorados_janela_total
        resposta_panorama["datas_hierarquizadas"] = datas_hierarquizadas
    else:
        items_panorama = resposta_panorama.get("items") if isinstance(resposta_panorama, dict) else []
        items_panorama = items_panorama if isinstance(items_panorama, list) else []
        if isinstance(resposta_panorama, dict):
            resposta_panorama["datas_hierarquizadas"] = []

    motivo_panorama = str((resposta_panorama or {}).get("motivo") or "").strip() if isinstance(resposta_panorama, dict) else ""
    if not items_panorama and payload.preferencia is not None:
        mensagem_panorama = "Nenhum horario encontrado dentro da preferencia informada. Ajuste a preferencia para consultar outras opcoes."
    elif not items_panorama:
        mensagem_panorama = f"{prefixo_mensagem} {motivo_panorama or 'Nenhum horario operacional encontrado para essa data.'}".strip()
    elif len(datas_hierarquizadas) > 1:
        descricoes_hierarquia = []
        for item in datas_hierarquizadas:
            data_item = str(item.get("data") or "").strip()
            categoria_item = str(item.get("categoria") or "").strip()
            if categoria_item == "ancora":
                sufixo = "ancora da mesma clinica"
            elif categoria_item == "data_vazia":
                sufixo = "agenda vazia"
            else:
                sufixo = "agenda operacional"
            descricoes_hierarquia.append(f"{int(item.get('ordem') or 0)}) {data_item} - {sufixo}")
        mensagem_panorama = f"{prefixo_mensagem} Panorama priorizado em {len(datas_hierarquizadas)} datas: {'; '.join(descricoes_hierarquia)}.".strip()
    elif all(not item.get("anterior") and not item.get("proximo") for item in items_panorama if isinstance(item, dict)):
        mensagem_panorama = f"{prefixo_mensagem} Nao ha agendamentos vizinhos nesta data; por isso o deslocamento pode aparecer como 0 min.".strip()
    else:
        mensagem_panorama = prefixo_mensagem.strip()

    _registrar_evento_funil_assistente(
        current_user=current_user,
        request=request,
        evento="ASSISTENTE_AGENDA_OFERTA_GERADA",
        detalhes={
            "clinica_id": payload.clinica_id,
            "servico_id": payload.servico_id,
            "perfil_usuario": "admin" if _usuario_tem_papel(current_user, "admin") else "nao_admin",
            "data_referencia": data_referencia,
            "data_base": data_base,
            "origem_data_automatica": origem_data_automatica,
            "datas_tentadas_panorama": datas_tentadas_panorama,
            "datas_hierarquizadas": datas_hierarquizadas,
            "total_sugestoes": len(items_panorama),
            "houve_sugestao_proximidade": bool((resposta_proximidade or {}).get("item")),
        },
    )

    return {
        "ok": True,
        "clinica_id": payload.clinica_id,
        "data_referencia": data_referencia,
        "data_contato": data_contato,
        "data_base": data_base,
        "origem_data_automatica": origem_data_automatica,
        "politica_oferta": politica_oferta,
        "sugestao_proximidade": resposta_proximidade,
        "panorama_ofertas": resposta_panorama,
        "mensagem_panorama": mensagem_panorama,
    }


@router.get("/assistente/metricas")
def obter_metricas_funil_assistente(
    data_inicio: Optional[str] = None,
    data_fim: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Consolida metricas do funil do assistente por etapa, perfil e clinica."""
    if not _usuario_tem_papel(current_user, "admin"):
        raise HTTPException(status_code=403, detail="Apenas administradores podem consultar metricas do assistente.")

    data_inicio_iso = _extract_date_filter(data_inicio) if data_inicio else None
    data_fim_iso = _extract_date_filter(data_fim) if data_fim else None
    if data_inicio and not data_inicio_iso:
        raise HTTPException(status_code=422, detail="Data inicial invalida. Use YYYY-MM-DD.")
    if data_fim and not data_fim_iso:
        raise HTTPException(status_code=422, detail="Data final invalida. Use YYYY-MM-DD.")

    acoes_funil = {
        "ASSISTENTE_AGENDA_OFERTA_GERADA": "oferta_gerada",
        "ASSISTENTE_AGENDA_ACEITE": "aceite",
        "ASSISTENTE_AGENDA_SEM_OPCAO": "sem_opcao",
        "ASSISTENTE_AGENDA_SOLICITACAO_EXCECAO": "solicitacao_excecao",
        "ASSISTENTE_AGENDA_EXCECAO_CONCEDIDA": "excecao_concedida",
        "ASSISTENTE_AGENDA_ENCERRADO_SEM_AGENDAMENTO": "encerramento",
    }

    query = db.query(AuditoriaEvento).filter(
        AuditoriaEvento.modulo == "agenda",
        AuditoriaEvento.entidade == "assistente_agendamento",
        AuditoriaEvento.acao.in_(list(acoes_funil.keys())),
    )
    if data_inicio_iso:
        query = query.filter(func.date(AuditoriaEvento.created_at) >= data_inicio_iso)
    if data_fim_iso:
        query = query.filter(func.date(AuditoriaEvento.created_at) <= data_fim_iso)

    eventos = query.order_by(AuditoriaEvento.created_at.asc(), AuditoriaEvento.id.asc()).all()

    totais_por_etapa: dict[str, int] = {etapa: 0 for etapa in acoes_funil.values()}
    por_perfil: dict[str, dict[str, int]] = {}
    por_clinica: dict[str, dict[str, Any]] = {}
    serie_diaria: dict[str, dict[str, int]] = {}

    for row in eventos:
        etapa = acoes_funil.get(str(row.acao or "").strip())
        if not etapa:
            continue
        detalhes = _parse_detalhes_auditoria(getattr(row, "detalhes_json", None))
        perfil = str(detalhes.get("perfil_usuario") or detalhes.get("perfil") or "nao_informado").strip() or "nao_informado"
        clinica_id_raw = detalhes.get("clinica_id")
        clinica_id = str(clinica_id_raw) if clinica_id_raw not in (None, "", 0, "0") else "nao_informada"
        clinica_nome = str(detalhes.get("clinica_nome") or "Nao informada")
        data_evento = _extrair_data_evento_local(getattr(row, "created_at", None)) or "sem_data"

        totais_por_etapa[etapa] = int(totais_por_etapa.get(etapa, 0)) + 1

        bucket_perfil = por_perfil.setdefault(perfil, {nome: 0 for nome in acoes_funil.values()})
        bucket_perfil[etapa] = int(bucket_perfil.get(etapa, 0)) + 1

        bucket_clinica = por_clinica.setdefault(
            clinica_id,
            {
                "clinica_id": None if clinica_id == "nao_informada" else clinica_id_raw,
                "clinica_nome": clinica_nome,
                "eventos": {nome: 0 for nome in acoes_funil.values()},
            },
        )
        bucket_clinica["eventos"][etapa] = int(bucket_clinica["eventos"].get(etapa, 0)) + 1

        bucket_dia = serie_diaria.setdefault(data_evento, {nome: 0 for nome in acoes_funil.values()})
        bucket_dia[etapa] = int(bucket_dia.get(etapa, 0)) + 1

    return {
        "ok": True,
        "periodo": {
            "data_inicio": data_inicio_iso,
            "data_fim": data_fim_iso,
        },
        "totais_por_etapa": totais_por_etapa,
        "por_perfil": por_perfil,
        "por_clinica": sorted(por_clinica.values(), key=lambda item: str(item.get("clinica_nome") or "")),
        "serie_diaria": [
            {"data": data_ref, "eventos": serie_diaria[data_ref]}
            for data_ref in sorted(serie_diaria.keys())
        ],
    }


@router.post("/assistente/encerramento")
def registrar_encerramento_assistente(
    payload: AssistenteEncerramentoPayload,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Registra desfechos estruturados do assistente guiado sem criar agendamento."""
    motivo = str(payload.motivo or "").strip()
    if len(motivo) < 5:
        raise HTTPException(status_code=422, detail="Motivo deve ter ao menos 5 caracteres.")

    def _parse_data_yyyy_mm_dd(raw_value: Optional[str], field_label: str) -> Optional[str]:
        raw = str(raw_value or "").strip()
        if not raw:
            return None
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
            raise HTTPException(
                status_code=422,
                detail=f"{field_label} invalida. Use o formato YYYY-MM-DD.",
            )
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date().isoformat()
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=f"{field_label} invalida. Use o formato YYYY-MM-DD.",
            )

    data_referencia = _parse_data_yyyy_mm_dd(payload.data_referencia, "Data de referencia")
    data_contato = _parse_data_yyyy_mm_dd(payload.data_contato, "Data de contato")
    contexto = payload.contexto if isinstance(payload.contexto, dict) else {}
    try:
        total_sugestoes = int(contexto.get("total_sugestoes", 0) or 0)
    except (TypeError, ValueError):
        total_sugestoes = 0
    if total_sugestoes < 1:
        raise HTTPException(
            status_code=422,
            detail="Para registrar recusa sem agendamento, e obrigatorio ter ao menos 1 oferta exibida.",
        )

    origem_atendimento = _normalizar_origem_atendimento(
        payload.origem_atendimento or (ORIGEM_ATENDIMENTO_DOMICILIAR if payload.tutor_id else ORIGEM_ATENDIMENTO_PADRAO)
    )
    if origem_atendimento == ORIGEM_ATENDIMENTO_DOMICILIAR:
        tutor = db.query(Tutor).filter(Tutor.id == int(payload.tutor_id or 0)).first() if payload.tutor_id else None
        clinica_nome = _rotulo_destino_operacional(
            _criar_destino_operacional_tutor(tutor, fallback_nome=_nome_tutor_por_id(db, payload.tutor_id))
        )
    else:
        clinica_nome = _nome_clinica_por_id(db, payload.clinica_id) if payload.clinica_id else "Nao informada"
    servico_nome = "Nao informado"
    if payload.servico_id:
        servico = db.query(Servico).filter(Servico.id == payload.servico_id).first()
        if servico and servico.nome:
            servico_nome = str(servico.nome).strip()

    eh_admin = bool(current_user.tem_papel("admin"))
    tipo = payload.tipo
    if tipo == "solicitacao_excecao":
        acao = "ASSISTENTE_AGENDA_SOLICITACAO_EXCECAO"
        descricao = (
            "Assistente de agenda sem oferta aderente: solicitacao de excecao registrada "
            f"({clinica_nome} | servico: {servico_nome})."
        )
        mensagem = "Solicitacao de excecao registrada com sucesso."
    else:
        acao = "ASSISTENTE_AGENDA_ENCERRADO_SEM_AGENDAMENTO"
        descricao = (
            "Assistente de agenda encerrado sem agendamento "
            f"({clinica_nome} | servico: {servico_nome})."
        )
        mensagem = "Encerramento sem agendamento registrado com sucesso."

    registrar_auditoria(
        current_user=current_user,
        modulo="agenda",
        entidade="assistente_agendamento",
        acao=acao,
        descricao=descricao,
        detalhes={
            "tipo": tipo,
            "motivo": motivo,
            "origem_atendimento": origem_atendimento,
            "clinica_id": payload.clinica_id,
            "clinica_nome": clinica_nome,
            "tutor_id": payload.tutor_id,
            "destino_operacional": clinica_nome,
            "servico_id": payload.servico_id,
            "servico_nome": servico_nome,
            "data_referencia": data_referencia,
            "data_contato": data_contato,
            "perfil_usuario": "admin" if eh_admin else "nao_admin",
            "contexto": contexto,
        },
        request=request,
    )
    _registrar_evento_funil_assistente(
        current_user=current_user,
        request=request,
        evento="ASSISTENTE_AGENDA_SEM_OPCAO",
        detalhes={
            "origem_atendimento": origem_atendimento,
            "clinica_id": payload.clinica_id,
            "tutor_id": payload.tutor_id,
            "destino_operacional": clinica_nome,
            "servico_id": payload.servico_id,
            "perfil_usuario": "admin" if eh_admin else "nao_admin",
            "tipo_desfecho": tipo,
            "motivo": motivo,
            "data_referencia": data_referencia,
            "data_contato": data_contato,
        },
    )

    return {
        "ok": True,
        "tipo": tipo,
        "mensagem": mensagem,
    }


@router.get("/{agendamento_id}", response_model=AgendamentoResponse)
def obter_agendamento(
    agendamento_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Obtem um agendamento especifico"""
    agendamento = db.query(Agendamento).filter(Agendamento.id == agendamento_id).first()
    if not agendamento:
        raise HTTPException(status_code=404, detail="Agendamento nao encontrado")
    related = _fetch_related_names(db, agendamento)
    return _serialize_agendamento(agendamento, **related)

@router.post("", response_model=AgendamentoResponse, status_code=status.HTTP_201_CREATED)
def criar_agendamento(
    agendamento: AgendamentoCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Cria novo agendamento"""
    _adquirir_lock_escrita_agenda(db)
    from app.services.whatsapp_bot_pedido_agenda import iniciar, vincular
    pedido, existente = iniciar(db, agendamento, current_user)
    if existente is not None:
        return _serialize_agendamento(existente, **_fetch_related_names(db, existente))

    confirmacao_sobreposicao = validar_pedido_sobreposicao(agendamento, current_user)
    override_conflito_deslocamento = bool(agendamento.confirmar_conflito_deslocamento)
    confirmou_slot_reserva_expirada = bool(
        getattr(agendamento, "confirmar_slot_reserva_expirada", False)
    )
    confirmar_agenda_fechada = bool(getattr(agendamento, "confirmar_agenda_fechada", False))
    excecao_operacional_concedida = bool(getattr(agendamento, "excecao_operacional_concedida", False))
    motivo_excecao_operacional = str(getattr(agendamento, "motivo_excecao_operacional", "") or "").strip()
    motivo_excecao_deslocamento = str(getattr(agendamento, "motivo_excecao_deslocamento", "") or "").strip()
    if override_conflito_deslocamento and not _usuario_tem_papel(current_user, "admin"):
        raise HTTPException(
            status_code=403,
            detail="Somente administradores podem confirmar excecao de conflito operacional.",
        )
    if confirmar_agenda_fechada and not _usuario_tem_papel(current_user, "admin"):
        raise HTTPException(
            status_code=403,
            detail="Somente administradores podem confirmar agendamento com a agenda fechada.",
        )
    if excecao_operacional_concedida and not _usuario_tem_papel(current_user, "admin"):
        raise HTTPException(
            status_code=403,
            detail="Somente administradores podem conceder excecao operacional da agenda.",
        )
    if excecao_operacional_concedida and not motivo_excecao_operacional:
        raise HTTPException(
            status_code=422,
            detail="Informe o motivo da excecao operacional concedida.",
        )

    now = datetime.now()
    db_agendamento = Agendamento(
        **agendamento.model_dump(
            exclude={
                "pedido_whatsapp_id", "pedido_whatsapp_versao", "pedido_whatsapp_divergencia_confirmada",
                "confirmar_sobreposicao", "escopo_sobreposicao_confirmado", "motivo_excecao_sobreposicao",
                "confirmar_conflito_deslocamento",
                "confirmar_slot_reserva_expirada",
                "confirmar_agenda_fechada",
                "excecao_operacional_concedida",
                "motivo_excecao_operacional",
                "motivo_excecao_deslocamento",
            }
        )
    )
    db_agendamento.status = _normalizar_status_agendamento(db_agendamento.status)
    if db_agendamento.status == "Reservado" and not db_agendamento.paciente_id:
        # Reservas podem existir antes da identificacao do paciente. Persista
        # NULL: o sentinela 0 viola a FK fk_agenda_paciente no PostgreSQL.
        db_agendamento.paciente_id = None
    db_agendamento.inicio = _coerce_datetime(db_agendamento.inicio)
    db_agendamento.fim = _coerce_datetime(db_agendamento.fim)
    db_agendamento.reserva_expira_em = _coerce_datetime(db_agendamento.reserva_expira_em)
    db_agendamento.criado_por_id = current_user.id
    db_agendamento.criado_por_nome = current_user.nome
    db_agendamento.criado_em = now
    db_agendamento.created_at = now
    db_agendamento.updated_at = now
    _validar_regras_origem_agendamento(db, db_agendamento, contexto="salvar o agendamento")

    _apply_service_duration_if_needed(db, db_agendamento, force_from_service=True)
    _validar_prazo_reserva(db_agendamento)
    motivo_agenda_fechada = _validar_agendamento_no_funcionamento(
        db,
        db_agendamento,
        permitir_excecao_agenda_fechada=confirmar_agenda_fechada,
    )
    if motivo_agenda_fechada:
        db_agendamento.excecao_agenda_fechada_escopo = _escopo_excecao_agenda_fechada(db_agendamento)
    reservas_expiradas_revisadas = _validar_slot_disponivel(
        db,
        db_agendamento,
        confirmar_slot_reserva_expirada=confirmou_slot_reserva_expirada,
        **confirmacao_sobreposicao,
    )
    bypass_deslocamento = _validar_deslocamento_agendamento(
        db,
        db_agendamento,
        confirmar_conflito_deslocamento=override_conflito_deslocamento,
    )
    if bypass_deslocamento and bypass_deslocamento.get("origem") == "confirmacao_admin":
        _conceder_excecao_deslocamento(
            db_agendamento,
            current_user=current_user,
            motivo=motivo_excecao_deslocamento or motivo_excecao_operacional,
        )
    _fill_data_hora_from_inicio(db_agendamento)
    related = _fetch_related_names(db, db_agendamento)
    _sync_denormalized_fields(db_agendamento, related)
    _validar_paciente_tutor_para_status(
        db,
        db_agendamento,
        status_destino=db_agendamento.status,
        related=related,
    )

    db.add(db_agendamento)
    vincular(db, pedido, db_agendamento, current_user)
    _commit_agenda_write(db)
    db.refresh(db_agendamento)
    contexto = _contexto_agendamento_auditoria(db_agendamento, related)

    registrar_auditoria(
        current_user=current_user,
        modulo="agenda",
        entidade="agendamento",
        entidade_id=db_agendamento.id,
        acao="AGENDAMENTO_CRIADO",
        descricao=f"Agendamento criado - {_descricao_contexto_agendamento(contexto)}",
        detalhes={
            "paciente_id": db_agendamento.paciente_id,
            "tutor_id": getattr(db_agendamento, "tutor_id", None),
            "clinica_id": db_agendamento.clinica_id,
            "servico_id": db_agendamento.servico_id,
            "status": db_agendamento.status,
            "origem_atendimento": _normalizar_origem_atendimento(getattr(db_agendamento, "origem_atendimento", None)),
            "excecao_sobreposicao": ler_concessao_sobreposicao(db_agendamento) or None,
            "override_conflito_deslocamento": override_conflito_deslocamento,
            "confirmou_revisao_slot_reserva_expirada": bool(reservas_expiradas_revisadas),
            "reservas_expiradas_revisadas_ids": [
                item.id for item in reservas_expiradas_revisadas
            ],
            "confirmacao_agenda_fechada": bool(motivo_agenda_fechada),
            "motivo_agenda_fechada": motivo_agenda_fechada,
            "contexto_agendamento": contexto,
        },
        request=request,
    )
    if motivo_agenda_fechada:
        registrar_auditoria(
            current_user=current_user,
            modulo="agenda",
            entidade="agendamento",
            entidade_id=db_agendamento.id,
            acao="AGENDAMENTO_AGENDA_FECHADA_CONFIRMADO",
            descricao=(
                "Administrador confirmou agendamento fora do funcionamento da agenda - "
                f"{_descricao_contexto_agendamento(contexto)}"
            ),
            detalhes={
                "motivo_validacao": motivo_agenda_fechada,
                "confirmado_por_admin": True,
                "agendamento_id": db_agendamento.id,
                "contexto_agendamento": contexto,
            },
            request=request,
        )
    observacoes_agendamento = str(db_agendamento.observacoes or "")
    if "[Assistente agenda] sugestao aceita" in observacoes_agendamento:
        _registrar_evento_funil_assistente(
            current_user=current_user,
            request=request,
            evento="ASSISTENTE_AGENDA_ACEITE",
            detalhes={
                "agendamento_id": db_agendamento.id,
                "clinica_id": db_agendamento.clinica_id,
                "servico_id": db_agendamento.servico_id,
                "perfil_usuario": "admin" if _usuario_tem_papel(current_user, "admin") else "nao_admin",
            },
        )
    if excecao_operacional_concedida:
        _registrar_auditoria_excecao_operacional_concedida(
            db=db,
            current_user=current_user,
            request=request,
            agendamento=db_agendamento,
            related=related,
            motivo=motivo_excecao_operacional,
        )
    if bypass_deslocamento:
        _registrar_auditoria_excecao_deslocamento(
            db=db,
            current_user=current_user,
            request=request,
            agendamento=db_agendamento,
            bypass=bypass_deslocamento,
            acao_operacional="criar_agendamento",
        )

    _notificar_agenda_update(
        db=db,
        action="created",
        agendamento_id=db_agendamento.id,
        data=_montar_payload_realtime(
            agendamento=db_agendamento,
            related=related,
            usuario=current_user,
        ),
    )

    return _serialize_agendamento(db_agendamento, **related)

@router.put("/{agendamento_id}", response_model=AgendamentoResponse)
def atualizar_agendamento(
    agendamento_id: int,
    agendamento: AgendamentoUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Atualiza agendamento"""
    _adquirir_lock_escrita_agenda(db)
    _expirar_reservas_vencidas(db)

    db_agendamento = db.query(Agendamento).filter(Agendamento.id == agendamento_id).first()
    if not db_agendamento:
        raise HTTPException(status_code=404, detail="Agendamento nao encontrado")

    dados_anteriores = {
        "inicio": str(db_agendamento.inicio) if db_agendamento.inicio else None,
        "fim": str(db_agendamento.fim) if db_agendamento.fim else None,
        "status": db_agendamento.status,
        "paciente_id": db_agendamento.paciente_id,
        "tutor_id": getattr(db_agendamento, "tutor_id", None),
        "clinica_id": db_agendamento.clinica_id,
        "servico_id": db_agendamento.servico_id,
        "origem_atendimento": _normalizar_origem_atendimento(getattr(db_agendamento, "origem_atendimento", None)),
    }

    inicio_original = _coerce_datetime(db_agendamento.inicio)
    fim_original = _coerce_datetime(db_agendamento.fim)
    servico_original = db_agendamento.servico_id
    clinica_original = db_agendamento.clinica_id
    tutor_original = getattr(db_agendamento, "tutor_id", None)
    origem_original = _normalizar_origem_atendimento(getattr(db_agendamento, "origem_atendimento", None))
    status_anterior = str(db_agendamento.status or "").strip() or "Agendado"

    confirmacao_sobreposicao = validar_pedido_sobreposicao(agendamento, current_user)
    override_conflito_deslocamento = bool(agendamento.confirmar_conflito_deslocamento)
    confirmou_slot_reserva_expirada = bool(
        getattr(agendamento, "confirmar_slot_reserva_expirada", False)
    )
    confirmar_agenda_fechada = bool(getattr(agendamento, "confirmar_agenda_fechada", False))
    if confirmar_agenda_fechada and not _usuario_tem_papel(current_user, "admin"):
        raise HTTPException(status_code=403, detail="Somente administradores podem confirmar agendamento com a agenda fechada.")
    excecao_operacional_concedida = bool(getattr(agendamento, "excecao_operacional_concedida", False))
    motivo_excecao_operacional = str(getattr(agendamento, "motivo_excecao_operacional", "") or "").strip()
    motivo_excecao_deslocamento = str(getattr(agendamento, "motivo_excecao_deslocamento", "") or "").strip()
    # O nome do campo diz "hoje" por compatibilidade: e contrato com o frontend e
    # renomear quebraria cliente antigo. O criterio que ele confirma e
    # "atendimento ja iniciado", nao "agendado para hoje" -- ver
    # `alterando_servico_ja_iniciado` abaixo.
    confirmar_alteracao_servico_hoje = bool(
        getattr(agendamento, "confirmar_alteracao_servico_hoje", False)
    )
    if override_conflito_deslocamento and not _usuario_tem_papel(current_user, "admin"):
        raise HTTPException(
            status_code=403,
            detail="Somente administradores podem confirmar excecao de conflito operacional.",
        )
    if excecao_operacional_concedida and not _usuario_tem_papel(current_user, "admin"):
        raise HTTPException(
            status_code=403,
            detail="Somente administradores podem conceder excecao operacional da agenda.",
        )
    if excecao_operacional_concedida and not motivo_excecao_operacional:
        raise HTTPException(
            status_code=422,
            detail="Informe o motivo da excecao operacional concedida.",
        )

    update_data = agendamento.model_dump(exclude_unset=True)
    for campo in ("confirmar_sobreposicao", "escopo_sobreposicao_confirmado", "motivo_excecao_sobreposicao"):
        update_data.pop(campo, None)
    update_data.pop("confirmar_conflito_deslocamento", None)
    update_data.pop("confirmar_slot_reserva_expirada", None)
    update_data.pop("confirmar_agenda_fechada", None)
    update_data.pop("excecao_operacional_concedida", None)
    update_data.pop("motivo_excecao_operacional", None)
    update_data.pop("motivo_excecao_deslocamento", None)
    update_data.pop("confirmar_alteracao_servico_hoje", None)

    novo_servico_id = update_data.get("servico_id", servico_original)
    alterando_servico = novo_servico_id != servico_original
    inicio_original_local = _to_local_naive(inicio_original)
    agora_local = datetime.now(LOCAL_TZ).replace(tzinfo=None)
    atendimento_ja_iniciado = bool(
        inicio_original_local is not None and inicio_original_local <= agora_local
    )
    alterando_servico_ja_iniciado = bool(alterando_servico and atendimento_ja_iniciado)
    if alterando_servico_ja_iniciado:
        if not _usuario_tem_papel(current_user, "admin"):
            raise HTTPException(
                status_code=403,
                detail="Somente administradores podem alterar o servico de um atendimento ja iniciado.",
            )
        if not confirmar_alteracao_servico_hoje:
            raise HTTPException(
                status_code=409,
                detail={
                    "codigo": "CONFIRMACAO_ALTERACAO_SERVICO_HOJE",
                    "mensagem": (
                        "Confirme a alteracao administrativa do servico deste atendimento ja iniciado."
                    ),
                    "confirmavel": True,
                },
            )

    baseline_regional = None
    altera_rota = any(campo in update_data for campo in (
        "inicio", "fim", "servico_id", "clinica_id", "origem_atendimento", "tutor_id",
    )) or (
        status_anterior in {"Cancelado", "Expirado"}
        and update_data.get("status", status_anterior) not in {"Cancelado", "Expirado"}
    )
    if altera_rota:
        baseline_regional = _capturar_baseline_regional_agendamento(
            db, update_data.get("inicio", inicio_original),
        )

    for field, value in update_data.items():
        setattr(db_agendamento, field, value)

    if "inicio" in update_data:
        db_agendamento.inicio = _coerce_datetime(db_agendamento.inicio)
        # A validacao de slot usa data/hora para compatibilidade com registros
        # legados. Sincronize esses campos antes de validar uma remarcacao.
        _fill_data_hora_from_inicio(db_agendamento)
    if "fim" in update_data:
        db_agendamento.fim = _coerce_datetime(db_agendamento.fim)
    if "reserva_expira_em" in update_data:
        db_agendamento.reserva_expira_em = _coerce_datetime(db_agendamento.reserva_expira_em)
    if "status" in update_data:
        db_agendamento.status = _normalizar_status_agendamento(db_agendamento.status, fallback=status_anterior)
    else:
        db_agendamento.status = status_anterior
    reativando_expirado = _exigir_confirmacao_reativacao_reserva_expirada(
        status_anterior=status_anterior,
        status_novo=db_agendamento.status,
        confirmado=confirmou_slot_reserva_expirada,
    )
    if db_agendamento.status == "Reservado" and not db_agendamento.paciente_id:
        # Tambem remove o sentinela legado 0 ao editar uma reserva sem paciente.
        db_agendamento.paciente_id = None
    _validar_regras_origem_agendamento(db, db_agendamento, contexto="salvar o agendamento")
    _validar_prazo_reserva(db_agendamento)

    origem_atual = _normalizar_origem_atendimento(getattr(db_agendamento, "origem_atendimento", None))
    campos_horario = (
        "inicio" in update_data or "fim" in update_data or "servico_id" in update_data
        or "clinica_id" in update_data or "origem_atendimento" in update_data
        or (origem_atual == ORIGEM_ATENDIMENTO_DOMICILIAR and "tutor_id" in update_data)
    )
    reativando_cancelado = status_anterior == "Cancelado" and db_agendamento.status != "Cancelado"
    reativando_inativo = reativando_cancelado or reativando_expirado
    inicio_atual_antes_duracao = _to_local_naive(_coerce_datetime(db_agendamento.inicio))
    preservar_intervalo_servico_iniciado = bool(
        alterando_servico_ja_iniciado
        and inicio_original_local is not None
        and inicio_atual_antes_duracao == inicio_original_local
        and inicio_original_local <= datetime.now(LOCAL_TZ).replace(tzinfo=None)
    )
    reservas_expiradas_revisadas: list[Agendamento] = []
    bypass_deslocamento: Optional[dict[str, str]] = None
    slot_ja_validado = False
    if campos_horario:
        if preservar_intervalo_servico_iniciado:
            db_agendamento.inicio = inicio_original
            db_agendamento.fim = fim_original
            _fill_data_hora_from_inicio(db_agendamento)
        else:
            _apply_service_duration_if_needed(db, db_agendamento)

        inicio_atual = _coerce_datetime(db_agendamento.inicio)
        fim_atual = _coerce_datetime(db_agendamento.fim)
        servico_atual = db_agendamento.servico_id
        clinica_atual = db_agendamento.clinica_id

        alterou_horario = False
        if "inicio" in update_data:
            alterou_horario = alterou_horario or (_to_local_naive(inicio_original) != _to_local_naive(inicio_atual))
        if "fim" in update_data:
            alterou_horario = alterou_horario or (_to_local_naive(fim_original) != _to_local_naive(fim_atual))
        if "servico_id" in update_data:
            alterou_horario = alterou_horario or (
                servico_original != servico_atual
                and not preservar_intervalo_servico_iniciado
            )
        if "clinica_id" in update_data:
            alterou_horario = alterou_horario or (clinica_original != clinica_atual)
        if "origem_atendimento" in update_data:
            alterou_horario = alterou_horario or (origem_original != origem_atual)
        if origem_atual == ORIGEM_ATENDIMENTO_DOMICILIAR and "tutor_id" in update_data:
            alterou_horario = alterou_horario or (tutor_original != getattr(db_agendamento, "tutor_id", None))

        if alterou_horario or reativando_inativo:
            motivo_agenda_fechada = _validar_agendamento_no_funcionamento(
                db, db_agendamento,
                permitir_excecao_agenda_fechada=(confirmar_agenda_fechada or _excecao_agenda_fechada_ativa(db_agendamento)),
            )
            if motivo_agenda_fechada and confirmar_agenda_fechada:
                db_agendamento.excecao_agenda_fechada_escopo = _escopo_excecao_agenda_fechada(db_agendamento)
            reservas_expiradas_revisadas = _validar_slot_disponivel(
                db,
                db_agendamento,
                agendamento_id_excluir=agendamento_id,
                confirmar_slot_reserva_expirada=confirmou_slot_reserva_expirada,
                **confirmacao_sobreposicao,
            )
            slot_ja_validado = True
            bypass_deslocamento = _validar_deslocamento_agendamento(
                db,
                db_agendamento,
                agendamento_id_excluir=agendamento_id,
                confirmar_conflito_deslocamento=override_conflito_deslocamento,
                baseline_regional=baseline_regional,
                validar_primeira_saida=not (
                    inicio_original_local is not None
                    and inicio_original_local <= agora_local
                    and _to_local_naive(inicio_atual) == inicio_original_local
                ),
            )
    elif reativando_inativo:
        _apply_service_duration_if_needed(db, db_agendamento)
        motivo_agenda_fechada = _validar_agendamento_no_funcionamento(
            db, db_agendamento,
            permitir_excecao_agenda_fechada=(confirmar_agenda_fechada or _excecao_agenda_fechada_ativa(db_agendamento)),
        )
        if motivo_agenda_fechada and confirmar_agenda_fechada:
            db_agendamento.excecao_agenda_fechada_escopo = _escopo_excecao_agenda_fechada(db_agendamento)
        reservas_expiradas_revisadas = _validar_slot_disponivel(
            db,
            db_agendamento,
            agendamento_id_excluir=agendamento_id,
            confirmar_slot_reserva_expirada=confirmou_slot_reserva_expirada,
            **confirmacao_sobreposicao,
        )
        slot_ja_validado = True
        bypass_deslocamento = _validar_deslocamento_agendamento(
            db,
            db_agendamento,
            agendamento_id_excluir=agendamento_id,
            confirmar_conflito_deslocamento=override_conflito_deslocamento,
            baseline_regional=baseline_regional,
            validar_primeira_saida=not atendimento_ja_iniciado,
        )
    if (
        not slot_ja_validado
        and (confirmacao_sobreposicao["confirmar_sobreposicao"] or db_agendamento.excecao_sobreposicao)
    ):
        _validar_slot_disponivel(
            db, db_agendamento, agendamento_id_excluir=agendamento_id,
            confirmar_slot_reserva_expirada=confirmou_slot_reserva_expirada or not reativando_inativo,
            **confirmacao_sobreposicao,
        )
    if bypass_deslocamento and bypass_deslocamento.get("origem") == "confirmacao_admin":
        _conceder_excecao_deslocamento(
            db_agendamento,
            current_user=current_user,
            motivo=motivo_excecao_deslocamento or motivo_excecao_operacional,
        )
    else:
        # Horario/destino/servico podem ter mudado: uma concessao anterior que
        # nao corresponde mais a rota atual e descartada.
        _descartar_excecao_deslocamento_obsoleta(db_agendamento)
    related = _fetch_related_names(db, db_agendamento)
    _sync_denormalized_fields(db_agendamento, related)
    if status_anterior == "Reservado" or "status" in update_data or "paciente_id" in update_data:
        _validar_paciente_tutor_para_status(
            db,
            db_agendamento,
            status_destino=db_agendamento.status,
            related=related,
        )

    db_agendamento.atualizado_em = datetime.now()
    db_agendamento.updated_at = datetime.now()

    _commit_agenda_write(db)
    db.refresh(db_agendamento)
    contexto = _contexto_agendamento_auditoria(db_agendamento, related)

    registrar_auditoria(
        current_user=current_user,
        modulo="agenda",
        entidade="agendamento",
        entidade_id=db_agendamento.id,
        acao="AGENDAMENTO_ATUALIZADO",
        descricao=f"Agendamento atualizado - {_descricao_contexto_agendamento(contexto)}",
        detalhes={
            "antes": dados_anteriores,
            "campos_alterados": list(update_data.keys()),
            "depois": {
                "inicio": str(db_agendamento.inicio) if db_agendamento.inicio else None,
                "fim": str(db_agendamento.fim) if db_agendamento.fim else None,
                "status": db_agendamento.status,
                "paciente_id": db_agendamento.paciente_id,
                "tutor_id": getattr(db_agendamento, "tutor_id", None),
                "clinica_id": db_agendamento.clinica_id,
                "servico_id": db_agendamento.servico_id,
                "origem_atendimento": _normalizar_origem_atendimento(getattr(db_agendamento, "origem_atendimento", None)),
            },
            "excecao_sobreposicao": ler_concessao_sobreposicao(db_agendamento) or None,
            "override_conflito_deslocamento": override_conflito_deslocamento,
            "excecao_agenda_fechada_reutilizada": bool(
                not confirmar_agenda_fechada and _excecao_agenda_fechada_ativa(db_agendamento)
            ),
            "confirmou_revisao_slot_reserva_expirada": bool(reservas_expiradas_revisadas),
            "confirmou_reativacao_reserva_expirada": bool(
                reativando_expirado and confirmou_slot_reserva_expirada
            ),
            "reservas_expiradas_revisadas_ids": [
                item.id for item in reservas_expiradas_revisadas
            ],
            "confirmou_alteracao_servico_hoje": (
                alterando_servico_ja_iniciado and confirmar_alteracao_servico_hoje
            ),
            "intervalo_original_preservado": preservar_intervalo_servico_iniciado,
            "contexto_agendamento": contexto,
        },
        request=request,
    )
    if confirmar_agenda_fechada and _excecao_agenda_fechada_ativa(db_agendamento):
        registrar_auditoria(
            current_user=current_user, modulo="agenda", entidade="agendamento",
            entidade_id=db_agendamento.id, acao="AGENDAMENTO_AGENDA_FECHADA_CONFIRMADO",
            descricao=f"Administrador confirmou edicao fora do funcionamento - {_descricao_contexto_agendamento(contexto)}",
            detalhes={"escopo": db_agendamento.excecao_agenda_fechada_escopo,
                      "contexto_agendamento": contexto}, request=request,
        )
    observacoes_atualizadas = str(db_agendamento.observacoes or "")
    if "[Assistente agenda] sugestao aceita" in observacoes_atualizadas:
        _registrar_evento_funil_assistente(
            current_user=current_user,
            request=request,
            evento="ASSISTENTE_AGENDA_ACEITE",
            detalhes={
                "agendamento_id": db_agendamento.id,
                "clinica_id": db_agendamento.clinica_id,
                "servico_id": db_agendamento.servico_id,
                "perfil_usuario": "admin" if _usuario_tem_papel(current_user, "admin") else "nao_admin",
            },
        )
    if excecao_operacional_concedida:
        _registrar_auditoria_excecao_operacional_concedida(
            db=db,
            current_user=current_user,
            request=request,
            agendamento=db_agendamento,
            related=related,
            motivo=motivo_excecao_operacional,
        )
    if bypass_deslocamento:
        _registrar_auditoria_excecao_deslocamento(
            db=db,
            current_user=current_user,
            request=request,
            agendamento=db_agendamento,
            bypass=bypass_deslocamento,
            acao_operacional="editar_agendamento",
        )

    acao_push_update = "updated"
    base_push_update: Optional[dict] = None
    if status_anterior != db_agendamento.status:
        base_push_update = {
            "status_anterior": status_anterior,
            "status_novo": db_agendamento.status,
        }
        acao_push_update = "cancelled" if db_agendamento.status == "Cancelado" else "status_changed"

    _notificar_agenda_update(
        db=db,
        action=acao_push_update,
        agendamento_id=db_agendamento.id,
        data=_montar_payload_realtime(
            agendamento=db_agendamento,
            related=related,
            usuario=current_user,
            base=base_push_update,
        ),
    )

    return _serialize_agendamento(db_agendamento, **related)

@router.patch("/{agendamento_id}/status")
def atualizar_status(
    agendamento_id: int,
    request: Request,
    status: str,
    tipo_horario: Optional[str] = "comercial",  # 'comercial' ou 'plantao'
    confirmar_slot_reserva_expirada: bool = False,
    confirmar_conflito_deslocamento: bool = False,
    motivo_excecao_deslocamento: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Atualiza apenas o status do agendamento."""
    from decimal import Decimal
    from app.models.ordem_servico import OrdemServico
    _adquirir_lock_escrita_agenda(db)
    _expirar_reservas_vencidas(db)

    def _gerar_numero_os() -> str:
        mes_ano = datetime.now().strftime("%Y%m")
        ultima_os = (
            db.query(OrdemServico)
            .filter(OrdemServico.numero_os.like(f"OS{mes_ano}%"))
            .order_by(OrdemServico.id.desc())
            .first()
        )

        seq = 1
        if ultima_os and ultima_os.numero_os:
            sufixo = "".join(ch for ch in str(ultima_os.numero_os)[-4:] if ch.isdigit())
            if len(sufixo) == 4:
                seq = int(sufixo) + 1

        while (
            db.query(OrdemServico)
            .filter(OrdemServico.numero_os == f"OS{mes_ano}{seq:04d}")
            .first()
        ):
            seq += 1

        return f"OS{mes_ano}{seq:04d}"

    db_agendamento = db.query(Agendamento).filter(Agendamento.id == agendamento_id).first()
    if not db_agendamento:
        raise HTTPException(status_code=404, detail="Agendamento nao encontrado")

    if confirmar_conflito_deslocamento and not _usuario_tem_papel(current_user, "admin"):
        raise HTTPException(
            status_code=403,
            detail="Somente administradores podem confirmar excecao de conflito operacional.",
        )

    status_normalizado = _normalizar_status_agendamento(status)
    transicao_clinica_protegida = status_normalizado == "Realizado" or (
        db_agendamento.status == "Realizado" and status_normalizado == "Em atendimento"
    )
    if (
        transicao_clinica_protegida
        and "atendimentos_clinicos" in inspect(db.connection()).get_table_names()
    ):
        from app.models.atendimento_clinico import AtendimentoClinico

        atendimento_vinculado = (
            db.query(AtendimentoClinico)
            .filter(AtendimentoClinico.agendamento_id == agendamento_id)
            .order_by(AtendimentoClinico.id.asc())
            .first()
        )
        if atendimento_vinculado:
            orientacao = (
                "Finalize pelo modulo Atendimento"
                if status_normalizado == "Realizado"
                else "A reabertura vinculada esta bloqueada nesta etapa"
            )
            raise HTTPException(
                status_code=409,
                detail=(
                    f"O agendamento possui o Atendimento #{atendimento_vinculado.id}. "
                    f"{orientacao} para manter prontuario, Agenda e OS consistentes."
                ),
            )
    status_anterior = str(db_agendamento.status or "").strip() or "Agendado"
    reativando_expirado = _exigir_confirmacao_reativacao_reserva_expirada(
        status_anterior=status_anterior,
        status_novo=status_normalizado,
        confirmado=confirmar_slot_reserva_expirada,
    )
    related_validacao = _fetch_related_names(db, db_agendamento)
    _validar_paciente_tutor_para_status(
        db,
        db_agendamento,
        status_destino=status_normalizado,
        related=related_validacao,
    )

    reativando_cancelado = status_anterior == "Cancelado" and status_normalizado != "Cancelado"
    reativando_inativo = reativando_cancelado or reativando_expirado
    baseline_regional = (
        _capturar_baseline_regional_agendamento(db, db_agendamento.inicio)
        if reativando_inativo and status_normalizado in AGENDA_STATUS_BLOQUEIAM_SLOT else None
    )
    db_agendamento.status = status_normalizado
    reservas_expiradas_revisadas: list[Agendamento] = []
    bypass_deslocamento: Optional[dict[str, str]] = None
    if status_normalizado in AGENDA_STATUS_BLOQUEIAM_SLOT:
        _apply_service_duration_if_needed(db, db_agendamento)
        if reativando_inativo:
            _validar_agendamento_no_funcionamento(
                db,
                db_agendamento,
                permitir_excecao_agenda_fechada=_excecao_agenda_fechada_ativa(db_agendamento),
            )
        reservas_expiradas_revisadas = _validar_slot_disponivel(
            db,
            db_agendamento,
            agendamento_id_excluir=agendamento_id,
            confirmar_slot_reserva_expirada=(
                confirmar_slot_reserva_expirada or not reativando_inativo
            ),
        )
        if reativando_inativo:
            inicio_local = _to_local_naive(_coerce_datetime(db_agendamento.inicio))
            bypass_deslocamento = _validar_deslocamento_agendamento(
                db,
                db_agendamento,
                agendamento_id_excluir=agendamento_id,
                confirmar_conflito_deslocamento=confirmar_conflito_deslocamento,
                baseline_regional=baseline_regional,
                # Como no PUT, corrigir o status apos o inicio original nao
                # exige uma nova saida da base; os conflitos entre vizinhos
                # continuam sendo validados.
                validar_primeira_saida=not (
                    inicio_local is not None
                    and inicio_local <= datetime.now(LOCAL_TZ).replace(tzinfo=None)
                ),
            )
            if bypass_deslocamento and bypass_deslocamento.get("origem") == "confirmacao_admin":
                _conceder_excecao_deslocamento(
                    db_agendamento,
                    current_user=current_user,
                    motivo=motivo_excecao_deslocamento or "",
                )
    db_agendamento.atualizado_em = datetime.now()
    db_agendamento.updated_at = datetime.now()

    if status_normalizado == "Confirmado":
        db_agendamento.confirmado_por_id = current_user.id
        db_agendamento.confirmado_por_nome = current_user.nome
        db_agendamento.confirmado_em = datetime.now()

    os_gerada = None
    os_reutilizada = False
    mensagens_adicionais: list[str] = []

    _commit_agenda_write(db)
    db.refresh(db_agendamento)

    if bypass_deslocamento:
        _registrar_auditoria_excecao_deslocamento(
            db=db,
            current_user=current_user,
            request=request,
            agendamento=db_agendamento,
            bypass=bypass_deslocamento,
            acao_operacional=f"atualizar_status:{status_normalizado}",
        )

    if status_anterior == "Realizado" and status_normalizado == "Em atendimento":
        from app.models.financeiro import Transacao

        try:
            ordens_vinculadas = (
                db.query(OrdemServico)
                .filter(
                    OrdemServico.agendamento_id == agendamento_id,
                    OrdemServico.status != "Cancelado",
                )
                .order_by(OrdemServico.id.desc())
                .all()
            )

            os_removidas: list[str] = []
            transacoes_canceladas = 0
            momento_desfazer = datetime.now()

            for os_data in ordens_vinculadas:
                marker = f"OS_ID={os_data.id};TIPO=RECEBIMENTO_OS"
                transacoes = (
                    db.query(Transacao)
                    .filter(
                        Transacao.tipo == "entrada",
                        Transacao.status.in_(["Recebido", "Pago"]),
                        Transacao.observacoes.like(f"%{marker}%"),
                    )
                    .all()
                )

                if not transacoes and os_data.numero_os:
                    transacoes = (
                        db.query(Transacao)
                        .filter(
                            Transacao.tipo == "entrada",
                            Transacao.status.in_(["Recebido", "Pago"]),
                            Transacao.descricao.like(f"%{os_data.numero_os}%"),
                        )
                        .all()
                    )

                for transacao in transacoes:
                    transacao.status = "Cancelado"
                    transacao.data_pagamento = None
                    transacao.updated_at = momento_desfazer
                    observacao_base = (transacao.observacoes or "").strip()
                    observacao_auto = (
                        f"Cancelada automaticamente ao desfazer realizado do agendamento {agendamento_id}"
                    )
                    transacao.observacoes = (
                        f"{observacao_base} | {observacao_auto}" if observacao_base else observacao_auto
                    )
                    transacoes_canceladas += 1

                os_removidas.append(os_data.numero_os or f"ID {os_data.id}")
                db.delete(os_data)

            db.commit()
            mensagens_adicionais.append("Marcacao de realizado desfeita.")
            if os_removidas:
                mensagens_adicionais.append(
                    f"OS removida(s) automaticamente: {', '.join(os_removidas)}."
                )
            if transacoes_canceladas:
                mensagens_adicionais.append(
                    f"Transacao(oes) de recebimento cancelada(s): {transacoes_canceladas}."
                )
        except SQLAlchemyError:
            db.rollback()
            try:
                agendamento_restaurado = (
                    db.query(Agendamento)
                    .filter(Agendamento.id == agendamento_id)
                    .first()
                )
                if agendamento_restaurado:
                    agendamento_restaurado.status = "Realizado"
                    agendamento_restaurado.atualizado_em = datetime.now()
                    agendamento_restaurado.updated_at = datetime.now()
                    db.commit()
            except SQLAlchemyError:
                db.rollback()
            raise HTTPException(
                status_code=500,
                detail=(
                    "Nao foi possivel desfazer a ordem de servico automaticamente. "
                    "O status foi restaurado para Realizado."
                ),
            )

    # Se status for "Realizado", tenta gerar Ordem de Servico automaticamente.
    if status_normalizado == "Realizado":
        try:
            origem_os = _normalizar_origem_atendimento(getattr(db_agendamento, "origem_atendimento", None))
            os_existente = (
                db.query(OrdemServico)
                .filter(
                    OrdemServico.agendamento_id == agendamento_id,
                    OrdemServico.status != "Cancelado",
                )
                .order_by(OrdemServico.id.desc())
                .first()
            )

            if os_existente:
                os_gerada = {
                    "id": os_existente.id,
                    "numero_os": os_existente.numero_os,
                    "valor_final": float(os_existente.valor_final or 0),
                }
                os_reutilizada = True
            elif not (
                db_agendamento.paciente_id
                and db_agendamento.servico_id
                and (
                    origem_os == ORIGEM_ATENDIMENTO_DOMICILIAR
                    or db_agendamento.clinica_id
                )
            ):
                mensagens_adicionais.append(
                    "Status atualizado, mas OS nao foi gerada por falta de paciente, servico ou base operacional."
                )
            else:
                valor_servico = Decimal("0.00")
                pode_gerar_os = True
                try:
                    valor_servico = calcular_preco_servico(
                        db=db,
                        clinica_id=db_agendamento.clinica_id,
                        servico_id=db_agendamento.servico_id,
                        tipo_horario=tipo_horario or "comercial",
                        usar_preco_clinica=True,
                        origem_atendimento=origem_os,
                    )
                except HTTPException as exc:
                    if exc.status_code in (404, 422):
                        mensagens_adicionais.append(
                            f"Status atualizado, mas OS nao foi gerada ({exc.detail})."
                        )
                        pode_gerar_os = False
                    else:
                        raise

                if pode_gerar_os:
                    nova_os = OrdemServico(
                        numero_os=_gerar_numero_os(),
                        agendamento_id=agendamento_id,
                        paciente_id=db_agendamento.paciente_id,
                        clinica_id=db_agendamento.clinica_id,
                        servico_id=db_agendamento.servico_id,
                        origem_atendimento=origem_os,
                        data_atendimento=db_agendamento.inicio,
                        tipo_horario=tipo_horario or "comercial",
                        valor_servico=valor_servico,
                        desconto=Decimal("0.00"),
                        valor_final=valor_servico,
                        status="Pendente",
                        observacoes=f"OS gerada automaticamente do agendamento {agendamento_id}",
                        criado_por_id=current_user.id,
                        criado_por_nome=current_user.nome,
                    )
                    db.add(nova_os)
                    db.commit()
                    db.refresh(nova_os)

                    os_gerada = {
                        "id": nova_os.id,
                        "numero_os": nova_os.numero_os,
                        "valor_final": float(nova_os.valor_final),
                    }
        except SQLAlchemyError:
            db.rollback()
            mensagens_adicionais.append("Status atualizado, mas houve erro ao processar a OS.")

    related_status = _fetch_related_names(db, db_agendamento)
    contexto_status = _contexto_agendamento_auditoria(db_agendamento, related_status)
    clinica_label_status = _rotulo_clinica_agendamento(
        db_agendamento,
        related_status.get("clinica_nome"),
    )

    resposta = {
        "id": db_agendamento.id,
        "status": db_agendamento.status,
        "paciente": related_status.get("paciente_nome") or "",
        "clinica": clinica_label_status,
        "servico": related_status.get("servico_nome") or "",
        "mensagem": f"Status atualizado para {status_normalizado}",
        "excecao_deslocamento_ativa": _excecao_deslocamento_ativa(db_agendamento),
    }

    if os_gerada:
        resposta["os_gerada"] = os_gerada
        if os_reutilizada:
            resposta["mensagem"] += f". OS {os_gerada['numero_os']} ja vinculada"
        else:
            resposta["mensagem"] += f". OS {os_gerada['numero_os']} gerada com valor R$ {os_gerada['valor_final']:.2f}"
    if mensagens_adicionais:
        resposta["mensagem"] += ". " + " ".join(mensagens_adicionais)

    if os_gerada and not os_reutilizada:
        try:
            send_financeiro_push_notification(
                db,
                action="os_generated",
                os_id=int(os_gerada["id"]),
                data={
                    "numero_os": os_gerada.get("numero_os"),
                    "valor_final": f"{float(os_gerada.get('valor_final') or 0):.2f}",
                    "paciente_nome": related_status.get("paciente_nome"),
                    "clinica_nome": clinica_label_status,
                    "servico_nome": related_status.get("servico_nome"),
                },
            )
        except Exception as exc:
            print(f"[financeiro-push] Falha ao enviar push de OS gerada: {exc}")

        try:
            lembrete_horas = 6
            preferencias_push = (
                db.query(
                    ConfiguracaoUsuario.notificacoes_push_lembrete_pendencias,
                    ConfiguracaoUsuario.notificacoes_push_lembrete_horas,
                )
                .filter(ConfiguracaoUsuario.user_id == current_user.id)
                .first()
            )
            lembrete_habilitado = True
            if preferencias_push:
                lembrete_habilitado = bool(
                    True
                    if preferencias_push.notificacoes_push_lembrete_pendencias is None
                    else preferencias_push.notificacoes_push_lembrete_pendencias
                )
                lembrete_horas = int(preferencias_push.notificacoes_push_lembrete_horas or 6)
            if lembrete_habilitado:
                if lembrete_horas < 1:
                    lembrete_horas = 1
                if lembrete_horas > 168:
                    lembrete_horas = 168
                schedule_pending_os_payment_reminder(
                    db,
                    os_id=int(os_gerada["id"]),
                    reminder_hours=lembrete_horas,
                    data={
                        "numero_os": os_gerada.get("numero_os"),
                        "valor_final": f"{float(os_gerada.get('valor_final') or 0):.2f}",
                        "paciente_nome": related_status.get("paciente_nome"),
                        "clinica_nome": clinica_label_status,
                        "servico_nome": related_status.get("servico_nome"),
                        "lembrete_horas": str(lembrete_horas),
                    },
                    commit=True,
                )
        except Exception as exc:
            print(f"[financeiro-push] Falha ao agendar lembrete de pendencia da OS: {exc}")

    if status_normalizado == "Cancelado":
        acao_log = "AGENDAMENTO_CANCELADO"
    elif status_anterior == "Realizado" and status_normalizado == "Em atendimento":
        acao_log = "AGENDAMENTO_REALIZADO_DESFEITO"
    else:
        acao_log = "AGENDAMENTO_STATUS_ALTERADO"

    registrar_auditoria(
        current_user=current_user,
        modulo="agenda",
        entidade="agendamento",
        entidade_id=db_agendamento.id,
        acao=acao_log,
        descricao=(
            f"Status do agendamento alterado de {status_anterior} para {status_normalizado}"
            f" - {_descricao_contexto_agendamento(contexto_status)}"
        ),
        detalhes={
            "status_anterior": status_anterior,
            "status_novo": status_normalizado,
            "tipo_horario": tipo_horario,
            "os_gerada": os_gerada,
            "mensagens_adicionais": mensagens_adicionais,
            "confirmou_revisao_slot_reserva_expirada": bool(reservas_expiradas_revisadas),
            "confirmou_reativacao_reserva_expirada": bool(
                reativando_expirado and confirmar_slot_reserva_expirada
            ),
            "reservas_expiradas_revisadas_ids": [
                item.id for item in reservas_expiradas_revisadas
            ],
            "contexto_agendamento": contexto_status,
        },
        request=request,
    )

    acao_push_status = "cancelled" if status_normalizado == "Cancelado" else "status_changed"

    _notificar_agenda_update(
        db=db,
        action=acao_push_status,
        agendamento_id=db_agendamento.id,
        data=_montar_payload_realtime(
            agendamento=db_agendamento,
            related=related_status,
            usuario=current_user,
            base={
                "status_anterior": status_anterior,
                "status_novo": db_agendamento.status,
            },
        ),
    )

    return resposta


@router.post("/{agendamento_id}/reabilitar-reserva")
def reabilitar_reserva_expirada(
    agendamento_id: int,
    payload: ReabilitarReservaPayload,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Devolve uma reserva expirada ao status Reservado com um novo prazo.

    Caso de uso: o prazo venceu sem os dados do paciente, mas depois disso a
    clinica voltou a querer o mesmo horario. Se o slot continua livre e sem
    conflito com outros agendamentos, a reserva volta a segurar o horario por
    mais um periodo, ate a clinica enviar os dados do paciente e do tutor.
    """
    _adquirir_lock_escrita_agenda(db)
    _expirar_reservas_vencidas(db)

    db_agendamento = db.query(Agendamento).filter(Agendamento.id == agendamento_id).first()
    if not db_agendamento:
        raise HTTPException(status_code=404, detail="Agendamento nao encontrado")

    if payload.confirmar_conflito_deslocamento and not _usuario_tem_papel(current_user, "admin"):
        raise HTTPException(
            status_code=403,
            detail="Somente administradores podem confirmar excecao de conflito operacional.",
        )

    status_anterior = str(db_agendamento.status or "").strip() or "Agendado"
    if status_anterior != "Expirado":
        raise HTTPException(
            status_code=409,
            detail=(
                "Somente reservas expiradas podem ser reabilitadas "
                f"(status atual: {status_anterior})."
            ),
        )

    prazo_anterior = _to_local_naive(
        _coerce_datetime(getattr(db_agendamento, "reserva_expira_em", None))
    )
    novo_prazo, prazo_encurtado = _calcular_prazo_reabilitacao_reserva(
        db_agendamento,
        horas=payload.prazo_confirmacao_horas,
        prazo_explicito=payload.reserva_expira_em,
    )

    baseline_regional = _capturar_baseline_regional_agendamento(db, db_agendamento.inicio)
    db_agendamento.status = "Reservado"
    db_agendamento.reserva_expira_em = novo_prazo
    _apply_service_duration_if_needed(db, db_agendamento)
    _validar_regras_origem_agendamento(db, db_agendamento, contexto="reabilitar a reserva")
    _validar_prazo_reserva(db_agendamento)
    _validar_agendamento_no_funcionamento(
        db,
        db_agendamento,
        permitir_excecao_agenda_fechada=_excecao_agenda_fechada_ativa(db_agendamento),
    )
    reservas_expiradas_revisadas = _validar_slot_disponivel(
        db,
        db_agendamento,
        agendamento_id_excluir=agendamento_id,
        confirmar_slot_reserva_expirada=payload.confirmar_slot_reserva_expirada,
    )
    bypass_deslocamento = _validar_deslocamento_agendamento(
        db,
        db_agendamento,
        agendamento_id_excluir=agendamento_id,
        confirmar_conflito_deslocamento=payload.confirmar_conflito_deslocamento,
        baseline_regional=baseline_regional,
    )
    if bypass_deslocamento and bypass_deslocamento.get("origem") == "confirmacao_admin":
        _conceder_excecao_deslocamento(
            db_agendamento,
            current_user=current_user,
            motivo=payload.motivo_excecao_deslocamento or "",
        )

    related = _fetch_related_names(db, db_agendamento)
    _sync_denormalized_fields(db_agendamento, related)
    db_agendamento.atualizado_em = datetime.now()
    db_agendamento.updated_at = datetime.now()

    _commit_agenda_write(db)
    db.refresh(db_agendamento)

    if bypass_deslocamento:
        _registrar_auditoria_excecao_deslocamento(
            db=db,
            current_user=current_user,
            request=request,
            agendamento=db_agendamento,
            bypass=bypass_deslocamento,
            acao_operacional="reabilitar_reserva",
        )

    related = _fetch_related_names(db, db_agendamento)
    contexto = _contexto_agendamento_auditoria(db_agendamento, related)
    prazo_final = _to_local_naive(_coerce_datetime(db_agendamento.reserva_expira_em)) or novo_prazo

    registrar_auditoria(
        current_user=current_user,
        modulo="agenda",
        entidade="agendamento",
        entidade_id=db_agendamento.id,
        acao="AGENDAMENTO_RESERVA_REABILITADA",
        descricao=(
            "Reserva expirada reabilitada com novo prazo de confirmacao "
            f"{prazo_final.strftime('%d/%m/%Y %H:%M')} - "
            f"{_descricao_contexto_agendamento(contexto)}"
        ),
        detalhes={
            "status_anterior": status_anterior,
            "status_novo": db_agendamento.status,
            "prazo_anterior": prazo_anterior.isoformat() if prazo_anterior else None,
            "prazo_novo": prazo_final.isoformat(),
            "prazo_confirmacao_horas": payload.prazo_confirmacao_horas,
            "prazo_encurtado_para_caber_antes_do_atendimento": prazo_encurtado,
            "confirmou_revisao_slot_reserva_expirada": bool(reservas_expiradas_revisadas),
            "reservas_expiradas_revisadas_ids": [item.id for item in reservas_expiradas_revisadas],
            "override_conflito_deslocamento": bool(payload.confirmar_conflito_deslocamento),
            "contexto_agendamento": contexto,
        },
        request=request,
    )

    _notificar_agenda_update(
        db=db,
        action="status_changed",
        agendamento_id=db_agendamento.id,
        data=_montar_payload_realtime(
            agendamento=db_agendamento,
            related=related,
            usuario=current_user,
            base={
                "status_anterior": status_anterior,
                "status_novo": db_agendamento.status,
            },
        ),
    )

    mensagem = (
        "Reserva reabilitada. A clinica tem ate "
        f"{prazo_final.strftime('%d/%m/%Y %H:%M')} para enviar os dados do paciente."
    )
    if prazo_encurtado:
        mensagem += " O prazo foi encurtado para terminar antes do horario reservado."

    return {
        **_serialize_agendamento(db_agendamento, **related),
        "mensagem": mensagem,
        "prazo_encurtado": prazo_encurtado,
    }


@router.delete("/{agendamento_id}")
def deletar_agendamento(
    agendamento_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Deleta agendamento quando o usuario e admin ou da recepcao."""
    if not usuario_pode_excluir_agendamento(current_user):
        raise HTTPException(
            status_code=403,
            detail="Apenas administradores e a equipe de recepcao podem excluir agendamentos",
        )

    db_agendamento = db.query(Agendamento).filter(Agendamento.id == agendamento_id).first()
    if not db_agendamento:
        raise HTTPException(status_code=404, detail="Agendamento nao encontrado")

    related_delete = _fetch_related_names(db, db_agendamento)
    contexto_delete = _contexto_agendamento_auditoria(db_agendamento, related_delete)

    snapshot = {
        "paciente_id": db_agendamento.paciente_id,
        "tutor_id": getattr(db_agendamento, "tutor_id", None),
        "clinica_id": db_agendamento.clinica_id,
        "servico_id": db_agendamento.servico_id,
        "status": db_agendamento.status,
        "data": db_agendamento.data,
        "hora": db_agendamento.hora,
        "origem_atendimento": _normalizar_origem_atendimento(getattr(db_agendamento, "origem_atendimento", None)),
        "contexto_agendamento": contexto_delete,
    }
    realtime_delete_payload = _montar_payload_realtime(
        agendamento=db_agendamento,
        related=related_delete,
        usuario=current_user,
        base={
            "status": snapshot.get("status"),
            "data": snapshot.get("data"),
            "hora": snapshot.get("hora"),
        },
    )

    laudos_vinculados = (
        db.query(Laudo)
        .filter(Laudo.agendamento_id == agendamento_id)
        .all()
    )
    laudos_desvinculados: list[int] = []
    for laudo in laudos_vinculados:
        laudo.agendamento_id = None
        laudo.updated_at = datetime.now()
        laudos_desvinculados.append(laudo.id)
    snapshot["laudos_desvinculados"] = laudos_desvinculados

    db.delete(db_agendamento)
    db.commit()

    registrar_auditoria(
        current_user=current_user,
        modulo="agenda",
        entidade="agendamento",
        entidade_id=agendamento_id,
        acao="AGENDAMENTO_EXCLUIDO",
        descricao=f"Agendamento excluido - {_descricao_contexto_agendamento(contexto_delete)}",
        detalhes=snapshot,
        request=request,
    )

    _notificar_agenda_update(
        db=db,
        action="deleted",
        agendamento_id=agendamento_id,
        data=realtime_delete_payload,
    )

    return {"message": "Agendamento deletado com sucesso"}
