"""Fila duravel para coleta confirmada; rollback do codigo preserva a tabela."""
import json
from datetime import datetime, timedelta, timezone
from sqlalchemy import text, inspect

VERSION = '20260909_81'
DESCRIPTION = 'Cria fila de solicitacoes do bot com responsavel, prazo e historico'


def upgrade(connection, dialect):
    pk = 'SERIAL PRIMARY KEY' if dialect == 'postgresql' else 'INTEGER PRIMARY KEY AUTOINCREMENT'
    dt = 'TIMESTAMP WITH TIME ZONE' if dialect == 'postgresql' else 'DATETIME'
    connection.execute(text(f'''CREATE TABLE IF NOT EXISTS whatsapp_bot_solicitacoes (
        id {pk}, resposta_id INTEGER NOT NULL UNIQUE,
        wa_identity VARCHAR(30) NOT NULL, conversation_id VARCHAR(64) NOT NULL,
        clinica_id INTEGER NOT NULL, resumo TEXT NOT NULL,
        status VARCHAR(30) NOT NULL DEFAULT 'aguardando_equipe',
        responsavel_id INTEGER, responsavel_nome VARCHAR(160), prazo_em {dt} NOT NULL,
        assumida_em {dt}, concluida_em {dt}, created_at {dt} NOT NULL,
        updated_at {dt} NOT NULL, versao INTEGER NOT NULL DEFAULT 1, historico TEXT NOT NULL DEFAULT '[]'
    )'''))
    for col in ('wa_identity', 'clinica_id', 'status', 'prazo_em'):
        connection.execute(text(f'CREATE INDEX IF NOT EXISTS ix_whatsapp_bot_solicitacoes_{col} ON whatsapp_bot_solicitacoes ({col})'))
    # Pedidos ja entregues antes da migracao tambem ficam visiveis para triagem.
    if 'whatsapp_bot_respostas' not in inspect(connection).get_table_names():
        return
    now = datetime.now(timezone.utc)
    rows = connection.execute(text("SELECT id, wa_identity, conversation_id, clinica_id, tools_usadas FROM whatsapp_bot_respostas WHERE decisao='sent' AND clinica_id IS NOT NULL AND tools_usadas LIKE '%solicitacao_agendamento%'")).mappings()
    for row in rows:
        try:
            state = json.loads(row['tools_usadas'] or '{}').get('solicitacao_agendamento')
        except (ValueError,TypeError):
            continue
        if not isinstance(state,dict) or state.get('status') != 'encaminhada' or state.get('clinica_id') != row['clinica_id']:
            continue
        dados = state.get('dados',{})
        resumo = '\n'.join(f'{label}: {dados.get(key) or "não informado"}' for key,label in (
            ('exame','Exame solicitado'),('paciente','Nome do paciente'),('tutor','Nome do tutor'),('preferencia','Preferência de dia e horário')))
        if state.get('preferencia_recebida_em'):
            resumo += '\nPreferência informada em: ' + state['preferencia_recebida_em']
        connection.execute(text('''INSERT INTO whatsapp_bot_solicitacoes
            (resposta_id,wa_identity,conversation_id,clinica_id,resumo,status,prazo_em,created_at,updated_at,versao,historico)
            VALUES (:id,:wa_identity,:conversation_id,:clinica_id,:resumo,'aguardando_equipe',:prazo,:now,:now,1,:historico)
            ON CONFLICT (resposta_id) DO NOTHING'''),
            dict(id=row['id'],wa_identity=row['wa_identity'],conversation_id=row['conversation_id'],clinica_id=row['clinica_id'],
                resumo=resumo,prazo=now+timedelta(hours=2),now=now,historico=json.dumps([{'acao':'importada_para_triagem','em':now.isoformat()}])))
