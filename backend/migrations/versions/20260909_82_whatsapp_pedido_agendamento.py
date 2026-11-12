"""Vinculo aditivo; preserva pedidos historicos sem inventar agendamentos."""
from sqlalchemy import inspect, text
VERSION='20260909_82'
DESCRIPTION='Vincula pedido WhatsApp ao agendamento criado na mesma transacao'

def upgrade(connection,dialect):
    table='whatsapp_bot_solicitacoes'
    if table not in inspect(connection).get_table_names():return
    if 'agendamento_id' not in {c['name'] for c in inspect(connection).get_columns(table)}:
        connection.execute(text(f'ALTER TABLE {table} ADD COLUMN agendamento_id INTEGER'))
    connection.execute(text(f'CREATE UNIQUE INDEX IF NOT EXISTS ux_whatsapp_pedido_agendamento ON {table} (agendamento_id)'))
