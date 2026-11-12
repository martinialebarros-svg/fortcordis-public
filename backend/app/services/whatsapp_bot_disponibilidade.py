"""Convite administrativo para outro pedido; nunca reabre ou agenda o anterior."""
import json
from datetime import datetime, timedelta, timezone

from app.models.whatsapp_bot import WhatsAppBotResposta
from app.services.whatsapp_bot_agendamento import KEY as COLETA_KEY, normalizar, preparar
from app.services.whatsapp_bot_fila import ultimo, utc

KEY = 'confirmacao_novo_pedido'
SIM = {'sim', 'quero sim', 'sim quero', 'pode iniciar', 'sim pode iniciar', 'pode seguir'}
NAO = {'nao', 'nao quero', 'nao obrigado', 'nao obrigada', 'agora nao'}


def _resposta(message):
    if '?' in message:
        return None
    command = normalizar(message).strip(' .!')
    if command in SIM:
        return True
    if command in NAO:
        return False
    return None


def _pedido_cancelado(pedido, wa_identity, clinica_id, conversation_id):
    return bool(pedido and conversation_id is not None
                and pedido.wa_identity == wa_identity and pedido.clinica_id == clinica_id
                and str(pedido.conversation_id) == str(conversation_id)
                and pedido.status == 'cancelado' and pedido.agendamento_id is None)


def convidar(pedido, exame, wa_identity, clinica_id, conversation_id):
    if not exame or not _pedido_cancelado(pedido, wa_identity, clinica_id, conversation_id):
        return None
    text = (f'Sua solicitação anterior foi cancelada. Você quer iniciar uma nova solicitação de {exame}? '
            'Pode responder sim ou não. Nenhum horário foi reservado.')
    return text, {KEY: {'clinica_id': clinica_id, 'pedido_id': pedido.id,
                       'pedido_versao': pedido.versao, 'exame': exame}}


def _convite_pendente(db, pedido, wa_identity, clinica_id, conversation_id):
    if not _pedido_cancelado(pedido, wa_identity, clinica_id, conversation_id):
        return None
    # Uma resposta mais recente invalida o convite, inclusive draft/bloqueio.
    row = db.query(WhatsAppBotResposta).filter_by(
        wa_identity=wa_identity, conversation_id=str(conversation_id),
    ).order_by(WhatsAppBotResposta.id.desc()).first()
    if (not row or row.clinica_id != clinica_id or row.decisao != 'sent' or not row.texto_enviado
            or row.texto_enviado != row.texto_gerado or row.created_at is None
            or not timedelta(0) <= datetime.now(timezone.utc) - utc(row.created_at) <= timedelta(minutes=30)):
        return None
    try:
        data = json.loads(row.tools_usadas or '{}').get(KEY)
    except (ValueError, TypeError, AttributeError):
        return None
    if (not isinstance(data, dict) or data.get('clinica_id') != clinica_id
            or data.get('pedido_id') != pedido.id or data.get('pedido_versao') != pedido.versao
            or not isinstance(data.get('exame'), str) or not data['exame']):
        return None
    # Metadados e texto devem corresponder ao convite renderizado, sem edições.
    invitation = convidar(pedido, data['exame'], wa_identity, clinica_id, conversation_id)
    return data if invitation and row.texto_enviado == invitation[0] else None


def responder(db, pedido, message, wa_identity, clinica_id, conversation_id, contexto):
    answer = _resposta(message)
    if answer is None:
        return None
    data = _convite_pendente(db, pedido, wa_identity, clinica_id, conversation_id)
    if not data:
        return None
    if not answer:
        return 'Tudo bem. Não vou iniciar uma nova solicitação. Se precisar de outra informação, é só me dizer.', {}
    # Só o exame foi informado no convite aceito. Os demais dados são novos.
    previous = {'status': 'coletando', 'dados': {'exame': data['exame']},
                'origens': {'exame': 'mensagem_cliente'}}
    coleta, text = preparar(previous, None, message, clinica_id, contexto)
    coleta['fila_anterior_id'] = pedido.id
    return text, {COLETA_KEY: coleta}


def resposta_ao_convite_pendente(db, identity, message, conversation_id):
    """Permite sim/não no gate de cortesia; a geração revalida o escopo atual."""
    if _resposta(message) is None or conversation_id is None:
        return False
    row = db.query(WhatsAppBotResposta).filter_by(
        wa_identity=identity, conversation_id=str(conversation_id),
    ).order_by(WhatsAppBotResposta.id.desc()).first()
    if not row or not row.clinica_id:
        return False
    pedido = ultimo(db, identity, row.clinica_id)
    return bool(_convite_pendente(db, pedido, identity, row.clinica_id, conversation_id))
