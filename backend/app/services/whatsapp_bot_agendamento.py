"""Coleta administrativa; nunca cria cadastro, reserva ou agendamento.

Snapshots vivem na auditoria existente, na mesma transacao da resposta.
Somente o worker persiste; simulacoes continuam sem efeitos colaterais.
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone

from app.models.whatsapp_bot import WhatsAppBotResposta

KEY = 'solicitacao_agendamento'
CONFIRMACOES = {'sim', 'confirmo', 'confirmo os dados', 'confirmo dados', 'confirmar dados', 'dados corretos', 'os dados estao corretos', 'esta correto', 'esta certo', 'tudo certo', 'pode seguir'}

FIELDS = {'exame': 'exame solicitado', 'paciente': 'nome do paciente',
          'tutor': 'nome do tutor', 'preferencia': 'preferência de dia e horário (ou sem preferência)'}


def normalizar(value):
    return ' '.join(unicodedata.normalize('NFKD', str(value)).encode('ascii', 'ignore').decode().lower().split())


def confirma_dados(message):
    # Perguntas e frases com ressalvas nunca confirmam implicitamente.
    return '?' not in message and normalizar(message).strip(' .!') in CONFIRMACOES


def saudacao_inicial(db, identity, message):
    if normalizar(message).strip(' .!?') not in ('oi', 'ola', 'bom dia', 'boa tarde', 'boa noite'):
        return False
    return not db.query(WhatsAppBotResposta.id).filter(
        WhatsAppBotResposta.wa_identity == identity,
        WhatsAppBotResposta.decisao.in_(['sent', 'draft', 'auto_pending', 'sending']),
        WhatsAppBotResposta.created_at >= datetime.now(timezone.utc) - timedelta(hours=6),
    ).first()


def carregar(db, identity, clinic_id, conversation_id=None):
    if not clinic_id:
        return None
    rows = db.query(WhatsAppBotResposta).filter(
        WhatsAppBotResposta.wa_identity == identity,
        WhatsAppBotResposta.clinica_id == clinic_id,
        WhatsAppBotResposta.created_at >= datetime.now(timezone.utc) - timedelta(hours=48),
        WhatsAppBotResposta.decisao.in_(['sent', 'draft', 'auto_pending', 'sending']),
    ).order_by(WhatsAppBotResposta.id.desc()).limit(100).all()
    for row in rows:
        if conversation_id is not None and str(row.conversation_id) != str(conversation_id):
            continue
        try:
            state = json.loads(row.tools_usadas or '{}').get(KEY)
        except (ValueError, TypeError):
            continue
        if isinstance(state, dict) and state.get('clinica_id') == clinic_id:
            state = dict(state)
            state['resumo_enviado'] = row.decisao == 'sent'
            return state
    return None


def resumo(state):
    values = state.get('dados', {})
    return '\n'.join(f'{label.capitalize()}: {values.get(key) or "não informado"}' for key, label in FIELDS.items())


def preparar(previous, update, message, clinic_id, contexto):
    """Extracao do modelo e nao confiavel: aceita apenas trechos do inbound atual.

    Confirmacao e cancelamento sao comandos exatos, independentes do modelo.
    Correcoes invalidam a confirmacao anterior.
    """
    state = {'clinica_id': clinic_id, 'status': 'coletando', 'dados': {}, 'origens': {}}
    command = normalizar(message).strip(' .!?')
    if previous and previous.get('status') not in ('encaminhada', 'cancelada') and command != 'nova solicitacao':
        state['dados'] = dict(previous.get('dados', {}))
        state['origens'] = dict(previous.get('origens', {}))
        state['preferencia_recebida_em'] = previous.get('preferencia_recebida_em')
    command = normalizar(message).strip(' .!?')
    if command in ('cancelar solicitacao', 'cancelar pedido'):
        state['status'] = 'cancelada'
        return state, 'Atendimento automático FortCordis: coleta cancelada. Nenhum agendamento foi criado. Para falar com a equipe, peça atendimento humano.'
    changed = False
    for key in FIELDS:
        value = getattr(update, key, None) if update else None
        if value and normalizar(value) not in ('nao sei', 'nao informado', 'a confirmar', 'desconhecido', 'exame', 'exames') and normalizar(value) in normalizar(message):
            value = re.sub(r'[\r\n\t]+', ' ', value).strip()
            if state['dados'].get(key) != value:
                state['dados'][key] = value
                state['origens'][key] = 'mensagem_cliente'
                changed = True
                if key == 'preferencia':
                    state['preferencia_recebida_em'] = datetime.now(timezone.utc).isoformat()
                if key == 'paciente' and state['origens'].get('tutor') == 'cadastro':
                    state['dados'].pop('tutor', None)
                    state['origens'].pop('tutor', None)
    # Reuso apenas de paciente explicitamente escolhido, unico no contexto
    # ja limitado pelo resolvedor aos atendimentos da clinica identificada.
    if state['dados'].get('paciente') and not state['dados'].get('tutor'):
        pets = [p for p in contexto.get('pets', []) if normalizar(p.get('nome')) == normalizar(state['dados']['paciente'])]
        if len(pets) == 1:
            tutors = [t for t in contexto.get('tutores', []) if t.get('id') == pets[0].get('tutor_id')]
            if len(tutors) == 1 and tutors[0].get('nome'):
                state['dados']['tutor'] = tutors[0]['nome'][:120]
                state['origens']['tutor'] = 'cadastro'
    missing = [label for key, label in FIELDS.items() if not state['dados'].get(key)]
    if missing:
        text = 'Para organizar a solicitação, informe ' + ', '.join(missing) + '.'
    elif previous and previous.get('status') == 'aguardando_confirmacao' and previous.get('resumo_enviado') and not changed and confirma_dados(message):
        state['status'] = 'encaminhada'
        text = 'Dados confirmados. A equipe vai verificar a disponibilidade e confirmar o agendamento. Nenhum horário foi reservado.'
    else:
        state['status'] = 'aguardando_confirmacao'
        text = 'Confira os dados da solicitação:\n' + resumo(state) + '\nEstá correto? Responda “confirmo os dados” ou envie uma correção. A equipe verificará a disponibilidade; ainda não há horário reservado.'
    return state, text


def validar_texto(state, text):
    from app.services.whatsapp_bot_guardrails import (
        avaliar_resposta, TurnoDeGeracao, GuardrailVeredito, _horarios_no_texto, _max_reply_chars,
    )
    if len(text) > _max_reply_chars():
        return GuardrailVeredito(aprovado=False, motivo='teto_caracteres')
    turno = TurnoDeGeracao(persona='clinica', tools_ok=['coleta_administrativa'])
    # Preferencia literal do cliente nao e disponibilidade da agenda.
    turno.horarios_permitidos = _horarios_no_texto(state.get('dados', {}).get('preferencia', ''))
    return avaliar_resposta(texto=text, intent='solicitar_agendamento', modo='suggest', turno=turno)


def encaminhar(db, resposta):
    """Notifica uma vez, somente depois da mensagem final efetivamente enviada."""
    from app.services.whatsapp_bot_handoff_service import trigger_active_handoff
    try:
        audit = json.loads(resposta.tools_usadas or '{}')
    except (ValueError, TypeError):
        return
    state = audit.get(KEY)
    if resposta.decisao != 'sent' or not isinstance(state, dict) or state.get('status') != 'encaminhada':
        return
    from app.services.whatsapp_bot_fila import registrar
    registrar(db, resposta, state)
    if state.get('notificada'):
        return
    trigger_active_handoff(db, wa_identity=resposta.wa_identity, conversation_id=resposta.conversation_id,
        motivo='solicitacao_agendamento', pausar=False, nivel='aviso', titulo='Solicitação de agendamento para conferir',
        mensagem_alerta='Dados conferidos pelo solicitante. Valide disponibilidade na agenda.\n' + resumo(state))
    state['notificada'] = True
    resposta.tools_usadas = json.dumps(audit, ensure_ascii=False)


def confirmacao_de_coleta_ativa(db, identity, message):
    if not confirma_dados(message):
        return False
    row = db.query(WhatsAppBotResposta).filter(
        WhatsAppBotResposta.wa_identity == identity,
        WhatsAppBotResposta.clinica_id.is_not(None),
    ).order_by(WhatsAppBotResposta.id.desc()).first()
    state = carregar(db, identity, row.clinica_id) if row else None
    return bool(state and state.get('status') == 'aguardando_confirmacao' and state.get('resumo_enviado'))


def exame_em_consulta_disponibilidade(message):
    """Intenção administrativa explícita; texto misto segue a triagem normal.

    Não infere horário nem sintomas. Devolve o nome literal do exame apenas
    para perguntas curtas de disponibilidade, nunca uma confirmação de agenda.
    O prefixo aceita saudações consecutivas, inclusive vindas de fragmentos;
    qualquer outro conteúdo continua na triagem normal, sem ser descartado.
    """
    text = str(message or '').strip().rstrip('?! .')
    match = re.fullmatch(
        r'(?:(?:oi|ol[aá]|bom dia|boa tarde|boa noite)[,!.\s]+)*'
        r'(?:qual\s+(?:[eé]\s+)?(?:a\s+)?disponibilidade(?:\s+de\s+hor[aá]rios?)?'
        r'|(?:quais|qual)\s+(?:os?\s+)?hor[aá]rios?'
        r'|(?:(?:voc[eê]s|vcs)\s+)?(?:t[eê]m|h[aá])\s+(?:disponibilidade(?:\s+de\s+hor[aá]rios?)?|hor[aá]rios?))'
        r'\s+(?:dispon[ií]ve(?:l|is)\s+)?(?:pra|para|de|do|pro)\s+(?:(?:o|um)\s+)?'
        r'(?P<exame>eco|ecocardiograma|ecodopplercardiograma|eletro|eletrocardiograma|ecg|consulta cardiol[oó]gica)'
        r'(?:,?\s+por favor)?',
        text, flags=re.IGNORECASE,
    )
    return match.group('exame') if match else None
