"""Fila de pedidos; nenhuma operacao envia mensagem ou escreve na agenda."""
from datetime import datetime, timedelta, timezone
import json

from fastapi import HTTPException
from sqlalchemy import func

from app.models.whatsapp_bot import WhatsAppBotSolicitacao as Pedido

ABERTOS = ('aguardando_equipe', 'em_atendimento', 'aguardando_cliente')
STATUS = (*ABERTOS, 'agendado', 'cancelado')
LABELS = dict(zip(STATUS, ('Aguardando equipe', 'Em atendimento', 'Aguardando cliente', 'Agendado', 'Cancelado')))


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def registrar(db, resposta, state):
    """Mesma transacao da resposta; lock + UNIQUE impedem duplicacao em retries."""
    from app.models.whatsapp_bot import WhatsAppBotResposta
    from app.services.whatsapp_bot_agendamento import resumo
    if resposta.decisao != 'sent' or state.get('status') != 'encaminhada' or not resposta.clinica_id or state.get('clinica_id') != resposta.clinica_id:
        return
    db.query(WhatsAppBotResposta).filter_by(id=resposta.id).with_for_update().first()
    if db.query(Pedido).filter_by(resposta_id=resposta.id).first():
        return
    now = datetime.now(timezone.utc)
    description = resumo(state)
    if state.get('preferencia_recebida_em'):
        description += '\nPreferência informada em: ' + state['preferencia_recebida_em']
    db.add(Pedido(resposta_id=resposta.id, wa_identity=resposta.wa_identity,
        conversation_id=resposta.conversation_id, clinica_id=resposta.clinica_id,
        resumo=description, status='aguardando_equipe', prazo_em=now + timedelta(hours=2),
        created_at=now, updated_at=now, versao=1,
        historico=json.dumps([{'acao':'recebida', 'em':now.isoformat()}])))
    db.flush()


def ultimo(db, identity, clinic_id):
    return db.query(Pedido).filter_by(wa_identity=identity, clinica_id=clinic_id).order_by(Pedido.id.desc()).first()


def contexto(pedido):
    return {'id': pedido.id, 'status': pedido.status, 'resumo': pedido.resumo} if pedido else None


def payload(row, user_id):
    return {'id':row.id, 'agendamento_id':row.agendamento_id, 'conversation_id':row.conversation_id, 'wa_identity':row.wa_identity, 'clinica_id':row.clinica_id,
        'resumo':row.resumo, 'status':row.status, 'responsavel_nome':row.responsavel_nome,
        'minha':row.responsavel_id == user_id, 'sem_responsavel':row.responsavel_id is None,
        'prazo_em':utc(row.prazo_em).isoformat(), 'atrasada':row.status in ABERTOS and utc(row.prazo_em) < datetime.now(timezone.utc),
        'created_at':utc(row.created_at).isoformat(), 'versao':row.versao,
        'historico':json.loads(row.historico)}


def listar(db, user_id, filtro, minhas, page, conversation_id=None):
    query = db.query(Pedido)
    if conversation_id is not None:
        query = query.filter(Pedido.conversation_id == conversation_id)
    if filtro == 'abertas':
        query = query.filter(Pedido.status.in_(ABERTOS))
    elif filtro == 'atrasadas':
        query = query.filter(Pedido.status.in_(ABERTOS), Pedido.prazo_em < datetime.now(timezone.utc))
    elif filtro != 'todas':
        query = query.filter(Pedido.status == filtro)
    if minhas:
        query = query.filter(Pedido.responsavel_id == user_id)
    counts = dict(db.query(Pedido.status, func.count(Pedido.id)).group_by(Pedido.status).all())
    rows = query.order_by(Pedido.prazo_em, Pedido.id).offset((page-1)*20).limit(20).all()
    from app.models.clinica import Clinica
    names = dict(db.query(Clinica.id, Clinica.nome).filter(Clinica.id.in_({r.clinica_id for r in rows})).all()) if rows else {}
    return {'total':query.count(), 'page':page, 'contagens':counts,
        'itens':[dict(payload(r,user_id), clinica_nome=names.get(r.clinica_id)) for r in rows]}


def atualizar(db, pedido_id, req, user):
    row = db.query(Pedido).filter_by(id=pedido_id).first()
    if not row:
        raise HTTPException(404, 'Solicitação não encontrada.')
    if row.versao != req.versao:
        raise HTTPException(409, 'A solicitação mudou. Atualize a fila antes de tentar novamente.')
    now = datetime.now(timezone.utc)
    values = {'versao':row.versao+1, 'updated_at':now}
    if req.acao == 'assumir':
        if row.status not in ABERTOS:
            raise HTTPException(409, 'Solicitação concluída.')
        if row.responsavel_id is not None and row.responsavel_id != user.id:
            raise HTTPException(409, 'Outro atendente já assumiu esta solicitação.')
        values.update(responsavel_id=user.id, responsavel_nome=(user.nome or "Atendente")[:160], assumida_em=now)
        if row.status == 'aguardando_equipe':
            values['status'] = 'em_atendimento'
    else:
        if row.responsavel_id != user.id and not (req.acao == 'liberar' and user.tem_papel('admin')):
            raise HTTPException(403, 'Assuma a solicitação antes de alterá-la.')
        if row.status not in ABERTOS:
            raise HTTPException(409, 'Solicitação concluída; o histórico foi preservado.')
        if req.acao == 'liberar':
            values.update(responsavel_id=None, responsavel_nome=None, status='aguardando_equipe')
        else:
            if req.status == 'agendado':
                raise HTTPException(422, 'Use Agendar pedido para salvar e vincular um agendamento real.')
            if req.status:
                if req.status == 'aguardando_equipe':
                    raise HTTPException(422, 'Use liberar para devolver o pedido à equipe.')
                values['status'] = req.status
                if req.status in ('agendado', 'cancelado'):
                    if not req.observacao or not req.observacao.strip():
                        raise HTTPException(422, 'Registre o resultado antes de concluir.')
                    values['concluida_em'] = now
            if req.prazo_em:
                if req.prazo_em.tzinfo is None or not now < req.prazo_em <= now + timedelta(days=30):
                    raise HTTPException(422, 'Informe prazo com fuso horário, futuro e até 30 dias.')
                values['prazo_em'] = req.prazo_em
            if not req.status and not req.prazo_em:
                raise HTTPException(422, 'Informe status ou prazo.')
    events = json.loads(row.historico)
    events.append({'acao':req.acao, 'em':now.isoformat(), 'usuario_id':user.id, 'usuario_nome':user.nome,
        'status':values.get('status',row.status), 'observacao':req.observacao,
        'prazo_em':utc(values.get('prazo_em',row.prazo_em)).isoformat()})
    values['historico'] = json.dumps(events, ensure_ascii=False)
    changed = db.query(Pedido).filter_by(id=pedido_id,versao=req.versao).update(values, synchronize_session=False)
    if changed != 1:
        db.rollback()
        raise HTTPException(409, 'Outro atendente alterou o pedido. Atualize a fila.')
    db.commit()
    db.refresh(row)
    return payload(row,user.id)
