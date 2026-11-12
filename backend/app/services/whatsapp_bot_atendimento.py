"""Assumir conversa e pedidos em uma ação recuperável, sem envio externo.

O claim remoto é idempotente e nunca transfere outro responsável. Se o commit
local falhar, o claim continua protegendo a conversa e repetir reconcilia a fila.
"""
import json
from datetime import datetime, timezone
from urllib.parse import quote

import httpx
from fastapi import HTTPException
from app.core.config import settings
from app.models.whatsapp_bot import WhatsAppBotSolicitacao as Pedido
from app.services.whatsapp_bot_fila import ABERTOS
from app.services.whatsapp_bot_gates import pause_conversation, set_handoff_motivo


def node(method, path, **kwargs):
    base = str(settings.WHATSAPP_AGENDA_SERVICE_URL or '').rstrip('/')
    token = str(settings.WHATSAPP_AGENDA_INTERNAL_TOKEN or '')
    if not base or not token:
        raise HTTPException(503, 'Integração indisponível. Nenhum pedido foi alterado.')
    try:
        r = httpx.request(method, base + path, headers={'x-whatsapp-internal-token': token}, timeout=8, **kwargs)
        if r.status_code == 409:
            raise HTTPException(409, 'A conversa já está com outro atendente. O responsável foi mantido.')
        r.raise_for_status()
        return r.json()
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, 'Não foi possível confirmar a atribuição. Atualize a conversa e repita Assumir atendimento para reconciliar os pedidos.') from None


def assumir(db, conversation_id, telefone, user, pedido_id=None, versao=None):
    conversation_id = str(conversation_id)
    conversations = node('GET', '/conversations', params={'phone': telefone, 'limit': 1}).get('data', [])
    if not conversations or str(conversations[0]['id']) != conversation_id:
        raise HTTPException(404, 'Conversa não encontrada para este contato.')
    identity = str(conversations[0]['wa_phone_number'])
    agents = node('GET', '/agents').get('data', [])
    own = [a for a in agents if a.get('active') and str(a.get('email') or '').strip().lower() == str(user.email or '').strip().lower()]
    if len(own) != 1:
        raise HTTPException(409, 'Vincule seu usuário a um único atendente ativo pelo email antes de assumir.')
    rows = db.query(Pedido).filter(Pedido.conversation_id == conversation_id, Pedido.wa_identity == identity, Pedido.status.in_(ABERTOS)).order_by(Pedido.id).populate_existing().with_for_update().all()
    if pedido_id is not None:
        selected = next((p for p in rows if p.id == pedido_id), None)
        if selected is None:
            raise HTTPException(409, 'Pedido concluído ou alterado. Atualize a fila.')
        if selected.versao != versao and selected.responsavel_id != user.id:
            raise HTTPException(409, 'Pedido alterado. Atualize a fila antes de assumir.')
    if any(p.responsavel_id not in (None, user.id) for p in rows):
        raise HTTPException(409, 'Um pedido desta conversa já está com outro atendente. Revise a atribuição com a equipe.')
    # Mantém os locks dos pedidos até confirmar o claim. Sem compensação cega
    # que poderia liberar uma conversa assumida pelo próprio usuário.
    node('POST', f'/conversations/{quote(conversation_id, safe="")}/claim', json={'agent_id': int(own[0]['id']), 'only_if_unassigned': True})
    now = datetime.now(timezone.utc)
    try:
        for row in rows:
            if row.responsavel_id == user.id:
                continue
            events = json.loads(row.historico)
            events.append({'acao':'assumir_atendimento', 'em':now.isoformat(), 'usuario_id':user.id, 'usuario_nome':user.nome, 'status':'em_atendimento'})
            row.responsavel_id=user.id;row.responsavel_nome=user.nome;row.assumida_em=now
            row.status='em_atendimento';row.updated_at=now;row.versao+=1
            row.historico=json.dumps(events, ensure_ascii=False)
        pause_conversation(db, identity, atualizado_por_id=user.id)
        set_handoff_motivo(db, identity, 'atendimento_assumido', atualizado_por_id=user.id)
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(503, 'A conversa foi assumida, mas os pedidos precisam ser reconciliados. Repita Assumir atendimento; o bot permanece protegido pelo responsável da conversa.') from None
    return {'message':'Conversa e pedidos assumidos. O bot aguarda a equipe.', 'agent_id':str(own[0]['id']), 'pedidos':[p.id for p in rows]}
