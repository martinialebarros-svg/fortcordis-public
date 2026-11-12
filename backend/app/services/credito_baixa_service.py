"""Saldo e baixa administrativa sem movimentacao de caixa."""
from datetime import datetime
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, text

from app.models.clinica import Clinica
from app.models.financeiro import CreditoFinanceiro
from app.models.paciente import Paciente
from app.models.tutor import Tutor


def bloquear_destino(db, destino):
    if db.get_bind().dialect.name == "sqlite":
        # SQLite ignores FOR UPDATE. Acquire its writer lock before reading the
        # ledger; an existing write transaction already holds that lock.
        connection = db.connection()
        if not connection.connection.driver_connection.in_transaction:
            connection.execute(text("BEGIN IMMEDIATE"))
    if destino["tipo_destino"] == "clinica":
        db.query(Clinica).filter(Clinica.id == destino["clinica_id"]).with_for_update().first()
    elif destino["tutor_id"]:
        db.query(Tutor).filter(Tutor.id == destino["tutor_id"]).with_for_update().first()
    else:
        db.query(Paciente).filter(Paciente.id == destino["paciente_id"]).with_for_update().first()


def destino_credito(db, *, tipo_destino, paciente_id=None, clinica_id=None, bloquear=False):
    """Serialize debits on the owner, including receipts consuming client credit."""
    if tipo_destino == "clinica":
        query = db.query(Clinica).filter(Clinica.id == clinica_id)
        registro = query.first()
        if not registro:
            raise HTTPException(404, "Clinica nao encontrada.")
        destino = {"tipo_destino": "clinica", "clinica_id": registro.id, "paciente_id": None, "tutor_id": None}
        if bloquear:
            bloquear_destino(db, destino)
        return destino
    paciente = db.query(Paciente).filter(Paciente.id == paciente_id).first()
    if not paciente:
        raise HTTPException(404, "Paciente nao encontrado.")
    destino = {"tipo_destino": "cliente", "clinica_id": None, "paciente_id": paciente.id, "tutor_id": paciente.tutor_id}
    if bloquear:
        bloquear_destino(db, destino)
    return destino


def movimentos_destino(db, destino):
    query = db.query(CreditoFinanceiro).filter(
        CreditoFinanceiro.tipo_destino == destino["tipo_destino"],
        CreditoFinanceiro.status == "Ativo",
    )
    if destino["tipo_destino"] == "clinica":
        return query.filter(CreditoFinanceiro.clinica_id == destino["clinica_id"])
    if destino["tutor_id"]:
        return query.filter(or_(
            CreditoFinanceiro.tutor_id == destino["tutor_id"],
            and_(CreditoFinanceiro.tutor_id.is_(None), CreditoFinanceiro.paciente_id == destino["paciente_id"]),
        ))
    return query.filter(CreditoFinanceiro.paciente_id == destino["paciente_id"])


def saldo_destino(db, destino):
    saldo = movimentos_destino(db, destino).with_entities(func.coalesce(func.sum(CreditoFinanceiro.valor), 0)).scalar()
    return Decimal(str(saldo or 0)).quantize(Decimal("0.01"))


def baixar_credito(db, dados, current_user):
    destino = destino_credito(db, tipo_destino=dados.tipo_destino, paciente_id=dados.paciente_id,
                             clinica_id=dados.clinica_id, bloquear=True)
    marcador = f"[BAIXA_ID={dados.idempotency_key}]"
    # Owner lock makes retries atomic without changing the ledger schema.
    anterior = db.query(CreditoFinanceiro).filter(
        CreditoFinanceiro.origem == "baixa_sem_contrapartida",
        CreditoFinanceiro.descricao.endswith(marcador),
    ).first()
    motivo = dados.motivo.strip()
    if len(motivo) < 3:
        raise HTTPException(422, "Informe o motivo da baixa (ao menos 3 caracteres).")
    descricao = f"Baixa sem contrapartida: {motivo} {marcador}"
    if anterior:
        if (any(getattr(anterior, chave) != valor for chave, valor in destino.items())
                or Decimal(str(-anterior.valor)).quantize(Decimal("0.01")) != dados.valor
                or anterior.descricao != descricao or anterior.status != "Ativo"):
            raise HTTPException(409, "Esta identificacao de baixa ja foi utilizada. Atualize o saldo.")
        return anterior, destino, saldo_destino(db, destino), False
    saldo = saldo_destino(db, destino)
    if dados.valor > saldo:
        raise HTTPException(400, "Valor da baixa maior que o saldo de credito disponivel.")
    now = datetime.now()
    movimento = CreditoFinanceiro(
        **destino, valor=-float(dados.valor), status="Ativo", origem="baixa_sem_contrapartida",
        descricao=descricao, data_movimento=now, created_at=now, updated_at=now,
        criado_por_id=current_user.id, criado_por_nome=current_user.nome,
        # Independent from any receipt: undoing an OS must not undo this decision.
        ordem_servico_id=None, transacao_id=None,
    )
    db.add(movimento)
    db.commit()
    db.refresh(movimento)
    return movimento, destino, saldo - dados.valor, True
