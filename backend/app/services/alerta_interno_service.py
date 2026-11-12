from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.models.alerta_interno import AlertaInterno


def criar_alerta_interno(
    db: Session,
    *,
    tipo: str,
    titulo: str,
    mensagem: str,
    nivel: str = "aviso",
    entidade_tipo: Optional[str] = None,
    entidade_id: Optional[int] = None,
    clinica_id: Optional[int] = None,
) -> AlertaInterno:
    """Adiciona um alerta interno na sessao atual (o chamador decide quando commitar).

    Ao contrario de `registrar_auditoria` (best-effort, sessao propria), este alerta e
    a entrega principal de uma acao (ex.: avisar a secretaria de um cancelamento feito
    pelo portal) e por isso e criado na MESMA transacao do chamador: se o commit falhar,
    a acao inteira falha em vez de "ter sucesso" silenciosamente sem avisar ninguem.
    """
    alerta = AlertaInterno(
        tipo=tipo,
        nivel=nivel,
        titulo=titulo,
        mensagem=mensagem,
        entidade_tipo=entidade_tipo,
        entidade_id=entidade_id,
        clinica_id=clinica_id,
    )
    db.add(alerta)
    return alerta
