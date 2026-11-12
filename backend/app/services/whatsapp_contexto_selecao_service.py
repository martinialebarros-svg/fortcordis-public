"""Identidade, versao e lock do cadastro escolhido para uma conversa WhatsApp."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from typing import Any

from sqlalchemy import text, update
from sqlalchemy.orm import Session

from app.models.whatsapp_bot import WhatsAppBotContextoSelecao
from app.services.whatsapp_agenda_service import normalize_whatsapp_number


def canonical_context_identity(phone: str) -> str:
    normalized = normalize_whatsapp_number(phone)
    if re.fullmatch(r"55\d{2}9\d{8}", normalized):
        return normalized[:4] + normalized[5:]
    return normalized


def lock_contexto(db: Session, wa_identity: str) -> None:
    """Serialize escolha e envio ate commit/rollback, inclusive primeira escolha.

    O chamador deve adquirir o lock antes de ler/validar o contexto e manter a
    transacao aberta ate o envio terminar. Nao altera pausa, modo ou versao.
    """
    identity = canonical_context_identity(wa_identity)
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        digest = hashlib.sha256(f"whatsapp-contexto:{identity}".encode()).digest()
        lock_key = int.from_bytes(digest[:8], byteorder="big", signed=True)
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
    elif dialect == "sqlite":
        # UPDATE adquire o lock de escrita mesmo sem linha. Informar updated_at
        # explicitamente evita o onupdate automatico do modelo neste no-op.
        db.execute(
            update(WhatsAppBotContextoSelecao)
            .where(WhatsAppBotContextoSelecao.wa_identity == identity)
            .values(updated_at=WhatsAppBotContextoSelecao.updated_at)
            .execution_options(synchronize_session=False)
        )
    else:
        raise RuntimeError("Dialeto sem lock de contexto WhatsApp suportado")


def carregar_selecao(db: Session, phone: str) -> WhatsAppBotContextoSelecao | None:
    return (
        db.query(WhatsAppBotContextoSelecao)
        .filter(WhatsAppBotContextoSelecao.wa_identity == canonical_context_identity(phone))
        .populate_existing()
        .first()
    )


def selecao_payload(selecao: WhatsAppBotContextoSelecao | None, candidatos: dict) -> dict | None:
    if selecao is None:
        return None
    if selecao.match_type is None and selecao.cadastro_id is None:
        valida = True  # Tombstone: voltar a resolver automaticamente.
    else:
        key = {"clinica": "clinicas", "tutor": "tutores"}.get(selecao.match_type)
        valida = key is not None and any(
            item["id"] == selecao.cadastro_id for item in candidatos.get(key, [])
        )
    return {
        "match_type": selecao.match_type,
        "cadastro_id": selecao.cadastro_id,
        "versao": selecao.versao,
        "valida": valida,
        "atualizado_por_id": selecao.atualizado_por_id,
        "updated_at": selecao.updated_at.isoformat() if selecao.updated_at else None,
    }


def criar_contexto_chave(phone: str, candidatos: dict, selecao: dict | None) -> str:
    identity = {
        "wa_identity": canonical_context_identity(phone),
        "candidatos": {
            key: sorted(item["id"] for item in candidatos.get(key, []))
            for key in ("clinicas", "tutores")
        },
        "selecao": {
            key: selecao.get(key) for key in ("match_type", "cadastro_id", "versao", "valida")
        } if selecao else None,
    }
    return hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def resposta_contexto_vigente(db: Session, resposta: Any) -> bool:
    """Falha fechada para respostas legadas, selecao alterada e vinculo removido.

    Nao adquire lock implicitamente: o envio precisa manter o mesmo lock desde
    esta verificacao ate o transporte terminar, sem commit intermediario.
    """
    expected = getattr(resposta, "contexto_chave", None)
    if not isinstance(expected, str) or len(expected) != 64:
        return False
    from app.api.v1.endpoints.whatsapp_contexto import resolve_whatsapp_context

    current = resolve_whatsapp_context(db, resposta.wa_identity)
    return hmac.compare_digest(expected, current["contexto_chave"])
