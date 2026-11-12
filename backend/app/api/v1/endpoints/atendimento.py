from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO
import json
import logging
import os
import re
import tempfile
import unicodedata
from typing import Any, Dict, List, Optional, Union
from xml.sax.saxutils import escape as xml_escape

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from app.api.v1.endpoints.ordens_servico import _bloquear_os_para_escrita, desfazer_recebimento_ordem
from app.schemas.atendimento import (
    AdendoPayload,
    AnexoPayload,
    AlertaPayload,
    AtendimentoCreatePayload,
    AtendimentoFinalizarPayload,
    AtendimentoUpdatePayload,
    CatalogoExameCustomPayload,
    ClinicalPhrasePayload,
    DiagnosticoPayload,
    DocumentoAtendimentoCreatePayload,
    DocumentoAtendimentoUpdatePayload,
    DocumentoTemplatePayload,
    ExameSolicitacaoPayload,
    EvolucaoPayload,
    MedicamentoPayload,
    PainelExamePayload,
    PrescricaoComplementarPayload,
    PrescricaoItemPayload,
    PrescricaoPayload,
    PrescricaoPreviewPayload,
    PrescricaoSyncPayload,
    TriagemPayload,
)
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import and_, func, or_, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.agenda_realtime import agenda_realtime_manager
from app.core.portal_release import PORTAL_RELEASED_STATUS, is_portal_released_status
from app.core.security import get_current_user
from app.db.database import get_db
from app.models.agendamento import Agendamento
from app.models.atendimento_clinico import (
    AlertaClinico,
    AnexoAtendimento,
    AtendimentoClinico,
    DocumentoAtendimento,
    DocumentoAtendimentoTemplate,
    EvolucaoClinica,
    ExameAjuste,
    Medicamento,
    PrescricaoClinica,
    PrescricaoItem,
    PrescricaoItemAjuste,
    UploadDedupeMetrica,
)
from app.models.catalogo_exame import CatalogoExame, PainelExame, PainelExameItem
from app.models.clinica import Clinica
from app.models.configuracao import Configuracao, ConfiguracaoUsuario
from app.models.laudo import Exame, Laudo
from app.models.ordem_servico import OrdemServico
from app.models.paciente import Paciente
from app.models.tutor import Tutor
from app.models.user import User
from app.services.clinical_phrase_service import montar_contexto_frases_clinicas
from app.services.atendimento.clinical_phrase_crud_service import (
    atualizar_frase_clinica,
    criar_frase_clinica,
    desativar_frase_clinica,
    restaurar_frase_clinica,
)
from app.services.atendimento.document_template_crud_service import (
    atualizar_template_documento,
    criar_template_documento,
    desativar_template_documento,
    listar_templates_documento,
    obter_template_documento_ou_404,
    restaurar_template_documento,
)
from app.services.atendimento.document_crud_service import (
    agora_documento,
    auditar_documento,
    validar_versao_documento,
    validar_documento_ativo,
    restaurar_documento_atendimento as restaurar_documento_atendimento_service,
    atualizar_documento_atendimento as atualizar_documento_atendimento_service,
    excluir_documento_atendimento as excluir_documento_atendimento_service,
    listar_documentos_atendimento as listar_documentos_atendimento_service,
    obter_documento_atendimento_ou_404 as obter_documento_atendimento_ou_404_service,
    serializar_documento_atendimento as serializar_documento_atendimento_service,
)
from app.services.atendimento.document_context_service import (
    atualizar_documento_template_se_contexto_mudou as atualizar_documento_template_se_contexto_mudou_service,
    carregar_contexto_entidades_documento as carregar_contexto_entidades_documento_service,
    identificar_variaveis_vazias as identificar_variaveis_vazias_service,
    montar_contexto_template_documento as montar_contexto_template_documento_service,
    renderizar_template_documento as renderizar_template_documento_service,
)
from app.services.exam_catalog_service import catalogo_exame_to_dict, montar_contexto_catalogo_exames
from app.services.atendimento.catalogo_exame_custom_service import (
    gerar_codigo_unico_catalogo_exame,
    obter_catalogo_exame_customizado,
)
from app.services.atendimento.painel_service import (
    CUSTOM_PAINEL_EXAME_PREFIX,
    gerar_codigo_unico_painel_exame,
    obter_painel_exame_customizado,
    resolver_ids_catalogo_exames,
    serializar_painel_exame_com_itens,
    substituir_itens_painel_exame,
)
from app.services.atendimento_upload_service import (
    AttachmentTooLargeError,
    AttachmentTypeError,
    build_upload_dedupe_key,
    calculate_attachment_sha256,
    store_atendimento_attachment_file,
    remove_atendimento_attachment_file,
)
from app.services.attachment_download_service import (
    attachment_has_download_source,
    attachment_is_verified_pdf,
    build_attachment_download_response,
)
from app.services.portal_clinic_device_trust_service import revoke_trusts_for_exam
from app.services.portal_clinic_exam_link_service import revoke_links_for_exam
from app.services.upload_dedupe_cleanup_service import (
    UploadDedupeCleanupBusyError,
    UploadDedupeCleanupExecutionError,
    get_upload_dedupe_cleanup_status,
    run_upload_dedupe_cleanup,
    UPLOAD_DEDUPE_CLEANUP_EXECUTOR_MANUAL,
)
from app.services.medication_automation import analyze_prescription_items, medication_to_dict
from app.services.auditoria_service import registrar_auditoria
from app.services.atendimento.edit_history_service import listar_historico_edicoes
from app.services.precos_service import calcular_preco_servico
from app.services.push_notifications import (
    send_agenda_push_notification,
    send_financeiro_push_notification,
)
from app.utils.paciente_idade import idade_do_paciente, dados_idade_paciente
from app.utils.paciente_helpers import normalizar_sexo_paciente
from app.utils.pdf_laudo import (
    create_pdf_styles,
    criar_cabecalho,
    criar_secao_assinatura,
    criar_titulo_secao,
    footer_todas_paginas,
)

router = APIRouter()
logger = logging.getLogger(__name__)

ATENDIMENTO_LOCAL_TZ = timezone(timedelta(hours=-3), name="America/Fortaleza")
ATENDIMENTO_STATUS_CANONICOS = {
    "triagem": "Triagem",
    "em atendimento": "Em atendimento",
    "aguardando exames": "Aguardando exames",
    "retorno agendado": "Retorno agendado",
    "concluido": "Concluido",
}
ATENDIMENTO_TIPOS_HORARIO = {"comercial", "plantao"}
ATENDIMENTO_AGENDA_STATUS_TERMINAIS = {"Cancelado", "Faltou", "Expirado"}
# Adendo = o que chega depois do encontro (resultado de exame que o tutor
# mandou dias depois, receita complementar, orientacao). Mora na mesma tabela
# de evolucao clinica: o episodio continua sendo o mesmo atendimento.
ADENDO_TIPOS_CANONICOS = {
    "evolucao",
    "resultado_exame",
    "receita_complementar",
    "orientacao",
}
ADENDO_TIPO_LABELS = {
    "evolucao": "Evolucao clinica",
    "resultado_exame": "Resultado de exame recebido",
    "receita_complementar": "Receita complementar",
    "orientacao": "Orientacao ao tutor",
}
ATENDIMENTO_FINALIZATION_LOCK_KEY = 24052302
ORIGEM_ATENDIMENTO_DOMICILIAR = "domiciliar"
ORIGEM_ATENDIMENTO_PADRAO = "clinica_parceira"

PORTAL_EXAME_RELEASE_MESSAGE = "Exame liberado no portal da clinica parceira."

UPLOAD_DEDUPE_EVENT_UPLOAD_NOVO = "upload_novo"
UPLOAD_DEDUPE_EVENT_PRECHECK = "dedupe_precheck"
UPLOAD_DEDUPE_EVENT_COLLISION = "dedupe_collision"
UPLOAD_DEDUPE_EVENTS_VALIDOS = {
    UPLOAD_DEDUPE_EVENT_UPLOAD_NOVO,
    UPLOAD_DEDUPE_EVENT_PRECHECK,
    UPLOAD_DEDUPE_EVENT_COLLISION,
}


def _serialize_medicamento(item: Medicamento) -> dict:
    return medication_to_dict(item)


def _resolver_peso_referencia(
    atendimento: Optional[AtendimentoClinico],
    paciente: Optional[Paciente],
) -> Optional[float]:
    if atendimento and atendimento.peso is not None:
        return float(atendimento.peso)
    if paciente and paciente.peso_kg is not None:
        return float(paciente.peso_kg)
    return None


def _registrar_ajuste_prescricao(
    db: Session,
    *,
    item: PrescricaoItem,
    atendimento_id: int,
    campo: str,
    valor_anterior: Any,
    valor_novo: Any,
    current_user: User,
    motivo: str = "Atualizacao manual da prescricao",
) -> None:
    anterior = "" if valor_anterior is None else str(valor_anterior).strip()
    novo = "" if valor_novo is None else str(valor_novo).strip()
    if anterior == novo:
        return

    db.add(
        PrescricaoItemAjuste(
            prescricao_item_id=item.id,
            atendimento_id=atendimento_id,
            campo=campo,
            valor_anterior=anterior,
            valor_novo=novo,
            motivo=motivo,
            responsavel_id=current_user.id,
            responsavel_nome=current_user.nome,
        )
    )


def _map_ajustes_por_item(
    db: Session,
    item_ids: List[int],
) -> Dict[int, List[dict]]:
    if not item_ids:
        return {}

    ajustes = (
        db.query(PrescricaoItemAjuste)
        .filter(PrescricaoItemAjuste.prescricao_item_id.in_(item_ids))
        .order_by(PrescricaoItemAjuste.created_at.desc(), PrescricaoItemAjuste.id.desc())
        .all()
    )
    grouped: Dict[int, List[dict]] = defaultdict(list)
    for ajuste in ajustes:
        grouped[ajuste.prescricao_item_id].append(
            {
                "id": ajuste.id,
                "campo": ajuste.campo,
                "valor_anterior": ajuste.valor_anterior or "",
                "valor_novo": ajuste.valor_novo or "",
                "motivo": ajuste.motivo or "",
                "responsavel_id": ajuste.responsavel_id,
                "responsavel_nome": ajuste.responsavel_nome or "",
                "created_at": _to_iso(ajuste.created_at),
            }
        )
    return grouped


def _registrar_ajuste_exame(
    db: Session,
    *,
    exame: Exame,
    atendimento_id: int,
    campo: str,
    valor_anterior: Any,
    valor_novo: Any,
    current_user: User,
    motivo: str = "Atualizacao manual do exame",
) -> None:
    anterior = "" if valor_anterior is None else str(valor_anterior).strip()
    novo = "" if valor_novo is None else str(valor_novo).strip()
    if anterior == novo:
        return

    db.add(
        ExameAjuste(
            exame_id=exame.id,
            atendimento_id=atendimento_id,
            campo=campo,
            valor_anterior=anterior,
            valor_novo=novo,
            motivo=motivo,
            responsavel_id=current_user.id,
            responsavel_nome=current_user.nome,
        )
    )


def _map_ajustes_por_exame(
    db: Session,
    exame_ids: List[int],
) -> Dict[int, List[dict]]:
    if not exame_ids:
        return {}

    ajustes = (
        db.query(ExameAjuste)
        .filter(ExameAjuste.exame_id.in_(exame_ids))
        .order_by(ExameAjuste.created_at.desc(), ExameAjuste.id.desc())
        .all()
    )
    grouped: Dict[int, List[dict]] = defaultdict(list)
    for ajuste in ajustes:
        grouped[ajuste.exame_id].append(
            {
                "id": ajuste.id,
                "campo": ajuste.campo,
                "valor_anterior": ajuste.valor_anterior or "",
                "valor_novo": ajuste.valor_novo or "",
                "motivo": ajuste.motivo or "",
                "responsavel_id": ajuste.responsavel_id,
                "responsavel_nome": ajuste.responsavel_nome or "",
                "created_at": _to_iso(ajuste.created_at),
            }
        )
    return grouped


def _normalizar_diagnostico(diagnostico: Optional[Union[DiagnosticoPayload, str]]) -> Dict[str, Optional[str]]:
    if isinstance(diagnostico, str):
        texto = diagnostico.strip()
        return {
            "diagnostico_principal": texto,
            "diagnostico_secundario": "",
            "diagnostico_diferencial": "",
            "prognostico": None,
        }

    if diagnostico is None:
        return {
            "diagnostico_principal": "",
            "diagnostico_secundario": "",
            "diagnostico_diferencial": "",
            "prognostico": None,
        }

    return {
        "diagnostico_principal": diagnostico.diagnostico_principal or "",
        "diagnostico_secundario": diagnostico.diagnostico_secundario or "",
        "diagnostico_diferencial": diagnostico.diagnostico_diferencial or "",
        "prognostico": diagnostico.prognostico or None,
    }


def _normalizar_token_status_atendimento(value: Any) -> str:
    raw = unicodedata.normalize("NFKD", str(value or "").strip())
    sem_acentos = "".join(ch for ch in raw if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", sem_acentos).strip().lower()


def _normalizar_status_atendimento(value: Any) -> str:
    token = _normalizar_token_status_atendimento(value)
    status_canonico = ATENDIMENTO_STATUS_CANONICOS.get(token)
    if status_canonico:
        return status_canonico
    permitidos = ", ".join(ATENDIMENTO_STATUS_CANONICOS.values())
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=f"Status de atendimento invalido. Use um destes estados: {permitidos}.",
    )


def _status_atendimento_concluido(value: Any) -> bool:
    return _normalizar_token_status_atendimento(value) == "concluido"


def _tem_texto_clinico(value: Any) -> bool:
    return bool(str(value or "").strip())


def _calcular_pendencias_documentacao(
    *,
    queixa_principal: Any,
    anamnese: Any,
    exame_fisico: Any,
    dados_clinicos: Any,
    diagnostico_principal: Any,
    diagnostico_secundario: Any,
    diagnostico_diferencial: Any,
    plano_terapeutico: Any,
) -> List[str]:
    """Pendencias de documentacao clinica minima, independente de status.

    Usada tanto para bloquear a primeira conclusao
    (`_validar_primeira_conclusao_atendimento`) quanto para sinalizar, depois,
    quais atendimentos ja concluidos ficaram com documentacao incompleta
    (`listar_atendimentos`, filtro `documentacao_incompleta`).
    """
    pendencias: List[str] = []
    if not _tem_texto_clinico(queixa_principal):
        pendencias.append("queixa principal")
    if not any(_tem_texto_clinico(item) for item in (anamnese, exame_fisico, dados_clinicos)):
        pendencias.append("anamnese, exame fisico ou dados clinicos")
    if not any(
        _tem_texto_clinico(item)
        for item in (
            diagnostico_principal,
            diagnostico_secundario,
            diagnostico_diferencial,
            plano_terapeutico,
        )
    ):
        pendencias.append("diagnostico ou plano terapeutico")
    return pendencias


def _condicao_sql_documentacao_incompleta():
    """Equivalente em SQL de `_calcular_pendencias_documentacao` retornar
    pendencias, para filtrar no banco sem quebrar paginacao."""

    def _vazio(coluna):
        return func.trim(func.coalesce(coluna, "")) == ""

    grupo_queixa = _vazio(AtendimentoClinico.queixa_principal)
    grupo_evolucao = and_(
        _vazio(AtendimentoClinico.anamnese),
        _vazio(AtendimentoClinico.exame_fisico),
        _vazio(AtendimentoClinico.dados_clinicos),
    )
    grupo_diagnostico = and_(
        _vazio(AtendimentoClinico.diagnostico_principal),
        _vazio(AtendimentoClinico.diagnostico_secundario),
        _vazio(AtendimentoClinico.diagnostico_diferencial),
        _vazio(AtendimentoClinico.plano_terapeutico),
    )
    return or_(grupo_queixa, grupo_evolucao, grupo_diagnostico)


def _validar_primeira_conclusao_atendimento(
    *,
    status_atual: Any,
    status_destino: Any,
    queixa_principal: Any,
    anamnese: Any,
    exame_fisico: Any,
    dados_clinicos: Any,
    diagnostico_principal: Any,
    diagnostico_secundario: Any,
    diagnostico_diferencial: Any,
    plano_terapeutico: Any,
    confirmado: bool = False,
) -> List[str]:
    """Barreira clinica minima antes da primeira conclusao do atendimento.

    Devolve a lista de pendencias (vazia se nao houver). Com pendencias e sem
    confirmacao, bloqueia com 409 confirmavel. Com `confirmado=True`, deixa
    passar e devolve as pendencias para o chamador decidir se audita a
    conclusao com documentacao incompleta.
    """
    if not _status_atendimento_concluido(status_destino) or _status_atendimento_concluido(status_atual):
        return []

    pendencias = _calcular_pendencias_documentacao(
        queixa_principal=queixa_principal,
        anamnese=anamnese,
        exame_fisico=exame_fisico,
        dados_clinicos=dados_clinicos,
        diagnostico_principal=diagnostico_principal,
        diagnostico_secundario=diagnostico_secundario,
        diagnostico_diferencial=diagnostico_diferencial,
        plano_terapeutico=plano_terapeutico,
    )

    if not pendencias:
        return []

    if not confirmado:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "codigo": "CONFIRMACAO_CONCLUSAO_PENDENCIAS",
                "mensagem": (
                    "Faltam preencher: "
                    + "; ".join(pendencias)
                    + ". Confirme para concluir mesmo assim, ou mantenha o "
                    "atendimento em andamento e continue depois."
                ),
                "confirmavel": True,
                "pendencias": pendencias,
            },
        )

    return pendencias


def _auditar_conclusao_com_pendencias(
    *,
    current_user: User,
    atendimento: AtendimentoClinico,
    pendencias: List[str],
    request: Optional[Request] = None,
) -> None:
    """Concluir sem diagnostico/plano terapeutico e uma decisao clinica que
    precisa deixar rastro, mesmo sendo permitida apos confirmacao explicita."""
    registrar_auditoria(
        current_user=current_user,
        modulo="atendimento",
        entidade="atendimento_clinico",
        entidade_id=atendimento.id,
        acao="CONCLUIR_COM_PENDENCIAS",
        descricao=(
            f"Atendimento #{atendimento.id} concluido com documentacao incompleta: "
            + "; ".join(pendencias)
        ),
        detalhes={"pendencias": pendencias, "paciente_id": atendimento.paciente_id},
        request=request,
    )


def _normalizar_tipo_horario_atendimento(value: Any) -> str:
    tipo_horario = str(value or "").strip().lower()
    if tipo_horario not in ATENDIMENTO_TIPOS_HORARIO:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Tipo de horario invalido. Use comercial ou plantao.",
        )
    return tipo_horario


def _normalizar_origem_atendimento(value: Any) -> str:
    raw = str(value or "").strip().lower()
    aliases = {
        "": ORIGEM_ATENDIMENTO_PADRAO,
        "clinica": ORIGEM_ATENDIMENTO_PADRAO,
        "clinica_parceira": ORIGEM_ATENDIMENTO_PADRAO,
        "parceira": ORIGEM_ATENDIMENTO_PADRAO,
        "domiciliar": ORIGEM_ATENDIMENTO_DOMICILIAR,
    }
    origem = aliases.get(raw, raw)
    if origem not in {ORIGEM_ATENDIMENTO_PADRAO, ORIGEM_ATENDIMENTO_DOMICILIAR}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Origem do agendamento invalida para finalizar o atendimento.",
        )
    return origem


def _adquirir_lock_finalizacao(db: Session) -> None:
    if db.info.get("_atendimento_finalization_lock"):
        return

    dialect_name = str(getattr(getattr(db.get_bind(), "dialect", None), "name", "")).lower()
    if dialect_name == "sqlite":
        if not db.in_transaction():
            db.execute(text("BEGIN IMMEDIATE"))
    elif dialect_name in {"postgres", "postgresql"}:
        db.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": ATENDIMENTO_FINALIZATION_LOCK_KEY},
        )
    else:
        (
            db.query(Configuracao)
            .order_by(Configuracao.id.asc())
            .with_for_update()
            .first()
        )
    db.info["_atendimento_finalization_lock"] = True


def _buscar_os_ativa(db: Session, agendamento_id: int) -> Optional[OrdemServico]:
    return (
        db.query(OrdemServico)
        .filter(
            OrdemServico.agendamento_id == agendamento_id,
            or_(OrdemServico.status.is_(None), OrdemServico.status != "Cancelado"),
        )
        .order_by(OrdemServico.id.desc())
        .first()
    )


def _gerar_numero_os_finalizacao(db: Session) -> str:
    mes_ano = datetime.now(ATENDIMENTO_LOCAL_TZ).strftime("%Y%m")
    ultima_os = (
        db.query(OrdemServico)
        .filter(OrdemServico.numero_os.like(f"OS{mes_ano}%"))
        .order_by(OrdemServico.id.desc())
        .first()
    )

    sequencia = 1
    if ultima_os and ultima_os.numero_os:
        sufixo = "".join(ch for ch in str(ultima_os.numero_os)[-4:] if ch.isdigit())
        if len(sufixo) == 4:
            sequencia = int(sufixo) + 1

    while (
        db.query(OrdemServico)
        .filter(OrdemServico.numero_os == f"OS{mes_ano}{sequencia:04d}")
        .first()
    ):
        sequencia += 1
    return f"OS{mes_ano}{sequencia:04d}"


def _carregar_e_validar_agendamento_atendimento(
    db: Session,
    *,
    agendamento_id: int,
    paciente_id: int,
    clinica_id: Optional[int],
    atendimento_id_excluir: Optional[int] = None,
    lock: bool = False,
) -> Agendamento:
    duplicado_query = db.query(AtendimentoClinico).filter(
        AtendimentoClinico.agendamento_id == agendamento_id
    )
    if atendimento_id_excluir is not None:
        duplicado_query = duplicado_query.filter(AtendimentoClinico.id != atendimento_id_excluir)
    duplicado = duplicado_query.order_by(AtendimentoClinico.id.asc()).first()
    if duplicado:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"O agendamento #{agendamento_id} ja possui o atendimento "
                f"#{duplicado.id}. Abra o registro existente."
            ),
        )

    agendamento_query = db.query(Agendamento).filter(Agendamento.id == agendamento_id)
    if lock:
        agendamento_query = agendamento_query.with_for_update()
    agendamento = agendamento_query.first()
    if not agendamento:
        raise HTTPException(status_code=404, detail="Agendamento vinculado nao encontrado.")

    if not agendamento.paciente_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="O agendamento precisa ter um paciente antes de iniciar o atendimento.",
        )
    if int(agendamento.paciente_id) != int(paciente_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="O paciente do atendimento e diferente do paciente da Agenda.",
        )

    origem = _normalizar_origem_atendimento(getattr(agendamento, "origem_atendimento", None))
    if origem != ORIGEM_ATENDIMENTO_DOMICILIAR and not agendamento.clinica_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="O agendamento precisa ter uma clinica antes de iniciar o atendimento.",
        )
    if (
        clinica_id is not None
        and agendamento.clinica_id is not None
        and int(agendamento.clinica_id) != int(clinica_id)
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A clinica do atendimento e diferente da base operacional da Agenda.",
        )
    return agendamento


def _raise_atendimento_integrity_conflict(
    db: Session,
    *,
    agendamento_id: Optional[int],
    exc: IntegrityError,
    atendimento_id_excluir: Optional[int] = None,
) -> None:
    db.rollback()
    if agendamento_id:
        existente_query = db.query(AtendimentoClinico).filter(
            AtendimentoClinico.agendamento_id == agendamento_id
        )
        if atendimento_id_excluir is not None:
            existente_query = existente_query.filter(
                AtendimentoClinico.id != atendimento_id_excluir
            )
        existente = existente_query.order_by(AtendimentoClinico.id.asc()).first()
        if existente:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"O agendamento #{agendamento_id} ja possui o atendimento "
                    f"#{existente.id}. Abra o registro existente."
                ),
            ) from exc
    raise HTTPException(
        status_code=409,
        detail="O atendimento entrou em conflito com outro registro salvo simultaneamente.",
    ) from exc


def _commit_atendimento_com_guard(
    db: Session,
    *,
    agendamento_id: Optional[int],
    atendimento_id_excluir: Optional[int] = None,
) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        _raise_atendimento_integrity_conflict(
            db,
            agendamento_id=agendamento_id,
            exc=exc,
            atendimento_id_excluir=atendimento_id_excluir,
        )


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    raw = str(value).strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _to_local_naive(value: Optional[datetime]) -> Optional[datetime]:
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(ATENDIMENTO_LOCAL_TZ).replace(tzinfo=None)


def _to_iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    return str(value)


def _to_operational_iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, datetime):
        return _to_iso(value)
    if value.tzinfo is None:
        local_value = value.replace(tzinfo=ATENDIMENTO_LOCAL_TZ)
    else:
        local_value = value.astimezone(ATENDIMENTO_LOCAL_TZ)
    return local_value.isoformat()


def _formatar_data_hora(value: Any) -> str:
    if not value:
        return "-"
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y %H:%M")
    try:
        parsed = _parse_datetime(str(value))
        if parsed:
            return parsed.strftime("%d/%m/%Y %H:%M")
    except Exception:
        pass
    return str(value)


def _nome_arquivo_limpo(raw: str, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", (raw or "").strip()).strip("_")
    return cleaned or fallback


def _headers_download_pdf(filename: str) -> Dict[str, str]:
    return {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0",
    }


def _formatar_data_curta(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y")
    try:
        parsed = _parse_datetime(str(value))
        if parsed:
            return parsed.strftime("%d/%m/%Y")
    except Exception:
        pass
    return str(value)


def _pdf_escape(value: Any) -> str:
    if value is None:
        return ""
    return xml_escape(str(value))


def _texto_pdf_html(value: Any, fallback: str = "-") -> str:
    texto = str(value or "").strip()
    if not texto:
        return fallback
    return _pdf_escape(texto).replace("\r\n", "\n").replace("\n", "<br/>")


_DOCUMENTO_PDF_NEGRITO_RE = re.compile(r"\*\*(.+?)\*\*")
_DOCUMENTO_PDF_ITALICO_RE = re.compile(r"\*(.+?)\*")


def _renderizar_linha_documento_pdf(linha: str) -> str:
    """Aplica a marcacao markdown-lite (**negrito**, *italico*, "- item") de
    um bloco de corpo de documento clinico, escapando o texto ANTES de
    inserir qualquer tag real do ReportLab (o `**`/`*`/`-` do usuario nao sao
    caracteres XML-especiais, entao a ordem escape-depois-marca e segura)."""
    escapada = _pdf_escape(linha)
    formatada = _DOCUMENTO_PDF_NEGRITO_RE.sub(r"<b>\1</b>", escapada)
    formatada = _DOCUMENTO_PDF_ITALICO_RE.sub(r"<i>\1</i>", formatada)
    sem_espacos_iniciais = formatada.lstrip()
    if sem_espacos_iniciais.startswith("- "):
        indentacao = formatada[: len(formatada) - len(sem_espacos_iniciais)]
        formatada = f"{indentacao}• {sem_espacos_iniciais[2:]}"
    return formatada


def _texto_pdf_html_documento(value: Any, fallback: str = "-") -> str:
    """Igual a `_texto_pdf_html`, mas so para o corpo de documentos/templates
    clinicos: tambem converte **negrito**, *italico* e linhas "- item" para
    as tags equivalentes do ReportLab. Uso restrito a esse contexto para nao
    mudar o comportamento dos outros ~7 lugares que chamam `_texto_pdf_html`
    (orientacoes de prescricao, contexto clinico, etc.) - la, um asterisco
    digitado a toa nao deveria virar negrito de surpresa."""
    texto = str(value or "").strip()
    if not texto:
        return fallback
    linhas = texto.replace("\r\n", "\n").split("\n")
    return "<br/>".join(_renderizar_linha_documento_pdf(linha) for linha in linhas)


def _formatar_moeda_brl(value: Any) -> str:
    if value in (None, ""):
        return "-"
    try:
        numero = float(value)
    except Exception:
        return str(value)
    formatado = f"{numero:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {formatado}"


def _obter_branding_pdf_documento(
    db: Session,
    current_user: User,
) -> Dict[str, Any]:
    config_sistema = None
    config_usuario = None
    try:
        config_sistema = db.query(Configuracao).first()
    except Exception:
        db.rollback()
    try:
        config_usuario = db.query(ConfiguracaoUsuario).filter(
            ConfiguracaoUsuario.user_id == current_user.id
        ).first()
    except Exception:
        db.rollback()

    logomarca_bytes = None
    assinatura_bytes = None
    texto_rodape = None
    crmv = ""

    if config_sistema:
        if config_sistema.mostrar_logomarca and config_sistema.logomarca_dados:
            logomarca_bytes = config_sistema.logomarca_dados
        texto_rodape = config_sistema.texto_rodape_laudo

    if config_usuario and config_usuario.assinatura_dados:
        assinatura_bytes = config_usuario.assinatura_dados
    elif config_sistema and config_sistema.mostrar_assinatura and config_sistema.assinatura_dados:
        assinatura_bytes = config_sistema.assinatura_dados

    if config_usuario and config_usuario.crmv:
        crmv = config_usuario.crmv

    return {
        "nome_veterinario": current_user.nome or "",
        "crmv": crmv,
        "logomarca_bytes": logomarca_bytes,
        "assinatura_bytes": assinatura_bytes,
        "texto_rodape": texto_rodape,
    }


def _atualizar_documento_template_se_contexto_mudou(
    db: Session,
    atendimento: AtendimentoClinico,
    documento: DocumentoAtendimento,
    branding: Dict[str, Any],
) -> tuple[Optional[Paciente], Optional[Tutor], Optional[Clinica]]:
    return atualizar_documento_template_se_contexto_mudou_service(
        db,
        atendimento,
        documento,
        branding,
    )


def _montar_dados_pdf_documento(
    atendimento: AtendimentoClinico,
    paciente: Optional[Paciente],
    tutor: Optional[Tutor],
    clinica: Optional[Clinica],
    nome_veterinario: str,
) -> Dict[str, Any]:
    peso = _resolver_peso_referencia(atendimento, paciente)
    return {
        "paciente": {
            "nome": paciente.nome if paciente else "N/A",
            "especie": paciente.especie if paciente else (atendimento.especie or ""),
            "raca": paciente.raca if paciente else "",
            "sexo": normalizar_sexo_paciente(paciente.sexo if paciente else ""),
            "idade": idade_do_paciente(paciente, data_referencia=atendimento.data_atendimento),
            "peso": f"{peso:.1f}" if peso is not None else "",
            "tutor": tutor.nome if tutor else "",
            "solicitante": atendimento.criado_por_nome or nome_veterinario or "",
            "data_exame": _formatar_data_curta(atendimento.data_atendimento),
        },
        "clinica": clinica.nome if clinica else "",
    }


def _gerar_pdf_documento_atendimento_bytes(
    atendimento: AtendimentoClinico,
    paciente: Optional[Paciente],
    tutor: Optional[Tutor],
    clinica: Optional[Clinica],
    documento: DocumentoAtendimento,
    *,
    nome_veterinario: str = "",
    crmv: str = "",
    logomarca_bytes: Optional[bytes] = None,
    assinatura_bytes: Optional[bytes] = None,
    texto_rodape: Optional[str] = None,
) -> bytes:
    styles = create_pdf_styles()
    corpo_style = ParagraphStyle(
        "DocumentoAtendimentoCorpo",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10.8,
        leading=16,
        textColor=colors.HexColor("#111827"),
        spaceAfter=0,
    )
    dados_pdf = _montar_dados_pdf_documento(
        atendimento,
        paciente,
        tutor,
        clinica,
        nome_veterinario,
    )

    temp_files: List[str] = []
    try:
        temp_logo_path = None
        temp_assinatura_path = None
        if logomarca_bytes:
            temp_logo = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
            temp_logo.write(logomarca_bytes)
            temp_logo.close()
            temp_logo_path = temp_logo.name
            temp_files.append(temp_logo_path)
        if assinatura_bytes:
            temp_assinatura = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
            temp_assinatura.write(assinatura_bytes)
            temp_assinatura.close()
            temp_assinatura_path = temp_assinatura.name
            temp_files.append(temp_assinatura_path)

        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=15 * mm,
            rightMargin=15 * mm,
            topMargin=15 * mm,
            bottomMargin=15 * mm,
            title=documento.titulo or f"Documento - Atendimento {atendimento.id}",
        )

        story: List[Any] = []
        story.extend(
            criar_cabecalho(
                dados_pdf,
                temp_logo_path=temp_logo_path,
                titulo_principal=(documento.titulo or "Documento Clinico").upper(),
                mostrar_linha_ritmo=False,
                label_data_exame="Data",
            )
        )

        blocos = [bloco.strip() for bloco in re.split(r"\n\s*\n", documento.corpo or "") if bloco.strip()]
        if not blocos:
            blocos = ["Sem conteudo registrado."]
        for bloco in blocos:
            story.append(Paragraph(_texto_pdf_html_documento(bloco, ""), corpo_style))
            story.append(Spacer(1, 4 * mm))

        if nome_veterinario:
            story.extend(
                criar_secao_assinatura(
                    nome_veterinario,
                    crmv=crmv,
                    temp_assinatura_path=temp_assinatura_path,
                )
            )

        def add_footer(canvas_obj, pdf_doc):
            footer_todas_paginas(canvas_obj, pdf_doc, texto_rodape)

        doc.build(story, onFirstPage=add_footer, onLaterPages=add_footer)
        pdf = buffer.getvalue()
        buffer.close()
        return pdf
    finally:
        for temp_file in temp_files:
            try:
                os.unlink(temp_file)
            except OSError:
                pass


def _autenticar_usuario_pdf(
    request: Request,
    db: Session,
) -> User:
    if "access_token" in request.query_params:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nao use access_token na URL. Use Authorization: Bearer <token>.",
        )

    # PDFs must validate the same provider/session and local permissions as the
    # rest of Atendimento. Pass token explicitly: this is a direct call, so
    # FastAPI does not resolve the Depends default for us.
    return get_current_user(request=request, token=None, db=db)


def _excluir_anexo_registro(db: Session, anexo: AnexoAtendimento) -> None:
    remove_atendimento_attachment_file(anexo.caminho_arquivo)
    db.delete(anexo)


def _excluir_anexos_por_exame(db: Session, exame_id: int) -> None:
    anexos = db.query(AnexoAtendimento).filter(AnexoAtendimento.exame_id == exame_id).all()
    for anexo in anexos:
        _excluir_anexo_registro(db, anexo)


def _excluir_anexos_por_atendimento(db: Session, atendimento_id: int) -> None:
    anexos = db.query(AnexoAtendimento).filter(AnexoAtendimento.atendimento_id == atendimento_id).all()
    for anexo in anexos:
        _excluir_anexo_registro(db, anexo)


def _montar_story_cabecalho_atendimento(
    atendimento: AtendimentoClinico,
    paciente: Optional[Paciente],
    tutor: Optional[Tutor],
    clinica: Optional[Clinica],
    titulo: str,
) -> list:
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "AtendimentoPdfTitle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=16,
        spaceAfter=8,
    )
    normal = ParagraphStyle(
        "AtendimentoPdfNormal",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=10,
        leading=13,
    )

    story: list = []
    story.append(Paragraph(titulo, title_style))
    story.append(Paragraph(f"<b>Atendimento:</b> #{atendimento.id}", normal))
    story.append(Paragraph(f"<b>Data:</b> {_formatar_data_hora(atendimento.data_atendimento)}", normal))
    story.append(Paragraph(f"<b>Status:</b> {atendimento.status or '-'}", normal))
    story.append(Paragraph(f"<b>Paciente:</b> {(paciente.nome if paciente else '-')}", normal))
    story.append(Paragraph(f"<b>Tutor:</b> {(tutor.nome if tutor else '-')}", normal))
    story.append(Paragraph(f"<b>Clinica:</b> {(clinica.nome if clinica else '-')}", normal))
    story.append(Paragraph(f"<b>Veterinario:</b> {atendimento.criado_por_nome or '-'}", normal))
    story.append(Spacer(1, 4 * mm))
    return story


# Helpers compartilhados para prescricao (usados por PDF final e preview)
def _prescricao_criar_box_texto(titulo: str, corpo_html: str, bg: str, border: str) -> Table:
    """Cria box de texto com titulo e corpo HTML."""
    styles = create_pdf_styles()
    label_style = ParagraphStyle(
        "PrescricaoBoxLabel",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=7,
        textColor=colors.HexColor("#6b7280"),
        leading=10,
    )
    texto_style = ParagraphStyle(
        "PrescricaoBoxTexto",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9.5,
        textColor=colors.HexColor("#111827"),
        leading=13,
    )
    conteudo = [
        Paragraph(
            f"<font name='Helvetica-Bold' size='7' color='#6b7280'>{_pdf_escape(titulo.upper())}</font>",
            label_style,
        ),
        Spacer(1, 1.2 * mm),
        Paragraph(corpo_html, texto_style),
    ]
    tabela = Table([[conteudo]], colWidths=[180 * mm])
    tabela.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor(border)),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(bg)),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return tabela


def _prescricao_criar_card_info(label: str, valor: str) -> Paragraph:
    """Cria card de informacao para item de prescricao."""
    styles = create_pdf_styles()
    obs_style = ParagraphStyle(
        "PrescricaoCardObs",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9.2,
        textColor=colors.HexColor("#111827"),
        leading=12.5,
    )
    return Paragraph(
        f"<font name='Helvetica-Bold' size='7' color='#6b7280'>{_pdf_escape(label.upper())}</font><br/>{_texto_pdf_html(valor)}",
        obs_style,
    )


def _prescricao_criar_card_prescricao(idx: int, nome: str, dose: str, frequencia: str, duracao: str, via: str, apresentacao: str = "", instrucoes: str = "") -> Table:
    """Cria card de prescricao (item) - versao generica."""
    styles = create_pdf_styles()
    titulo_style = ParagraphStyle(
        "PrescricaoItemTitulo",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=11.5,
        textColor=colors.HexColor("#111827"),
        leading=14,
        spaceAfter=1,
    )
    obs_style = ParagraphStyle(
        "PrescricaoItemObs",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9.2,
        textColor=colors.HexColor("#111827"),
        leading=12.5,
    )

    nome_item = nome.strip() or "Medicamento sem nome"
    formula_manipulada = "formula manipulada" in nome_item.lower()
    apres = apresentacao.strip()
    if formula_manipulada and not apres:
        apres = "Formula manipulada"
    titulo_html = f"{idx}. {_pdf_escape(nome_item)}"
    if formula_manipulada:
        titulo_html += " <font name='Helvetica-Bold' size='7' color='#9a3412'>FORMULA MANIPULADA</font>"

    info_table = Table(
        [[
            _prescricao_criar_card_info("Dose", dose or "-"),
            _prescricao_criar_card_info("Frequencia", frequencia or "-"),
            _prescricao_criar_card_info("Duracao", duracao or "-"),
            _prescricao_criar_card_info("Via", via or "-"),
        ]],
        colWidths=[45 * mm, 45 * mm, 45 * mm, 45 * mm],
    )
    info_table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#d1d5db")),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e5e7eb")),
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))

    conteudo: List[Any] = [Paragraph(titulo_html, titulo_style)]
    if apres:
        conteudo.extend([
            Spacer(1, 1.2 * mm),
            Paragraph(
                f"<font name='Helvetica-Bold' size='7' color='#6b7280'>APRESENTACAO</font><br/>{_texto_pdf_html(apres)}",
                obs_style,
            ),
        ])
    conteudo.extend([Spacer(1, 2 * mm), info_table])
    if instrucoes.strip():
        conteudo.extend([
            Spacer(1, 2.2 * mm),
            Paragraph(
                f"<font name='Helvetica-Bold' size='7' color='#6b7280'>INSTRUCOES ESPECIFICAS</font><br/>{_texto_pdf_html(instrucoes)}",
                obs_style,
            ),
        ])
    card_bg = "#fff7ed" if formula_manipulada else "#fafafa"
    card_border = "#fdba74" if formula_manipulada else "#e5e7eb"
    card = Table([[conteudo]], colWidths=[180 * mm])
    card.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor(card_border)),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(card_bg)),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return card


def _gerar_pdf_prescricao_bytes(
    atendimento: AtendimentoClinico,
    paciente: Optional[Paciente],
    tutor: Optional[Tutor],
    clinica: Optional[Clinica],
    prescricao: PrescricaoClinica,
    itens: List[PrescricaoItem],
    *,
    nome_veterinario: str = "",
    crmv: str = "",
    logomarca_bytes: Optional[bytes] = None,
    assinatura_bytes: Optional[bytes] = None,
    texto_rodape: Optional[str] = None,
) -> bytes:
    styles = create_pdf_styles()
    resumo_label_style = ParagraphStyle(
        "PrescricaoResumoLabel",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=7,
        textColor=colors.HexColor("#6b7280"),
        leading=10,
    )
    card_texto_style = ParagraphStyle(
        "PrescricaoCardTexto",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9.5,
        textColor=colors.HexColor("#111827"),
        leading=13,
    )
    item_titulo_style = ParagraphStyle(
        "PrescricaoItemTitulo",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=11.5,
        textColor=colors.HexColor("#111827"),
        leading=14,
        spaceAfter=1,
    )
    data_referencia = atendimento.data_atendimento if isinstance(atendimento.data_atendimento, datetime) else datetime.now()
    peso_referencia = _resolver_peso_referencia(atendimento, paciente)
    dados_pdf = {
        "paciente": {
            "nome": paciente.nome if paciente else "N/A",
            "especie": paciente.especie if paciente else "",
            "raca": paciente.raca if paciente else "",
            "sexo": normalizar_sexo_paciente(paciente.sexo if paciente else ""),
            "idade": idade_do_paciente(paciente, data_referencia=atendimento.data_atendimento),
            "peso": f"{peso_referencia:.1f}" if peso_referencia is not None else "",
            "tutor": tutor.nome if tutor else "",
            "solicitante": atendimento.criado_por_nome or nome_veterinario or "",
            "data_exame": data_referencia.strftime("%d/%m/%Y"),
        },
        "clinica": clinica.nome if clinica else "",
    }

    orientacoes_bloco: List[str] = []
    if (prescricao.orientacoes_gerais or "").strip():
        orientacoes_bloco.append(_texto_pdf_html(prescricao.orientacoes_gerais, ""))
    if prescricao.retorno_dias:
        orientacoes_bloco.append(f"<b>Retorno sugerido:</b> {prescricao.retorno_dias} dia(s)")

    temp_files: List[str] = []
    try:
        temp_logo_path = None
        temp_assinatura_path = None
        if logomarca_bytes:
            temp_logo = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
            temp_logo.write(logomarca_bytes)
            temp_logo.close()
            temp_logo_path = temp_logo.name
            temp_files.append(temp_logo_path)
        if assinatura_bytes:
            temp_assinatura = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
            temp_assinatura.write(assinatura_bytes)
            temp_assinatura.close()
            temp_assinatura_path = temp_assinatura.name
            temp_files.append(temp_assinatura_path)

        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=15 * mm,
            rightMargin=15 * mm,
            topMargin=15 * mm,
            bottomMargin=15 * mm,
            title=f"Receita - Atendimento {atendimento.id}",
        )

        story: List[Any] = []
        story.extend(
            criar_cabecalho(
                dados_pdf,
                temp_logo_path=temp_logo_path,
                titulo_principal="RECEITA VETERINARIA",
                mostrar_linha_ritmo=False,
                label_data_exame="Data",
            )
        )

        if orientacoes_bloco:
            story.append(
                _prescricao_criar_box_texto(
                    "Orientacoes gerais",
                    "<br/><br/>".join(orientacoes_bloco),
                    "#fafafa",
                    "#e5e7eb",
                )
            )
            story.append(Spacer(1, 4 * mm))

        story.append(criar_titulo_secao("ITENS PRESCRITOS"))
        if itens:
            for idx, item in enumerate(itens, start=1):
                story.append(_prescricao_criar_card_prescricao(
                    idx,
                    item.medicamento_nome or "",
                    item.dose or "",
                    item.frequencia or "",
                    item.duracao or "",
                    item.via or "",
                    item.apresentacao_selecionada or "",
                    item.instrucoes or "",
                ))
                story.append(Spacer(1, 3 * mm))
        else:
            story.append(Paragraph("Nenhum item de medicacao foi registrado.", card_texto_style))

        if nome_veterinario:
            story.extend(criar_secao_assinatura(nome_veterinario, crmv=crmv, temp_assinatura_path=temp_assinatura_path))

        def add_footer(canvas_obj, pdf_doc):
            footer_todas_paginas(canvas_obj, pdf_doc, texto_rodape)

        doc.build(story, onFirstPage=add_footer, onLaterPages=add_footer)
        pdf = buffer.getvalue()
        buffer.close()
        return pdf
    finally:
        for temp_file in temp_files:
            try:
                os.unlink(temp_file)
            except OSError:
                pass


def _gerar_pdf_exames_bytes(
    atendimento: AtendimentoClinico,
    paciente: Optional[Paciente],
    tutor: Optional[Tutor],
    clinica: Optional[Clinica],
    exames: List[Exame],
    *,
    nome_veterinario: str = "",
    crmv: str = "",
    logomarca_bytes: Optional[bytes] = None,
    assinatura_bytes: Optional[bytes] = None,
    texto_rodape: Optional[str] = None,
) -> bytes:
    styles = create_pdf_styles()
    resumo_label_style = ParagraphStyle(
        "SolicitacaoResumoLabel",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=7,
        textColor=colors.HexColor("#6b7280"),
        leading=10,
    )
    card_texto_style = ParagraphStyle(
        "SolicitacaoExameTexto",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9.5,
        textColor=colors.HexColor("#111827"),
        leading=13,
    )
    exame_item_style = ParagraphStyle(
        "SolicitacaoExameItem",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=11,
        textColor=colors.HexColor("#111827"),
        leading=14,
        spaceAfter=2,
    )

    def _criar_box_texto(titulo: str, corpo_html: str, bg: str, border: str) -> Table:
        conteudo = [
            Paragraph(
                f"<font name='Helvetica-Bold' size='7' color='#6b7280'>{_pdf_escape(titulo.upper())}</font>",
                resumo_label_style,
            ),
            Spacer(1, 1.2 * mm),
            Paragraph(corpo_html, card_texto_style),
        ]
        tabela = Table([[conteudo]], colWidths=[180 * mm])
        tabela.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor(border)),
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(bg)),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]))
        return tabela

    datas_solicitacao_validas = [
        exame.data_solicitacao
        for exame in exames
        if isinstance(exame.data_solicitacao, datetime)
    ]
    if datas_solicitacao_validas:
        data_solicitacao_ref = min(datas_solicitacao_validas)
    elif isinstance(atendimento.data_atendimento, datetime):
        data_solicitacao_ref = atendimento.data_atendimento
    else:
        data_solicitacao_ref = datetime.now()

    peso_referencia = _resolver_peso_referencia(atendimento, paciente)
    dados_pdf = {
        "paciente": {
            "nome": paciente.nome if paciente else "N/A",
            "especie": paciente.especie if paciente else "",
            "raca": paciente.raca if paciente else "",
            "sexo": normalizar_sexo_paciente(paciente.sexo if paciente else ""),
            "idade": idade_do_paciente(paciente, data_referencia=atendimento.data_atendimento),
            "peso": f"{peso_referencia:.1f}" if peso_referencia is not None else "",
            "tutor": tutor.nome if tutor else "",
            "solicitante": atendimento.criado_por_nome or nome_veterinario or "",
            "data_exame": data_solicitacao_ref.strftime("%d/%m/%Y"),
        },
        "clinica": clinica.nome if clinica else "",
    }

    contexto_clinico = []
    if atendimento.queixa_principal:
        contexto_clinico.append(f"<b>Queixa principal:</b> {_texto_pdf_html(atendimento.queixa_principal, '')}")

    temp_files: List[str] = []
    try:
        temp_logo_path = None
        temp_assinatura_path = None
        if logomarca_bytes:
            temp_logo = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
            temp_logo.write(logomarca_bytes)
            temp_logo.close()
            temp_logo_path = temp_logo.name
            temp_files.append(temp_logo_path)
        if assinatura_bytes:
            temp_assinatura = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
            temp_assinatura.write(assinatura_bytes)
            temp_assinatura.close()
            temp_assinatura_path = temp_assinatura.name
            temp_files.append(temp_assinatura_path)

        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=15 * mm,
            rightMargin=15 * mm,
            topMargin=15 * mm,
            bottomMargin=15 * mm,
            title=f"Solicitacao de exames - Atendimento {atendimento.id}",
        )

        story: List[Any] = []
        story.extend(
            criar_cabecalho(
                dados_pdf,
                temp_logo_path=temp_logo_path,
                titulo_principal="SOLICITACAO DE EXAMES",
                mostrar_linha_ritmo=False,
                label_data_exame="Data",
            )
        )

        if contexto_clinico:
            story.append(
                _criar_box_texto(
                    "Contexto clinico",
                    "<br/><br/>".join(contexto_clinico),
                    "#fafafa",
                    "#e5e7eb",
                )
            )
            story.append(Spacer(1, 4 * mm))

        story.append(criar_titulo_secao("EXAMES SOLICITADOS"))
        if exames:
            for idx, exame in enumerate(exames, start=1):
                nome_exame = (exame.tipo_exame or "").strip() or "Exame sem descricao"
                story.append(Paragraph(f"{idx}. {_pdf_escape(nome_exame)}", exame_item_style))
        else:
            story.append(Paragraph("Nenhum exame solicitado para este atendimento.", card_texto_style))

        if nome_veterinario:
            story.extend(criar_secao_assinatura(nome_veterinario, crmv=crmv, temp_assinatura_path=temp_assinatura_path))

        def add_footer(canvas_obj, pdf_doc):
            footer_todas_paginas(canvas_obj, pdf_doc, texto_rodape)

        doc.build(story, onFirstPage=add_footer, onLaterPages=add_footer)
        pdf = buffer.getvalue()
        buffer.close()
        return pdf
    finally:
        for temp_file in temp_files:
            try:
                os.unlink(temp_file)
            except OSError:
                pass


def _resolver_tutor_paciente(db: Session, paciente_id: int) -> Optional[int]:
    paciente = db.query(Paciente).filter(Paciente.id == paciente_id).first()
    if not paciente:
        raise HTTPException(status_code=404, detail="Paciente nao encontrado.")
    if paciente.mesclado_em_id:
        raise HTTPException(409, f"Paciente mesclado. Selecione o cadastro principal #{paciente.mesclado_em_id}.")
    if paciente.tutor_id:
        from app.services.tutor_identidade_service import exigir_tutor_utilizavel
        exigir_tutor_utilizavel(db, paciente.tutor_id)
    return paciente.tutor_id


def _resolver_especie_paciente(db: Session, paciente_id: int) -> Optional[str]:
    paciente = db.query(Paciente).filter(Paciente.id == paciente_id).first()
    if not paciente:
        return None
    return (paciente.especie or "").strip() or None


def _map_exame(exame: Exame) -> dict:
    return {
        "id": exame.id,
        "catalogo_exame_id": exame.catalogo_exame_id,
        "painel_exame_id": exame.painel_exame_id,
        "painel_exame_nome": exame.painel_exame_nome or "",
        "tipo_exame": exame.tipo_exame,
        "categoria_exame": exame.categoria_exame or "",
        "preparo": exame.preparo or "",
        "prioridade": exame.prioridade or "Rotina",
        "status": exame.status,
        "resultado": exame.resultado or "",
        "valor_referencia": exame.valor_referencia or "",
        "unidade": exame.unidade or "",
        "observacoes": exame.observacoes or "",
        "valor": exame.valor or 0,
        "laudo_id": exame.laudo_id,
        "data_solicitacao": _to_iso(exame.data_solicitacao),
        "data_resultado": _to_operational_iso(exame.data_resultado),
        "visualizado_portal_em": _to_iso(exame.visualizado_portal_em),
    }


def _normalizar_tipo_exame_portal_externo(value: Optional[str]) -> str:
    raw = (value or "").strip()
    if not raw:
        return "Exame"
    normalizado = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode("ascii")
    normalizado = " ".join(normalizado.lower().split())
    if normalizado in {"ecg", "eletro", "eletrocardiograma"} or "eletrocardio" in normalizado:
        return "Eletrocardiograma"
    return raw


def _normalizar_status(value: Optional[str]) -> str:
    status = (value or "").strip().lower()
    if not status:
        return ""
    normalizado = unicodedata.normalize("NFKD", status)
    normalizado = "".join(ch for ch in normalizado if not unicodedata.combining(ch))
    normalizado = normalizado.replace("\u00ad", "")
    return " ".join(normalizado.split())


def _status_exame_concluido(value: Optional[str]) -> bool:
    status = _normalizar_status(value)
    return status in {"concluido", "concluida"} or status.startswith("concluid")


def _status_exame_regressao_bloqueada(value: Optional[str]) -> bool:
    """Status que nao pode ser rebaixado por efeito colateral de upload."""
    return _status_exame_concluido(value) or is_portal_released_status(value)


def _contar_anexos_por_exame(db: Session, atendimento_id: int) -> dict[int, int]:
    """Contagem de anexos por exame em uma consulta, para derivar status."""
    linhas = (
        db.query(AnexoAtendimento.exame_id, func.count(AnexoAtendimento.id))
        .filter(
            AnexoAtendimento.atendimento_id == atendimento_id,
            AnexoAtendimento.exame_id.isnot(None),
        )
        .group_by(AnexoAtendimento.exame_id)
        .all()
    )
    return {int(exame_id): int(total) for exame_id, total in linhas if exame_id is not None}


def _derivar_status_exame(
    *,
    status_atual: Optional[str],
    resultado: Optional[str],
    total_anexos: int,
) -> str:
    """Status do exame e propriedade do servidor.

    A liberacao no portal e preservada porque e o valor exato que autoriza o
    acesso da clinica parceira; revogar exige acao explicita.
    """
    if is_portal_released_status(status_atual):
        return str(status_atual)
    if (resultado or "").strip():
        return "Concluido"
    if total_anexos > 0:
        return "Em andamento"
    return "Solicitado"


def _motivo_bloqueio_exclusao_exame(exame: Exame, total_anexos: int) -> Optional[str]:
    """Motivo para recusar a exclusao de um exame do prontuario."""
    if exame.laudo_id:
        return (
            f"O exame #{exame.id} possui laudo vinculado (#{exame.laudo_id}) e nao pode ser "
            "excluido pelo prontuario."
        )
    if is_portal_released_status(exame.status):
        return (
            f"O exame #{exame.id} esta liberado no portal da clinica parceira. Revogue a "
            "liberacao antes de excluir."
        )
    if total_anexos > 0:
        return (
            f"O exame #{exame.id} possui {total_anexos} arquivo(s) anexado(s). Remova os "
            "arquivos antes de excluir o exame."
        )
    return None


def _anexo_eh_pdf(anexo: AnexoAtendimento) -> bool:
    mime = (anexo.mime_type or "").strip().lower()
    nome = (anexo.nome_original or anexo.url or anexo.caminho_arquivo or "").strip().lower()
    return mime == "application/pdf" or nome.endswith(".pdf")


def _serialize_anexo(anexo: AnexoAtendimento) -> dict:
    download_url = None
    if anexo.caminho_arquivo:
        download_url = f"/api/v1/atendimentos/anexos/{anexo.id}/arquivo"

    mime = anexo.mime_type or ""
    preview_disponivel = bool(
        download_url and (mime.startswith("image/") or mime == "application/pdf")
    )

    return {
        "id": anexo.id,
        "atendimento_id": anexo.atendimento_id,
        "exame_id": anexo.exame_id,
        "evolucao_id": getattr(anexo, "evolucao_id", None),
        "tipo": anexo.tipo,
        "descricao": anexo.descricao or "",
        "url": anexo.url,
        "nome_original": anexo.nome_original or "",
        "tamanho": anexo.tamanho,
        "mime_type": mime,
        "origem": anexo.origem or "externo",
        "download_url": download_url,
        "preview_disponivel": preview_disponivel,
        "created_at": _to_iso(anexo.created_at),
    }


def _find_existing_upload_anexo_by_dedupe_key(
    db: Session,
    *,
    atendimento_id: int,
    dedupe_key: str,
) -> Optional[AnexoAtendimento]:
    return (
        db.query(AnexoAtendimento)
        .filter(
            AnexoAtendimento.atendimento_id == atendimento_id,
            AnexoAtendimento.origem == "upload",
            AnexoAtendimento.dedupe_key == dedupe_key,
        )
        .order_by(AnexoAtendimento.id.desc())
        .first()
    )


def _parse_upload_metrics_date(value: Optional[str], param_name: str) -> Optional[date]:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"{param_name} invalido. Use o formato YYYY-MM-DD.",
        ) from exc


def _require_admin_cleanup_access(current_user: User) -> None:
    if not current_user.tem_papel("admin"):
        raise HTTPException(
            status_code=403,
            detail="Acesso negado. Apenas administradores podem executar cleanup de metricas.",
        )


def _registrar_upload_dedupe_metrica(
    db: Session,
    *,
    atendimento: AtendimentoClinico,
    evento: str,
    dedupe_key: Optional[str] = None,
) -> None:
    if evento not in UPLOAD_DEDUPE_EVENTS_VALIDOS:
        return
    if not isinstance(db, Session):
        return
    try:
        db.add(
            UploadDedupeMetrica(
                atendimento_id=atendimento.id,
                clinica_id=atendimento.clinica_id,
                evento=evento,
                dedupe_key=(dedupe_key or "").strip()[:120] or None,
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.exception(
            "Falha ao registrar metrica de upload dedupe (atendimento_id=%s, clinica_id=%s, evento=%s)",
            atendimento.id,
            atendimento.clinica_id,
            evento,
        )


def _map_prescricao_item(item: PrescricaoItem) -> dict:
    return {
        "id": item.id,
        "medicamento_id": item.medicamento_id,
        "medicamento_nome": item.medicamento_nome,
        "apresentacao_selecionada": item.apresentacao_selecionada or "",
        "dose": item.dose or "",
        "frequencia": item.frequencia or "",
        "duracao": item.duracao or "",
        "via": item.via or "",
        "instrucoes": item.instrucoes or "",
        "ordem": item.ordem or 0,
        "dose_mg_kg": item.dose_mg_kg or "",
        "peso_referencia_kg": item.peso_referencia_kg or "",
        "unidade_dose_calculo": item.unidade_dose_calculo or "",
        "concentracao_personalizada": item.concentracao_personalizada or "",
    }


def _obter_nome_medicamento(
    medicamento_id: Optional[int],
    medicamento_nome: Optional[str],
    medicamentos_por_id: Dict[int, "Medicamento"],
) -> str:
    nome_limpo = (medicamento_nome or "").strip()
    if nome_limpo:
        return nome_limpo
    if medicamento_id:
        medicamento = medicamentos_por_id.get(medicamento_id)
        if medicamento:
            return medicamento.nome
    raise HTTPException(status_code=422, detail="Informe o nome do medicamento.")


# === ADENDOS E RECEITAS ===


def _normalizar_tipo_adendo(value: Any) -> str:
    token = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not token:
        return "evolucao"
    if token in ADENDO_TIPOS_CANONICOS:
        return token
    permitidos = ", ".join(sorted(ADENDO_TIPOS_CANONICOS))
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=f"Tipo de adendo invalido. Use um de: {permitidos}.",
    )


def _tipo_adendo(evolucao: EvolucaoClinica) -> str:
    return (getattr(evolucao, "tipo", None) or "evolucao").strip().lower() or "evolucao"


def _titulo_adendo(evolucao: EvolucaoClinica) -> str:
    titulo = (getattr(evolucao, "titulo", None) or "").strip()
    if titulo:
        return titulo
    return ADENDO_TIPO_LABELS.get(_tipo_adendo(evolucao), ADENDO_TIPO_LABELS["evolucao"])


def _serialize_adendo(
    evolucao: EvolucaoClinica,
    *,
    anexos: Optional[List[dict]] = None,
    prescricao_id: Optional[int] = None,
) -> dict:
    return {
        "id": evolucao.id,
        "atendimento_id": evolucao.atendimento_id,
        "tipo": _tipo_adendo(evolucao),
        "titulo": _titulo_adendo(evolucao),
        "descricao": evolucao.descricao or "",
        "sinais_vitais": evolucao.sinais_vitais or "",
        "data_evolucao": _to_iso(evolucao.data_evolucao),
        "pos_conclusao": int(getattr(evolucao, "pos_conclusao", 0) or 0),
        "responsavel_id": evolucao.responsavel_id,
        "responsavel_nome": evolucao.responsavel_nome or "",
        "anexos": anexos or [],
        "prescricao_id": prescricao_id,
        "created_at": _to_iso(evolucao.created_at),
    }


def _carregar_adendo_do_atendimento(
    db: Session,
    *,
    atendimento_id: int,
    adendo_id: Any,
) -> Optional[EvolucaoClinica]:
    if adendo_id is None:
        return None
    adendo = (
        db.query(EvolucaoClinica)
        .filter(
            EvolucaoClinica.id == int(adendo_id),
            EvolucaoClinica.atendimento_id == atendimento_id,
        )
        .first()
    )
    if not adendo:
        raise HTTPException(status_code=404, detail="Adendo nao encontrado para este atendimento.")
    return adendo


def _sequencia_prescricao(prescricao: PrescricaoClinica) -> int:
    return int(getattr(prescricao, "sequencia", 1) or 1)


def _proxima_sequencia_prescricao(db: Session, atendimento_id: int) -> int:
    maior = (
        db.query(func.max(PrescricaoClinica.sequencia))
        .filter(PrescricaoClinica.atendimento_id == atendimento_id)
        .scalar()
    )
    return int(maior or 0) + 1


def _buscar_prescricao_principal(db: Session, atendimento_id: int) -> Optional[PrescricaoClinica]:
    """Receita do dia da consulta (`sequencia = 1`).

    A ordenacao por sequencia (e nao por id) mantem o alvo estavel depois que
    o atendimento passa a ter receitas complementares, e o fallback pela menor
    sequencia cobre bases anteriores a migracao 20260910_83."""
    return (
        db.query(PrescricaoClinica)
        .filter(PrescricaoClinica.atendimento_id == atendimento_id)
        .order_by(PrescricaoClinica.sequencia.asc(), PrescricaoClinica.id.asc())
        .first()
    )


def _carregar_prescricao_do_atendimento(
    db: Session,
    *,
    atendimento_id: int,
    prescricao_id: int,
) -> PrescricaoClinica:
    prescricao = (
        db.query(PrescricaoClinica)
        .filter(
            PrescricaoClinica.id == prescricao_id,
            PrescricaoClinica.atendimento_id == atendimento_id,
        )
        .first()
    )
    if not prescricao:
        raise HTTPException(status_code=404, detail="Receita nao encontrada para este atendimento.")
    return prescricao


def _snapshot_prescricao(db: Session, prescricao: Optional[PrescricaoClinica], *, reler: bool = False) -> dict:
    if prescricao is None:
        return {"orientacoes_gerais": "", "retorno_dias": None, "itens": []}
    if reler:
        db.refresh(prescricao)
    itens = (db.query(PrescricaoItem).filter(PrescricaoItem.prescricao_id == prescricao.id)
             .populate_existing().order_by(PrescricaoItem.ordem.asc(), PrescricaoItem.id.asc()).all())
    return {
        "orientacoes_gerais": prescricao.orientacoes_gerais or "",
        "retorno_dias": prescricao.retorno_dias,
        "itens": [_map_prescricao_item(item) for item in itens],
    }


def _auditar_edicao_prescricao(
    db: Session, *, current_user: User, atendimento: AtendimentoClinico,
    prescricao: PrescricaoClinica, antes: dict, request: Optional[Request] = None,
) -> None:
    db.flush()
    depois = _snapshot_prescricao(db, prescricao)
    alteracoes = {campo: {"antes": antes[campo], "depois": depois[campo]}
                  for campo in antes if antes[campo] != depois[campo]}
    if not alteracoes:
        return
    registrar_auditoria(
        db=db, current_user=current_user, modulo="atendimento", entidade="prescricao_clinica",
        entidade_id=prescricao.id,
        acao="EDITAR_RECEITA_EMITIDA" if prescricao.emitida_em else "PRESCRICAO_ATUALIZADA",
        descricao=f"Receita {_sequencia_prescricao(prescricao)} do atendimento #{atendimento.id} atualizada.",
        detalhes={"atendimento_id": atendimento.id, "prescricao_id": prescricao.id,
                  "sequencia": _sequencia_prescricao(prescricao),
                  "emitida_em": _to_operational_iso(prescricao.emitida_em),
                  "alteracoes": alteracoes},
        request=request,
    )


def _marcar_receita_emitida(db: Session, prescricao: PrescricaoClinica) -> None:
    """Primeira geracao do PDF congela a receita como documento entregue."""
    if prescricao.emitida_em:
        return
    prescricao.emitida_em = datetime.now(ATENDIMENTO_LOCAL_TZ)
    db.commit()


def _sync_exames(
    db: Session,
    atendimento: AtendimentoClinico,
    exames_payload: List[ExameSolicitacaoPayload],
    current_user: User,
) -> None:
    existentes = {
        exame.id: exame
        for exame in db.query(Exame).filter(Exame.atendimento_id == atendimento.id).all()
    }
    anexos_por_exame = _contar_anexos_por_exame(db, atendimento.id)
    excluir_ids: list[int] = []

    # Uma query por id distinto para todo o payload, em vez de uma por item
    # (o mesmo id de catalogo/painel se repete em todo autosave, ja que o
    # cliente reenvia os campos denormalizados a cada PUT independente do
    # que de fato mudou - buildAtendimentoPayload sempre inclui `exames`).
    catalogo_ids = {item.catalogo_exame_id for item in exames_payload if item.catalogo_exame_id}
    catalogos_por_id = (
        {c.id: c for c in db.query(CatalogoExame).filter(CatalogoExame.id.in_(catalogo_ids)).all()}
        if catalogo_ids
        else {}
    )
    painel_ids = {item.painel_exame_id for item in exames_payload if item.painel_exame_id}
    paineis_por_id = (
        {p.id: p for p in db.query(PainelExame).filter(PainelExame.id.in_(painel_ids)).all()}
        if painel_ids
        else {}
    )

    for payload in exames_payload:
        if payload.destroy:
            # Exclusao acontece somente por marcacao explicita. Item novo ou ja
            # inexistente e ignorado, para que repetir o save seja idempotente.
            if payload.id and payload.id in existentes:
                excluir_ids.append(payload.id)
            continue

        exame = None
        if payload.id is not None:
            exame = existentes.get(payload.id)
            if exame is None:
                # Um id so existe para registros ja persistidos. Recriar o
                # exame quando chega um autosave atrasado de outra aba (ou
                # logo apos uma exclusao) transforma uma atualizacao velha em
                # um novo item e faz a solicitacao voltar duplicada no PDF.
                logger.warning(
                    "Payload de exame ignorado por id inexistente (atendimento_id=%s, exame_id=%s)",
                    atendimento.id,
                    payload.id,
                )
                continue
        campos_exame_antes = (
            {
                "resultado": exame.resultado,
                "valor_referencia": exame.valor_referencia,
                "unidade": exame.unidade,
                "prioridade": exame.prioridade,
                "status": exame.status,
                "observacoes": exame.observacoes,
            }
            if exame is not None
            else None
        )

        if exame is None:
            exame = Exame(
                atendimento_id=atendimento.id,
                paciente_id=atendimento.paciente_id,
                criado_por_id=current_user.id,
                criado_por_nome=current_user.nome,
            )
            db.add(exame)

        catalogo_exame = catalogos_por_id.get(payload.catalogo_exame_id) if payload.catalogo_exame_id else None
        painel_exame = paineis_por_id.get(payload.painel_exame_id) if payload.painel_exame_id else None

        exame.atendimento_id = atendimento.id
        exame.paciente_id = atendimento.paciente_id
        exame.catalogo_exame_id = catalogo_exame.id if catalogo_exame else None
        exame.painel_exame_id = painel_exame.id if painel_exame else None
        exame.painel_exame_nome = (
            (payload.painel_exame_nome or "").strip()
            or (painel_exame.nome if painel_exame else "")
            or None
        )
        exame.tipo_exame = (
            (payload.tipo_exame or "").strip()
            or (catalogo_exame.nome if catalogo_exame else "").strip()
        )
        exame.categoria_exame = (
            (payload.categoria_exame or "").strip()
            or (catalogo_exame.categoria if catalogo_exame else "")
            or None
        )
        exame.preparo = (
            (payload.preparo or "").strip()
            or (catalogo_exame.preparo if catalogo_exame else "")
            or None
        )
        exame.prioridade = (payload.prioridade or "Rotina").strip() or "Rotina"
        exame.status = _derivar_status_exame(
            status_atual=exame.status,
            resultado=payload.resultado,
            total_anexos=anexos_por_exame.get(payload.id or 0, 0),
        )
        if not is_portal_released_status(exame.status):
            # Mesmo cuidado que _derivar_status_exame ja tem com o status:
            # enquanto o exame esta liberado no portal, o conteudo que a
            # clinica parceira/tutor ja visualizou (resultado, referencia,
            # unidade, observacoes) nao pode ser sobrescrito por um
            # save/autosave sem trilha nem nova notificacao - so a acao
            # explicita de revogar reabre esses campos para edicao.
            exame.resultado = (payload.resultado or "").strip() or None
            exame.valor_referencia = (payload.valor_referencia or "").strip() or None
            exame.unidade = (payload.unidade or "").strip() or None
            exame.observacoes = (
                (payload.observacoes or "").strip()
                or (catalogo_exame.observacoes_padrao if catalogo_exame else "")
                or ""
            )
        exame.valor = payload.valor if payload.valor not in (None, "") else (catalogo_exame.valor_padrao if catalogo_exame else 0)
        if payload.laudo_id and payload.laudo_id != exame.laudo_id:
            # O frontend so faz round-trip do valor ja hidratado, mas o payload
            # e a verdade do cliente - um laudo_id de outro paciente nao pode
            # ser aceito (exporia o exame como "liberado" via o laudo alheio no
            # portal da clinica parceira). Sem laudo valido para este paciente,
            # mantem o vinculo atual em vez de aceitar o valor recebido.
            laudo_valido = (
                db.query(Laudo)
                .filter(Laudo.id == payload.laudo_id, Laudo.paciente_id == atendimento.paciente_id)
                .first()
            )
            exame.laudo_id = payload.laudo_id if laudo_valido else exame.laudo_id
        elif not payload.laudo_id and exame.laudo_id:
            # Payload vazio para um exame que ja tem laudo vinculado no banco:
            # o atendimento nunca oferece um jeito de desvincular por aqui (o
            # vinculo so e criado por laudos.py) - um payload vazio aqui e
            # sempre um snapshot desatualizado do cliente (o vinculo foi
            # criado por outra aba/sessao enquanto este atendimento estava
            # aberto), nunca uma intencao real de desvincular. Mesmo cuidado
            # que _derivar_status_exame ja tem com o status.
            pass
        else:
            exame.laudo_id = payload.laudo_id
        exame.data_solicitacao = exame.data_solicitacao or datetime.now()
        exame.data_resultado = _to_local_naive(_parse_datetime(payload.data_resultado)) if payload.data_resultado else exame.data_resultado
        if _status_exame_concluido(exame.status) and exame.data_resultado is None:
            exame.data_resultado = datetime.now()

        if campos_exame_antes is not None:
            for campo, valor_anterior in campos_exame_antes.items():
                _registrar_ajuste_exame(
                    db,
                    exame=exame,
                    atendimento_id=atendimento.id,
                    campo=campo,
                    valor_anterior=valor_anterior,
                    valor_novo=getattr(exame, campo),
                    current_user=current_user,
                )

    for exame_id in excluir_ids:
        exame = existentes[exame_id]
        motivo = _motivo_bloqueio_exclusao_exame(exame, anexos_por_exame.get(exame_id, 0))
        if motivo:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=motivo)
        _excluir_anexos_por_exame(db, exame.id)
        db.delete(exame)


def _sync_prescricao(
    db: Session,
    atendimento: AtendimentoClinico,
    prescricao_payload: Optional[PrescricaoPayload],
    current_user: User,
    *,
    prescricao: Optional[PrescricaoClinica] = None,
) -> Optional[PrescricaoClinica]:
    """Sincroniza uma receita do atendimento.

    Sem `prescricao`, o alvo e a receita do dia da consulta (`sequencia = 1`),
    que e o que o `PUT /atendimentos/{id}` continua editando. As receitas
    complementares passam o alvo explicitamente."""
    if prescricao_payload is None:
        if prescricao is not None:
            return prescricao
        return _buscar_prescricao_principal(db, atendimento.id)

    if prescricao is None:
        prescricao = _buscar_prescricao_principal(db, atendimento.id)
    if prescricao is None:
        prescricao = PrescricaoClinica(atendimento_id=atendimento.id, sequencia=1)
        db.add(prescricao)
        db.flush()

    prescricao.orientacoes_gerais = prescricao_payload.orientacoes_gerais or ""
    prescricao.retorno_dias = prescricao_payload.retorno_dias
    prescricao.updated_at = datetime.now()

    itens_existentes = {
        item.id: item
        for item in db.query(PrescricaoItem).filter(PrescricaoItem.prescricao_id == prescricao.id).all()
    }
    itens_recebidos_ids: set[int] = set()

    # Uma query para todos os medicamentos referenciados sem nome no payload,
    # em vez de uma por item de prescricao (mesmo motivo do batching de
    # catalogo/painel em _sync_exames).
    medicamento_ids_sem_nome = {
        item_payload.medicamento_id
        for item_payload in prescricao_payload.itens
        if item_payload.medicamento_id and not (item_payload.medicamento_nome or "").strip()
    }
    medicamentos_por_id = (
        {m.id: m for m in db.query(Medicamento).filter(Medicamento.id.in_(medicamento_ids_sem_nome)).all()}
        if medicamento_ids_sem_nome
        else {}
    )

    for index, item_payload in enumerate(prescricao_payload.itens):
        item = None
        if item_payload.id and item_payload.id in itens_existentes:
            item = itens_existentes[item_payload.id]
            itens_recebidos_ids.add(item_payload.id)

        if item is None:
            item = PrescricaoItem(prescricao_id=prescricao.id)
            db.add(item)

        previous_values = {
            "medicamento_nome": item.medicamento_nome,
            "apresentacao_selecionada": item.apresentacao_selecionada,
            "dose": item.dose,
            "frequencia": item.frequencia,
            "duracao": item.duracao,
            "via": item.via,
            "instrucoes": item.instrucoes,
            "dose_mg_kg": item.dose_mg_kg,
            "peso_referencia_kg": item.peso_referencia_kg,
            "unidade_dose_calculo": item.unidade_dose_calculo,
            "concentracao_personalizada": item.concentracao_personalizada,
        }
        item.prescricao_id = prescricao.id
        item.medicamento_id = item_payload.medicamento_id
        item.medicamento_nome = _obter_nome_medicamento(
            item_payload.medicamento_id,
            item_payload.medicamento_nome,
            medicamentos_por_id,
        )
        item.apresentacao_selecionada = item_payload.apresentacao_selecionada or ""
        item.dose = item_payload.dose or ""
        item.frequencia = item_payload.frequencia or ""
        item.duracao = item_payload.duracao or ""
        item.via = item_payload.via or ""
        item.instrucoes = item_payload.instrucoes or ""
        item.ordem = item_payload.ordem if item_payload.ordem is not None else index
        item.dose_mg_kg = item_payload.dose_mg_kg or ""
        item.peso_referencia_kg = item_payload.peso_referencia_kg or ""
        item.unidade_dose_calculo = item_payload.unidade_dose_calculo or ""
        item.concentracao_personalizada = item_payload.concentracao_personalizada or ""
        item.updated_at = datetime.now()

        if item_payload.id and item.id:
            for field_name, previous in previous_values.items():
                _registrar_ajuste_prescricao(
                    db,
                    item=item,
                    atendimento_id=atendimento.id,
                    campo=field_name,
                    valor_anterior=previous,
                    valor_novo=getattr(item, field_name),
                    current_user=current_user,
                )

    for item_id, item in itens_existentes.items():
        if item_id not in itens_recebidos_ids:
            db.delete(item)

    return prescricao


def _montar_prescricao_dict(
    db: Session,
    prescricao: PrescricaoClinica,
    itens_dict: List[dict],
    *,
    peso_referencia: Any,
    medicamentos_map: Optional[Dict[int, dict]] = None,
) -> dict:
    if medicamentos_map is None:
        medicamentos_ids = [
            item.get("medicamento_id") for item in itens_dict if item.get("medicamento_id")
        ]
        medicamentos = (
            db.query(Medicamento).filter(Medicamento.id.in_(medicamentos_ids)).all()
            if medicamentos_ids
            else []
        )
        medicamentos_map = {med.id: _serialize_medicamento(med) for med in medicamentos}

    apoio_prescricao = analyze_prescription_items(
        peso_kg=peso_referencia,
        medicamentos=medicamentos_map,
        itens=itens_dict,
    )
    return {
        "id": prescricao.id,
        "sequencia": _sequencia_prescricao(prescricao),
        "emitida_em": _to_operational_iso(prescricao.emitida_em),
        "adendo_id": getattr(prescricao, "adendo_id", None),
        "orientacoes_gerais": prescricao.orientacoes_gerais or "",
        "retorno_dias": prescricao.retorno_dias,
        "peso_referencia_kg": peso_referencia,
        "itens": itens_dict,
        "apoio_clinico": apoio_prescricao,
        "created_at": _to_iso(prescricao.created_at),
        "updated_at": _to_iso(prescricao.updated_at),
    }


def _montar_detalhe_atendimento(
    db: Session,
    atendimento: AtendimentoClinico,
) -> dict:
    paciente = db.query(Paciente).filter(Paciente.id == atendimento.paciente_id).first()
    tutor = None
    if atendimento.tutor_id:
        tutor = db.query(Tutor).filter(Tutor.id == atendimento.tutor_id).first()
    clinica = None
    if atendimento.clinica_id:
        clinica = db.query(Clinica).filter(Clinica.id == atendimento.clinica_id).first()

    exames = (
        db.query(Exame)
        .filter(Exame.atendimento_id == atendimento.id)
        .order_by(Exame.id.asc())
        .all()
    )
    historico_por_exame = _map_ajustes_por_exame(db, [exame.id for exame in exames if exame.id])

    # Um atendimento pode ter varias receitas (a do dia + complementares dos
    # adendos). Tudo carregado em consultas agregadas por atendimento, e nao
    # por receita, para nao reintroduzir N+1 no detalhe.
    prescricoes = (
        db.query(PrescricaoClinica)
        .filter(PrescricaoClinica.atendimento_id == atendimento.id)
        .order_by(PrescricaoClinica.sequencia.asc(), PrescricaoClinica.id.asc())
        .all()
    )
    prescricao_ids = [item.id for item in prescricoes if item.id]
    itens_prescricao = (
        db.query(PrescricaoItem)
        .filter(PrescricaoItem.prescricao_id.in_(prescricao_ids))
        .order_by(
            PrescricaoItem.prescricao_id.asc(),
            PrescricaoItem.ordem.asc(),
            PrescricaoItem.id.asc(),
        )
        .all()
        if prescricao_ids
        else []
    )
    historico_por_item = _map_ajustes_por_item(
        db, [item.id for item in itens_prescricao if item.id]
    )
    medicamentos_ids = [item.medicamento_id for item in itens_prescricao if item.medicamento_id]
    medicamentos = (
        db.query(Medicamento).filter(Medicamento.id.in_(medicamentos_ids)).all()
        if medicamentos_ids
        else []
    )
    medicamentos_map = {med.id: _serialize_medicamento(med) for med in medicamentos}

    itens_por_prescricao: Dict[int, List[dict]] = defaultdict(list)
    for item in itens_prescricao:
        mapped_item = _map_prescricao_item(item)
        mapped_item["historico_ajustes"] = historico_por_item.get(item.id, [])
        itens_por_prescricao[item.prescricao_id].append(mapped_item)

    peso_referencia_prescricao = _resolver_peso_referencia(atendimento, paciente)
    prescricoes_dict = [
        _montar_prescricao_dict(
            db,
            item,
            itens_por_prescricao.get(item.id, []),
            peso_referencia=peso_referencia_prescricao,
            medicamentos_map=medicamentos_map,
        )
        for item in prescricoes
    ]
    # Ordenado por sequencia: a primeira e a receita do dia da consulta, que e
    # o que a chave legada `prescricao` continua expondo.
    prescricao_dict = prescricoes_dict[0] if prescricoes_dict else None

    # Buscar evoluÃ§Ãµes
    evolucoes = (
        db.query(EvolucaoClinica)
        .filter(EvolucaoClinica.atendimento_id == atendimento.id)
        .order_by(EvolucaoClinica.data_evolucao.desc())
        .all()
    )

    # Buscar anexos
    anexos = (
        db.query(AnexoAtendimento)
        .filter(AnexoAtendimento.atendimento_id == atendimento.id)
        .order_by(AnexoAtendimento.created_at.desc())
        .all()
    )
    anexos_por_exame: Dict[int, List[dict]] = defaultdict(list)
    for anexo in anexos:
        if anexo.exame_id:
            anexos_por_exame[anexo.exame_id].append(_serialize_anexo(anexo))

    documentos = (
        db.query(DocumentoAtendimento)
        .filter(DocumentoAtendimento.atendimento_id == atendimento.id)
        .order_by(DocumentoAtendimento.updated_at.desc(), DocumentoAtendimento.created_at.desc(), DocumentoAtendimento.id.desc())
        .all()
    )

    return {
        "id": atendimento.id,
        "paciente_id": atendimento.paciente_id,
        "tutor_id": atendimento.tutor_id,
        "clinica_id": atendimento.clinica_id,
        "agendamento_id": atendimento.agendamento_id,
        "veterinario_id": atendimento.veterinario_id,
        "especie": atendimento.especie or "",
        "data_atendimento": _to_operational_iso(atendimento.data_atendimento),
        "status": atendimento.status,
        # Triagem
        "triagem": {
            "peso": atendimento.peso,
            "temperatura": atendimento.temperatura,
            "frequencia_cardiaca": atendimento.frequencia_cardiaca,
            "frequencia_respiratoria": atendimento.frequencia_respiratoria,
            "pressao_arterial": atendimento.pressao_arterial or "",
            "saturacao_oxigenio": atendimento.saturacao_oxigenio,
            "escore_condicion_corpo": atendimento.escore_condicion_corpo,
            "mucosas": atendimento.mucosas or "",
            "hidratacao": atendimento.hidratacao or "",
            "triagem_observacoes": atendimento.triagem_observacoes or "",
        },
        "triagem_concluida": atendimento.triagem_concluida or 0,
        "consulta_concluida": atendimento.consulta_concluida or 0,
        # Consulta
        "queixa_principal": atendimento.queixa_principal or "",
        "anamnese": atendimento.anamnese or "",
        "exame_fisico": atendimento.exame_fisico or "",
        "dados_clinicos": atendimento.dados_clinicos or "",
        # DiagnÃ³sticos
        "diagnostico_principal": atendimento.diagnostico_principal or "",
        "diagnostico_secundario": atendimento.diagnostico_secundario or "",
        "diagnostico_diferencial": atendimento.diagnostico_diferencial or "",
        "diagnostico": atendimento.diagnostico_principal or "",  # Compatibilidade
        "prognostico": atendimento.prognostico or "",
        # Tratamento
        "plano_terapeutico": atendimento.plano_terapeutico or "",
        # Retorno
        "retorno_recomendado": atendimento.retorno_recomendado or "",
        "motivo_retorno": atendimento.motivo_retorno or "",
        "observacoes": atendimento.observacoes or "",
        # Metadados
        "created_at": _to_iso(atendimento.created_at),
        "updated_at": _to_iso(atendimento.updated_at),
        "criado_por_id": atendimento.criado_por_id,
        "criado_por_nome": atendimento.criado_por_nome,
        # Relacionamentos
        "paciente_nome": paciente.nome if paciente else "",
        "tutor_nome": tutor.nome if tutor else "",
        "clinica_nome": clinica.nome if clinica else "",
        "peso_referencia_kg": _resolver_peso_referencia(atendimento, paciente),
        # Extras
        "exames": [
            {
                **_map_exame(exame),
                "anexos_resultado": anexos_por_exame.get(exame.id, []),
                "historico_ajustes": historico_por_exame.get(exame.id, []),
            }
            for exame in exames
        ],
        "prescricao": prescricao_dict,
        "prescricoes": prescricoes_dict,
        "adendos": _carregar_adendos_serializados(db, atendimento.id, anexos=anexos),
        "evolucoes": [
            {
                "id": e.id,
                "data_evolucao": _to_iso(e.data_evolucao),
                "descricao": e.descricao,
                "sinais_vitais": e.sinais_vitais or "",
                "responsavel_nome": e.responsavel_nome or "",
            }
            for e in evolucoes
        ],
        "anexos": [_serialize_anexo(a) for a in anexos],
        "documentos": [serializar_documento_atendimento_service(documento) for documento in documentos],
    }


@router.get("")
def listar_atendimentos(
    data_inicio: Optional[str] = None,
    data_fim: Optional[str] = None,
    paciente_id: Optional[int] = None,
    clinica_id: Optional[int] = None,
    agendamento_id: Optional[int] = None,
    status: Optional[str] = None,
    documentacao_incompleta: Optional[bool] = None,
    search: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = current_user
    query = (
        db.query(
            AtendimentoClinico,
            Paciente.nome.label("paciente_nome"),
            Tutor.nome.label("tutor_nome"),
            Clinica.nome.label("clinica_nome"),
        )
        .outerjoin(Paciente, AtendimentoClinico.paciente_id == Paciente.id)
        .outerjoin(Tutor, AtendimentoClinico.tutor_id == Tutor.id)
        .outerjoin(Clinica, AtendimentoClinico.clinica_id == Clinica.id)
    )

    dt_inicio = _parse_datetime(data_inicio)
    dt_fim = _parse_datetime(data_fim)
    if dt_inicio:
        query = query.filter(AtendimentoClinico.data_atendimento >= dt_inicio)
    if dt_fim:
        query = query.filter(AtendimentoClinico.data_atendimento <= dt_fim)
    if paciente_id:
        query = query.filter(AtendimentoClinico.paciente_id == paciente_id)
    if clinica_id:
        query = query.filter(AtendimentoClinico.clinica_id == clinica_id)
    if agendamento_id:
        query = query.filter(AtendimentoClinico.agendamento_id == agendamento_id)
    if status:
        query = query.filter(AtendimentoClinico.status == status)
    if documentacao_incompleta:
        # So faz sentido sinalizar retrabalho pendente em prontuario ja
        # fechado; um atendimento aberto naturalmente tem campos vazios.
        query = query.filter(AtendimentoClinico.status == "Concluido")
        query = query.filter(_condicao_sql_documentacao_incompleta())
    if search:
        termo = f"%{search.strip()}%"
        query = query.filter(
            or_(
                Paciente.nome.ilike(termo),
                Tutor.nome.ilike(termo),
                Clinica.nome.ilike(termo),
                AtendimentoClinico.diagnostico_principal.ilike(termo),
                AtendimentoClinico.diagnostico_secundario.ilike(termo),
                AtendimentoClinico.diagnostico_diferencial.ilike(termo),
                AtendimentoClinico.queixa_principal.ilike(termo),
            )
        )

    total = query.count()
    rows = (
        query.order_by(
            AtendimentoClinico.data_atendimento.desc(),
            AtendimentoClinico.id.desc(),
        )
        .offset(skip)
        .limit(limit)
        .all()
    )

    atendimento_ids = [atendimento.id for atendimento, *_ in rows]
    exames_por_atendimento: Dict[int, int] = {}
    prescricoes_atendimento_ids = set()
    if atendimento_ids:
        exames_por_atendimento = {
            int(atendimento_id): int(total_exames)
            for atendimento_id, total_exames in (
                db.query(
                    Exame.atendimento_id,
                    func.count(Exame.id),
                )
                .filter(Exame.atendimento_id.in_(atendimento_ids))
                .group_by(Exame.atendimento_id)
                .all()
            )
            if atendimento_id is not None
        }
        prescricoes_atendimento_ids = {
            int(atendimento_id)
            for atendimento_id, in (
                db.query(PrescricaoClinica.atendimento_id)
                .filter(PrescricaoClinica.atendimento_id.in_(atendimento_ids))
                .distinct()
                .all()
            )
            if atendimento_id is not None
        }

    items = []
    for atendimento, paciente_nome, tutor_nome, clinica_nome in rows:
        total_exames = exames_por_atendimento.get(atendimento.id, 0)
        prescricao_existe = atendimento.id in prescricoes_atendimento_ids
        # So sinaliza retrabalho pendente para prontuario ja fechado; um
        # atendimento ainda aberto tem campos vazios por natureza.
        pendencias_documentacao = (
            _calcular_pendencias_documentacao(
                queixa_principal=atendimento.queixa_principal,
                anamnese=atendimento.anamnese,
                exame_fisico=atendimento.exame_fisico,
                dados_clinicos=atendimento.dados_clinicos,
                diagnostico_principal=atendimento.diagnostico_principal,
                diagnostico_secundario=atendimento.diagnostico_secundario,
                diagnostico_diferencial=atendimento.diagnostico_diferencial,
                plano_terapeutico=atendimento.plano_terapeutico,
            )
            if _status_atendimento_concluido(atendimento.status)
            else []
        )
        items.append(
            {
                "id": atendimento.id,
                "paciente_id": atendimento.paciente_id,
                "especie": atendimento.especie or "",
                "clinica_id": atendimento.clinica_id,
                "agendamento_id": atendimento.agendamento_id,
                "data_atendimento": _to_operational_iso(atendimento.data_atendimento),
                "status": atendimento.status,
                "queixa_principal": atendimento.queixa_principal or "",
                "diagnostico": atendimento.diagnostico_principal or "",
                "paciente_nome": paciente_nome or "",
                "tutor_nome": tutor_nome or "",
                "clinica_nome": clinica_nome or "",
                "total_exames": total_exames,
                "tem_prescricao": prescricao_existe,
                "documentacao_pendencias": pendencias_documentacao,
                "created_at": _to_iso(atendimento.created_at),
            }
        )

    return {"total": total, "items": items}


@router.get("/exames/catalogo")
def listar_catalogo_exames_atendimento(
    search: Optional[str] = None,
    categoria: Optional[str] = None,
    ativos: int = 1,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = current_user
    return montar_contexto_catalogo_exames(
        db,
        search=search,
        categoria=categoria,
        ativos=ativos,
    )


def _normalizar_sinonimos_catalogo_exame(values: List[str], nome: str) -> List[str]:
    normalized: List[str] = []
    seen = {nome.casefold()}
    for value in values:
        item = str(value or "").strip()
        key = item.casefold()
        if not item or key in seen:
            continue
        seen.add(key)
        normalized.append(item)
    return normalized


def _validar_nome_catalogo_exame_disponivel(
    db: Session,
    nome: str,
    *,
    ignore_id: Optional[int] = None,
) -> None:
    query = db.query(CatalogoExame).filter(
        CatalogoExame.ativo == 1,
        func.lower(CatalogoExame.nome) == nome.lower(),
    )
    if ignore_id is not None:
        query = query.filter(CatalogoExame.id != ignore_id)
    if query.first() is not None:
        raise HTTPException(status_code=409, detail="Ja existe um exame ativo com esse nome no catalogo.")


def _aplicar_payload_catalogo_exame_customizado(
    exame: CatalogoExame,
    payload: CatalogoExameCustomPayload,
) -> None:
    nome = (payload.nome or "").strip()
    categoria = (payload.categoria or "").strip()
    if len(nome) < 2:
        raise HTTPException(status_code=422, detail="Informe o nome do exame com pelo menos 2 caracteres.")
    if len(categoria) < 2:
        raise HTTPException(status_code=422, detail="Informe a categoria do exame com pelo menos 2 caracteres.")

    exame.nome = nome
    exame.categoria = categoria
    exame.subcategoria = (payload.subcategoria or "").strip() or None
    exame.especie_alvo = (payload.especie_alvo or "").strip() or None
    exame.prioridade_padrao = (payload.prioridade_padrao or "Rotina").strip() or "Rotina"
    exame.valor_padrao = float(payload.valor_padrao or 0)
    exame.preparo = (payload.preparo or "").strip() or None
    exame.observacoes_padrao = (payload.observacoes_padrao or "").strip() or None
    exame.sinonimos_json = json.dumps(
        _normalizar_sinonimos_catalogo_exame(payload.sinonimos, nome),
        ensure_ascii=False,
    )
    exame.ativo = 1
    exame.updated_at = datetime.now()


@router.post("/exames/catalogo", status_code=status.HTTP_201_CREATED)
def criar_catalogo_exame_customizado_atendimento(
    payload: CatalogoExameCustomPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = current_user
    nome = (payload.nome or "").strip()
    _validar_nome_catalogo_exame_disponivel(db, nome)
    exame = CatalogoExame(
        codigo=gerar_codigo_unico_catalogo_exame(db, nome),
        created_at=datetime.now(),
    )
    _aplicar_payload_catalogo_exame_customizado(exame, payload)
    db.add(exame)
    db.commit()
    db.refresh(exame)
    return catalogo_exame_to_dict(exame)


@router.put("/exames/catalogo/{exame_id}")
def atualizar_catalogo_exame_customizado_atendimento(
    exame_id: int,
    payload: CatalogoExameCustomPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = current_user
    exame = obter_catalogo_exame_customizado(db, exame_id)
    nome = (payload.nome or "").strip()
    _validar_nome_catalogo_exame_disponivel(db, nome, ignore_id=exame.id)
    exame.codigo = gerar_codigo_unico_catalogo_exame(db, nome, ignore_id=exame.id)
    _aplicar_payload_catalogo_exame_customizado(exame, payload)
    db.commit()
    db.refresh(exame)
    return catalogo_exame_to_dict(exame)


@router.delete("/exames/catalogo/{exame_id}")
def excluir_catalogo_exame_customizado_atendimento(
    exame_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = current_user
    exame = obter_catalogo_exame_customizado(db, exame_id)
    db.query(PainelExameItem).filter(
        PainelExameItem.catalogo_exame_id == exame.id
    ).delete(synchronize_session=False)
    exame.ativo = 0
    exame.updated_at = datetime.now()
    db.commit()
    return {"message": "Exame customizado removido do catalogo.", "id": exame.id}


@router.get("/paineis")
def listar_paineis_customizados_atendimento(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = current_user
    paineis = (
        db.query(PainelExame)
        .filter(PainelExame.ativo == 1, PainelExame.codigo.like(f"{CUSTOM_PAINEL_EXAME_PREFIX}%"))
        .order_by(PainelExame.categoria.asc(), PainelExame.nome.asc())
        .all()
    )
    return [serializar_painel_exame_com_itens(db, painel) for painel in paineis]


@router.post("/paineis", status_code=status.HTTP_201_CREATED)
def criar_painel_customizado_atendimento(
    payload: PainelExamePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = current_user
    nome = (payload.nome or "").strip()
    if not nome:
        raise HTTPException(status_code=422, detail="Nome do painel e obrigatorio.")

    ordered_exam_ids = resolver_ids_catalogo_exames(db, payload)
    codigo = gerar_codigo_unico_painel_exame(db, nome)
    now = datetime.now()

    painel = PainelExame(
        codigo=codigo,
        nome=nome,
        categoria=(payload.categoria or "").strip(),
        especie_alvo=(payload.especie_alvo or "").strip(),
        observacoes=(payload.observacoes or "").strip(),
        ativo=1 if payload.ativo is None else int(payload.ativo),
        created_at=now,
        updated_at=now,
    )
    db.add(painel)
    db.flush()
    substituir_itens_painel_exame(db, painel.id, ordered_exam_ids)
    db.commit()
    db.refresh(painel)
    return serializar_painel_exame_com_itens(db, painel)


@router.put("/paineis/{painel_id}")
def atualizar_painel_customizado_atendimento(
    painel_id: int,
    payload: PainelExamePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = current_user
    painel = obter_painel_exame_customizado(db, painel_id)
    nome = (payload.nome or "").strip()
    if not nome:
        raise HTTPException(status_code=422, detail="Nome do painel e obrigatorio.")

    ordered_exam_ids = resolver_ids_catalogo_exames(db, payload)
    painel.codigo = gerar_codigo_unico_painel_exame(db, nome, ignore_id=painel.id)
    painel.nome = nome
    painel.categoria = (payload.categoria or "").strip()
    painel.especie_alvo = (payload.especie_alvo or "").strip()
    painel.observacoes = (payload.observacoes or "").strip()
    painel.ativo = 1 if payload.ativo is None else int(payload.ativo)
    painel.updated_at = datetime.now()

    substituir_itens_painel_exame(db, painel.id, ordered_exam_ids)
    db.commit()
    db.refresh(painel)
    return serializar_painel_exame_com_itens(db, painel)


@router.delete("/paineis/{painel_id}")
def excluir_painel_customizado_atendimento(
    painel_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = current_user
    painel = obter_painel_exame_customizado(db, painel_id)
    painel.ativo = 0
    painel.updated_at = datetime.now()
    db.commit()
    return {"message": "Painel removido com sucesso.", "id": painel_id}


@router.get("/frases-clinicas")
def listar_frases_clinicas_atendimento(
    secao: Optional[str] = None,
    search: Optional[str] = None,
    include_inactive: int = 0,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = current_user
    return montar_contexto_frases_clinicas(
        db,
        secao=(secao or "").strip() or None,
        search=(search or "").strip() or None,
        include_inactive=bool(include_inactive),
        skip=skip,
        limit=limit,
    )


@router.post("/frases-clinicas", status_code=status.HTTP_201_CREATED)
def criar_frase_clinica_atendimento(
    payload: ClinicalPhrasePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return criar_frase_clinica(db, payload, created_by=current_user.id)


@router.put("/frases-clinicas/{phrase_id}")
def atualizar_frase_clinica_atendimento(
    phrase_id: int,
    payload: ClinicalPhrasePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = current_user
    return atualizar_frase_clinica(db, phrase_id, payload)


@router.delete("/frases-clinicas/{phrase_id}")
def desativar_frase_clinica_atendimento(
    phrase_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = current_user
    return desativar_frase_clinica(db, phrase_id)


@router.post("/frases-clinicas/{phrase_id}/restaurar")
def restaurar_frase_clinica_atendimento(
    phrase_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = current_user
    return restaurar_frase_clinica(db, phrase_id)


@router.get("/documentos/templates")
def listar_templates_documentos_atendimento(
    include_inactive: int = 0,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = current_user
    return listar_templates_documento(
        db,
        include_inactive=include_inactive,
        search=search,
    )


@router.post("/documentos/templates", status_code=status.HTTP_201_CREATED)
def criar_template_documento_atendimento(
    payload: DocumentoTemplatePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return criar_template_documento(
        db,
        payload,
        criado_por_id=current_user.id,
        criado_por_nome=current_user.nome,
    )


@router.put("/documentos/templates/{template_id}")
def atualizar_template_documento_atendimento(
    template_id: int,
    payload: DocumentoTemplatePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = current_user
    return atualizar_template_documento(db, template_id, payload)


@router.delete("/documentos/templates/{template_id}")
def desativar_template_documento_atendimento(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = current_user
    return desativar_template_documento(db, template_id)


@router.post("/documentos/templates/{template_id}/restaurar")
def restaurar_template_documento_atendimento(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = current_user
    return restaurar_template_documento(db, template_id)


@router.get("/{atendimento_id}/historico-edicoes")
def obter_historico_edicoes_atendimento(
    atendimento_id: int,
    documento_id: Optional[int] = Query(default=None, ge=1),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # A mesma dependencia e matriz de acesso do prontuario; nunca expoe a
    # auditoria global, IPs ou dados de outros atendimentos.
    return listar_historico_edicoes(db, atendimento_id, documento_id=documento_id, skip=skip, limit=limit)


@router.get("/{atendimento_id}/documentos")
def listar_documentos_atendimento(
    atendimento_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = current_user
    atendimento = db.query(AtendimentoClinico).filter(AtendimentoClinico.id == atendimento_id).first()
    if not atendimento:
        raise HTTPException(status_code=404, detail="Atendimento nao encontrado.")
    return listar_documentos_atendimento_service(db, atendimento_id)


@router.post("/{atendimento_id}/documentos", status_code=status.HTTP_201_CREATED)
def criar_documento_atendimento(
    atendimento_id: int,
    payload: DocumentoAtendimentoCreatePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    request: Request = None,
):
    atendimento = db.query(AtendimentoClinico).filter(AtendimentoClinico.id == atendimento_id).with_for_update().first()
    if not atendimento:
        raise HTTPException(status_code=404, detail="Atendimento nao encontrado.")

    paciente, tutor, clinica = carregar_contexto_entidades_documento_service(db, atendimento)
    branding = _obter_branding_pdf_documento(db, current_user)
    contexto = montar_contexto_template_documento_service(atendimento, paciente, tutor, clinica, branding)

    template = None
    titulo_base = ""
    corpo_base = ""
    if payload.template_id:
        template = obter_template_documento_ou_404(db, payload.template_id)
        if template.ativo != 1:
            raise HTTPException(status_code=422, detail="Template inativo nao pode gerar novo documento.")
        titulo_base = renderizar_template_documento_service(template.titulo_padrao or "", contexto)
        corpo_base = renderizar_template_documento_service(template.corpo_template or "", contexto)

    titulo = (payload.titulo or "").strip() or titulo_base
    corpo = (payload.corpo or "").strip() or corpo_base
    if not titulo or not corpo:
        raise HTTPException(status_code=422, detail="Informe um template ativo ou preencha titulo e corpo do documento.")

    variaveis_vazias: List[str] = []
    if template and titulo == titulo_base and corpo == corpo_base:
        # So reporta "vazias" quando o documento salvo e realmente o texto
        # renderizado do template sem sobrescrita pelo chamador - senao a
        # analise descreveria placeholders que nem estao no texto final.
        variaveis_vazias = sorted(
            set(
                identificar_variaveis_vazias_service(template.titulo_padrao or "", contexto)
                + identificar_variaveis_vazias_service(template.corpo_template or "", contexto)
            )
        )

    documento = DocumentoAtendimento(
        atendimento_id=atendimento.id,
        template_id=template.id if template else None,
        titulo=titulo,
        corpo=corpo,
        status="rascunho",
        criado_por_id=current_user.id,
        criado_por_nome=current_user.nome,
        created_at=agora_documento(),
        updated_at=agora_documento(),
    )
    db.add(documento)
    atendimento.updated_at = agora_documento()
    auditar_documento(db, documento, "DOCUMENTO_ATENDIMENTO_CRIADO", current_user=current_user,
                      request=request, detalhes={"titulo": titulo, "corpo": corpo})
    db.commit()
    db.refresh(documento)
    resultado = serializar_documento_atendimento_service(documento)
    if variaveis_vazias:
        resultado["variaveis_vazias"] = variaveis_vazias
    return resultado


@router.put("/{atendimento_id}/documentos/{documento_id}")
def atualizar_documento_atendimento(
    atendimento_id: int,
    documento_id: int,
    payload: DocumentoAtendimentoUpdatePayload,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    atendimento = db.query(AtendimentoClinico).filter(AtendimentoClinico.id == atendimento_id).first()
    if not atendimento:
        raise HTTPException(status_code=404, detail="Atendimento nao encontrado.")
    return atualizar_documento_atendimento_service(
        db,
        atendimento,
        atendimento_id,
        documento_id,
        payload,
        current_user=current_user,
        request=request,
    )


@router.delete("/{atendimento_id}/documentos/{documento_id}")
def excluir_documento_atendimento(
    atendimento_id: int,
    documento_id: int,
    request: Request,
    versao: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return excluir_documento_atendimento_service(
        db, atendimento_id, documento_id, current_user=current_user, request=request, versao=versao
    )


@router.post("/{atendimento_id}/documentos/{documento_id}/restaurar")
def restaurar_documento_atendimento(
    atendimento_id: int, documento_id: int, payload: DocumentoAtendimentoUpdatePayload,
    request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    return restaurar_documento_atendimento_service(
        db, atendimento_id, documento_id, current_user=current_user, versao=payload.versao, request=request
    )


@router.get("/contexto")
def obter_contexto_agendamento(
    agendamento_id: int = Query(..., ge=1),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = current_user
    agendamento = db.query(Agendamento).filter(Agendamento.id == agendamento_id).first()
    if not agendamento:
        raise HTTPException(status_code=404, detail="Agendamento nao encontrado.")

    paciente = db.query(Paciente).filter(Paciente.id == agendamento.paciente_id).first() if agendamento.paciente_id else None
    tutor = db.query(Tutor).filter(Tutor.id == paciente.tutor_id).first() if paciente and paciente.tutor_id else None
    clinica = db.query(Clinica).filter(Clinica.id == agendamento.clinica_id).first() if agendamento.clinica_id else None

    return {
        "agendamento_id": agendamento.id,
        "paciente_id": agendamento.paciente_id,
        "especie": (paciente.especie or "").strip() if paciente else "",
        "paciente_nome": paciente.nome if paciente else (agendamento.paciente or ""),
        "tutor_id": tutor.id if tutor else None,
        "tutor_nome": tutor.nome if tutor else (agendamento.tutor or ""),
        "clinica_id": agendamento.clinica_id,
        "clinica_nome": clinica.nome if clinica else (agendamento.clinica or ""),
        "inicio": _to_operational_iso(agendamento.inicio),
        "status": agendamento.status,
    }


@router.get("/{atendimento_id}")
def obter_atendimento(
    atendimento_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = current_user
    atendimento = db.query(AtendimentoClinico).filter(AtendimentoClinico.id == atendimento_id).first()
    if not atendimento:
        raise HTTPException(status_code=404, detail="Atendimento nao encontrado.")
    return _montar_detalhe_atendimento(db, atendimento)


def _responder_pdf_prescricao(
    db: Session,
    *,
    atendimento: AtendimentoClinico,
    prescricao: PrescricaoClinica,
    current_user: User,
) -> StreamingResponse:
    paciente, tutor, clinica = carregar_contexto_entidades_documento_service(db, atendimento)

    itens = (
        db.query(PrescricaoItem)
        .filter(PrescricaoItem.prescricao_id == prescricao.id)
        .order_by(PrescricaoItem.ordem.asc(), PrescricaoItem.id.asc())
        .all()
    )
    if not itens:
        raise HTTPException(status_code=404, detail="Prescricao sem itens para gerar PDF.")

    branding = _obter_branding_pdf_documento(db, current_user)
    pdf_bytes = _gerar_pdf_prescricao_bytes(
        atendimento,
        paciente,
        tutor,
        clinica,
        prescricao,
        itens,
        nome_veterinario=branding["nome_veterinario"],
        crmv=branding["crmv"],
        logomarca_bytes=branding["logomarca_bytes"],
        assinatura_bytes=branding["assinatura_bytes"],
        texto_rodape=branding["texto_rodape"],
    )

    # So depois do PDF existir de fato: uma falha de geracao nao pode deixar a
    # receita marcada como emitida.
    _marcar_receita_emitida(db, prescricao)

    paciente_nome = _nome_arquivo_limpo(paciente.nome if paciente else "", f"paciente_{atendimento.paciente_id}")
    sequencia = _sequencia_prescricao(prescricao)
    # Sequencia 1 mantem o nome historico do arquivo.
    sufixo = "" if sequencia <= 1 else f"_{sequencia}"
    filename = f"receita{sufixo}_atendimento_{atendimento.id}_{paciente_nome}.pdf"
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers=_headers_download_pdf(filename),
    )


@router.get("/{atendimento_id}/prescricao/pdf")
def gerar_pdf_prescricao(
    atendimento_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Receita do dia da consulta. Contrato legado, preservado."""
    current_user = _autenticar_usuario_pdf(request, db)
    atendimento = db.query(AtendimentoClinico).filter(AtendimentoClinico.id == atendimento_id).first()
    if not atendimento:
        raise HTTPException(status_code=404, detail="Atendimento nao encontrado.")

    prescricao = _buscar_prescricao_principal(db, atendimento.id)
    if not prescricao:
        raise HTTPException(status_code=404, detail="Prescricao nao encontrada para este atendimento.")

    return _responder_pdf_prescricao(
        db,
        atendimento=atendimento,
        prescricao=prescricao,
        current_user=current_user,
    )


@router.get("/{atendimento_id}/prescricoes/{prescricao_id}/pdf")
def gerar_pdf_prescricao_por_id(
    atendimento_id: int,
    prescricao_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    current_user = _autenticar_usuario_pdf(request, db)
    atendimento = db.query(AtendimentoClinico).filter(AtendimentoClinico.id == atendimento_id).first()
    if not atendimento:
        raise HTTPException(status_code=404, detail="Atendimento nao encontrado.")

    prescricao = _carregar_prescricao_do_atendimento(
        db,
        atendimento_id=atendimento.id,
        prescricao_id=prescricao_id,
    )
    return _responder_pdf_prescricao(
        db,
        atendimento=atendimento,
        prescricao=prescricao,
        current_user=current_user,
    )


def _gerar_pdf_prescricao_preview_bytes(
    dados: PrescricaoPreviewPayload,
    *,
    logomarca_bytes: Optional[bytes] = None,
) -> bytes:
    """Gera PDF da prescricao a partir de dados dict (sem modelo SQLAlchemy).
    Usa a mesma estrutura e helpers do PDF final para garantir visual consistente."""
    # Montar dados_pdf no mesmo formato usado pelo PDF final
    data_exame = dados.data_atendimento or ""
    peso_str = f"{dados.paciente_peso:.1f}" if dados.paciente_peso else ""

    dados_pdf = {
        "paciente": {
            "nome": dados.paciente_nome or "N/A",
            "especie": dados.paciente_especie or "",
            "raca": dados.paciente_raca or "",
            "sexo": dados.paciente_sexo or "",
            "idade": dados.paciente_idade or "",
            "peso": peso_str,
            "tutor": dados.tutor_nome or "",
            "solicitante": dados.veterinario_nome or "",
            "data_exame": data_exame,
        },
        "clinica": "",
    }

    # Orientacoes (mesmo formato do PDF final)
    orientacoes_bloco: List[str] = []
    if (dados.orientacoes_gerais or "").strip():
        orientacoes_bloco.append(_texto_pdf_html(dados.orientacoes_gerais, ""))
    if dados.retorno_dias:
        orientacoes_bloco.append(f"<b>Retorno sugerido:</b> {dados.retorno_dias} dia(s)")

    # Criar temp file para logo (mesmo padrao do PDF final)
    temp_files: List[str] = []
    temp_logo_path = None
    if logomarca_bytes:
        temp_logo = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        temp_logo.write(logomarca_bytes)
        temp_logo.close()
        temp_logo_path = temp_logo.name
        temp_files.append(temp_logo_path)

    try:
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=15 * mm,
            rightMargin=15 * mm,
            topMargin=15 * mm,
            bottomMargin=15 * mm,
            title=f"Receita - {dados.paciente_nome or 'Preview'}",
        )

        story: List[Any] = []

        # Cabecalho padrao com logo (mesmo do PDF final)
        story.extend(
            criar_cabecalho(
                dados_pdf,
                temp_logo_path=temp_logo_path,
                titulo_principal="RECEITA VETERINARIA",
                mostrar_linha_ritmo=False,
                label_data_exame="Data",
            )
        )

        # Orientacoes antes dos itens (mesma posicao do PDF final)
        if orientacoes_bloco:
            story.append(
                _prescricao_criar_box_texto(
                    "Orientacoes gerais",
                    "<br/><br/>".join(orientacoes_bloco),
                    "#fafafa",
                    "#e5e7eb",
                )
            )
            story.append(Spacer(1, 4 * mm))

        # Titulo da secao de itens (fundo preto, mesma estrutura do PDF final)
        story.append(criar_titulo_secao("ITENS PRESCRITOS"))

        if dados.itens:
            for idx, item in enumerate(dados.itens, start=1):
                story.append(_prescricao_criar_card_prescricao(
                    idx,
                    item.medicamento_nome or "",
                    item.dose or "",
                    item.frequencia or "",
                    item.duracao or "",
                    item.via or "",
                    item.apresentacao_selecionada or "",
                    item.instrucoes or "",
                ))
                story.append(Spacer(1, 3 * mm))
        else:
            styles = create_pdf_styles()
            story.append(Paragraph("Nenhum item de medicacao foi registrado.", styles["Normal"]))

        doc.build(story)
        return buffer.getvalue()
    finally:
        for temp_file in temp_files:
            try:
                os.unlink(temp_file)
            except OSError:
                pass


@router.post("/prescricao/preview")
def preview_pdf_prescricao(
    payload: PrescricaoPreviewPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Gera preview da prescricao em PDF (nao salva no banco)."""
    if not payload.itens:
        raise HTTPException(status_code=400, detail="Adicione pelo menos um item para gerar o preview.")

    # Filter out empty items
    itens_validos = [i for i in payload.itens if (i.medicamento_nome or "").strip()]
    if not itens_validos:
        raise HTTPException(status_code=400, detail="Adicione pelo menos um medicamento para gerar o preview.")

    branding = _obter_branding_pdf_documento(db, current_user)
    import base64
    pdf_bytes = _gerar_pdf_prescricao_preview_bytes(
        payload,
        logomarca_bytes=branding.get("logomarca_bytes"),
    )
    return {"pdf_base64": base64.b64encode(pdf_bytes).decode()}


@router.get("/{atendimento_id}/exames/pdf")
def gerar_pdf_solicitacao_exames(
    atendimento_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    current_user = _autenticar_usuario_pdf(request, db)
    atendimento = db.query(AtendimentoClinico).filter(AtendimentoClinico.id == atendimento_id).first()
    if not atendimento:
        raise HTTPException(status_code=404, detail="Atendimento nao encontrado.")

    paciente, tutor, clinica = carregar_contexto_entidades_documento_service(db, atendimento)
    exames = (
        db.query(Exame)
        .filter(Exame.atendimento_id == atendimento.id)
        .order_by(Exame.id.asc())
        .all()
    )
    if not exames:
        raise HTTPException(status_code=404, detail="Nao ha exames para este atendimento.")

    branding = _obter_branding_pdf_documento(db, current_user)
    pdf_bytes = _gerar_pdf_exames_bytes(
        atendimento,
        paciente,
        tutor,
        clinica,
        exames,
        nome_veterinario=branding["nome_veterinario"],
        crmv=branding["crmv"],
        logomarca_bytes=branding["logomarca_bytes"],
        assinatura_bytes=branding["assinatura_bytes"],
        texto_rodape=branding["texto_rodape"],
    )
    paciente_nome = _nome_arquivo_limpo(paciente.nome if paciente else "", f"paciente_{atendimento.paciente_id}")
    filename = f"solicitacao_exames_atendimento_{atendimento.id}_{paciente_nome}.pdf"
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers=_headers_download_pdf(filename),
    )


@router.get("/{atendimento_id}/documentos/{documento_id}/pdf")
def gerar_pdf_documento_atendimento(
    atendimento_id: int,
    documento_id: int,
    request: Request,
    versao: Optional[str] = None,
    db: Session = Depends(get_db),
):
    current_user = _autenticar_usuario_pdf(request, db)
    atendimento = db.query(AtendimentoClinico).filter(AtendimentoClinico.id == atendimento_id).first()
    if not atendimento:
        raise HTTPException(status_code=404, detail="Atendimento nao encontrado.")

    branding = _obter_branding_pdf_documento(db, current_user)
    documento = obter_documento_atendimento_ou_404_service(db, atendimento_id, documento_id, bloquear=True)
    validar_versao_documento(documento, versao)
    validar_documento_ativo(documento)
    paciente, tutor, clinica = atualizar_documento_template_se_contexto_mudou_service(
        db,
        atendimento,
        documento,
        branding,
    )
    pdf_bytes = _gerar_pdf_documento_atendimento_bytes(
        atendimento,
        paciente,
        tutor,
        clinica,
        documento,
        nome_veterinario=branding["nome_veterinario"],
        crmv=branding["crmv"],
        logomarca_bytes=branding["logomarca_bytes"],
        assinatura_bytes=branding["assinatura_bytes"],
        texto_rodape=branding["texto_rodape"],
    )

    documento.status = "emitido"
    documento.emitido_at = agora_documento()
    documento.updated_at = agora_documento()
    auditar_documento(db, documento, "DOCUMENTO_ATENDIMENTO_PDF_GERADO", current_user=current_user,
                      request=request, detalhes={"titulo": documento.titulo, "corpo": documento.corpo,
                                               "pdf_bytes": len(pdf_bytes), "emitido_at": documento.emitido_at})
    db.commit()

    paciente_nome = _nome_arquivo_limpo(paciente.nome if paciente else "", f"paciente_{atendimento.paciente_id}")
    titulo = _nome_arquivo_limpo(documento.titulo or "", f"documento_{documento.id}")
    filename = f"{titulo}_atendimento_{atendimento.id}_{paciente_nome}.pdf"
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers=_headers_download_pdf(filename),
    )


@router.post("", status_code=status.HTTP_201_CREATED)
def criar_atendimento(
    payload: AtendimentoCreatePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    request: Request = None,
):
    status_atendimento = _normalizar_status_atendimento(payload.status or "Triagem")
    triagem = payload.triagem
    diagnostico = _normalizar_diagnostico(payload.diagnostico)
    pendencias_conclusao = _validar_primeira_conclusao_atendimento(
        status_atual=None,
        status_destino=status_atendimento,
        queixa_principal=payload.queixa_principal,
        anamnese=payload.anamnese,
        exame_fisico=payload.exame_fisico,
        dados_clinicos=payload.dados_clinicos,
        diagnostico_principal=diagnostico["diagnostico_principal"],
        diagnostico_secundario=diagnostico["diagnostico_secundario"],
        diagnostico_diferencial=diagnostico["diagnostico_diferencial"],
        plano_terapeutico=payload.plano_terapeutico,
        confirmado=bool(payload.confirmar_conclusao_pendencias),
    )

    agendamento = None
    if payload.agendamento_id:
        agendamento = _carregar_e_validar_agendamento_atendimento(
            db,
            agendamento_id=payload.agendamento_id,
            paciente_id=payload.paciente_id,
            clinica_id=payload.clinica_id,
        )
        if status_atendimento == "Concluido":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Atendimentos vinculados devem ser criados em andamento e concluidos "
                    "pela acao Finalizar atendimento."
                ),
            )
    clinica_id = (
        payload.clinica_id
        if payload.clinica_id is not None
        else (agendamento.clinica_id if agendamento else None)
    )
    data_atendimento = (
        _parse_datetime(payload.data_atendimento)
        or (agendamento.inicio if agendamento else None)
        or datetime.now(ATENDIMENTO_LOCAL_TZ)
    )
    tutor_id = _resolver_tutor_paciente(db, payload.paciente_id)
    especie = _resolver_especie_paciente(db, payload.paciente_id)

    atendimento = AtendimentoClinico(
        paciente_id=payload.paciente_id,
        tutor_id=tutor_id,
        clinica_id=clinica_id,
        agendamento_id=payload.agendamento_id,
        veterinario_id=current_user.id,
        especie=especie,
        data_atendimento=data_atendimento,
        status=status_atendimento,
        # Triagem
        peso=triagem.peso if triagem else None,
        temperatura=triagem.temperatura if triagem else None,
        frequencia_cardiaca=triagem.frequencia_cardiaca if triagem else None,
        frequencia_respiratoria=triagem.frequencia_respiratoria if triagem else None,
        pressao_arterial=triagem.pressao_arterial if triagem else None,
        saturacao_oxigenio=triagem.saturacao_oxigenio if triagem else None,
        escore_condicion_corpo=triagem.escore_condicion_corpo if triagem else None,
        mucosas=triagem.mucosas if triagem else None,
        hidratacao=triagem.hidratacao if triagem else None,
        triagem_observacoes=triagem.triagem_observacoes if triagem else None,
        triagem_concluida=1 if payload.triagem_concluida else 0,
        # Consulta
        queixa_principal=payload.queixa_principal or "",
        anamnese=payload.anamnese or "",
        exame_fisico=payload.exame_fisico or "",
        dados_clinicos=payload.dados_clinicos or "",
        # DiagnÃ³sticos
        diagnostico_principal=diagnostico["diagnostico_principal"] or "",
        diagnostico_secundario=diagnostico["diagnostico_secundario"] or "",
        diagnostico_diferencial=diagnostico["diagnostico_diferencial"] or "",
        prognostico=diagnostico["prognostico"],
        # Tratamento
        plano_terapeutico=payload.plano_terapeutico or "",
        # Retorno
        retorno_recomendado=payload.retorno_recomendado or "",
        motivo_retorno=payload.motivo_retorno or "",
        observacoes=payload.observacoes or "",
        consulta_concluida=(
            1 if status_atendimento == "Concluido" else (1 if payload.consulta_concluida else 0)
        ),
        created_at=datetime.now(),
        updated_at=datetime.now(),
        criado_por_id=current_user.id,
        criado_por_nome=current_user.nome,
    )
    db.add(atendimento)
    try:
        db.flush()
        _sync_exames(db, atendimento, payload.exames, current_user)
        _sync_prescricao(db, atendimento, payload.prescricao, current_user)
    except IntegrityError as exc:
        _raise_atendimento_integrity_conflict(
            db,
            agendamento_id=payload.agendamento_id,
            exc=exc,
        )

    _commit_atendimento_com_guard(db, agendamento_id=payload.agendamento_id)
    db.refresh(atendimento)
    if pendencias_conclusao:
        _auditar_conclusao_com_pendencias(
            current_user=current_user,
            atendimento=atendimento,
            pendencias=pendencias_conclusao,
            request=request,
        )
    return _montar_detalhe_atendimento(db, atendimento)


_CAMPOS_CONTEUDO_CLINICO_AUDITAVEIS = (
    "paciente_id",
    "tutor_id",
    "clinica_id",
    "agendamento_id",
    "especie",
    "status",
    "data_atendimento",
    "triagem_concluida",
    "consulta_concluida",
    "peso",
    "temperatura",
    "frequencia_cardiaca",
    "frequencia_respiratoria",
    "pressao_arterial",
    "saturacao_oxigenio",
    "escore_condicion_corpo",
    "mucosas",
    "hidratacao",
    "triagem_observacoes",
    "queixa_principal",
    "anamnese",
    "exame_fisico",
    "dados_clinicos",
    "diagnostico_principal",
    "diagnostico_secundario",
    "diagnostico_diferencial",
    "prognostico",
    "plano_terapeutico",
    "retorno_recomendado",
    "motivo_retorno",
    "observacoes",
)


def _snapshot_conteudo_clinico(atendimento: AtendimentoClinico) -> dict:
    valores = {campo: getattr(atendimento, campo) for campo in _CAMPOS_CONTEUDO_CLINICO_AUDITAVEIS}
    valores["data_atendimento"] = _to_operational_iso(atendimento.data_atendimento)
    return valores


def _snapshot_exames(db: Session, atendimento_id: int) -> list:
    campos = ("id", "paciente_id", "catalogo_exame_id", "painel_exame_id", "painel_exame_nome",
              "tipo_exame", "categoria_exame", "preparo", "prioridade", "status", "resultado",
              "valor_referencia", "unidade", "observacoes", "valor", "laudo_id",
              "data_solicitacao", "data_resultado")
    textos = {"painel_exame_nome", "tipo_exame", "categoria_exame", "preparo", "prioridade",
              "status", "resultado", "valor_referencia", "unidade", "observacoes"}
    exames = (db.query(Exame).filter(Exame.atendimento_id == atendimento_id)
              .populate_existing().order_by(Exame.id.asc()).all())
    return [{campo: (_to_operational_iso(getattr(exame, campo)) if campo.startswith("data_")
                     else (getattr(exame, campo) or "") if campo in textos
                     else getattr(exame, campo)) for campo in campos} for exame in exames]


def _diff_conteudo_clinico(antes: dict, depois: dict) -> dict:
    return {
        campo: {"antes": antes[campo], "depois": depois[campo]}
        for campo in antes
        if antes[campo] != depois[campo]
    }


def _auditar_conteudo_clinico_atualizado(
    db: Session,
    *,
    current_user: User,
    atendimento: AtendimentoClinico,
    alteracoes: dict,
    request: Optional[Request] = None,
) -> None:
    """PUT /atendimentos/{id} e o unico caminho de escrita do prontuario (save
    manual e autosave): sem isso, diagnostico/triagem/queixa podiam ser
    reescritos a qualquer momento sem nenhum rastro de quem mudou o que."""
    registrar_auditoria(
        db=db,
        current_user=current_user,
        modulo="atendimento",
        entidade="atendimento_clinico",
        entidade_id=atendimento.id,
        acao="ATENDIMENTO_CONTEUDO_CLINICO_ATUALIZADO",
        descricao=(
            f"Atendimento #{atendimento.id} teve conteudo clinico atualizado: "
            + ", ".join(sorted(alteracoes))
        ),
        detalhes={"paciente_id": atendimento.paciente_id, "alteracoes": alteracoes},
        request=request,
    )


@router.put("/{atendimento_id}")
def atualizar_atendimento(
    atendimento_id: int,
    payload: AtendimentoUpdatePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    request: Request = None,
):
    atendimento = (db.query(AtendimentoClinico).filter(AtendimentoClinico.id == atendimento_id)
                   .populate_existing().with_for_update().first())
    if not atendimento:
        raise HTTPException(status_code=404, detail="Atendimento nao encontrado.")

    conteudo_clinico_antes = _snapshot_conteudo_clinico(atendimento)
    if payload.exames is not None:
        conteudo_clinico_antes["exames"] = _snapshot_exames(db, atendimento.id)

    data = payload.model_dump(
        exclude_unset=True,
        exclude={"triagem", "diagnostico", "confirmar_desvinculo_agendamento"},
    )

    paciente_destino = (
        data["paciente_id"]
        if data.get("paciente_id") is not None
        else atendimento.paciente_id
    )
    clinica_destino = data.get("clinica_id", atendimento.clinica_id)
    agendamento_atual = atendimento.agendamento_id
    agendamento_destino = data.get("agendamento_id", agendamento_atual)
    # Os guards da finalizacao transacional avaliam o vinculo relevante: um PUT
    # parcial com `agendamento_id: null` nao pode zerar a referencia e escapar.
    agendamento_referencia = agendamento_destino or agendamento_atual
    desvinculando_agendamento = bool(
        "agendamento_id" in data and not data["agendamento_id"] and agendamento_atual
    )
    agendamento_validado = None
    if agendamento_destino:
        agendamento_validado = _carregar_e_validar_agendamento_atendimento(
            db,
            agendamento_id=int(agendamento_destino),
            paciente_id=int(paciente_destino),
            clinica_id=clinica_destino,
            atendimento_id_excluir=atendimento.id,
        )
        if clinica_destino is None:
            clinica_destino = agendamento_validado.clinica_id

    status_atual = atendimento.status
    if _status_atendimento_concluido(status_atual) and paciente_destino != atendimento.paciente_id:
        raise HTTPException(status_code=409, detail="A correcao de um atendimento concluido deve preservar o paciente original.")
    status_destino = atendimento.status
    if "status" in data and data["status"] is not None:
        status_destino = _normalizar_status_atendimento(data["status"])

    diagnostico_destino = (
        _normalizar_diagnostico(payload.diagnostico)
        if payload.diagnostico is not None
        else {
            "diagnostico_principal": atendimento.diagnostico_principal or "",
            "diagnostico_secundario": atendimento.diagnostico_secundario or "",
            "diagnostico_diferencial": atendimento.diagnostico_diferencial or "",
            "prognostico": atendimento.prognostico,
        }
    )
    pendencias_conclusao = _validar_primeira_conclusao_atendimento(
        status_atual=status_atual,
        status_destino=status_destino,
        queixa_principal=data.get("queixa_principal", atendimento.queixa_principal),
        anamnese=data.get("anamnese", atendimento.anamnese),
        exame_fisico=data.get("exame_fisico", atendimento.exame_fisico),
        dados_clinicos=data.get("dados_clinicos", atendimento.dados_clinicos),
        diagnostico_principal=diagnostico_destino["diagnostico_principal"],
        diagnostico_secundario=diagnostico_destino["diagnostico_secundario"],
        diagnostico_diferencial=diagnostico_destino["diagnostico_diferencial"],
        plano_terapeutico=data.get("plano_terapeutico", atendimento.plano_terapeutico),
        confirmado=bool(payload.confirmar_conclusao_pendencias),
    )
    if (
        agendamento_referencia
        and status_destino == "Concluido"
        and not _status_atendimento_concluido(status_atual)
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Use a acao Finalizar atendimento para concluir o prontuario, "
                "a Agenda e a OS em uma unica operacao."
            ),
        )
    if (
        _status_atendimento_concluido(status_atual)
        and not _status_atendimento_concluido(status_destino)
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "A edicao preserva o status Concluido. Recarregue o atendimento e "
                "salve as correcoes mantendo a conclusao; nao e necessario reabrir "
                "o registro para editar seu conteudo."
            ),
        )
    alterando_vinculo_agendamento = bool(
        "agendamento_id" in data and agendamento_destino != agendamento_atual
    )
    if alterando_vinculo_agendamento and _status_atendimento_concluido(status_atual):
        # Um prontuario concluido sustenta a Agenda realizada e a OS gerada: nem
        # desvincular (agendamento_id: null) nem reatribuir para OUTRO agendamento
        # nao-nulo pode acontecer fora do fluxo explicito de finalizacao/reabertura.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Um atendimento concluido nao pode ter o vinculo com o agendamento "
                "alterado: o vinculo sustenta a Agenda realizada e a OS gerada."
            ),
        )
    if desvinculando_agendamento:
        if not payload.confirmar_desvinculo_agendamento:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "codigo": "CONFIRMACAO_DESVINCULO_AGENDAMENTO",
                    "mensagem": (
                        "Confirme a desvinculacao deste prontuario do agendamento "
                        f"#{agendamento_atual}."
                    ),
                    "confirmavel": True,
                    "agendamento_id": agendamento_atual,
                },
            )

    if "paciente_id" in data and data["paciente_id"] is not None:
        atendimento.paciente_id = data["paciente_id"]
        atendimento.tutor_id = _resolver_tutor_paciente(db, atendimento.paciente_id)
        atendimento.especie = _resolver_especie_paciente(db, atendimento.paciente_id)

    if "clinica_id" in data:
        atendimento.clinica_id = clinica_destino
    elif agendamento_validado and atendimento.clinica_id is None:
        atendimento.clinica_id = clinica_destino
    if "agendamento_id" in data:
        atendimento.agendamento_id = data["agendamento_id"]
    if "status" in data and data["status"] is not None:
        atendimento.status = status_destino

    if "data_atendimento" in data:
        atendimento.data_atendimento = _parse_datetime(data["data_atendimento"]) or atendimento.data_atendimento

    # Triagem
    if payload.triagem:
        triagem = payload.triagem
        atendimento.peso = triagem.peso
        atendimento.temperatura = triagem.temperatura
        atendimento.frequencia_cardiaca = triagem.frequencia_cardiaca
        atendimento.frequencia_respiratoria = triagem.frequencia_respiratoria
        atendimento.pressao_arterial = triagem.pressao_arterial
        atendimento.saturacao_oxigenio = triagem.saturacao_oxigenio
        atendimento.escore_condicion_corpo = triagem.escore_condicion_corpo
        atendimento.mucosas = triagem.mucosas
        atendimento.hidratacao = triagem.hidratacao
        atendimento.triagem_observacoes = triagem.triagem_observacoes

    if "triagem_concluida" in data:
        atendimento.triagem_concluida = data["triagem_concluida"]
    if "consulta_concluida" in data:
        atendimento.consulta_concluida = data["consulta_concluida"]
    if _status_atendimento_concluido(status_destino):
        atendimento.consulta_concluida = 1

    # DiagnÃ³sticos
    if payload.diagnostico is not None:
        diag = diagnostico_destino
        atendimento.diagnostico_principal = diag["diagnostico_principal"] or ""
        atendimento.diagnostico_secundario = diag["diagnostico_secundario"] or ""
        atendimento.diagnostico_diferencial = diag["diagnostico_diferencial"] or ""
        atendimento.prognostico = diag["prognostico"]

    for field in [
        "queixa_principal",
        "anamnese",
        "exame_fisico",
        "dados_clinicos",
        "diagnostico_principal",
        "diagnostico_secundario",
        "diagnostico_diferencial",
        "plano_terapeutico",
        "retorno_recomendado",
        "motivo_retorno",
        "observacoes",
    ]:
        if field in data and data[field] is not None:
            setattr(atendimento, field, data[field])

    atendimento.updated_at = datetime.now()

    try:
        if payload.exames is not None:
            _sync_exames(db, atendimento, payload.exames, current_user)
        if "prescricao" in data and payload.prescricao is not None:
            prescricao_alvo = _buscar_prescricao_principal(db, atendimento.id)
            prescricao_antes = _snapshot_prescricao(db, prescricao_alvo, reler=True)
            prescricao_alvo = _sync_prescricao(
                db, atendimento, payload.prescricao, current_user, prescricao=prescricao_alvo,
            )
            _auditar_edicao_prescricao(
                db, current_user=current_user, atendimento=atendimento,
                prescricao=prescricao_alvo, antes=prescricao_antes, request=request,
            )
        conteudo_clinico_depois = _snapshot_conteudo_clinico(atendimento)
        if payload.exames is not None:
            db.flush()
            conteudo_clinico_depois["exames"] = _snapshot_exames(db, atendimento.id)
        alteracoes_conteudo_clinico = _diff_conteudo_clinico(
            conteudo_clinico_antes, conteudo_clinico_depois,
        )
        if alteracoes_conteudo_clinico:
            _auditar_conteudo_clinico_atualizado(
                db, current_user=current_user, atendimento=atendimento,
                alteracoes=alteracoes_conteudo_clinico, request=request,
            )
        _commit_atendimento_com_guard(
            db, agendamento_id=atendimento.agendamento_id,
            atendimento_id_excluir=atendimento.id,
        )
    except IntegrityError as exc:
        _raise_atendimento_integrity_conflict(
            db, agendamento_id=atendimento.agendamento_id, exc=exc,
            atendimento_id_excluir=atendimento.id,
        )
    except Exception:
        db.rollback()
        raise
    db.refresh(atendimento)
    if desvinculando_agendamento:
        _auditar_desvinculo_agendamento(
            current_user=current_user,
            atendimento=atendimento,
            agendamento_id=agendamento_atual,
            request=request,
        )
    if pendencias_conclusao:
        _auditar_conclusao_com_pendencias(
            current_user=current_user,
            atendimento=atendimento,
            pendencias=pendencias_conclusao,
            request=request,
        )
    return _montar_detalhe_atendimento(db, atendimento)


def _auditar_desvinculo_agendamento(
    *,
    current_user: User,
    atendimento: AtendimentoClinico,
    agendamento_id: Optional[int],
    request: Optional[Request] = None,
) -> None:
    """Desvincular prontuario da Agenda e acao explicita e precisa deixar rastro."""
    registrar_auditoria(
        current_user=current_user,
        modulo="atendimento",
        entidade="atendimento_clinico",
        entidade_id=atendimento.id,
        acao="DESVINCULAR_AGENDAMENTO",
        descricao=(
            f"Atendimento #{atendimento.id} desvinculado do agendamento #{agendamento_id}."
        ),
        detalhes={
            "agendamento_id_anterior": agendamento_id,
            "paciente_id": atendimento.paciente_id,
            "clinica_id": atendimento.clinica_id,
            "status_atendimento": atendimento.status,
        },
        request=request,
    )


def _emitir_efeitos_finalizacao(
    *,
    db: Session,
    request: Request,
    current_user: User,
    atendimento: AtendimentoClinico,
    agendamento: Optional[Agendamento],
    ordem_servico: Optional[OrdemServico],
    atendimento_status_anterior: str,
    agenda_status_anterior: Optional[str],
    os_reutilizada: bool,
    tipo_horario: str,
) -> None:
    detalhes = {
        "atendimento_id": atendimento.id,
        "agendamento_id": agendamento.id if agendamento else None,
        "atendimento_status_anterior": atendimento_status_anterior,
        "atendimento_status_novo": atendimento.status,
        "agenda_status_anterior": agenda_status_anterior,
        "agenda_status_novo": agendamento.status if agendamento else None,
        "ordem_servico_id": ordem_servico.id if ordem_servico else None,
        "os_reutilizada": os_reutilizada,
        "tipo_horario": tipo_horario,
    }
    finalizacao_repetida = (
        _status_atendimento_concluido(atendimento_status_anterior)
        and (
            agendamento is None
            or (
                agenda_status_anterior == agendamento.status
                and os_reutilizada
            )
        )
    )
    registrar_auditoria(
        current_user=current_user,
        modulo="atendimento",
        entidade="atendimento_clinico",
        entidade_id=atendimento.id,
        acao=(
            "ATENDIMENTO_FINALIZACAO_REPETIDA"
            if finalizacao_repetida
            else "ATENDIMENTO_FINALIZADO"
        ),
        descricao=(
            f"Finalizacao do Atendimento #{atendimento.id} "
            + ("reconfirmada" if finalizacao_repetida else "concluida")
            + (f" com Agenda #{agendamento.id}" if agendamento else " sem Agenda vinculada")
        ),
        detalhes=detalhes,
        request=request,
    )

    if not agendamento:
        return

    if agenda_status_anterior != agendamento.status:
        registrar_auditoria(
            current_user=current_user,
            modulo="agenda",
            entidade="agendamento",
            entidade_id=agendamento.id,
            acao="AGENDAMENTO_REALIZADO_POR_ATENDIMENTO",
            descricao=(
                f"Agenda #{agendamento.id} realizada pela finalizacao transacional "
                f"do Atendimento #{atendimento.id}"
            ),
            detalhes=detalhes,
            request=request,
        )
        payload_agenda = {
            "status_anterior": agenda_status_anterior,
            "status_novo": agendamento.status,
            "atendimento_id": atendimento.id,
            "os_id": ordem_servico.id if ordem_servico else None,
        }
        try:
            agenda_realtime_manager.publish(
                action="status_changed",
                agendamento_id=agendamento.id,
                data=payload_agenda,
            )
        except Exception as exc:
            logger.warning("Falha ao publicar finalizacao na Agenda em tempo real: %s", exc)
        try:
            send_agenda_push_notification(
                db,
                action="status_changed",
                agendamento_id=agendamento.id,
                data=payload_agenda,
                actor_user_id=current_user.id,
            )
        except Exception as exc:
            logger.warning("Falha ao notificar finalizacao na Agenda: %s", exc)

    if ordem_servico and not os_reutilizada:
        try:
            send_financeiro_push_notification(
                db,
                action="os_generated",
                os_id=ordem_servico.id,
                data={
                    "numero_os": ordem_servico.numero_os,
                    "valor_final": f"{float(ordem_servico.valor_final or 0):.2f}",
                    "agendamento_id": agendamento.id,
                    "atendimento_id": atendimento.id,
                },
                actor_user_id=current_user.id,
            )
        except Exception as exc:
            logger.warning("Falha ao notificar a OS gerada na finalizacao: %s", exc)


@router.post("/{atendimento_id}/finalizar")
def finalizar_atendimento(
    atendimento_id: int,
    payload: AtendimentoFinalizarPayload,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tipo_horario = _normalizar_tipo_horario_atendimento(payload.tipo_horario)
    atendimento = None
    agendamento = None
    ordem_servico = None
    os_reutilizada = False
    atendimento_status_anterior = ""
    agenda_status_anterior = None

    try:
        _adquirir_lock_finalizacao(db)
        atendimento = (
            db.query(AtendimentoClinico)
            .filter(AtendimentoClinico.id == atendimento_id)
            .with_for_update()
            .first()
        )
        if not atendimento:
            raise HTTPException(status_code=404, detail="Atendimento nao encontrado.")

        atendimento_status_anterior = atendimento.status
        pendencias_conclusao = _validar_primeira_conclusao_atendimento(
            status_atual=atendimento.status,
            status_destino="Concluido",
            queixa_principal=atendimento.queixa_principal,
            anamnese=atendimento.anamnese,
            exame_fisico=atendimento.exame_fisico,
            dados_clinicos=atendimento.dados_clinicos,
            diagnostico_principal=atendimento.diagnostico_principal,
            diagnostico_secundario=atendimento.diagnostico_secundario,
            diagnostico_diferencial=atendimento.diagnostico_diferencial,
            plano_terapeutico=atendimento.plano_terapeutico,
            confirmado=bool(payload.confirmar_conclusao_pendencias),
        )

        if atendimento.agendamento_id:
            agendamento = _carregar_e_validar_agendamento_atendimento(
                db,
                agendamento_id=int(atendimento.agendamento_id),
                paciente_id=int(atendimento.paciente_id),
                clinica_id=atendimento.clinica_id,
                atendimento_id_excluir=atendimento.id,
                lock=True,
            )
            agenda_status_anterior = agendamento.status
            if agendamento.status in ATENDIMENTO_AGENDA_STATUS_TERMINAIS:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"A Agenda #{agendamento.id} esta como {agendamento.status}. "
                        "Reabra ou corrija o agendamento antes de finalizar."
                    ),
                )

            origem_atendimento = _normalizar_origem_atendimento(
                getattr(agendamento, "origem_atendimento", None)
            )
            if not agendamento.servico_id:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Informe o servico na Agenda antes de finalizar o atendimento.",
                )
            if (
                origem_atendimento != ORIGEM_ATENDIMENTO_DOMICILIAR
                and not agendamento.clinica_id
            ):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Informe a clinica na Agenda antes de finalizar o atendimento.",
                )

            ordem_servico = _buscar_os_ativa(db, agendamento.id)
            os_reutilizada = ordem_servico is not None
            if ordem_servico is None:
                try:
                    valor_servico = calcular_preco_servico(
                        db=db,
                        clinica_id=agendamento.clinica_id,
                        servico_id=int(agendamento.servico_id),
                        tipo_horario=tipo_horario,
                        usar_preco_clinica=True,
                        origem_atendimento=origem_atendimento,
                    )
                except HTTPException as exc:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail=f"Nao foi possivel gerar a OS: {exc.detail}.",
                    ) from exc

                valor_servico = Decimal(valor_servico)
                if valor_servico <= Decimal("0.00"):
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail=(
                            "Nao foi possivel gerar a OS: configure um preco maior que zero "
                            "para o servico e o tipo de horario selecionado."
                        ),
                    )

                ordem_servico = OrdemServico(
                    numero_os=_gerar_numero_os_finalizacao(db),
                    agendamento_id=agendamento.id,
                    paciente_id=int(agendamento.paciente_id),
                    clinica_id=agendamento.clinica_id,
                    servico_id=int(agendamento.servico_id),
                    origem_atendimento=origem_atendimento,
                    data_atendimento=agendamento.inicio,
                    tipo_horario=tipo_horario,
                    valor_servico=valor_servico,
                    desconto=Decimal("0.00"),
                    valor_final=valor_servico,
                    status="Pendente",
                    observacoes=(
                        f"OS gerada pela finalizacao do atendimento {atendimento.id} "
                        f"vinculado ao agendamento {agendamento.id}"
                    ),
                    criado_por_id=current_user.id,
                    criado_por_nome=current_user.nome,
                )
                db.add(ordem_servico)
                db.flush()

            agendamento.status = "Realizado"
            agendamento.atualizado_em = datetime.now()
            agendamento.updated_at = datetime.now()

        atendimento.status = "Concluido"
        atendimento.consulta_concluida = 1
        atendimento.updated_at = datetime.now()
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "A finalizacao entrou em conflito com outra requisicao. "
                "Recarregue o atendimento; a repeticao e segura."
            ),
        ) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        logger.exception("Falha transacional ao finalizar Atendimento #%s", atendimento_id)
        raise HTTPException(
            status_code=500,
            detail=(
                "Nao foi possivel finalizar o atendimento. "
                "Nenhuma mudanca parcial foi mantida."
            ),
        ) from exc

    db.refresh(atendimento)
    if agendamento:
        db.refresh(agendamento)
    if ordem_servico:
        db.refresh(ordem_servico)

    _emitir_efeitos_finalizacao(
        db=db,
        request=request,
        current_user=current_user,
        atendimento=atendimento,
        agendamento=agendamento,
        ordem_servico=ordem_servico,
        atendimento_status_anterior=atendimento_status_anterior,
        agenda_status_anterior=agenda_status_anterior,
        os_reutilizada=os_reutilizada,
        tipo_horario=tipo_horario,
    )
    if pendencias_conclusao:
        _auditar_conclusao_com_pendencias(
            current_user=current_user,
            atendimento=atendimento,
            pendencias=pendencias_conclusao,
            request=request,
        )

    if agendamento and ordem_servico:
        acao_os = "reutilizada" if os_reutilizada else "gerada"
        mensagem = (
            f"Atendimento finalizado. Agenda #{agendamento.id} realizada e "
            f"OS {ordem_servico.numero_os} {acao_os}."
        )
    else:
        mensagem = "Atendimento finalizado sem Agenda vinculada."

    return {
        "atendimento": _montar_detalhe_atendimento(db, atendimento),
        "agenda": (
            {
                "id": agendamento.id,
                "status": agendamento.status,
                "status_anterior": agenda_status_anterior,
            }
            if agendamento
            else None
        ),
        "ordem_servico": (
            {
                "id": ordem_servico.id,
                "numero_os": ordem_servico.numero_os,
                "valor_final": float(ordem_servico.valor_final or 0),
                "reutilizada": os_reutilizada,
            }
            if ordem_servico
            else None
        ),
        "mensagem": mensagem,
    }


@router.delete("/{atendimento_id}")
def excluir_atendimento(
    atendimento_id: int,
    request: Request,
    confirmar_exclusao: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    atendimento = db.query(AtendimentoClinico).filter(AtendimentoClinico.id == atendimento_id).with_for_update().first()
    if not atendimento:
        raise HTTPException(status_code=404, detail="Atendimento nao encontrado.")

    if db.query(DocumentoAtendimento.id).filter(DocumentoAtendimento.atendimento_id == atendimento_id).first():
        raise HTTPException(status_code=409, detail="Atendimento possui documentos clinicos preservados e nao pode ser excluido. Arquive os documentos individualmente.")

    exames_do_atendimento = db.query(Exame).filter(Exame.atendimento_id == atendimento_id).all()
    # Um exame pode estar liberado no portal parceiro mesmo com o atendimento
    # ainda em andamento (liberar_exame_no_portal nao exige status Concluido) -
    # excluir o atendimento inteiro nao pode ser um atalho para contornar o
    # guard de excluir_anexo, que ja bloqueia apagar o unico PDF desse exame.
    tem_exame_liberado_portal = any(is_portal_released_status(e.status) for e in exames_do_atendimento)

    if (_status_atendimento_concluido(atendimento.status) or tem_exame_liberado_portal) and not confirmar_exclusao:
        motivos = []
        if _status_atendimento_concluido(atendimento.status):
            motivos.append("esta concluido")
        if tem_exame_liberado_portal:
            motivos.append("tem exame(s) liberado(s) no portal da clinica parceira")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "codigo": "CONFIRMACAO_EXCLUSAO_ATENDIMENTO_CONCLUIDO",
                "mensagem": (
                    f"Atendimento #{atendimento_id} {' e '.join(motivos)}. Confirme para "
                    "excluir mesmo assim - o agendamento vinculado (se houver) volta "
                    'para "Confirmado", a Ordem de Servico ativa e cancelada, e '
                    "qualquer PDF liberado no portal parceiro e removido definitivamente."
                ),
                "confirmavel": True,
            },
        )

    status_anterior = atendimento.status
    agendamento_id_vinculado = atendimento.agendamento_id
    agendamento = None
    agenda_status_anterior = None
    ordem_servico_cancelada_id = None

    if agendamento_id_vinculado:
        agendamento = db.query(Agendamento).filter(Agendamento.id == agendamento_id_vinculado).first()
        if agendamento:
            agenda_status_anterior = agendamento.status
            agendamento.status = "Confirmado"
            agendamento.atualizado_em = datetime.now()
            agendamento.updated_at = datetime.now()

            ordem_servico_ativa = _buscar_os_ativa(db, agendamento_id_vinculado)
            if ordem_servico_ativa:
                # O recebimento em lote e o individual usam este mesmo lock.
                # Recarrega o status antes de decidir se ha baixa a desfazer.
                ordem_servico_ativa = _bloquear_os_para_escrita(db, ordem_servico_ativa.id)
                if (
                    not ordem_servico_ativa
                    or ordem_servico_ativa.status not in {"Pendente", "Pago"}
                    or ordem_servico_ativa.agendamento_id != agendamento_id_vinculado
                ):
                    raise HTTPException(409, "A OS vinculada mudou. Recarregue antes de excluir o atendimento.")
                if ordem_servico_ativa.status == "Pago":
                    # Cancelar direto perderia o rastro do recebimento: a
                    # Transacao continuaria "Pago"/"Recebido" e nenhum
                    # CreditoFinanceiro consumido seria restituido, divergindo
                    # do financeiro. Desfaz pelo mesmo fluxo usado manualmente
                    # antes de cancelar a OS.
                    desfazer_recebimento_ordem(
                        os_id=ordem_servico_ativa.id,
                        request=request,
                        db=db,
                        current_user=current_user,
                    )
                    # O desfazer confirma a propria transacao. Recupera o lock
                    # antes de cancelar, pois outra sessao pode receber de novo.
                    ordem_servico_ativa = _bloquear_os_para_escrita(db, ordem_servico_ativa.id)
                    if (
                        not ordem_servico_ativa
                        or ordem_servico_ativa.status != "Pendente"
                        or ordem_servico_ativa.agendamento_id != agendamento_id_vinculado
                    ):
                        raise HTTPException(409, "A OS mudou apos desfazer o recebimento. Recarregue antes de excluir o atendimento.")
                ordem_servico_ativa.status = "Cancelado"
                ordem_servico_cancelada_id = ordem_servico_ativa.id

    db.query(EvolucaoClinica).filter(EvolucaoClinica.atendimento_id == atendimento_id).delete(
        synchronize_session=False
    )
    db.query(PrescricaoItemAjuste).filter(PrescricaoItemAjuste.atendimento_id == atendimento_id).delete(
        synchronize_session=False
    )

    for exame in exames_do_atendimento:
        _excluir_anexos_por_exame(db, exame.id)
        db.delete(exame)

    _excluir_anexos_por_atendimento(db, atendimento_id)

    # Todas as receitas, nao so a do dia: um atendimento pode ter
    # complementares emitidas em adendos.
    prescricoes_do_atendimento = (
        db.query(PrescricaoClinica)
        .filter(PrescricaoClinica.atendimento_id == atendimento_id)
        .all()
    )
    for prescricao in prescricoes_do_atendimento:
        itens = db.query(PrescricaoItem).filter(PrescricaoItem.prescricao_id == prescricao.id).all()
        for item in itens:
            db.delete(item)
        db.delete(prescricao)

    registrar_auditoria(
        current_user=current_user,
        modulo="atendimento",
        entidade="atendimento_clinico",
        entidade_id=atendimento_id,
        acao="ATENDIMENTO_EXCLUIDO",
        descricao=f"Atendimento #{atendimento_id} excluido (status anterior: {status_anterior}).",
        detalhes={
            "status_anterior": status_anterior,
            "agendamento_id": agendamento_id_vinculado,
            "agenda_status_anterior": agenda_status_anterior,
            "agenda_status_novo": agendamento.status if agendamento else None,
            "ordem_servico_cancelada_id": ordem_servico_cancelada_id,
        },
        request=request,
    )
    if agendamento and agenda_status_anterior != agendamento.status:
        registrar_auditoria(
            current_user=current_user,
            modulo="agenda",
            entidade="agendamento",
            entidade_id=agendamento.id,
            acao="AGENDAMENTO_REVERTIDO_POR_EXCLUSAO_ATENDIMENTO",
            descricao=(
                f"Agenda #{agendamento.id} revertida para \"{agendamento.status}\" "
                f"pela exclusao do Atendimento #{atendimento_id}."
            ),
            detalhes={
                "atendimento_id": atendimento_id,
                "status_anterior": agenda_status_anterior,
                "status_novo": agendamento.status,
                "ordem_servico_cancelada_id": ordem_servico_cancelada_id,
            },
            request=request,
        )

    db.delete(atendimento)
    db.commit()
    return {"message": "Atendimento removido com sucesso.", "id": atendimento_id}


@router.get("/medicamentos/banco")
def listar_medicamentos(
    search: Optional[str] = None,
    ativos: int = 1,
    skip: int = 0,
    limit: int = 200,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = current_user
    query = db.query(Medicamento)
    if ativos == 1:
        query = query.filter(Medicamento.ativo == 1)
    if search:
        termo = f"%{search.strip()}%"
        query = query.filter(
            or_(
                Medicamento.nome.ilike(termo),
                Medicamento.principio_ativo.ilike(termo),
                Medicamento.categoria.ilike(termo),
                Medicamento.classe_terapeutica.ilike(termo),
            )
        )

    total = query.count()
    items = (
        query.order_by(Medicamento.nome.asc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    return {
        "total": total,
        "items": [_serialize_medicamento(item) for item in items],
    }


@router.post("/medicamentos/banco", status_code=status.HTTP_201_CREATED)
def criar_medicamento(
    payload: MedicamentoPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = current_user
    nome_limpo = payload.nome.strip()
    if not nome_limpo:
        raise HTTPException(status_code=422, detail="Nome do medicamento e obrigatorio.")

    duplicado = (
        db.query(Medicamento)
        .filter(Medicamento.nome.ilike(nome_limpo))
        .first()
    )
    if duplicado:
        raise HTTPException(status_code=400, detail="Ja existe medicamento com esse nome.")

    medicamento = Medicamento(
        nome=nome_limpo,
        principio_ativo=payload.principio_ativo or "",
        concentracao=payload.concentracao or "",
        forma_farmaceutica=payload.forma_farmaceutica or "",
        categoria=payload.categoria or "",
        classe_terapeutica=payload.classe_terapeutica or "",
        especie_alvo=payload.especie_alvo or "Canina,Felina",
        dose_min_mg_kg=payload.dose_min_mg_kg,
        dose_max_mg_kg=payload.dose_max_mg_kg,
        dose_intervalo_horas=payload.dose_intervalo_horas,
        dose_unidade=payload.dose_unidade or "mg/kg",
        via_padrao=payload.via_padrao or "",
        duracao_padrao=payload.duracao_padrao or "",
        concentracao_mg_ml=payload.concentracao_mg_ml,
        concentracao_mg_comprimido=payload.concentracao_mg_comprimido,
        indicacoes=payload.indicacoes or "",
        contraindicacoes=payload.contraindicacoes or "",
        interacoes_json=json.dumps(payload.interacoes or []),
        observacao_seguranca=payload.observacao_seguranca or "",
        parametrizacao_origem=payload.parametrizacao_origem or "manual",
        observacoes=payload.observacoes or "",
        ativo=1 if payload.ativo else 0,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    db.add(medicamento)
    db.commit()
    db.refresh(medicamento)
    return _serialize_medicamento(medicamento)


@router.put("/medicamentos/banco/{medicamento_id}")
def atualizar_medicamento(
    medicamento_id: int,
    payload: MedicamentoPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = current_user
    medicamento = db.query(Medicamento).filter(Medicamento.id == medicamento_id).first()
    if not medicamento:
        raise HTTPException(status_code=404, detail="Medicamento nao encontrado.")

    nome_limpo = payload.nome.strip()
    if not nome_limpo:
        raise HTTPException(status_code=422, detail="Nome do medicamento e obrigatorio.")

    duplicado = (
        db.query(Medicamento)
        .filter(Medicamento.id != medicamento_id, Medicamento.nome.ilike(nome_limpo))
        .first()
    )
    if duplicado:
        raise HTTPException(status_code=400, detail="Ja existe medicamento com esse nome.")

    medicamento.nome = nome_limpo
    medicamento.principio_ativo = payload.principio_ativo or ""
    medicamento.concentracao = payload.concentracao or ""
    medicamento.forma_farmaceutica = payload.forma_farmaceutica or ""
    medicamento.categoria = payload.categoria or ""
    medicamento.classe_terapeutica = payload.classe_terapeutica or ""
    medicamento.especie_alvo = payload.especie_alvo or "Canina,Felina"
    medicamento.dose_min_mg_kg = payload.dose_min_mg_kg
    medicamento.dose_max_mg_kg = payload.dose_max_mg_kg
    medicamento.dose_intervalo_horas = payload.dose_intervalo_horas
    medicamento.dose_unidade = payload.dose_unidade or "mg/kg"
    medicamento.via_padrao = payload.via_padrao or ""
    medicamento.duracao_padrao = payload.duracao_padrao or ""
    medicamento.concentracao_mg_ml = payload.concentracao_mg_ml
    medicamento.concentracao_mg_comprimido = payload.concentracao_mg_comprimido
    medicamento.indicacoes = payload.indicacoes or ""
    medicamento.contraindicacoes = payload.contraindicacoes or ""
    medicamento.interacoes_json = json.dumps(payload.interacoes or [])
    medicamento.observacao_seguranca = payload.observacao_seguranca or ""
    medicamento.parametrizacao_origem = payload.parametrizacao_origem or medicamento.parametrizacao_origem or "manual"
    medicamento.observacoes = payload.observacoes or ""
    medicamento.ativo = 1 if payload.ativo else 0
    medicamento.updated_at = datetime.now()

    db.commit()
    db.refresh(medicamento)
    return _serialize_medicamento(medicamento)


@router.delete("/medicamentos/banco/{medicamento_id}")
def desativar_medicamento(
    medicamento_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = current_user
    medicamento = db.query(Medicamento).filter(Medicamento.id == medicamento_id).first()
    if not medicamento:
        raise HTTPException(status_code=404, detail="Medicamento nao encontrado.")

    medicamento.ativo = 0
    medicamento.updated_at = datetime.now()
    db.commit()
    return {"message": "Medicamento desativado com sucesso.", "id": medicamento_id}


# === EVOLUÃ‡Ã•ES CLÃNICAS ===
@router.get("/{atendimento_id}/evolucoes")
def listar_evolucoes(
    atendimento_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = current_user
    evolucoes = (
        db.query(EvolucaoClinica)
        .filter(EvolucaoClinica.atendimento_id == atendimento_id)
        .order_by(EvolucaoClinica.data_evolucao.desc())
        .all()
    )
    return {
        "items": [
            {
                "id": e.id,
                "atendimento_id": e.atendimento_id,
                "data_evolucao": _to_iso(e.data_evolucao),
                "descricao": e.descricao,
                "sinais_vitais": e.sinais_vitais or "",
                "responsavel_id": e.responsavel_id,
                "responsavel_nome": e.responsavel_nome or "",
                "created_at": _to_iso(e.created_at),
            }
            for e in evolucoes
        ]
    }


@router.post("/{atendimento_id}/evolucoes", status_code=status.HTTP_201_CREATED)
def criar_evolucao(
    atendimento_id: int,
    payload: EvolucaoPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    atendimento = db.query(AtendimentoClinico).filter(AtendimentoClinico.id == atendimento_id).first()
    if not atendimento:
        raise HTTPException(status_code=404, detail="Atendimento nao encontrado.")

    evolucao = EvolucaoClinica(
        atendimento_id=atendimento_id,
        descricao=payload.descricao,
        sinais_vitais=payload.sinais_vitais,
        # Mesma derivacao do endpoint de adendo: uma evolucao registrada
        # depois da conclusao e um adendo, independente da rota usada.
        pos_conclusao=1 if _status_atendimento_concluido(atendimento.status) else 0,
        responsavel_id=current_user.id,
        responsavel_nome=current_user.nome,
    )
    db.add(evolucao)
    db.commit()
    db.refresh(evolucao)

    return {
        "id": evolucao.id,
        "atendimento_id": evolucao.atendimento_id,
        "data_evolucao": _to_iso(evolucao.data_evolucao),
        "descricao": evolucao.descricao,
        "sinais_vitais": evolucao.sinais_vitais or "",
        "responsavel_nome": evolucao.responsavel_nome,
    }


# === ADENDOS E RECEITAS COMPLEMENTARES ===


def _carregar_adendos_serializados(
    db: Session,
    atendimento_id: int,
    *,
    anexos: Optional[List[AnexoAtendimento]] = None,
) -> List[dict]:
    """Adendos do atendimento com seus anexos e receita vinculada.

    Recebe `anexos` ja carregados quando o chamador tem a lista em maos, para
    nao repetir a consulta (o detalhe do atendimento ja busca todos)."""
    adendos = (
        db.query(EvolucaoClinica)
        .filter(EvolucaoClinica.atendimento_id == atendimento_id)
        .order_by(EvolucaoClinica.data_evolucao.desc(), EvolucaoClinica.id.desc())
        .all()
    )
    if not adendos:
        return []

    adendo_ids = [adendo.id for adendo in adendos if adendo.id]
    if anexos is None:
        anexos = (
            db.query(AnexoAtendimento)
            .filter(AnexoAtendimento.evolucao_id.in_(adendo_ids))
            .order_by(AnexoAtendimento.created_at.desc(), AnexoAtendimento.id.desc())
            .all()
            if adendo_ids
            else []
        )

    anexos_por_adendo: Dict[int, List[dict]] = defaultdict(list)
    for anexo in anexos:
        if getattr(anexo, "evolucao_id", None):
            anexos_por_adendo[anexo.evolucao_id].append(_serialize_anexo(anexo))

    prescricao_por_adendo: Dict[int, int] = {}
    if adendo_ids:
        for prescricao_id, adendo_id in (
            db.query(PrescricaoClinica.id, PrescricaoClinica.adendo_id)
            .filter(PrescricaoClinica.adendo_id.in_(adendo_ids))
            .all()
        ):
            prescricao_por_adendo.setdefault(adendo_id, prescricao_id)

    return [
        _serialize_adendo(
            adendo,
            anexos=anexos_por_adendo.get(adendo.id, []),
            prescricao_id=prescricao_por_adendo.get(adendo.id),
        )
        for adendo in adendos
    ]


def _serializar_prescricao(
    db: Session,
    atendimento: AtendimentoClinico,
    prescricao: PrescricaoClinica,
) -> dict:
    itens = (
        db.query(PrescricaoItem)
        .filter(PrescricaoItem.prescricao_id == prescricao.id)
        .order_by(PrescricaoItem.ordem.asc(), PrescricaoItem.id.asc())
        .all()
    )
    historico_por_item = _map_ajustes_por_item(db, [item.id for item in itens if item.id])
    itens_dict = []
    for item in itens:
        mapped_item = _map_prescricao_item(item)
        mapped_item["historico_ajustes"] = historico_por_item.get(item.id, [])
        itens_dict.append(mapped_item)

    paciente = db.query(Paciente).filter(Paciente.id == atendimento.paciente_id).first()
    peso_referencia = _resolver_peso_referencia(atendimento, paciente)
    return _montar_prescricao_dict(
        db,
        prescricao,
        itens_dict,
        peso_referencia=peso_referencia,
    )


@router.get("/{atendimento_id}/adendos")
def listar_adendos(
    atendimento_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = current_user
    atendimento = db.query(AtendimentoClinico).filter(AtendimentoClinico.id == atendimento_id).first()
    if not atendimento:
        raise HTTPException(status_code=404, detail="Atendimento nao encontrado.")
    return {"items": _carregar_adendos_serializados(db, atendimento_id)}


@router.post("/{atendimento_id}/adendos", status_code=status.HTTP_201_CREATED)
def criar_adendo(
    atendimento_id: int,
    payload: AdendoPayload,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Registra o que chega depois do encontro, dentro do mesmo atendimento.

    Nao gera ordem de servico e nao altera o status do atendimento nem o da
    Agenda: o adendo e continuidade do atendimento original, ja faturado."""
    atendimento = db.query(AtendimentoClinico).filter(AtendimentoClinico.id == atendimento_id).first()
    if not atendimento:
        raise HTTPException(status_code=404, detail="Atendimento nao encontrado.")

    tipo = _normalizar_tipo_adendo(payload.tipo)
    pos_conclusao = 1 if _status_atendimento_concluido(atendimento.status) else 0
    data_evolucao = _parse_datetime(payload.data_evolucao) or datetime.now(ATENDIMENTO_LOCAL_TZ)

    adendo = EvolucaoClinica(
        atendimento_id=atendimento.id,
        data_evolucao=data_evolucao,
        tipo=tipo,
        titulo=(payload.titulo or "").strip() or None,
        pos_conclusao=pos_conclusao,
        descricao=(payload.descricao or "").strip(),
        sinais_vitais=payload.sinais_vitais,
        responsavel_id=current_user.id,
        responsavel_nome=current_user.nome,
    )
    db.add(adendo)
    db.commit()
    db.refresh(adendo)

    if pos_conclusao:
        registrar_auditoria(
            current_user=current_user,
            modulo="atendimento",
            entidade="evolucao_clinica",
            entidade_id=adendo.id,
            acao="CRIAR_ADENDO_POS_CONCLUSAO",
            descricao=(
                f"Adendo '{_titulo_adendo(adendo)}' registrado no atendimento "
                f"#{atendimento.id}, ja concluido."
            ),
            detalhes={
                "atendimento_id": atendimento.id,
                "paciente_id": atendimento.paciente_id,
                "tipo": tipo,
            },
            request=request,
        )

    return {"adendo": _serialize_adendo(adendo)}


@router.post("/{atendimento_id}/prescricoes", status_code=status.HTTP_201_CREATED)
def criar_prescricao_complementar(
    atendimento_id: int,
    payload: PrescricaoComplementarPayload,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Cria a proxima receita do atendimento, sem tocar nas anteriores."""
    atendimento = db.query(AtendimentoClinico).filter(AtendimentoClinico.id == atendimento_id).first()
    if not atendimento:
        raise HTTPException(status_code=404, detail="Atendimento nao encontrado.")

    adendo = _carregar_adendo_do_atendimento(
        db,
        atendimento_id=atendimento.id,
        adendo_id=payload.adendo_id,
    )
    origem = None
    if payload.copiar_de_prescricao_id:
        origem = _carregar_prescricao_do_atendimento(
            db,
            atendimento_id=atendimento.id,
            prescricao_id=int(payload.copiar_de_prescricao_id),
        )

    prescricao = PrescricaoClinica(
        atendimento_id=atendimento.id,
        sequencia=_proxima_sequencia_prescricao(db, atendimento.id),
        adendo_id=adendo.id if adendo else None,
        orientacoes_gerais=(origem.orientacoes_gerais if origem else "") or "",
        retorno_dias=origem.retorno_dias if origem else None,
    )
    db.add(prescricao)
    db.flush()

    if origem:
        itens_origem = (
            db.query(PrescricaoItem)
            .filter(PrescricaoItem.prescricao_id == origem.id)
            .order_by(PrescricaoItem.ordem.asc(), PrescricaoItem.id.asc())
            .all()
        )
        # Copia como registros novos: a receita de origem nao empresta ids,
        # entao editar a copia nunca alcanca o documento ja emitido.
        for index, item in enumerate(itens_origem):
            db.add(
                PrescricaoItem(
                    prescricao_id=prescricao.id,
                    medicamento_id=item.medicamento_id,
                    medicamento_nome=item.medicamento_nome,
                    apresentacao_selecionada=item.apresentacao_selecionada,
                    dose=item.dose,
                    frequencia=item.frequencia,
                    duracao=item.duracao,
                    via=item.via,
                    instrucoes=item.instrucoes,
                    ordem=index,
                    dose_mg_kg=item.dose_mg_kg,
                    peso_referencia_kg=item.peso_referencia_kg,
                    unidade_dose_calculo=item.unidade_dose_calculo,
                    concentracao_personalizada=item.concentracao_personalizada,
                )
            )

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Outra receita foi criada para este atendimento ao mesmo tempo. Recarregue e tente de novo.",
        ) from exc

    db.refresh(prescricao)

    registrar_auditoria(
        current_user=current_user,
        modulo="atendimento",
        entidade="prescricao_clinica",
        entidade_id=prescricao.id,
        acao="CRIAR_RECEITA_COMPLEMENTAR",
        descricao=(
            f"Receita {_sequencia_prescricao(prescricao)} criada no atendimento "
            f"#{atendimento.id}"
            + (f", copiada da receita #{origem.id}." if origem else ".")
        ),
        detalhes={
            "atendimento_id": atendimento.id,
            "prescricao_id": prescricao.id,
            "sequencia": _sequencia_prescricao(prescricao),
            "adendo_id": adendo.id if adendo else None,
            "copiada_de": origem.id if origem else None,
        },
        request=request,
    )

    return {"prescricao": _serializar_prescricao(db, atendimento, prescricao)}


@router.put("/{atendimento_id}/prescricoes/{prescricao_id}")
def atualizar_prescricao(
    atendimento_id: int,
    prescricao_id: int,
    payload: PrescricaoSyncPayload,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    atendimento = (db.query(AtendimentoClinico).filter(AtendimentoClinico.id == atendimento_id)
                   .populate_existing().with_for_update().first())
    if not atendimento:
        raise HTTPException(status_code=404, detail="Atendimento nao encontrado.")

    prescricao = _carregar_prescricao_do_atendimento(
        db,
        atendimento_id=atendimento.id,
        prescricao_id=prescricao_id,
    )

    antes = _snapshot_prescricao(db, prescricao, reler=True)
    try:
        _sync_prescricao(db, atendimento, payload, current_user, prescricao=prescricao)
        _auditar_edicao_prescricao(
            db, current_user=current_user, atendimento=atendimento,
            prescricao=prescricao, antes=antes, request=request,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(prescricao)

    return {"prescricao": _serializar_prescricao(db, atendimento, prescricao)}


# === ANEXOS ===
@router.get("/upload-metrics/dedupe")
def consultar_metricas_upload_dedupe(
    data_inicio: Optional[str] = Query(None, description="Data inicial no formato YYYY-MM-DD"),
    data_fim: Optional[str] = Query(None, description="Data final no formato YYYY-MM-DD"),
    clinica_id: Optional[int] = Query(None, ge=1),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = current_user
    inicio = _parse_upload_metrics_date(data_inicio, "data_inicio")
    fim = _parse_upload_metrics_date(data_fim, "data_fim")
    if inicio and fim and inicio > fim:
        raise HTTPException(status_code=400, detail="data_inicio nao pode ser maior que data_fim.")

    params = {
        "data_inicio": inicio.isoformat() if inicio else None,
        "data_fim": fim.isoformat() if fim else None,
        "clinica_id": clinica_id,
    }
    rows = db.execute(
        text(
            """
            SELECT
                DATE(created_at) AS dia,
                SUM(CASE WHEN evento = 'upload_novo' THEN 1 ELSE 0 END) AS uploads_novos,
                SUM(CASE WHEN evento = 'dedupe_precheck' THEN 1 ELSE 0 END) AS dedupe_precheck,
                SUM(CASE WHEN evento = 'dedupe_collision' THEN 1 ELSE 0 END) AS dedupe_collision,
                COUNT(*) AS total_uploads
            FROM upload_dedupe_metricas
            WHERE (:data_inicio IS NULL OR DATE(created_at) >= :data_inicio)
              AND (:data_fim IS NULL OR DATE(created_at) <= :data_fim)
              AND (:clinica_id IS NULL OR clinica_id = :clinica_id)
            GROUP BY DATE(created_at)
            ORDER BY DATE(created_at) DESC
            """
        ),
        params,
    ).fetchall()

    items = []
    for row in rows:
        mapping = row._mapping if hasattr(row, "_mapping") else None
        dia_raw = mapping["dia"] if mapping is not None else row[0]
        dia = dia_raw.isoformat() if hasattr(dia_raw, "isoformat") else str(dia_raw)
        uploads_novos = int((mapping["uploads_novos"] if mapping is not None else row[1]) or 0)
        dedupe_precheck = int((mapping["dedupe_precheck"] if mapping is not None else row[2]) or 0)
        dedupe_collision = int((mapping["dedupe_collision"] if mapping is not None else row[3]) or 0)
        total_uploads = int((mapping["total_uploads"] if mapping is not None else row[4]) or 0)
        items.append(
            {
                "date": dia,
                "uploads_novos": uploads_novos,
                "dedupe_precheck": dedupe_precheck,
                "dedupe_collision": dedupe_collision,
                "total_uploads": total_uploads,
            }
        )

    return {
        "items": items,
        "filters": {
            "data_inicio": params["data_inicio"],
            "data_fim": params["data_fim"],
            "clinica_id": clinica_id,
        },
    }


@router.post("/upload-metrics/dedupe/cleanup")
def executar_cleanup_upload_dedupe_metricas(
    current_user: User = Depends(get_current_user),
):
    _require_admin_cleanup_access(current_user)

    try:
        return run_upload_dedupe_cleanup(executor=UPLOAD_DEDUPE_CLEANUP_EXECUTOR_MANUAL)
    except UploadDedupeCleanupBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except UploadDedupeCleanupExecutionError as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/upload-metrics/dedupe/cleanup/status")
def consultar_status_cleanup_upload_dedupe_metricas(
    current_user: User = Depends(get_current_user),
):
    _require_admin_cleanup_access(current_user)
    return get_upload_dedupe_cleanup_status()


def _auditar_transicao_exame_portal(
    *,
    current_user: User,
    exame: Exame,
    acao: str,
    descricao: str,
    status_anterior: str,
    request: Optional[Request] = None,
) -> None:
    """Auditoria best-effort da liberacao e da revogacao no portal."""
    registrar_auditoria(
        current_user=current_user,
        modulo="atendimento",
        entidade="exame",
        entidade_id=exame.id,
        acao=acao,
        descricao=descricao,
        detalhes={
            "atendimento_id": exame.atendimento_id,
            "paciente_id": exame.paciente_id,
            "status_anterior": status_anterior,
            "status_atual": exame.status,
        },
        request=request,
    )


@router.post("/exames/{exame_id}/portal/liberar")
def liberar_exame_no_portal(
    exame_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    request: Request = None,
):
    exame = db.query(Exame).filter(Exame.id == exame_id).first()
    if not exame:
        raise HTTPException(status_code=404, detail="Exame nao encontrado.")
    if not exame.atendimento_id:
        raise HTTPException(status_code=422, detail="Exame sem atendimento vinculado.")

    atendimento = db.query(AtendimentoClinico).filter(AtendimentoClinico.id == exame.atendimento_id).first()
    if not atendimento:
        raise HTTPException(status_code=404, detail="Atendimento do exame nao encontrado.")
    if not atendimento.clinica_id:
        raise HTTPException(status_code=422, detail="Vincule uma clinica ao atendimento antes de liberar no portal.")
    if not exame.paciente_id:
        raise HTTPException(status_code=422, detail="Exame sem paciente vinculado.")

    if is_portal_released_status(exame.status):
        # Idempotente: chamar liberar de novo enquanto ja liberado nao pode
        # reprocessar - reescreveria observacoes_pre_portal com a propria
        # mensagem fixa (ja ocorreu com duplo clique/retry de rede antes
        # desta guarda), perdendo o texto original para sempre no revogar.
        anexos_atuais = (
            db.query(AnexoAtendimento)
            .filter(AnexoAtendimento.exame_id == exame.id)
            .order_by(AnexoAtendimento.created_at.desc(), AnexoAtendimento.id.desc())
            .all()
        )
        return {
            "message": "Exame ja estava liberado no portal da clinica parceira.",
            "exame_id": exame.id,
            "paciente_id": exame.paciente_id,
            "atendimento_id": exame.atendimento_id,
            "clinic_id": atendimento.clinica_id,
            "status": exame.status,
            "released_at": _to_operational_iso(exame.data_resultado),
            "exame": {
                **_map_exame(exame),
                "anexos_resultado": [_serialize_anexo(anexo) for anexo in anexos_atuais],
            },
        }

    anexos = (
        db.query(AnexoAtendimento)
        .filter(AnexoAtendimento.exame_id == exame.id)
        .order_by(AnexoAtendimento.created_at.desc(), AnexoAtendimento.id.desc())
        .all()
    )
    # _anexo_eh_pdf sozinho so confere mime_type/extensao - campos que o
    # cliente controla ao criar um anexo "externo" (POST /{id}/anexos, sem
    # upload real). attachment_has_download_source confirma que existe de
    # fato algo baixavel (arquivo local ou URL remota valida) antes de
    # liberar o exame como "resultado disponivel" para o portal externo.
    # attachment_is_verified_pdf vai alem: confirma os bytes magicos "%PDF-"
    # no CONTEUDO real (nao so que existe algo baixavel) - um arquivo
    # renomeado para .pdf sem ser um PDF de verdade nao passa por essa
    # checagem extra.
    if not any(
        _anexo_eh_pdf(anexo) and attachment_has_download_source(anexo) and attachment_is_verified_pdf(anexo)
        for anexo in anexos
    ):
        raise HTTPException(status_code=422, detail="Anexe o PDF do resultado antes de liberar no portal.")

    released_at = datetime.now()
    status_anterior = exame.status or ""
    exame.tipo_exame = _normalizar_tipo_exame_portal_externo(exame.tipo_exame)
    if exame.tipo_exame == "Eletrocardiograma" and not (exame.categoria_exame or "").strip():
        exame.categoria_exame = "Cardiologia"
    exame.status = PORTAL_RELEASED_STATUS
    exame.data_resultado = released_at
    exame.observacoes_pre_portal = exame.observacoes or ""
    exame.observacoes = PORTAL_EXAME_RELEASE_MESSAGE
    exame.visualizado_portal_em = None
    if not exame.criado_por_id:
        exame.criado_por_id = getattr(current_user, "id", None)
    if not exame.criado_por_nome:
        exame.criado_por_nome = getattr(current_user, "nome", None)

    db.commit()
    db.refresh(exame)
    anexos_atualizados = (
        db.query(AnexoAtendimento)
        .filter(AnexoAtendimento.exame_id == exame.id)
        .order_by(AnexoAtendimento.created_at.desc(), AnexoAtendimento.id.desc())
        .all()
    )
    exame_payload = {
        **_map_exame(exame),
        "anexos_resultado": [_serialize_anexo(anexo) for anexo in anexos_atualizados],
    }
    _auditar_transicao_exame_portal(
        current_user=current_user,
        exame=exame,
        acao="LIBERAR_EXAME_PORTAL",
        descricao=f"Exame #{exame.id} liberado no portal da clinica parceira.",
        status_anterior=status_anterior,
        request=request,
    )
    return {
        "message": "Exame liberado no portal da clinica parceira.",
        "exame_id": exame.id,
        "paciente_id": exame.paciente_id,
        "atendimento_id": exame.atendimento_id,
        "clinic_id": atendimento.clinica_id,
        "status": exame.status,
        "released_at": _to_operational_iso(exame.data_resultado),
        "exame": exame_payload,
    }


@router.post("/exames/{exame_id}/portal/revogar")
def revogar_liberacao_exame_no_portal(
    exame_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    request: Request = None,
):
    exame = db.query(Exame).filter(Exame.id == exame_id).first()
    if not exame:
        raise HTTPException(status_code=404, detail="Exame nao encontrado.")
    if not is_portal_released_status(exame.status):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Este exame nao esta liberado no portal.",
        )

    status_anterior = exame.status or ""
    total_anexos = (
        db.query(AnexoAtendimento).filter(AnexoAtendimento.exame_id == exame.id).count()
    )
    exame.status = _derivar_status_exame(
        status_atual=None,
        resultado=exame.resultado,
        total_anexos=total_anexos,
    )
    if (exame.observacoes or "").strip() == PORTAL_EXAME_RELEASE_MESSAGE:
        exame.observacoes = exame.observacoes_pre_portal or ""
    exame.observacoes_pre_portal = None
    exame.visualizado_portal_em = None

    # O link direto enviado no WhatsApp da clinica nao pode sobreviver a
    # despublicacao do exame. O endpoint publico ja reconfere o status a cada
    # abertura e falharia de qualquer forma; revogar aqui deixa o corte
    # explicito e auditavel, em vez de depender so daquela checagem.
    # A confianca do dispositivo e revogada ANTES dos links: ela e localizada
    # pelo `origin_exam_link_id`, entao precisa das linhas ainda identificaveis.
    dispositivos_revogados = revoke_trusts_for_exam(db, exame.id, motivo="liberacao_revogada")
    links_revogados = revoke_links_for_exam(db, exame.id, motivo="liberacao_revogada")

    db.commit()
    db.refresh(exame)

    anexos_atualizados = (
        db.query(AnexoAtendimento)
        .filter(AnexoAtendimento.exame_id == exame.id)
        .order_by(AnexoAtendimento.created_at.desc(), AnexoAtendimento.id.desc())
        .all()
    )
    _auditar_transicao_exame_portal(
        current_user=current_user,
        exame=exame,
        acao="REVOGAR_EXAME_PORTAL",
        descricao=f"Liberacao do exame #{exame.id} no portal foi revogada.",
        status_anterior=status_anterior,
        request=request,
    )
    return {
        "message": "Liberacao do exame no portal revogada.",
        "exame_id": exame.id,
        "paciente_id": exame.paciente_id,
        "atendimento_id": exame.atendimento_id,
        "status": exame.status,
        "status_anterior": status_anterior,
        "links_revogados": links_revogados,
        "dispositivos_revogados": dispositivos_revogados,
        "exame": {
            **_map_exame(exame),
            "anexos_resultado": [_serialize_anexo(anexo) for anexo in anexos_atualizados],
        },
    }


@router.get("/{atendimento_id}/anexos")
def listar_anexos(
    atendimento_id: int,
    exame_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = current_user
    query = db.query(AnexoAtendimento).filter(AnexoAtendimento.atendimento_id == atendimento_id)
    if exame_id is not None:
        query = query.filter(AnexoAtendimento.exame_id == exame_id)
    anexos = query.order_by(AnexoAtendimento.created_at.desc()).all()
    return {"items": [_serialize_anexo(a) for a in anexos]}


@router.post("/{atendimento_id}/anexos", status_code=status.HTTP_201_CREATED)
def criar_anexo(
    atendimento_id: int,
    payload: AnexoPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = current_user
    atendimento = db.query(AtendimentoClinico).filter(AtendimentoClinico.id == atendimento_id).first()
    if not atendimento:
        raise HTTPException(status_code=404, detail="Atendimento nao encontrado.")
    if payload.exame_id:
        exame = (
            db.query(Exame)
            .filter(Exame.id == payload.exame_id, Exame.atendimento_id == atendimento_id)
            .first()
        )
        if not exame:
            raise HTTPException(status_code=404, detail="Exame nao encontrado para este atendimento.")
    adendo = _carregar_adendo_do_atendimento(
        db,
        atendimento_id=atendimento_id,
        adendo_id=payload.evolucao_id,
    )

    anexo = AnexoAtendimento(
        atendimento_id=atendimento_id,
        exame_id=payload.exame_id,
        evolucao_id=adendo.id if adendo else None,
        tipo=payload.tipo,
        descricao=payload.descricao,
        url=payload.url,
        nome_original=payload.nome_original,
        tamanho=payload.tamanho,
        mime_type=payload.mime_type,
        origem="externo",
    )
    db.add(anexo)
    db.commit()
    db.refresh(anexo)

    return _serialize_anexo(anexo)


@router.post("/{atendimento_id}/anexos/upload", status_code=status.HTTP_201_CREATED)
async def upload_anexo(
    atendimento_id: int,
    arquivo: UploadFile = File(...),
    tipo: str = Form(...),
    descricao: str = Form(""),
    exame_id: Optional[int] = Form(None),
    evolucao_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = current_user
    atendimento = db.query(AtendimentoClinico).filter(AtendimentoClinico.id == atendimento_id).first()
    if not atendimento:
        raise HTTPException(status_code=404, detail="Atendimento nao encontrado.")

    exame = None
    if exame_id is not None:
        exame = db.query(Exame).filter(Exame.id == exame_id, Exame.atendimento_id == atendimento_id).first()
        if not exame:
            raise HTTPException(status_code=404, detail="Exame nao encontrado para este atendimento.")

    adendo = _carregar_adendo_do_atendimento(
        db,
        atendimento_id=atendimento_id,
        adendo_id=evolucao_id,
    )

    content = await arquivo.read()
    if not content:
        logger.warning(
            "Upload de anexo rejeitado: arquivo vazio (atendimento_id=%s, user_id=%s, filename=%s)",
            atendimento_id,
            current_user.id,
            arquivo.filename,
        )
        raise HTTPException(status_code=400, detail="Arquivo vazio.")

    arquivo_hash = calculate_attachment_sha256(content)
    dedupe_key = build_upload_dedupe_key(exame.id if exame else None, arquivo_hash)
    anexo_existente = _find_existing_upload_anexo_by_dedupe_key(
        db,
        atendimento_id=atendimento_id,
        dedupe_key=dedupe_key,
    )
    if anexo_existente:
        logger.info(
            "Upload de anexo deduplicado (atendimento_id=%s, exame_id=%s, user_id=%s, anexo_id=%s, dedupe_key=%s)",
            atendimento_id,
            exame.id if exame else None,
            current_user.id,
            anexo_existente.id,
            dedupe_key,
        )
        _registrar_upload_dedupe_metrica(
            db,
            atendimento=atendimento,
            evento=UPLOAD_DEDUPE_EVENT_PRECHECK,
            dedupe_key=dedupe_key,
        )
        # O dedupe e por (atendimento, exame, bytes). Quando o mesmo arquivo ja
        # existia solto e agora chega por um adendo, adota o anexo no adendo em
        # vez de devolver um adendo sem nada dentro.
        if adendo and not getattr(anexo_existente, "evolucao_id", None):
            anexo_existente.evolucao_id = adendo.id
            db.commit()
            db.refresh(anexo_existente)
        payload = _serialize_anexo(anexo_existente)
        payload["deduplicado"] = True
        return JSONResponse(status_code=status.HTTP_200_OK, content=payload)

    try:
        storage_path, normalized_name, normalized_mime_type = store_atendimento_attachment_file(
            atendimento_id,
            arquivo.filename,
            content,
            arquivo.content_type,
        )
    except AttachmentTooLargeError as exc:
        logger.warning(
            "Upload de anexo rejeitado: arquivo acima do limite (atendimento_id=%s, user_id=%s, filename=%s, size_bytes=%s)",
            atendimento_id,
            current_user.id,
            arquivo.filename,
            len(content),
        )
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=str(exc),
        ) from exc
    except AttachmentTypeError as exc:
        logger.warning(
            "Upload de anexo rejeitado: tipo invalido (atendimento_id=%s, user_id=%s, filename=%s, content_type=%s)",
            atendimento_id,
            current_user.id,
            arquivo.filename,
            arquivo.content_type,
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        logger.exception(
            "Upload de anexo falhou por erro de storage (atendimento_id=%s, user_id=%s, filename=%s)",
            atendimento_id,
            current_user.id,
            arquivo.filename,
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    anexo = AnexoAtendimento(
        atendimento_id=atendimento_id,
        exame_id=exame.id if exame else None,
        evolucao_id=adendo.id if adendo else None,
        tipo=(tipo or "documento").strip() or "documento",
        descricao=(descricao or "").strip() or None,
        url="",
        nome_original=normalized_name,
        tamanho=len(content),
        mime_type=normalized_mime_type,
        arquivo_hash=arquivo_hash,
        dedupe_key=dedupe_key,
        caminho_arquivo=storage_path,
        origem="upload",
    )
    db.add(anexo)
    try:
        db.flush()
        anexo.url = f"/api/v1/atendimentos/anexos/{anexo.id}/arquivo"

        if exame and not _status_exame_regressao_bloqueada(exame.status):
            exame.status = "Em andamento"
        if exame and not exame.data_resultado:
            exame.data_resultado = datetime.now()

        db.commit()
        db.refresh(anexo)

        _registrar_upload_dedupe_metrica(
            db,
            atendimento=atendimento,
            evento=UPLOAD_DEDUPE_EVENT_UPLOAD_NOVO,
            dedupe_key=dedupe_key,
        )
        payload = _serialize_anexo(anexo)
        payload["deduplicado"] = False
        return payload
    except IntegrityError:
        db.rollback()
        remove_atendimento_attachment_file(storage_path)
        anexo_concorrente = _find_existing_upload_anexo_by_dedupe_key(
            db,
            atendimento_id=atendimento_id,
            dedupe_key=dedupe_key,
        )
        if anexo_concorrente:
            logger.info(
                "Upload deduplicado por corrida de concorrencia (atendimento_id=%s, exame_id=%s, user_id=%s, anexo_id=%s, dedupe_key=%s)",
                atendimento_id,
                exame.id if exame else None,
                current_user.id,
                anexo_concorrente.id,
                dedupe_key,
            )
            _registrar_upload_dedupe_metrica(
                db,
                atendimento=atendimento,
                evento=UPLOAD_DEDUPE_EVENT_COLLISION,
                dedupe_key=dedupe_key,
            )
            payload = _serialize_anexo(anexo_concorrente)
            payload["deduplicado"] = True
            return JSONResponse(status_code=status.HTTP_200_OK, content=payload)

        logger.exception(
            "Falha ao resolver colisao de upload por dedupe_key (atendimento_id=%s, exame_id=%s, user_id=%s, dedupe_key=%s)",
            atendimento_id,
            exame.id if exame else None,
            current_user.id,
            dedupe_key,
        )
        raise HTTPException(status_code=409, detail="Conflito ao processar upload duplicado. Tente novamente.")


@router.get("/anexos/{anexo_id}/arquivo")
def baixar_arquivo_anexo(
    anexo_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = current_user
    anexo = db.query(AnexoAtendimento).filter(AnexoAtendimento.id == anexo_id).first()
    if not anexo:
        raise HTTPException(status_code=404, detail="Anexo nao encontrado.")
    return build_attachment_download_response(
        anexo,
        missing_detail="Arquivo nao encontrado no armazenamento.",
    )


@router.delete("/anexos/{anexo_id}")
def excluir_anexo(
    anexo_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = current_user
    anexo = db.query(AnexoAtendimento).filter(AnexoAtendimento.id == anexo_id).first()
    if not anexo:
        raise HTTPException(status_code=404, detail="Anexo nao encontrado.")

    if anexo.exame_id and _anexo_eh_pdf(anexo):
        exame = db.query(Exame).filter(Exame.id == anexo.exame_id).first()
        if exame and is_portal_released_status(exame.status):
            outros_pdfs = (
                db.query(AnexoAtendimento)
                .filter(AnexoAtendimento.exame_id == exame.id, AnexoAtendimento.id != anexo.id)
                .all()
            )
            if not any(_anexo_eh_pdf(outro) for outro in outros_pdfs):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"O exame #{exame.id} esta liberado no portal da clinica parceira e este "
                        "e o unico PDF vinculado. Revogue a liberacao antes de excluir este anexo."
                    ),
                )

    _excluir_anexo_registro(db, anexo)
    db.commit()
    return {"message": "Anexo removido com sucesso.", "id": anexo_id}


# === ALERTAS CLÃNICOS ===
@router.get("/paciente/{paciente_id}/alertas")
def listar_alertas_paciente(
    paciente_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = current_user
    alertas = (
        db.query(AlertaClinico)
        .filter(AlertaClinico.paciente_id == paciente_id, AlertaClinico.ativo == 1)
        .order_by(AlertaClinico.gravidade.desc(), AlertaClinico.created_at.desc())
        .all()
    )
    return {
        "items": [
            {
                "id": a.id,
                "paciente_id": a.paciente_id,
                "tipo": a.tipo,
                "titulo": a.titulo,
                "descricao": a.descricao or "",
                "gravidade": a.gravidade or "media",
                "data_inicio": _to_iso(a.data_inicio),
                "data_fim": _to_iso(a.data_fim),
            }
            for a in alertas
        ]
    }


@router.post("/paciente/{paciente_id}/alertas", status_code=status.HTTP_201_CREATED)
def criar_alerta(
    paciente_id: int,
    payload: AlertaPayload,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    paciente = db.query(Paciente).filter(Paciente.id == paciente_id).first()
    if not paciente:
        raise HTTPException(status_code=404, detail="Paciente nao encontrado.")

    alerta = AlertaClinico(
        paciente_id=paciente_id,
        tipo=payload.tipo,
        titulo=payload.titulo,
        descricao=payload.descricao,
        gravidade=payload.gravidade or "media",
    )
    db.add(alerta)
    db.commit()
    db.refresh(alerta)

    registrar_auditoria(
        current_user=current_user,
        modulo="atendimento",
        entidade="alerta_clinico",
        entidade_id=alerta.id,
        acao="ALERTA_CLINICO_CRIADO",
        descricao=f"Alerta clinico '{alerta.titulo}' ({alerta.gravidade}) criado para o paciente #{paciente_id}.",
        detalhes={
            "paciente_id": paciente_id,
            "tipo": alerta.tipo,
            "titulo": alerta.titulo,
            "gravidade": alerta.gravidade,
        },
        request=request,
    )

    return {
        "id": alerta.id,
        "paciente_id": alerta.paciente_id,
        "tipo": alerta.tipo,
        "titulo": alerta.titulo,
        "descricao": alerta.descricao or "",
        "gravidade": alerta.gravidade,
    }


@router.put("/alertas/{alerta_id}")
def atualizar_alerta(
    alerta_id: int,
    payload: AlertaPayload,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    alerta = db.query(AlertaClinico).filter(AlertaClinico.id == alerta_id).first()
    if not alerta:
        raise HTTPException(status_code=404, detail="Alerta nao encontrado.")

    valores_anteriores = {
        "tipo": alerta.tipo,
        "titulo": alerta.titulo,
        "descricao": alerta.descricao or "",
        "gravidade": alerta.gravidade,
    }

    alerta.tipo = payload.tipo
    alerta.titulo = payload.titulo
    alerta.descricao = payload.descricao or ""
    alerta.gravidade = payload.gravidade or "media"
    db.commit()
    db.refresh(alerta)

    valores_novos = {
        "tipo": alerta.tipo,
        "titulo": alerta.titulo,
        "descricao": alerta.descricao or "",
        "gravidade": alerta.gravidade,
    }
    alteracoes = {
        campo: {"antes": valores_anteriores[campo], "depois": valores_novos[campo]}
        for campo in valores_anteriores
        if valores_anteriores[campo] != valores_novos[campo]
    }
    if alteracoes:
        registrar_auditoria(
            current_user=current_user,
            modulo="atendimento",
            entidade="alerta_clinico",
            entidade_id=alerta.id,
            acao="ALERTA_CLINICO_ATUALIZADO",
            descricao=f"Alerta clinico #{alerta.id} atualizado: {', '.join(sorted(alteracoes))}.",
            detalhes={"paciente_id": alerta.paciente_id, "alteracoes": alteracoes},
            request=request,
        )

    return {
        "id": alerta.id,
        "paciente_id": alerta.paciente_id,
        "tipo": alerta.tipo,
        "titulo": alerta.titulo,
        "descricao": alerta.descricao or "",
        "gravidade": alerta.gravidade,
    }


@router.delete("/alertas/{alerta_id}")
def desativar_alerta(
    alerta_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    alerta = db.query(AlertaClinico).filter(AlertaClinico.id == alerta_id).first()
    if not alerta:
        raise HTTPException(status_code=404, detail="Alerta nao encontrado.")

    alerta.ativo = 0
    db.commit()

    registrar_auditoria(
        current_user=current_user,
        modulo="atendimento",
        entidade="alerta_clinico",
        entidade_id=alerta_id,
        acao="ALERTA_CLINICO_DESATIVADO",
        descricao=f"Alerta clinico '{alerta.titulo}' ({alerta.gravidade}) desativado.",
        detalhes={
            "paciente_id": alerta.paciente_id,
            "tipo": alerta.tipo,
            "titulo": alerta.titulo,
            "gravidade": alerta.gravidade,
        },
        request=request,
    )
    return {"message": "Alerta desativado com sucesso.", "id": alerta_id}


def _resumir_texto_timeline(value: Optional[str], fallback: str) -> str:
    text = (value or "").strip()
    if not text:
        return fallback
    compact = re.sub(r"\s+", " ", text)
    return compact[:140]


def _montar_timeline_paciente(
    db: Session,
    paciente_id: int,
    *,
    limite: int = 12,
    atendimentos_paciente: Optional[List[AtendimentoClinico]] = None,
) -> List[dict]:
    """Limitada ao historico mais recente do paciente - sem isso, um paciente
    cronico com anos de acompanhamento faz esta funcao escanear TODO o
    historico (atendimentos, exames, laudos) a cada chamada, custo que so
    cresce com o tempo de uso do sistema. `atendimentos_paciente` permite
    reaproveitar uma lista ja buscada pelo chamador (historico_paciente ja
    consulta AtendimentoClinico com o mesmo limite) em vez de reconsultar a
    mesma tabela. A ordem de `atendimentos` nao importa para o resultado: os
    eventos de todas as categorias sao reordenados por data ao final, do
    mais recente para o mais antigo (anos e eventos dentro do ano)."""
    atendimentos = (
        atendimentos_paciente
        if atendimentos_paciente is not None
        else db.query(AtendimentoClinico)
        .filter(AtendimentoClinico.paciente_id == paciente_id)
        .order_by(AtendimentoClinico.data_atendimento.desc(), AtendimentoClinico.id.desc())
        .limit(limite)
        .all()
    )
    atendimento_ids = [item.id for item in atendimentos if item.id]

    evolucoes = (
        db.query(EvolucaoClinica)
        .filter(EvolucaoClinica.atendimento_id.in_(atendimento_ids))
        .order_by(EvolucaoClinica.data_evolucao.asc(), EvolucaoClinica.id.asc())
        .all()
        if atendimento_ids
        else []
    )
    anexos = (
        db.query(AnexoAtendimento)
        .filter(AnexoAtendimento.atendimento_id.in_(atendimento_ids))
        .order_by(AnexoAtendimento.created_at.asc(), AnexoAtendimento.id.asc())
        .all()
        if atendimento_ids
        else []
    )
    exames = (
        db.query(Exame)
        .filter(Exame.paciente_id == paciente_id)
        .order_by(Exame.data_solicitacao.desc(), Exame.id.desc())
        .limit(limite)
        .all()
    )
    laudos = (
        db.query(Laudo)
        .filter(Laudo.paciente_id == paciente_id)
        .order_by(Laudo.data_laudo.desc(), Laudo.id.desc())
        .limit(limite)
        .all()
    )

    events: List[dict] = []
    exame_map = {exame.id: exame for exame in exames if exame.id}
    for atendimento in atendimentos:
        data_evento = atendimento.data_atendimento or atendimento.created_at
        if not data_evento:
            continue
        events.append(
            {
                "data": _to_iso(data_evento),
                "tipo": "atendimento",
                "titulo": atendimento.diagnostico_principal or atendimento.status or "Atendimento clinico",
                "descricao": _resumir_texto_timeline(
                    atendimento.queixa_principal or atendimento.observacoes,
                    "Registro de atendimento clinico.",
                ),
                "status": atendimento.status or "",
                "referencia_id": atendimento.id,
            }
        )

    for evolucao in evolucoes:
        data_evento = evolucao.data_evolucao or evolucao.created_at
        if not data_evento:
            continue
        # `tipo` continua "evolucao" (a categoria que a UI usa para icone e
        # cor); o que o adendo e vai em `subtipo`, aditivo.
        events.append(
            {
                "data": _to_iso(data_evento),
                "tipo": "evolucao",
                "subtipo": _tipo_adendo(evolucao),
                "pos_conclusao": int(getattr(evolucao, "pos_conclusao", 0) or 0),
                "titulo": _titulo_adendo(evolucao),
                "descricao": _resumir_texto_timeline(evolucao.descricao, "Acompanhamento clinico registrado."),
                "status": evolucao.responsavel_nome or "",
                "referencia_id": evolucao.id,
            }
        )

    for exame in exames:
        data_solicitacao = exame.data_solicitacao or exame.created_at
        if data_solicitacao:
            events.append(
                {
                    "data": _to_iso(data_solicitacao),
                    "tipo": "exame_solicitado",
                    "titulo": f"Solicitacao: {exame.tipo_exame or 'Exame'}",
                    "descricao": _resumir_texto_timeline(
                        exame.preparo or exame.observacoes,
                        "Exame solicitado para acompanhamento clinico.",
                    ),
                    "status": exame.prioridade or "",
                    "referencia_id": exame.id,
                }
            )

        if exame.resultado or exame.data_resultado or _status_exame_concluido(exame.status):
            data_resultado = exame.data_resultado or exame.created_at
            if data_resultado:
                events.append(
                    {
                        "data": _to_iso(data_resultado),
                        "tipo": "exame_resultado",
                        "titulo": f"Resultado: {exame.tipo_exame or 'Exame'}",
                        "descricao": _resumir_texto_timeline(
                            exame.resultado or exame.observacoes,
                            "Resultado ou andamento de exame registrado.",
                        ),
                        "status": exame.status or "",
                        "referencia_id": exame.id,
                    }
                )

    for anexo in anexos:
        data_evento = anexo.created_at
        if not data_evento:
            continue
        exam_prefix = ""
        if anexo.exame_id:
            exame = exame_map.get(anexo.exame_id)
            if exame:
                exam_prefix = f"{exame.tipo_exame}: "
        events.append(
            {
                "data": _to_iso(data_evento),
                "tipo": "anexo",
                "titulo": "Arquivo anexado",
                "descricao": _resumir_texto_timeline(
                    f"{exam_prefix}{anexo.nome_original or anexo.descricao or anexo.tipo}",
                    "Arquivo clinico anexado ao prontuario.",
                ),
                "status": anexo.tipo or "",
                "referencia_id": anexo.id,
            }
        )

    for laudo in laudos:
        data_evento = laudo.data_laudo or laudo.created_at
        if not data_evento:
            continue
        events.append(
            {
                "data": _to_iso(data_evento),
                "tipo": "laudo",
                "titulo": laudo.titulo or laudo.tipo or "Laudo",
                "descricao": _resumir_texto_timeline(laudo.diagnostico or laudo.descricao, "Documento clinico registrado."),
                "status": laudo.status or "",
                "referencia_id": laudo.id,
            }
        )

    grouped: Dict[str, List[dict]] = defaultdict(list)
    for event in sorted(events, key=lambda item: item.get("data") or "", reverse=True):
        year = "Sem data"
        if event.get("data"):
            parsed = _parse_datetime(event["data"])
            if parsed:
                year = str(parsed.year)
        grouped[year].append(event)

    anos_reais = sorted((year for year in grouped if year != "Sem data"), reverse=True)
    ordered_years = anos_reais + (["Sem data"] if "Sem data" in grouped else [])
    return [{"ano": year, "eventos": grouped[year]} for year in ordered_years]


# === HISTÃ“RICO DO PACIENTE ===
@router.get("/paciente/{paciente_id}/historico")
def historico_paciente(
    paciente_id: int,
    limite: int = 10,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = current_user
    paciente = db.query(Paciente).filter(Paciente.id == paciente_id).first()
    if not paciente:
        raise HTTPException(status_code=404, detail="Paciente nao encontrado.")

    # Buscar atendimentos anteriores
    atendimentos = (
        db.query(AtendimentoClinico)
        .filter(AtendimentoClinico.paciente_id == paciente_id)
        .order_by(AtendimentoClinico.data_atendimento.desc(), AtendimentoClinico.id.desc())
        .limit(limite)
        .all()
    )

    # A prescricao pertence ao atendimento, nao ao paciente. Carregar o bloco
    # terapeutico em lote deixa essa separacao explicita para a UI e evita que
    # um retorno precise editar a receita do encontro anterior.
    atendimento_ids = [item.id for item in atendimentos if item.id]
    prescricoes = (
        db.query(PrescricaoClinica)
        .filter(PrescricaoClinica.atendimento_id.in_(atendimento_ids))
        .order_by(PrescricaoClinica.atendimento_id.desc(), PrescricaoClinica.id.desc())
        .all()
        if atendimento_ids
        else []
    )
    prescricoes_por_atendimento: Dict[int, PrescricaoClinica] = {}
    total_receitas_por_atendimento: Dict[int, int] = defaultdict(int)
    for prescricao in prescricoes:
        # O historico mostra a conduta mais recente do encontro: com receitas
        # complementares, e a de maior sequencia. `total_receitas` deixa
        # explicito que existem outras.
        total_receitas_por_atendimento[prescricao.atendimento_id] += 1
        atual = prescricoes_por_atendimento.get(prescricao.atendimento_id)
        if atual is None or _sequencia_prescricao(prescricao) > _sequencia_prescricao(atual):
            prescricoes_por_atendimento[prescricao.atendimento_id] = prescricao

    prescricao_ids = [item.id for item in prescricoes_por_atendimento.values() if item.id]
    itens_prescricao = (
        db.query(PrescricaoItem)
        .filter(PrescricaoItem.prescricao_id.in_(prescricao_ids))
        .order_by(PrescricaoItem.prescricao_id.asc(), PrescricaoItem.ordem.asc(), PrescricaoItem.id.asc())
        .all()
        if prescricao_ids
        else []
    )
    itens_por_prescricao: Dict[int, List[dict]] = defaultdict(list)
    for item in itens_prescricao:
        itens_por_prescricao[item.prescricao_id].append(_map_prescricao_item(item))

    def _prescricao_historica(atendimento_id: int) -> Optional[dict]:
        prescricao = prescricoes_por_atendimento.get(atendimento_id)
        if not prescricao:
            return None
        itens = itens_por_prescricao.get(prescricao.id, [])
        return {
            "id": prescricao.id,
            "sequencia": _sequencia_prescricao(prescricao),
            "emitida_em": _to_operational_iso(prescricao.emitida_em),
            "total_receitas": total_receitas_por_atendimento.get(atendimento_id, 1),
            "orientacoes_gerais": prescricao.orientacoes_gerais or "",
            "retorno_dias": prescricao.retorno_dias,
            "total_itens": len(itens),
            "itens": itens,
            "created_at": _to_iso(prescricao.created_at),
            "updated_at": _to_iso(prescricao.updated_at),
        }

    # Buscar alertas ativos
    alertas = (
        db.query(AlertaClinico)
        .filter(AlertaClinico.paciente_id == paciente_id, AlertaClinico.ativo == 1)
        .all()
    )

    return {
        "paciente": {
            "id": paciente.id,
            "nome": paciente.nome,
            "especie": paciente.especie or "",
            "raca": paciente.raca or "",
            "peso": paciente.peso_kg,
            "nascimento": paciente.nascimento or None,
            **dados_idade_paciente(paciente),
        },
        "alertas": [
            {
                "id": a.id,
                "tipo": a.tipo,
                "titulo": a.titulo,
                "descricao": a.descricao or "",
                "gravidade": a.gravidade or "media",
            }
            for a in alertas
        ],
        "atendimentos": [
            {
                "id": a.id,
                "data_atendimento": _to_operational_iso(a.data_atendimento),
                "status": a.status,
                "queixa_principal": a.queixa_principal or "",
                "diagnostico_principal": a.diagnostico_principal or "",
                "veterinario": a.criado_por_nome or "",
                "peso": a.peso,
                "tem_prescricao": a.id in prescricoes_por_atendimento,
                "prescricao": _prescricao_historica(a.id),
            }
            for a in atendimentos
        ],
        "pesos": [
            {
                "atendimento_id": a.id,
                "data_atendimento": _to_operational_iso(a.data_atendimento),
                "peso": a.peso,
            }
            for a in atendimentos
            if a.peso is not None
        ],
        "temperaturas": [
            {
                "atendimento_id": a.id,
                "data_atendimento": _to_operational_iso(a.data_atendimento),
                "temperatura": a.temperatura,
            }
            for a in atendimentos
            if a.temperatura is not None
        ],
        "frequencias_cardiacas": [
            {
                "atendimento_id": a.id,
                "data_atendimento": _to_operational_iso(a.data_atendimento),
                "frequencia_cardiaca": a.frequencia_cardiaca,
            }
            for a in atendimentos
            if a.frequencia_cardiaca is not None
        ],
        "frequencias_respiratorias": [
            {
                "atendimento_id": a.id,
                "data_atendimento": _to_operational_iso(a.data_atendimento),
                "frequencia_respiratoria": a.frequencia_respiratoria,
            }
            for a in atendimentos
            if a.frequencia_respiratoria is not None
        ],
        "timeline": _montar_timeline_paciente(db, paciente_id, limite=limite, atendimentos_paciente=atendimentos),
    }


@router.get("/paciente/{paciente_id}/timeline")
def timeline_paciente(
    paciente_id: int,
    limite: int = 12,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = current_user
    paciente = db.query(Paciente).filter(Paciente.id == paciente_id).first()
    if not paciente:
        raise HTTPException(status_code=404, detail="Paciente nao encontrado.")

    return {
        "paciente": {
            "id": paciente.id,
            "nome": paciente.nome,
            "especie": paciente.especie or "",
            "raca": paciente.raca or "",
        },
        "timeline": _montar_timeline_paciente(db, paciente_id, limite=limite),
    }
