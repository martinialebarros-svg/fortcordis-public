"""Ordens de serviço explícitas para laudos de ECG sem agenda."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.security import _user_has_matrix_permission
from app.models.auditoria_evento import AuditoriaEvento
from app.models.clinica import Clinica
from app.models.laudo import Laudo
from app.models.ordem_servico import OrdemServico
from app.models.servico import Servico
from app.models.user import User
from app.services.precos_service import calcular_preco_servico


def pode_acessar_ordens(db: Session, user: User, action: str) -> bool:
    return user.tem_papel("admin") or _user_has_matrix_permission(db, user, "ordens_servico", action)


def exigir_criacao_ordem(db: Session, user: User) -> None:
    if not pode_acessar_ordens(db, user, "editar"):
        raise HTTPException(403, "Sem permissao para gerar ordens de servico.")


def validar_preco_ordem(db: Session, clinic_id: int | None, servico_id: int | None, tipo_horario: str) -> Decimal:
    if tipo_horario not in {"comercial", "plantao"}:
        raise HTTPException(422, "Tipo de horario invalido. Use comercial ou plantao.")
    clinica = db.query(Clinica).filter(Clinica.id == clinic_id, Clinica.ativo.is_(True)).first()
    if not clinica:
        raise HTTPException(422, "Selecione uma clinica parceira ativa para gerar a OS.")
    servico = db.query(Servico).filter(Servico.id == servico_id, Servico.ativo.is_(True)).first()
    if not servico:
        raise HTTPException(422, "Selecione um servico ativo para gerar a OS.")
    valor = calcular_preco_servico(
        db, clinic_id, servico_id, tipo_horario,
        usar_preco_clinica=True, origem_atendimento="clinica_parceira",
    )
    if not valor.is_finite() or valor <= 0:
        raise HTTPException(422, "Configure um preco maior que zero para a clinica, o servico e o horario selecionados.")
    return valor.quantize(Decimal("0.01"))


def chave_upload_ordem(user_id: int, value: str | None) -> str:
    value = str(value or "").strip()
    if not 8 <= len(value) <= 128:
        raise HTTPException(422, "Informe uma chave de idempotencia de 8 a 128 caracteres para gerar a OS.")
    return f"laudo-eletro:{user_id}:{value}"


def hash_upload_ordem(**payload) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def buscar_ordem_por_chave(db: Session, chave: str, request_hash: str) -> OrdemServico | None:
    ordem = db.query(OrdemServico).filter(OrdemServico.idempotency_key == chave).first()
    if ordem and ordem.request_hash != request_hash:
        raise HTTPException(409, "Esta tentativa de envio ja foi usada com outros dados. Inicie um novo envio.")
    return ordem


def buscar_ordem_laudo(db: Session, laudo_id: int, *, somente_ativa: bool = False) -> OrdemServico | None:
    query = db.query(OrdemServico).filter(OrdemServico.laudo_id == laudo_id)
    if somente_ativa:
        query = query.filter(or_(OrdemServico.status.is_(None), OrdemServico.status != "Cancelado"))
    return query.order_by(OrdemServico.id.desc()).first()


def resumo_ordem(ordem: OrdemServico | None) -> dict | None:
    if ordem is None:
        return None
    return {"id": ordem.id, "numero_os": ordem.numero_os, "valor_final": float(ordem.valor_final), "status": ordem.status}


def mesma_data(db: Session, original: datetime | None, nova: datetime | None) -> bool:
    # SQLite persiste DateTime sem offset; PostgreSQL preserva o instante.
    if db.get_bind().dialect.name == "sqlite":
        original = original.replace(tzinfo=None) if original else None
        nova = nova.replace(tzinfo=None) if nova else None
    return original == nova


def criar_ordem_laudo(
    db: Session, *, laudo: Laudo, servico_id: int, tipo_horario: str,
    valor: Decimal, chave: str, request_hash: str, user: User,
) -> OrdemServico:
    ordem = OrdemServico(
        numero_os=f"OS-LAUDO-{laudo.id}", laudo_id=laudo.id, agendamento_id=None,
        idempotency_key=chave, request_hash=request_hash,
        paciente_id=laudo.paciente_id, clinica_id=laudo.clinic_id, servico_id=servico_id,
        origem_atendimento="clinica_parceira", data_atendimento=laudo.data_exame,
        tipo_horario=tipo_horario, valor_servico=valor, desconto=Decimal("0.00"),
        valor_final=valor, status="Pendente",
        observacoes=f"OS gerada no upload do laudo de eletrocardiograma {laudo.id}, sem agendamento.",
        criado_por_id=user.id, criado_por_nome=user.nome,
    )
    db.add(ordem)
    db.flush()
    # A cobrança e sua evidência de autoria pertencem à mesma transação.
    db.add(AuditoriaEvento(
        usuario_id=user.id, usuario_nome=user.nome, usuario_email=user.email,
        modulo="ordens_servico", entidade="ordem_servico", entidade_id=str(ordem.id),
        acao="ORDEM_SERVICO_CRIADA", descricao="OS criada pelo upload de eletrocardiograma sem agenda.",
        rota="/api/v1/laudos/eletrocardiograma/upload-pdf", metodo="POST",
        detalhes_json=json.dumps({"laudo_id": laudo.id, "numero_os": ordem.numero_os,
            "clinic_id": laudo.clinic_id, "paciente_id": laudo.paciente_id,
            "servico_id": servico_id, "tipo_horario": tipo_horario, "valor_final": str(valor)}, sort_keys=True),
    ))
    return ordem
