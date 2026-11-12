"""Rotina fiscal consultiva e confirmações humanas; sem emissão, envio ou cron."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime, time, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.models.agendamento import Agendamento
from app.models.atendimento_clinico import AtendimentoClinico
from app.models.clinica import Clinica
from app.models.fiscal import FiscalAndamentoEvento, FiscalFechamento, FiscalFechamentoOS, FiscalRotinaPreferencia
from app.models.laudo import Laudo
from app.models.ordem_servico import OrdemServico
from app.services import fiscal_fechamento_service as fechamento

FiscalRotinaError = fechamento.FiscalFechamentoError
FUSO = fechamento.FISCAL_TIMEZONE
VET_FAUNA_CNPJ = "14986833000188"
ETAPAS = ("preparado", "enviado_contador", "nota_recebida", "nota_encaminhada")
PADRAO = {"modo": "semanal", "dia_semana": "domingo", "horario": "17:00", "timezone": "America/Fortaleza", "automatico": False}


def _agora_local() -> datetime:
    return datetime.now(FUSO)


def _token(value: Any) -> str:
    return "".join(char for char in unicodedata.normalize("NFKD", str(value or "")) if not unicodedata.combining(char)).strip().casefold()


def _documento(value: Any) -> str:
    return re.sub(r"[.\s/\-]", "", str(value or "").upper())


def _preferencia(clinica: Clinica | None, personalizada: FiscalRotinaPreferencia | None = None) -> dict:
    vet_fauna = clinica is not None and _documento(clinica.cnpj) == VET_FAUNA_CNPJ
    return {
        "clinica_id": clinica.id if clinica is not None else None,
        "nome": str(clinica.nome or "") if clinica is not None else "Atendimento domiciliar",
        "modo": personalizada.modo if personalizada else ("por_servico" if vet_fauna else "semanal"),
        "pagamento_depende_nf": bool(personalizada.pagamento_depende_nf) if personalizada else vet_fauna,
        "versao": personalizada.versao if personalizada else 0,
        "origem": "personalizada" if personalizada else ("vet_fauna" if vet_fauna else "padrao"),
    }


def _preferencias(db: Session, ids: set[int]) -> dict[int, dict]:
    if not ids:
        return {}
    clinicas = db.query(Clinica).filter(Clinica.id.in_(ids)).populate_existing().all()
    personalizadas = {
        row.clinica_id: row for row in db.query(FiscalRotinaPreferencia)
        .filter(FiscalRotinaPreferencia.clinica_id.in_(ids)).populate_existing().all()
    }
    return {clinica.id: _preferencia(clinica, personalizadas.get(clinica.id)) for clinica in clinicas}


def listar_rotinas(db: Session) -> dict:
    clinicas = db.query(Clinica).order_by(Clinica.nome.asc(), Clinica.id.asc()).all()
    personalizadas = {row.clinica_id: row for row in db.query(FiscalRotinaPreferencia).all()}
    return {"padrao": dict(PADRAO), "clinicas": [_preferencia(row, personalizadas.get(row.id)) for row in clinicas]}


def atualizar_preferencia(db: Session, clinica_id: int, *, modo: str, pagamento_depende_nf: bool, versao_esperada: int, usuario_id: int | None = None, usuario_nome: str | None = None) -> dict:
    if modo not in {"semanal", "por_servico"} or type(versao_esperada) is not int or versao_esperada < 0 or type(pagamento_depende_nf) is not bool:
        raise FiscalRotinaError(422, "Preferência fiscal inválida.")
    try:
        clinica = db.query(Clinica).filter(Clinica.id == clinica_id).with_for_update().populate_existing().first()
        if clinica is None:
            raise FiscalRotinaError(404, "Clínica não encontrada.")
        row = db.query(FiscalRotinaPreferencia).filter(FiscalRotinaPreferencia.clinica_id == clinica_id).populate_existing().first()
        versao = row.versao if row else 0
        if versao != versao_esperada:
            raise FiscalRotinaError(409, "A preferência mudou. Atualize os dados antes de salvar.", versao_atual=versao)
        if row is None:
            row = FiscalRotinaPreferencia(clinica_id=clinica_id)
            db.add(row)
        row.modo = modo
        row.pagamento_depende_nf = pagamento_depende_nf
        row.versao = versao + 1
        row.atualizado_em = _agora_local().isoformat()
        row.usuario_id = usuario_id
        row.usuario_nome = str(usuario_nome or "").strip() or None
        db.commit()
        db.refresh(row)
        return _preferencia(clinica, row)
    except (IntegrityError, OperationalError):
        db.rollback()
        atual = db.query(FiscalRotinaPreferencia).filter(FiscalRotinaPreferencia.clinica_id == clinica_id).first()
        raise FiscalRotinaError(409, "A preferência foi atualizada por outra pessoa. Recarregue os dados.", versao_atual=atual.versao if atual else 0)
    except Exception:
        db.rollback()
        raise


def _proximo_domingo(instante: datetime) -> datetime:
    instante = fechamento._data_local(instante)
    dia = instante.date() + timedelta(days=(6 - instante.weekday()) % 7)
    corte = datetime.combine(dia, time(17), tzinfo=FUSO)
    if corte < instante:
        corte += timedelta(days=7)
    return corte


def _contexto(competencia: str, modo: str, data_corte: str | None, clinica_id: int | None, agora: datetime) -> dict:
    fechamento._limites_competencia(competencia)
    if modo not in {"semanal", "por_servico", "mensal"}:
        raise FiscalRotinaError(422, "Modo de preparação inválido.")
    if clinica_id is not None and (type(clinica_id) is not int or clinica_id <= 0):
        raise FiscalRotinaError(422, "Clínica inválida.")
    if modo != "semanal":
        if data_corte is not None:
            raise FiscalRotinaError(422, "A data de corte só é usada na rotina semanal.")
        return {"modo": modo, "competencia": competencia, "data_corte": None, "corte_em": None, "clinica_id": clinica_id}
    if data_corte is None:
        corte = _proximo_domingo(agora)
    else:
        try:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", data_corte):
                raise ValueError
            dia = datetime.strptime(data_corte, "%Y-%m-%d").date()
            if dia.weekday() != 6:
                raise ValueError
            corte = datetime.combine(dia, time(17), tzinfo=FUSO)
        except (ValueError, TypeError):
            raise FiscalRotinaError(422, "Informe um domingo válido como data de corte (YYYY-MM-DD).")
    return {"modo": modo, "competencia": competencia, "data_corte": corte.date().isoformat(), "corte_em": corte.isoformat(), "clinica_id": clinica_id}


def _data_item(item: dict) -> datetime | None:
    value = item.get("data_atendimento")
    if not value:
        return None
    try:
        return fechamento._data_local(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except (TypeError, ValueError):
        return None


def _realizacoes(db: Session, items: list[dict]) -> dict[int, tuple[bool, str, str]]:
    """Consulta apenas metadados de vínculos/status; nada clínico vai para a saída."""
    ids = [item["os_id"] for item in items]
    ordens = db.query(OrdemServico.id, OrdemServico.agendamento_id, OrdemServico.laudo_id, OrdemServico.paciente_id, OrdemServico.clinica_id).filter(OrdemServico.id.in_(ids)).all() if ids else []
    agenda_ids = {row.agendamento_id for row in ordens if row.agendamento_id is not None}
    laudo_ids = {row.laudo_id for row in ordens if row.laudo_id is not None}
    agendas = {row.id: row for row in db.query(Agendamento.id, Agendamento.status, Agendamento.paciente_id, Agendamento.clinica_id).filter(Agendamento.id.in_(agenda_ids)).all()} if agenda_ids else {}
    atendimentos = {row.agendamento_id: row for row in db.query(AtendimentoClinico.agendamento_id, AtendimentoClinico.status, AtendimentoClinico.paciente_id, AtendimentoClinico.clinica_id).filter(AtendimentoClinico.agendamento_id.in_(agenda_ids)).all()} if agenda_ids else {}
    laudos = {row.id: row for row in db.query(Laudo.id, Laudo.status, Laudo.finalizado_em, Laudo.paciente_id, Laudo.clinic_id).filter(Laudo.id.in_(laudo_ids)).all()} if laudo_ids else {}
    result = {}
    for row in ordens:
        if row.agendamento_id is not None:
            agenda = agendas.get(row.agendamento_id)
            if agenda is None:
                result[row.id] = (False, "sem_evidencia", "Agendamento vinculado não encontrado para conferir a prestação.")
            elif agenda.paciente_id != row.paciente_id or agenda.clinica_id != row.clinica_id:
                result[row.id] = (False, "agenda", "Vínculo da OS com paciente ou clínica da Agenda precisa de conferência.")
            elif _token(agenda.status) in {"cancelado", "faltou", "expirado"}:
                result[row.id] = (False, "agenda", "Agendamento cancelado, com falta ou expirado não confirma a prestação.")
            elif _token(agenda.status) == "realizado":
                result[row.id] = (True, "agenda", "")
            else:
                atendimento = atendimentos.get(row.agendamento_id)
                concluido = atendimento is not None and _token(atendimento.status) == "concluido" and atendimento.paciente_id == row.paciente_id and atendimento.clinica_id == row.clinica_id
                result[row.id] = (True, "atendimento", "") if concluido else (False, "agenda", "A Agenda ainda não confirma a realização do serviço.")
        elif row.laudo_id is not None:
            laudo = laudos.get(row.laudo_id)
            coerente = laudo is not None and laudo.paciente_id == row.paciente_id and laudo.clinic_id == row.clinica_id
            realizado = coerente and (_token(laudo.status) == "finalizado" or laudo.finalizado_em is not None)
            result[row.id] = (True, "laudo", "") if realizado else (False, "laudo" if laudo is not None else "sem_evidencia", "Laudo vinculado sem evidência coerente de finalização do serviço.")
        else:
            result[row.id] = (False, "sem_evidencia", "Prestação sem vínculo verificável com Agenda, atendimento concluído ou laudo finalizado.")
    return result


def _aplicar_contexto(db: Session, base: dict, contexto: dict, agora: datetime) -> dict:
    clinica_id = contexto.get("clinica_id")
    corte = datetime.fromisoformat(contexto["corte_em"]) if contexto.get("corte_em") else None
    rows = [item for item in base["items"] if clinica_id is None or item["clinica_id"] == clinica_id]
    if corte is not None:
        rows = [item for item in rows if _data_item(item) is None or _data_item(item) <= corte]
    preferencias = _preferencias(db, {item["clinica_id"] for item in rows if item["clinica_id"] is not None})
    realizacoes = _realizacoes(db, rows)
    todos = []
    for original in rows:
        item = dict(original)
        preferencia = preferencias.get(item["clinica_id"], _preferencia(None))
        realizado, fonte, motivo = realizacoes.get(item["os_id"], (False, "sem_evidencia", "Prestação sem evidência verificável."))
        data = _data_item(item)
        motivos = list(item["motivos_pendencia"])
        if not realizado:
            motivos.append(motivo)
        if data is not None and data > agora:
            motivos.append("Data de prestação futura. Aguarde a realização e confira a data da OS.")
        item.update({
            "modo_preparacao": preferencia["modo"],
            "pagamento_depende_nf": preferencia["pagamento_depende_nf"],
            "realizacao_confirmada": realizado,
            "fonte_realizacao": fonte,
            "prazo_preparacao": (_proximo_domingo(data).isoformat() if preferencia["modo"] == "semanal" else data.isoformat()) if data else None,
            "motivos_pendencia": list(dict.fromkeys(motivos)),
            "elegivel": not motivos,
        })
        todos.append(item)
    modo = contexto["modo"]
    items = [item for item in todos if modo == "mensal" or item["modo_preparacao"] == modo]
    if modo == "por_servico":
        items.sort(key=lambda item: (not item["pagamento_depende_nf"], item["data_atendimento"] or "", item["os_id"]))
    nao_canceladas = [item for item in items if _token(item["status_os"]) != "cancelado"]
    sem_claim_ou_cancelamento = [item for item in todos if item["fechamento_id"] is None and _token(item["status_os"]) != "cancelado"]
    resumo = {
        "quantidade_os": len(items), "quantidade_aptas": sum(item["elegivel"] for item in items),
        "quantidade_pendentes": sum(not item["elegivel"] for item in items),
        "quantidade_canceladas": len(items) - len(nao_canceladas),
        "quantidade_ja_preparadas": sum(item["fechamento_id"] is not None for item in items),
        "quantidade_exportadas_anteriormente": sum(item["exportacoes_anteriores"] > 0 for item in items),
        "quantidade_por_servico": sum(item["modo_preparacao"] == "por_servico" for item in sem_claim_ou_cancelamento),
        "quantidade_pagamento_depende_nf": sum(item["pagamento_depende_nf"] for item in sem_claim_ou_cancelamento),
        "valor_total": sum((item["valor_final"] for item in nao_canceladas), Decimal("0.00")),
        "valor_apto": sum((item["valor_final"] for item in items if item["elegivel"]), Decimal("0.00")),
    }
    return {**base, "items": items, "resumo": resumo, "rotina": {"modo": modo, "data_corte": contexto["data_corte"], "corte_em": contexto["corte_em"], "proxima_preparacao_em": _proximo_domingo(agora).isoformat() if modo == "semanal" else None, "horario": "17:00", "timezone": "America/Fortaleza", "automatico": False}}


def previa_rotina(db: Session, competencia: str, modo: str = "semanal", data_corte: str | None = None, clinica_id: int | None = None) -> dict:
    agora = _agora_local()
    contexto = _contexto(competencia, modo, data_corte, clinica_id, agora)
    return _aplicar_contexto(db, fechamento.previa_fechamento(db, competencia), contexto, agora)


def validar_selecao_rotina(db: Session, items: list[dict], contexto: dict) -> tuple[list[dict], list[dict]]:
    """Chamado pelo core depois de bloquear OS e clínicas, dentro da transação."""
    modo = contexto["modo"]
    if modo not in {"semanal", "por_servico"} or (modo == "por_servico" and len(items) != 1):
        raise FiscalRotinaError(422, "A preparação por serviço exige exatamente uma OS.")
    preferencias = _preferencias(db, {item["clinica_id"] for item in items if item["clinica_id"] is not None})
    for item in items:
        if contexto["clinica_id"] is not None and item["clinica_id"] != contexto["clinica_id"]:
            raise FiscalRotinaError(422, "A seleção contém OS de outra clínica. Nenhum pacote foi preparado.")
        if preferencias.get(item["clinica_id"], _preferencia(None))["modo"] != modo:
            raise FiscalRotinaError(409, "A rotina da clínica mudou ou a OS pertence a outro modo. Atualize a prévia.", os_ids=[item["os_id"]])
    previa = _aplicar_contexto(db, fechamento.previa_fechamento(db, contexto["competencia"]), contexto, _agora_local())
    by_id = {item["os_id"]: item for item in previa["items"]}
    faltantes = [item["os_id"] for item in items if item["os_id"] not in by_id]
    if faltantes:
        raise FiscalRotinaError(422, "Há serviços fora do corte ou do escopo selecionado. Nenhum pacote foi preparado.", os_ids=faltantes)
    return [by_id[item["os_id"]] for item in items], [item for item in previa["items"] if not item["elegivel"]]


def preparar_rotina(db: Session, *, competencia: str, modo: str, os_ids: list[int], chave_idempotencia: UUID | str, confirmar_datas_prestacao: bool, confirmar_exportacoes_anteriores: bool = False, data_corte: str | None = None, clinica_id: int | None = None, usuario_id: int | None = None, usuario_nome: str | None = None) -> FiscalFechamento:
    if modo not in {"semanal", "por_servico"} or (modo == "por_servico" and len(os_ids) != 1):
        raise FiscalRotinaError(422, "A preparação por serviço exige exatamente uma OS; mensal é apenas conferência nesta rota.")
    try:
        key = str(UUID(str(chave_idempotencia)))
    except (ValueError, TypeError, AttributeError):
        raise FiscalRotinaError(422, "Chave de idempotência inválida.")
    corte_implicito = modo == "semanal" and data_corte is None
    existente = db.query(FiscalFechamento.snapshot_json).filter(FiscalFechamento.chave_idempotencia == key).first()
    armazenado = {}
    if existente:
        try:
            armazenado = json.loads(existente.snapshot_json).get("rotina") or {}
        except (ValueError, TypeError, AttributeError):
            raise FiscalRotinaError(503, "Snapshot fiscal inconsistente. Não foi possível recuperar a operação.")
    if modo == "semanal" and data_corte is None and armazenado.get("modo") == "semanal":
        data_corte = armazenado.get("data_corte")
    if modo == "por_servico" and clinica_id is None:
        if armazenado.get("modo") == "por_servico":
            clinica_id = armazenado.get("clinica_id")
        else:
            row = db.query(OrdemServico.clinica_id).filter(OrdemServico.id == os_ids[0]).first()
            clinica_id = row.clinica_id if row else None
    # Repetir uma operação antiga conserva inclusive o corte de sexta às 18h.
    # Somente a UUID já persistida pode recuperar esse contexto; o núcleo ainda
    # confere todo o fingerprint, os bytes e o payload antes de retornar.
    if existente and modo == "semanal" and armazenado.get("modo") == modo and data_corte == armazenado.get("data_corte"):
        contexto = {**armazenado, "competencia": competencia, "clinica_id": clinica_id}
    else:
        contexto = _contexto(competencia, modo, data_corte, clinica_id, _agora_local())
    argumentos = dict(competencia=competencia, os_ids=os_ids, chave_idempotencia=key, confirmar_datas_prestacao=confirmar_datas_prestacao, confirmar_exportacoes_anteriores=confirmar_exportacoes_anteriores, usuario_id=usuario_id, usuario_nome=usuario_nome)
    try:
        return fechamento.preparar_fechamento(db, **argumentos, contexto_rotina=contexto)
    except FiscalRotinaError as exc:
        if exc.status_code != 409 or not corte_implicito or existente is not None:
            raise
        # Um retry concorrente pode ter calculado o próximo corte depois das
        # 17h, antes do primeiro commit ficar visível. A UUID já persistida fixa
        # o corte implícito. O core ainda compara todos os campos da requisição.
        persistido = db.query(FiscalFechamento.snapshot_json).filter(FiscalFechamento.chave_idempotencia == key).first()
        if persistido is None:
            raise
        try:
            salvo = json.loads(persistido.snapshot_json).get("rotina") or {}
        except (ValueError, TypeError, AttributeError):
            raise FiscalRotinaError(503, "Snapshot fiscal inconsistente. Não foi possível recuperar a operação.")
        if salvo.get("modo") != "semanal" or not salvo.get("data_corte"):
            raise
        contexto_retry = _contexto(competencia, modo, salvo["data_corte"], clinica_id, _agora_local())
        return fechamento.preparar_fechamento(db, **argumentos, contexto_rotina=contexto_retry)


def _snapshot(db: Session, fechamento_id: int) -> tuple[dict, str]:
    row = db.query(FiscalFechamento.snapshot_json, FiscalFechamento.preparado_em).filter(FiscalFechamento.id == fechamento_id).first()
    if row is None:
        raise FiscalRotinaError(404, "Pacote não encontrado.")
    try:
        data = json.loads(row.snapshot_json)
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            raise ValueError
    except (ValueError, TypeError):
        raise FiscalRotinaError(503, "Snapshot do pacote inconsistente.")
    return data, row.preparado_em


def _evento_publico(row: FiscalAndamentoEvento) -> dict:
    return {field: getattr(row, field) for field in ("id", "etapa_anterior", "destino", "versao", "referencia_nota", "observacao", "registrado_em", "usuario_id", "usuario_nome")}


def _item_andamento(db: Session, claim: FiscalFechamentoOS, snapshot: tuple[dict, str] | None = None, eventos: list[FiscalAndamentoEvento] | None = None) -> dict:
    data, preparado_em = snapshot or _snapshot(db, claim.fechamento_id)
    original = next((item for item in data["items"] if item.get("os_id") == claim.os_id), None)
    if original is None:
        raise FiscalRotinaError(503, "O snapshot do pacote não contém o vínculo fiscal esperado.")
    if eventos is None:
        eventos = db.query(FiscalAndamentoEvento).filter(FiscalAndamentoEvento.os_id == claim.os_id).order_by(FiscalAndamentoEvento.versao.asc()).populate_existing().all()
    etapa, versao, referencia, atualizado = "preparado", 0, None, preparado_em
    for row in eventos:
        if (
            not 0 < row.versao < len(ETAPAS)
            or row.versao != versao + 1
            or row.etapa_anterior != etapa
            or row.destino != ETAPAS[row.versao]
        ):
            raise FiscalRotinaError(503, "Histórico de andamento fiscal inconsistente.")
        etapa, versao, referencia, atualizado = row.destino, row.versao, row.referencia_nota, row.registrado_em
    return {"os_id": claim.os_id, "numero_os": str(original.get("numero_os") or ""), "cliente_nome": str(original.get("cliente_nome") or ""), "clinica_nome": str(original.get("clinica_nome") or ""), "etapa": etapa, "versao": versao, "referencia_nota": referencia, "atualizado_em": atualizado, "eventos": [_evento_publico(row) for row in eventos]}


def listar_andamentos(db: Session, fechamento_id: int) -> dict:
    snapshot = _snapshot(db, fechamento_id)
    claims = db.query(FiscalFechamentoOS).filter(FiscalFechamentoOS.fechamento_id == fechamento_id).order_by(FiscalFechamentoOS.os_id.asc()).all()
    eventos_por_os = {claim.os_id: [] for claim in claims}
    if eventos_por_os:
        for evento in db.query(FiscalAndamentoEvento).filter(FiscalAndamentoEvento.os_id.in_(eventos_por_os)).order_by(FiscalAndamentoEvento.versao.asc()).populate_existing().all():
            eventos_por_os[evento.os_id].append(evento)
    return {"fechamento_id": fechamento_id, "items": [_item_andamento(db, claim, snapshot, eventos_por_os[claim.os_id]) for claim in claims]}


def atualizar_andamento(db: Session, os_id: int, *, destino: str, versao_esperada: int, chave_idempotencia: UUID | str, confirmar_acao_manual: bool, referencia_nota: str | None = None, observacao: str | None = None, usuario_id: int | None = None, usuario_nome: str | None = None) -> dict:
    if confirmar_acao_manual is not True:
        raise FiscalRotinaError(422, "Confirme que esta ação já foi realizada manualmente. O sistema não envia nem emite documentos.")
    if destino not in ETAPAS[1:] or type(versao_esperada) is not int or versao_esperada < 0:
        raise FiscalRotinaError(422, "Etapa ou versão inválida.")
    try:
        key = str(UUID(str(chave_idempotencia)))
    except (ValueError, TypeError, AttributeError):
        raise FiscalRotinaError(422, "Chave de idempotência inválida.")
    referencia_nota = str(referencia_nota or "").strip() or None
    observacao = str(observacao or "").strip() or None
    if (referencia_nota and len(referencia_nota) > 200) or (observacao and len(observacao) > 2000):
        raise FiscalRotinaError(422, "Referência ou observação excede o tamanho permitido.")
    payload = {"os_id": os_id, "destino": destino, "versao_esperada": versao_esperada, "confirmar_acao_manual": confirmar_acao_manual, "referencia_nota": referencia_nota, "observacao": observacao}
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    try:
        claim = db.query(FiscalFechamentoOS).filter(FiscalFechamentoOS.os_id == os_id).with_for_update().populate_existing().first()
        if claim is None:
            raise FiscalRotinaError(404, "A OS ainda não está vinculada a um pacote preparado.")
        retry = db.query(FiscalAndamentoEvento).filter(FiscalAndamentoEvento.chave_idempotencia == key).first()
        if retry:
            if retry.fingerprint != fingerprint:
                raise FiscalRotinaError(409, "Esta chave já registrou outra ação manual.")
            return _item_andamento(db, claim)
        atual = _item_andamento(db, claim)
        if atual["versao"] != versao_esperada:
            raise FiscalRotinaError(409, "O andamento mudou. Atualize antes de registrar outra etapa.", versao_atual=atual["versao"])
        if atual["versao"] >= len(ETAPAS) - 1 or destino != ETAPAS[atual["versao"] + 1]:
            raise FiscalRotinaError(422, "Registre somente a próxima etapa, sem saltos ou retrocessos.", versao_atual=atual["versao"])
        if destino == "nota_recebida" and not referencia_nota:
            raise FiscalRotinaError(422, "Informe a referência da nota recebida do contador.")
        if destino == "nota_encaminhada":
            if referencia_nota and referencia_nota != atual["referencia_nota"]:
                raise FiscalRotinaError(422, "A nota encaminhada deve preservar a referência da nota recebida.")
            referencia_nota = atual["referencia_nota"]
        row = FiscalAndamentoEvento(os_id=os_id, versao=atual["versao"] + 1, etapa_anterior=atual["etapa"], destino=destino, referencia_nota=referencia_nota, observacao=observacao, chave_idempotencia=key, fingerprint=fingerprint, registrado_em=_agora_local().isoformat(), usuario_id=usuario_id, usuario_nome=str(usuario_nome or "").strip() or None)
        db.add(row)
        db.commit()
        return _item_andamento(db, claim)
    except (IntegrityError, OperationalError):
        db.rollback()
        retry = db.query(FiscalAndamentoEvento).filter(FiscalAndamentoEvento.chave_idempotencia == key).first()
        claim = db.query(FiscalFechamentoOS).filter(FiscalFechamentoOS.os_id == os_id).first()
        if retry and retry.fingerprint == fingerprint and claim is not None:
            return _item_andamento(db, claim)
        atual = _item_andamento(db, claim) if claim is not None else None
        raise FiscalRotinaError(409, "Outra ação já atualizou o andamento. Recarregue os dados.", versao_atual=atual["versao"] if atual else 0)
    except Exception:
        db.rollback()
        raise
