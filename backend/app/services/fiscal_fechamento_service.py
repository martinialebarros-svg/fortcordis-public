"""Preparação mensal para contabilidade, sem emissão fiscal nem envio externo."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, defer

from app.models.clinica import Clinica
from app.models.fiscal import FiscalFechamento, FiscalFechamentoOS, RelatorioFiscalEmissao
from app.models.ordem_servico import OrdemServico
from app.models.paciente import Paciente
from app.models.servico import Servico
from app.models.tutor import Tutor
from app.services import fiscal_export_service
from app.services.fiscal_endereco_service import resolver_endereco

FISCAL_TIMEZONE = ZoneInfo("America/Fortaleza")
CENTAVO = Decimal("0.01")


class FiscalFechamentoError(Exception):
    def __init__(self, status_code: int, message: str, **details: Any):
        super().__init__(message)
        self.status_code = status_code
        self.detail = {"message": message, **details}


def _limites_competencia(competencia: str) -> tuple[datetime, datetime]:
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", competencia or ""):
        raise FiscalFechamentoError(422, "Competência inválida. Use YYYY-MM.")
    ano, mes = map(int, competencia.split("-"))
    if not 1 <= ano <= 9998:
        raise FiscalFechamentoError(422, "Ano da competência inválido.")
    inicio = datetime(ano, mes, 1, tzinfo=FISCAL_TIMEZONE)
    fim = datetime(ano + (mes == 12), 1 if mes == 12 else mes + 1, 1, tzinfo=FISCAL_TIMEZONE)
    return inicio, fim


def _data_local(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        # OS antigas sem offset seguem a convenção local do cadastro.
        return value.replace(tzinfo=FISCAL_TIMEZONE)
    return value.astimezone(FISCAL_TIMEZONE)


def _money(value: Any) -> Decimal:
    try:
        result = Decimal(str(value if value is not None else 0))
        if not result.is_finite():
            raise InvalidOperation
        return result.quantize(CENTAVO)
    except (InvalidOperation, ValueError, TypeError):
        raise FiscalFechamentoError(422, "Existe valor monetário inválido na seleção.")


def _documento_valido(documento: str, tipo: str) -> bool:
    if not documento or len(set(documento)) == 1:
        return False
    if tipo == "PF":
        if not re.fullmatch(r"[0-9]{11}", documento):
            return False
        digits = list(map(int, documento))
        for length in (9, 10):
            check = (sum(digits[i] * (length + 1 - i) for i in range(length)) * 10) % 11
            if digits[length] != (0 if check == 10 else check):
                return False
        return True
    if not re.fullmatch(r"[A-Z0-9]{12}[0-9]{2}", documento):
        return False
    # CNPJ numérico e alfanumérico usam pesos iguais. No formato novo os
    # caracteres da base valem ASCII - 48, conforme manual DV da Receita.
    digits = [ord(character) - 48 for character in documento]
    for length, weights in ((12, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]), (13, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])):
        resto = sum(digits[i] * weights[i] for i in range(length)) % 11
        if digits[length] != (0 if resto < 2 else 11 - resto):
            return False
    return True


def _query_os(db: Session):
    return (
        db.query(OrdemServico, Clinica, Tutor, Servico)
        .outerjoin(Clinica, Clinica.id == OrdemServico.clinica_id)
        .outerjoin(Paciente, Paciente.id == OrdemServico.paciente_id)
        .outerjoin(Tutor, Tutor.id == Paciente.tutor_id)
        .outerjoin(Servico, Servico.id == OrdemServico.servico_id)
    )


def _exportacoes_anteriores(db: Session, os_ids: list[int]) -> dict[int, int]:
    counts = dict.fromkeys(os_ids, 0)
    # Histórico legado é textual e não comprova envio nem nota emitida.
    for row in db.query(RelatorioFiscalEmissao.os_ids_json).all():
        try:
            ids = json.loads(row.os_ids_json or "[]")
            if not isinstance(ids, list) or any(type(value) is not int for value in ids):
                raise ValueError
        except (TypeError, ValueError, json.JSONDecodeError):
            raise FiscalFechamentoError(503, "Histórico fiscal inconsistente. Confira os registros antes de preparar um pacote.")
        for os_id in set(ids).intersection(counts):
            counts[os_id] += 1
    return counts


def _serializar_os(row, competencia: str, claims: dict[int, int], exportacoes: dict[int, int]) -> dict:
    os_row, clinica, tutor, servico = row
    tipo = "PJ" if os_row.clinica_id is not None else "PF"
    tomador = clinica if tipo == "PJ" else tutor
    data = _data_local(os_row.data_atendimento)
    nome_base = (getattr(clinica, "razao_social", None) or getattr(clinica, "nome", None)) if tipo == "PJ" else getattr(tutor, "nome", None)
    nome = str(nome_base or "").strip()
    doc = re.sub(r"[.\s/\-]", "", str(getattr(tomador, "cnpj" if tipo == "PJ" else "cpf", None) or "").upper())
    endereco_base, endereco_fonte, pendencias_endereco = resolver_endereco(tomador, tipo, doc)
    endereco = ", ".join(endereco_base[field] for field in ("endereco", "numero", "complemento") if endereco_base[field])
    item = {
        "os_id": os_row.id,
        "numero_os": os_row.numero_os,
        "data_atendimento": os_row.data_atendimento.isoformat() if os_row.data_atendimento else None,
        "data_prestacao": data.date().isoformat() if data else None,
        "competencia": data.strftime("%Y-%m") if data else None,
        "valor_servico": _money(os_row.valor_servico),
        "valor_desconto": _money(os_row.desconto),
        "valor_final": _money(os_row.valor_final),
        "status_os": os_row.status or "",
        "tipo_cliente": tipo,
        "cliente_nome": nome,
        "cliente_documento": doc,
        "cliente_endereco": endereco,
        **{f"cliente_{field}": endereco_base[field] for field in ("bairro", "cidade", "estado", "cep")},
        **{f"cliente_{field}": str(getattr(tomador, field, None) or "").strip() for field in ("telefone", "email")},
        **endereco_fonte,
        "clinica_id": os_row.clinica_id,
        "clinica_nome": getattr(clinica, "nome", None) or ("Atendimento domiciliar" if tipo == "PF" else ""),
        "servico_nome": getattr(servico, "nome", None) or "",
        "origem_atendimento": os_row.origem_atendimento or "",
        "fechamento_id": claims.get(os_row.id),
        "exportacoes_anteriores": exportacoes.get(os_row.id, 0),
    }
    motivos = list(pendencias_endereco)
    if str(os_row.status or "").strip().casefold() == "cancelado":
        motivos.append("OS cancelada.")
    if not data:
        motivos.append("Data de prestação ausente.")
    elif item["competencia"] != competencia:
        motivos.append("Data de prestação fora da competência selecionada.")
    if item["fechamento_id"] is not None:
        motivos.append(f"OS já incluída no pacote {item['fechamento_id']}.")
    if not nome:
        motivos.append("Nome/razão social do tomador ausente.")
    if not _documento_valido(doc, tipo):
        motivos.append(f"{'CNPJ' if tipo == 'PJ' else 'CPF'} do tomador ausente ou inválido.")
    for field, label in (("endereco", "Endereço"), ("bairro", "Bairro"), ("cidade", "Cidade"), ("estado", "UF"), ("cep", "CEP")):
        if not item[f"cliente_{field}"]:
            motivos.append(f"{label} do tomador ausente.")
    if not item["servico_nome"]:
        motivos.append("Descrição do serviço ausente.")
    if item["valor_final"] <= 0:
        motivos.append("Valor final deve ser maior que zero.")
    if item["valor_servico"] < 0 or item["valor_desconto"] < 0 or item["valor_final"] != item["valor_servico"] - item["valor_desconto"]:
        motivos.append("Valores da OS não reconciliam serviço, desconto e valor final.")
    item["motivos_pendencia"] = motivos
    item["elegivel"] = not motivos
    return item


def _items(db: Session, rows, competencia: str) -> list[dict]:
    ids = [row[0].id for row in rows]
    claims = {}
    if ids:
        claims = dict(
            db.query(FiscalFechamentoOS.os_id, FiscalFechamentoOS.fechamento_id)
            .filter(FiscalFechamentoOS.os_id.in_(ids))
            .all()
        )
    exportacoes = _exportacoes_anteriores(db, ids)
    return [_serializar_os(row, competencia, claims, exportacoes) for row in rows]


def previa_fechamento(db: Session, competencia: str) -> dict:
    inicio, fim = _limites_competencia(competencia)
    # Faixa larga permite normalizar offsets no Python e preservar OS antigas sem fuso.
    inicio_query = inicio.replace(tzinfo=None)
    margem_inicio = inicio_query - timedelta(days=1) if inicio.year > 1 else inicio_query
    rows = (
        _query_os(db)
        .filter(
            or_(
                OrdemServico.data_atendimento.is_(None),
                (OrdemServico.data_atendimento >= margem_inicio)
                & (OrdemServico.data_atendimento < fim.replace(tzinfo=None) + timedelta(days=1)),
            )
        )
        .order_by(OrdemServico.data_atendimento.asc(), OrdemServico.id.asc())
        .all()
    )
    rows = [
        row for row in rows
        if row[0].data_atendimento is None or inicio <= _data_local(row[0].data_atendimento) < fim
    ]
    items = _items(db, rows, competencia)
    nao_canceladas = [item for item in items if item["status_os"].strip().casefold() != "cancelado"]
    return {
        "competencia": competencia,
        "data_inicio": inicio.date().isoformat(),
        "data_fim": (fim - timedelta(days=1)).date().isoformat(),
        "items": items,
        "resumo": {
            "quantidade_os": len(items),
            "quantidade_aptas": sum(item["elegivel"] for item in items),
            "quantidade_pendentes": sum(not item["elegivel"] for item in items),
            "quantidade_canceladas": len(items) - len(nao_canceladas),
            "quantidade_ja_preparadas": sum(item["fechamento_id"] is not None for item in items),
            "quantidade_exportadas_anteriormente": sum(item["exportacoes_anteriores"] > 0 for item in items),
            "valor_total": sum((item["valor_final"] for item in nao_canceladas), Decimal("0.00")),
            "valor_apto": sum((item["valor_final"] for item in items if item["elegivel"]), Decimal("0.00")),
        },
    }


def _fingerprint(
    competencia: str, os_ids: list[int], confirmar_datas: bool, confirmar_exportacoes: bool,
    contexto_rotina: dict | None = None,
) -> str:
    payload = {
        "competencia": competencia,
        "os_ids": sorted(os_ids),
        "confirmar_datas_prestacao": confirmar_datas,
        "confirmar_exportacoes_anteriores": confirmar_exportacoes,
    }
    # Sem contexto, o contrato de idempotência dos pacotes mensais é idêntico.
    if contexto_rotina is not None:
        payload["rotina"] = contexto_rotina
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _conferir_retry(fechamento: FiscalFechamento, fingerprint: str) -> FiscalFechamento:
    if fechamento.fingerprint != fingerprint:
        raise FiscalFechamentoError(409, "Esta chave já foi usada para outra seleção. Baixe o pacote anterior ou atualize a seleção.", fechamento_id=fechamento.id)
    if hashlib.sha256(fechamento.pacote_bytes).hexdigest() != fechamento.checksum:
        raise FiscalFechamentoError(503, "O pacote persistido falhou na verificação de integridade.")
    return fechamento


def preparar_fechamento(
    db: Session,
    *,
    competencia: str,
    os_ids: list[int],
    chave_idempotencia: UUID | str,
    confirmar_datas_prestacao: bool,
    confirmar_exportacoes_anteriores: bool = False,
    usuario_id: int | None = None,
    usuario_nome: str | None = None,
    contexto_rotina: dict | None = None,
) -> FiscalFechamento:
    _limites_competencia(competencia)
    if (
        not os_ids or len(os_ids) > 2000
        or any(type(value) is not int or value <= 0 for value in os_ids)
        or len(set(os_ids)) != len(os_ids)
    ):
        raise FiscalFechamentoError(422, "Selecione de 1 a 2000 OS únicas com IDs positivos.")
    try:
        key = str(UUID(str(chave_idempotencia)))
    except (ValueError, AttributeError):
        raise FiscalFechamentoError(422, "Chave de idempotência inválida.")
    fingerprint = _fingerprint(competencia, os_ids, confirmar_datas_prestacao, confirmar_exportacoes_anteriores, contexto_rotina)
    existente = db.query(FiscalFechamento).filter(FiscalFechamento.chave_idempotencia == key).first()
    if existente:
        return _conferir_retry(existente, fingerprint)
    if not confirmar_datas_prestacao:
        raise FiscalFechamentoError(422, "Confirme a conferência das datas de prestação antes de preparar o pacote.")
    try:
        # Ordem determinística reduz deadlocks. Postgres bloqueia as OS; unique claims
        # também protegem SQLite e qualquer disputa na persistência.
        locked = (
            db.query(OrdemServico.id)
            .filter(OrdemServico.id.in_(os_ids))
            .order_by(OrdemServico.id.asc())
            .with_for_update()
            .all()
        )
        missing = sorted(set(os_ids) - {row.id for row in locked})
        if missing:
            raise FiscalFechamentoError(422, "Algumas OS selecionadas não existem. Nenhum pacote foi preparado.", os_ids=missing)
        # A primeira leitura pode preceder o commit de outro retry concorrente.
        existente = db.query(FiscalFechamento).filter(FiscalFechamento.chave_idempotencia == key).first()
        if existente:
            return _conferir_retry(existente, fingerprint)
        if contexto_rotina is not None:
            clinica_ids = [row.clinica_id for row in db.query(OrdemServico.clinica_id).filter(OrdemServico.id.in_(os_ids)).distinct().all() if row.clinica_id is not None]
            # A preferência e a seleção ficam estáveis até persistir o pacote.
            # O PUT usa o mesmo lock de clínica e não precisa bloquear as OS.
            db.query(Clinica.id).filter(Clinica.id.in_(clinica_ids)).order_by(Clinica.id.asc()).with_for_update().all()
        selected_rows = (
            _query_os(db).filter(OrdemServico.id.in_(os_ids))
            .order_by(OrdemServico.id.asc()).populate_existing().all()
        )
        items = _items(db, selected_rows, competencia)
        pendencias_rotina = None
        if contexto_rotina is not None:
            from app.services.fiscal_rotina_service import validar_selecao_rotina
            items, pendencias_rotina = validar_selecao_rotina(db, items, contexto_rotina)
        claimed = [item for item in items if item["fechamento_id"] is not None]
        if claimed:
            ids = sorted({item["fechamento_id"] for item in claimed})
            raise FiscalFechamentoError(409, "Há serviços já incluídos em pacote preparado. Use a segunda via do pacote original.", fechamentos_ids=ids, fechamento_id=ids[0] if len(ids) == 1 else None, os_ids=[item["os_id"] for item in claimed])
        invalid = [item for item in items if not item["elegivel"]]
        if invalid:
            raise FiscalFechamentoError(422, "A seleção contém pendências. Nenhum pacote foi preparado.", pendencias=[{"os_id": item["os_id"], "motivos_pendencia": item["motivos_pendencia"]} for item in invalid])
        legacy = [item["os_id"] for item in items if item["exportacoes_anteriores"]]
        if legacy and not confirmar_exportacoes_anteriores:
            raise FiscalFechamentoError(422, "Há exportações anteriores. Confirme que conferiu o histórico para evitar cobrança duplicada.", os_ids=legacy)
        previa = previa_fechamento(db, competencia)
        pendencias = pendencias_rotina if pendencias_rotina is not None else [item for item in previa["items"] if not item["elegivel"]]
        export_args = {"contexto_rotina": contexto_rotina} if contexto_rotina is not None else {}
        content, filename = fiscal_export_service.gerar_pacote_contador(
            items, db, competencia=competencia, lote_id=key, pendencias=pendencias, **export_args
        )
        if not content:
            raise FiscalFechamentoError(500, "Não foi possível gerar o pacote. Nenhum serviço foi vinculado.")
        snapshot = {
            "competencia": competencia,
            "items": items,
            "pendencias": pendencias,
            "confirmar_datas_prestacao": confirmar_datas_prestacao,
            "confirmar_exportacoes_anteriores": confirmar_exportacoes_anteriores,
        }
        if contexto_rotina is not None:
            snapshot["rotina"] = contexto_rotina
        fechamento = FiscalFechamento(
            competencia=competencia,
            chave_idempotencia=key,
            fingerprint=fingerprint,
            data_inicio=previa["data_inicio"],
            data_fim=previa["data_fim"],
            quantidade_os=len(items),
            valor_total=sum((item["valor_final"] for item in items), Decimal("0.00")),
            snapshot_json=json.dumps(
                snapshot, ensure_ascii=False,
                default=lambda value: format(value, ".2f") if isinstance(value, Decimal) else str(value),
            ),
            arquivo_nome=filename,
            pacote_bytes=content,
            checksum=hashlib.sha256(content).hexdigest(),
            usuario_id=usuario_id,
            usuario_nome=(usuario_nome or "").strip() or None,
            preparado_em=datetime.now(FISCAL_TIMEZONE).isoformat(),
        )
        db.add(fechamento)
        db.flush()
        db.add_all([FiscalFechamentoOS(os_id=item["os_id"], fechamento_id=fechamento.id) for item in items])
        db.commit()
        db.refresh(fechamento)
        return fechamento
    except (IntegrityError, OperationalError):
        db.rollback()
        existente = db.query(FiscalFechamento).filter(FiscalFechamento.chave_idempotencia == key).first()
        if existente:
            return _conferir_retry(existente, fingerprint)
        claims = db.query(FiscalFechamentoOS).filter(FiscalFechamentoOS.os_id.in_(os_ids)).all()
        if claims:
            ids = sorted({row.fechamento_id for row in claims})
            raise FiscalFechamentoError(409, "Outro pacote já reservou serviços desta seleção. Nenhum pacote parcial foi preparado.", fechamentos_ids=ids, fechamento_id=ids[0] if len(ids) == 1 else None, os_ids=[row.os_id for row in claims])
        raise FiscalFechamentoError(409, "Não foi possível reservar a seleção concorrente. Atualize a prévia e tente novamente.")
    except Exception:
        db.rollback()
        raise


def listar_fechamentos(
    db: Session, *, skip: int = 0, limit: int = 20, competencia: str | None = None
) -> dict:
    query = db.query(FiscalFechamento).options(
        defer(FiscalFechamento.pacote_bytes), defer(FiscalFechamento.snapshot_json)
    )
    if competencia is not None:
        _limites_competencia(competencia)
        query = query.filter(FiscalFechamento.competencia == competencia)
    total = query.count()
    rows = query.order_by(FiscalFechamento.id.desc()).offset(skip).limit(limit).all()
    return {
        "total": total,
        "items": [
            {
                "id": row.id,
                "competencia": row.competencia,
                "chave_idempotencia": row.chave_idempotencia,
                "data_inicio": row.data_inicio,
                "data_fim": row.data_fim,
                "quantidade_os": row.quantidade_os,
                "valor_total": row.valor_total,
                "arquivo_nome": row.arquivo_nome,
                "checksum": row.checksum,
                "usuario_nome": row.usuario_nome,
                "preparado_em": row.preparado_em,
            }
            for row in rows
        ],
    }


def buscar_fechamento(db: Session, fechamento_id: int) -> FiscalFechamento:
    row = db.query(FiscalFechamento).filter(FiscalFechamento.id == fechamento_id).first()
    if row is None:
        raise FiscalFechamentoError(404, "Pacote não encontrado.")
    if hashlib.sha256(row.pacote_bytes).hexdigest() != row.checksum:
        raise FiscalFechamentoError(503, "O pacote persistido falhou na verificação de integridade.")
    return row
