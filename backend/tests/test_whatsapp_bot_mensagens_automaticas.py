import tempfile
import unicodedata
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from tests import test_whatsapp_bot_process_job as cases
from app.services.whatsapp_bot_mensagens_automaticas import AVISOS, mensagem_automatica
from app.services import whatsapp_bot_worker_service as worker
from app.models.whatsapp_bot import WhatsAppBotResposta, WhatsAppBotConversaEstado
from app.models.alerta_interno import AlertaInterno


# Corpos observados na auditoria, independentes da allowlist da implementação.
# Se uma entrada for removida/alterada em AVISOS, estes casos precisam falhar.
AVISOS_AUDITADOS = {
    '769': """Olá!! Seja Bem Vindo a *Clínica Veterinária Popular Vitoria's Pet*

Dispomos de serviços a PREÇO POPULAR:\x20
Consultas, Vacinas,Exames laboratoriais e de Imagem, Cirurgias eletivas e de emergência, Testes rápidos, Farmácia completa e muito mais !!! 🏅🐾

_Nossos horários de funcionamento:_
_Segunda a Sexta de 8 as 18h_
_Sábado 8 as 12h_\x20


‎Agradecemos seu contato. Como podemos ajudar?""",
    '783': """Agradecemos sua mensagem. Não estamos disponíveis no momento, mas responderemos assim que possível.

Se for emergência buscar atendimento veterinário mais próximo e disponível.

🕐 HORÁRIO DE FUNCIONAMENTO DA LOJA

🛑 *SEGUNDA A SÁBADO*
🕐 08:00 ÀS 12:00\x20
🕐 14:00 ÀS 19:00

🛑 *DOMINGO E FERIADOS*
🕐  08:00 às 12:00
🕐 A TARDE - FECHADO\x20

🐶😻❤️""",
    '804': """A gente tá descansando agora 🌙  Nosso atendimento é:\x20

📅 Seg a sex: 9h às 18h\x20
📅 Sábado: 8h às 17h\x20\x20

⚠️ Se for emergência agora (sangramento, convulsão, dificuldade pra respirar ou ingestão de algo tóxico), procure um pronto-socorro veterinário 24h imediatamente.\x20\x20

Mas se puder esperar até abrirmos, deixa tudo registrado aqui — assim eu já organizo seu atendimento e você fica no topo da fila da manhã ⭐""",
    '807': """Olá!! estamos fora do horário de atendimento\x20\x20

Em caso de emergência fora do horário de funcionamento, indicamos se dirigir às clínicas 24horas mais próximas.

Nosso horário de funcionamento é:
Seg-sex das 08h as 18h\x20
Sáb das 08h as 12h

Conosco a saúde do seu pet tem Vitória garantida 🥇""",
    '810': """Olá, tudo bem?! No momento não estamos disponíveis.

Nosso horário de funcionamento:

*Segundas:* 13:30h às 17:30h
*Terça a Sábado:* 08:30h às 17:30h
* Domingo:* Fechado\x20



Em caso de emergência, sugerimos levar o seu pet em uma clínica 24h.""",
}


@pytest.mark.parametrize('texto', AVISOS_AUDITADOS.values(), ids=AVISOS_AUDITADOS.keys())
def test_avisos_auditados_reconhecidos_apenas_inteiros(texto):
    from app.services.whatsapp_bot_mensagens_automaticas import sem_aviso_automatico

    sem_acentos = ''.join(c for c in unicodedata.normalize('NFKD', texto)
                         if not unicodedata.combining(c))
    apresentacao = '🚨 ** ' + ' \t '.join(sem_acentos.upper().split()) + ' ** !!!'
    for body in (texto, apresentacao):
        item = {'type': 'text', 'from_me': False, 'body': body}
        assert mensagem_automatica(item)
        assert sem_aviso_automatico(item)['body'] == ''
        assert item['body'] == body
        assert not mensagem_automatica({**item, 'from_me': True})
        assert not mensagem_automatica({**item, 'type': 'image'})
        for relato in ('Meu pet está com falta de ar.', 'Quero falar com um humano.',
                       'Preciso de um laudo.'):
            for misto in (body + '\n' + relato, relato + '\n' + body):
                mixed_item = {**item, 'body': misto}
                assert not mensagem_automatica(mixed_item)
                assert sem_aviso_automatico(mixed_item)['body'] == misto


@pytest.mark.parametrize('relato', (
    'Meu pet está em emergência.',
    'Meu gato está com falta de ar.',
    'Meu cachorro está com convulsão.',
    'Estamos fora do expediente, mas meu pet está com falta de ar.',
))
def test_relato_real_nunca_e_aviso_automatico(relato):
    from app.services.whatsapp_bot_gates import detecta_emergencia
    from app.services.whatsapp_bot_mensagens_automaticas import sem_aviso_automatico

    item = {'type': 'text', 'from_me': False, 'body': relato}
    assert not mensagem_automatica(item)
    assert detecta_emergencia(sem_aviso_automatico(item)['body'])


def test_reconhecimento_exato_sem_ocultar_complementos():
    for texto in AVISOS:
        item = {'type': 'text', 'from_me': False, 'body': '🚨 *' + texto + '*'}
        assert mensagem_automatica(item)
        assert not mensagem_automatica({**item, 'from_me': True})
        assert not mensagem_automatica({**item, 'type': 'image'})
        for extra in (' meu pet está com falta de ar', ' preciso de um laudo', ' quero falar com humano'):
            assert not mensagem_automatica({**item, 'body': texto + extra})
    assert not mensagem_automatica({'type': 'text', 'body': 'Fora do expediente, meu pet está em emergência'})


def test_worker_avisos_fragmentos_e_pausas():
    helper = cases.WhatsAppBotProcessJobTest()
    now = datetime.now(timezone.utc)
    def msg(body, offset=0):
        return {'type': 'text', 'from_me': False, 'body': body,
                'created_at': (now + timedelta(seconds=offset)).isoformat()}
    scenarios = [
        *[(texto, [], False, 'mensagem_automatica') for texto in AVISOS],
        *[(texto, [], True, 'mensagem_automatica') for texto in AVISOS_AUDITADOS.values()],
        *[(texto + '\nMeu pet está com falta de ar.', [], True, 'emergencia')
          for texto in AVISOS_AUDITADOS.values()],
        *[(texto, [msg('Meu pet está com falta de ar.', -10)], True, 'emergencia')
          for texto in AVISOS_AUDITADOS.values()],
        *[('Meu pet está com falta de ar.', [msg(texto, -10)], True, 'emergencia')
          for texto in AVISOS_AUDITADOS.values()],
        (AVISOS[0], [msg('meu pet está com falta de ar', -10)], True, 'emergencia'),
        ('meu pet está com falta de ar', [msg(AVISOS[0], -10)], True, 'emergencia'),
        (AVISOS[0] + '\nmeu pet está com falta de ar', [], True, 'emergencia'),
        (AVISOS[0], [msg('quero falar com humano', -10)], False, 'pedido_humano'),
        ('qual o valor do exame?', [msg(AVISOS[0], -10)], True, 'pausado'),
        (AVISOS[0], [], True, 'mensagem_automatica'),
    ]
    for current, history, paused, expected in scenarios:
        with tempfile.TemporaryDirectory() as tmp:
            factory, engine = helper._build_session_factory(tmp)
            try:
                with factory() as db, ExitStack() as stack:
                    job = helper._make_job(db)
                    if paused:
                        db.add(WhatsAppBotConversaEstado(wa_identity=job.wa_identity, pausado_ate=now+timedelta(hours=1)))
                        db.commit()
                    stack.enter_context(patch.object(worker, 'is_whatsapp_bot_enabled', return_value=True))
                    stack.enter_context(patch.object(worker, 'resolve_conversation_mode', return_value='auto'))
                    stack.enter_context(patch.object(worker, '_bot_internal_client_config', return_value=('local', {}, 1)))
                    stack.enter_context(patch.object(worker, '_fetch_conversation_by_phone', return_value={'id':job.conversation_id}))
                    stack.enter_context(patch.object(worker, '_last_message_from_conversation', return_value=msg(current)))
                    stack.enter_context(patch.object(worker, '_fetch_historico', return_value=history+[msg(current)]))
                    handoff = stack.enter_context(patch.object(worker, 'trigger_active_handoff'))
                    generator = stack.enter_context(patch.object(worker, 'gerar_resposta'))
                    pause = stack.enter_context(patch.object(worker, 'pause_conversation'))
                    stack.enter_context(patch.object(worker, 'build_handoff_message', return_value='Equipe avisada'))
                    worker._process_job(db, job)
                    db.flush()
                    audit = db.query(WhatsAppBotResposta).one()
                    assert audit.motivo == expected, (current, expected, audit.motivo)
                    assert audit.texto_enviado is None
                    assert handoff.call_count == int(expected in ('emergencia', 'pedido_humano'))
                    pause.assert_not_called()
                    generator.assert_not_called()
                    assert db.query(AlertaInterno).count() == 0
                    if expected == 'mensagem_automatica':
                        assert db.query(WhatsAppBotConversaEstado).count() == int(paused)
            finally:
                engine.dispose()


def test_pedido_real_contiguo_preservado_sem_cruzar_limites():
    from app.services.whatsapp_bot_continuidade import agrupar_fragmentos
    from app.services.whatsapp_bot_mensagens_automaticas import sem_aviso_automatico
    now = datetime.now(timezone.utc)
    current = {'body': AVISOS[0], 'from_me': False, 'type': 'text', 'created_at': now.isoformat()}
    previous = {**current, 'body': 'Poderia enviar a chave Pix e o valor?', 'created_at': (now-timedelta(seconds=15)).isoformat()}
    original = dict(current)
    body, _ = agrupar_fragmentos([sem_aviso_automatico(previous)], sem_aviso_automatico(current))
    assert body.strip() == previous['body']
    assert current == original
    for change in ({'from_me': True}, {'type': 'image'}, {'created_at': (now-timedelta(minutes=3)).isoformat()}):
        body, _ = agrupar_fragmentos([sem_aviso_automatico({**previous, **change})], sem_aviso_automatico(current))
        assert not body.strip()
