"""Continuidade administrativa com fatos persistidos, sem alterar a agenda."""
import json
import re
from datetime import datetime, timedelta, timezone
from app.models.whatsapp_bot import WhatsAppBotSolicitacao as Pedido
from app.services.whatsapp_bot_agendamento import normalizar
from app.services.whatsapp_bot_fila import LABELS

KEY = 'continuidade_pedido'
NOVOS = {'nova solicitacao', 'novo pedido', 'novo agendamento', 'quero outro agendamento',
         'quero agendar outro exame', 'quero fazer um novo agendamento'}


def novo_pedido(message):
    return normalizar(message).strip(' .!?') in NOVOS


def resposta_pedido(db, pedido, message, coleta):
    text = normalizar(message)
    status = bool(re.search(r'\b(status|andamento|novidade|como esta|como ficou|ja foi agendado|foi marcado|qual o horario do meu|quando sera)\b', text))
    active = coleta and coleta.get('status') in ('coletando', 'aguardando_confirmacao')
    correction = not active and bool(re.search(r'\b(corrigir|correcao|na verdade|trocar|mudar|alterar|cancelar|desistir)\b', text))
    if not status and not correction:
        return None
    if correction:
        return (f'Recebi sua atualização para o pedido #{pedido.id}. A equipe vai revisar a mudança solicitada antes de confirmá-la.',
                {'pedido_id':pedido.id, 'complemento':message[:2000]})
    body = f'O pedido #{pedido.id} está como “{LABELS[pedido.status]}”. '
    if pedido.agendamento_id:
        from app.models.agendamento import Agendamento
        agenda = db.get(Agendamento, pedido.agendamento_id)
        if agenda and agenda.clinica_id == pedido.clinica_id:
            from app.services.assistente_ia_tools import LOCAL_TZ
            inicio = agenda.inicio
            # Agenda armazena datas sem timezone no horário local da operação.
            if inicio.tzinfo:
                inicio = inicio.astimezone(LOCAL_TZ)
            body = f'O agendamento do pedido #{pedido.id} está como “{agenda.status}”, para {inicio.strftime("%d/%m/%Y às %H:%M")} (horário de Fortaleza). '
        else:
            body = f'O pedido #{pedido.id} tem um vínculo de agenda que precisa ser conferido pela equipe. '
    elif pedido.status == 'aguardando_equipe':
        body += 'A equipe ainda vai verificar a disponibilidade; nenhum horário está reservado. '
    elif pedido.status == 'cancelado':
        body += 'O pedido foi encerrado pela equipe. '
    else:
        body += 'A equipe está acompanhando a solicitação. '
    return body + 'Para outro exame, escreva “novo pedido”.', {'pedido_id':pedido.id}


def registrar_complemento(db, resposta):
    data = json.loads(resposta.tools_usadas or '{}').get(KEY, {})
    if not data.get('complemento'):
        return
    row = db.query(Pedido).filter_by(id=data['pedido_id'], wa_identity=resposta.wa_identity,
        clinica_id=resposta.clinica_id, conversation_id=resposta.conversation_id).populate_existing().with_for_update().first()
    if row is None:
        raise ValueError('Pedido indisponível para registrar atualização')
    events = json.loads(row.historico)
    if any(e.get('job_id') == resposta.job_id and e.get('acao') == 'complemento_cliente' for e in events):
        return
    if data.get('horario_preferido') and (row.versao != data.get('pedido_versao') or row.status != 'aguardando_equipe' or row.responsavel_id is not None):
        # A escolha chegou, mas não pode sobrescrever uma atualização concorrente.
        data['complemento'] = 'Escolha recebida após alteração do pedido; a equipe precisa revisar: ' + data['horario_preferido']
        data['horario_preferido'] = None
        resposta.texto_gerado = 'O pedido mudou durante a consulta. A equipe vai conferir sua escolha; nenhum horário foi reservado.'
        audit = json.loads(resposta.tools_usadas or '{}')
        audit[KEY] = data
        audit['opcoes_agenda'] = {'estado':'equipe', 'pedido_id':row.id}
        resposta.tools_usadas = json.dumps(audit, ensure_ascii=False)
    now = datetime.now(timezone.utc)
    events.append({'acao':'complemento_cliente', 'em':now.isoformat(), 'job_id':resposta.job_id,
        'observacao':data['complemento'], 'usuario_nome':'Cliente pelo WhatsApp',
        'horario_preferido':data.get('horario_preferido')})
    row.historico=json.dumps(events, ensure_ascii=False);row.updated_at=now;row.versao+=1
    # Complemento vira pendência para a equipe, inclusive após conclusão do
    # pedido; não reabre/cancela o agendamento nem troca dados confirmados.
    from app.services.alerta_interno_service import criar_alerta_interno
    criar_alerta_interno(db, tipo='whatsapp_bot_complemento', nivel='aviso',
        titulo=f'Atualização do cliente no pedido #{row.id}', mensagem=data['complemento'])
    db.flush()


def agrupar_fragmentos(history, current):
    """Somente textos contíguos nos dois minutos anteriores à última mensagem."""
    try:
        now = datetime.fromisoformat(str(current.get('created_at')).replace('Z', '+00:00'))
    except (ValueError, TypeError):
        return str(current.get('body') or ''), history
    if current.get("from_me") or current.get("type") != "text":
        return str(current.get("body") or ""), history
    collected = []
    for item in reversed(history):
        try:
            when = datetime.fromisoformat(str(item.get('created_at')).replace('Z', '+00:00'))
            age = now - when
        except (ValueError, TypeError):
            break
        if item.get('from_me') or item.get('type') != 'text' or not timedelta(0) <= age <= timedelta(minutes=2):
            break
        collected.insert(0, str(item.get('body') or ''))
        if len(collected) >= 5:
            break
    combined = '\n'.join(collected + [str(current.get('body') or '')])
    if len(combined) > 4000:
        return str(current.get('body') or ''), history
    return combined, history[:-len(collected)] if collected else history


def pedido_assumido(db, identity, conversation_id):
    from app.services.whatsapp_bot_fila import ABERTOS
    return db.query(Pedido.id).filter(Pedido.wa_identity == identity,
        Pedido.conversation_id == str(conversation_id), Pedido.status.in_(ABERTOS),
        Pedido.responsavel_id.is_not(None)).first() is not None
