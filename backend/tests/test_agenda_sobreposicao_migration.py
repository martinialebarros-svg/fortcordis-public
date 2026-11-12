import importlib.util
import os
import threading
import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from tests import test_agenda_concorrencia_slot as fixture
from app.api.v1.endpoints import agenda
from app.models.agendamento import Agendamento
from app.models.clinica import Clinica
from app.models.configuracao import Configuracao
from app.models.servico import Servico


def carregar(nome):
    caminho = Path(__file__).resolve().parents[1] / 'migrations' / 'versions' / nome
    spec = importlib.util.spec_from_file_location(caminho.stem, caminho)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


MIGRACAO = carregar('20261105_107_agenda_sobreposicao_admin.py')
ANTERIOR = carregar('20260715_49_agendamentos_slot_overlap_guard.py')


class AgendaSobreposicaoSQLiteMigrationTest(unittest.TestCase):
    def test_coluna_nullable_sem_concessao_retroativa_e_idempotente(self):
        engine = create_engine('sqlite:///:memory:')
        with engine.begin() as conn:
            conn.execute(text('CREATE TABLE agendamentos (id INTEGER PRIMARY KEY)'))
            conn.execute(text('INSERT INTO agendamentos (id) VALUES (1)'))
            MIGRACAO.upgrade(conn, 'sqlite')
            MIGRACAO.upgrade(conn, 'sqlite')
            self.assertIsNone(conn.execute(text('SELECT excecao_sobreposicao FROM agendamentos')).scalar_one())
            self.assertIn('excecao_sobreposicao', {c['name'] for c in inspect(conn).get_columns('agendamentos')})
        engine.dispose()


@unittest.skipUnless(os.getenv('AGENDA_TEST_POSTGRES_URL'), 'PostgreSQL temporario opt-in nao configurado')
class AgendaSobreposicaoPostgresTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(os.environ['AGENDA_TEST_POSTGRES_URL'])
        url = self.engine.url
        # Estes testes criam/removem tabelas: aceitar somente o cluster descartavel desta tarefa.
        if url.database != 'agenda_admin_sintetico' or not str(url.query.get('host', '')).startswith('/tmp/fortcordis-agenda-admin-pg.'):
            self.fail('Use somente o banco sintetico no socket temporario dedicado')
        self.addCleanup(self.engine.dispose)
        tabelas = [Configuracao.__table__, Clinica.__table__, Servico.__table__, Agendamento.__table__]
        with self.engine.begin() as conn:
            for tabela in reversed(tabelas):
                tabela.drop(conn, checkfirst=True)
            for tabela in tabelas:
                tabela.create(conn)
            ANTERIOR._create_exclusion_constraint(conn)
            MIGRACAO.upgrade(conn, 'postgresql')
        self.sessions = sessionmaker(bind=self.engine, autoflush=False)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for nome in ('registrar_auditoria', '_notificar_agenda_update', '_validar_deslocamento_agendamento'):
            self.stack.enter_context(patch.object(agenda, nome, return_value=None))
        self.admin = SimpleNamespace(id=1, nome='Admin Sintetico', tem_papel=lambda p: p == 'admin')

    def inserir(self, conn, id_, inicio='08:30', fim='09:00', concessao=None):
        conn.execute(text('''INSERT INTO agendamentos
            (id, inicio, fim, status, origem_atendimento, excecao_sobreposicao, urgente_laudo, whatsapp_reminder_attempts)
            VALUES (:id, :inicio, :fim, 'Agendado', 'clinica_parceira', :concessao, false, 0)'''), {
                'id': id_, 'inicio': f'2099-05-27 {inicio}:00-03',
                'fim': f'2099-05-27 {fim}:00-03', 'concessao': concessao,
            })

    def test_exclusao_comum_continua_bloqueando_e_migracao_e_idempotente(self):
        with self.engine.begin() as conn:
            MIGRACAO.upgrade(conn, 'postgresql')
            self.inserir(conn, 1)
        with self.assertRaises(IntegrityError) as erro, self.engine.begin() as conn:
            self.inserir(conn, 2)
        self.assertEqual(erro.exception.orig.pgcode, "23P01")
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(text('SELECT count(*) FROM agendamentos')).scalar_one(), 1)

    def test_intervalos_adjacentes_sem_sobreposicao_sao_permitidos(self):
        with self.engine.begin() as conn:
            self.inserir(conn, 1)
            self.inserir(conn, 2, '09:00', '09:45')

    def test_trigger_revoga_reuso_do_escopo_e_exclusao_recusa_movimento(self):
        with self.engine.begin() as conn:
            self.inserir(conn, 1)
            self.inserir(conn, 2, '08:00', '08:45', '{"escopo":"sintetico"}')
        with self.assertRaises(IntegrityError) as erro, self.engine.begin() as conn:
            conn.execute(text("UPDATE agendamentos SET inicio='2099-05-27 08:05:00-03' WHERE id=2"))
        self.assertEqual(erro.exception.orig.pgcode, "23P01")
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(text('SELECT count(*) FROM agendamentos')).scalar_one(), 2)

    def test_trigger_preserva_edicao_sem_mudanca_de_escopo(self):
        with self.engine.begin() as conn:
            self.inserir(conn, 1)
            self.inserir(conn, 2, '08:00', '08:45', '{"escopo":"sintetico"}')
            conn.execute(text("UPDATE agendamentos SET observacoes='Revisado', status='Confirmado' WHERE id=2"))
            self.assertIsNotNone(conn.execute(text('SELECT excecao_sobreposicao FROM agendamentos WHERE id=2')).scalar_one())

    def test_api_autoriza_15_minutos_e_mantem_ocupacao_para_nova_solicitacao(self):
        with self.sessions() as db:
            clinica = Clinica(nome='Clinica Sintetica', ativo=True, latitude=-3.7319, longitude=-38.5267)
            servico = Servico(nome='Servico Sintetico', ativo=True, duracao_minutos=45)
            db.add_all([clinica, servico]); db.commit()
            def payload(hora):
                return agenda.AgendamentoCreate(clinica_id=clinica.id, servico_id=servico.id,
                    inicio=datetime(2099, 5, 27, hora, 30 if hora == 8 else 0), status='Reservado')
            ocupado = payload(8)
            agenda.criar_agendamento(ocupado, SimpleNamespace(), db, self.admin)
            candidato = ocupado.model_copy(update={'inicio': datetime(2099, 5, 27, 8)})
            with self.assertRaises(agenda.HTTPException) as erro:
                agenda.criar_agendamento(candidato, SimpleNamespace(), db, self.admin)
            token = erro.exception.detail['escopo']
            db.rollback()
            autorizado = candidato.model_copy(update={'confirmar_sobreposicao': True,
                'escopo_sobreposicao_confirmado': token, 'motivo_excecao_sobreposicao': 'Autorizacao sintetica dos 15 minutos'})
            resposta = agenda.criar_agendamento(autorizado, SimpleNamespace(), db, self.admin)
            self.assertTrue(resposta['fim'].endswith('08:45:00'))
            self.assertTrue(resposta['excecao_sobreposicao'])
            with self.assertRaises(agenda.HTTPException) as erro:
                agenda.criar_agendamento(candidato, SimpleNamespace(), db, self.admin)
            self.assertEqual(erro.exception.status_code, 409)
            self.assertEqual(db.query(Agendamento).count(), 2)
            mudanca = agenda.AgendamentoUpdate(inicio=datetime(2099, 5, 27, 8, 5))
            with self.assertRaises(agenda.HTTPException) as erro:
                agenda.atualizar_agendamento(resposta['id'], mudanca, SimpleNamespace(), db, self.admin)
            novo_token = erro.exception.detail['escopo']
            db.rollback()
            self.assertNotEqual(novo_token, token)
            mudanca = mudanca.model_copy(update={'confirmar_sobreposicao': True,
                'escopo_sobreposicao_confirmado': novo_token, 'motivo_excecao_sobreposicao': 'Novo horario revisado'})
            alterado = agenda.atualizar_agendamento(resposta['id'], mudanca, SimpleNamespace(), db, self.admin)
            self.assertEqual(alterado['excecao_sobreposicao']['confirmacao'], novo_token)
            self.assertTrue(alterado['inicio'].endswith('08:05:00'))

    def test_duas_criacoes_comuns_concorrentes_criam_apenas_uma(self):
        with self.sessions() as db:
            clinica = Clinica(nome='Clinica Sintetica', ativo=True, latitude=-3.7319, longitude=-38.5267)
            servico = Servico(nome='Servico Sintetico', ativo=True, duracao_minutos=45)
            db.add_all([clinica, servico]); db.commit()
            payload = agenda.AgendamentoCreate(clinica_id=clinica.id, servico_id=servico.id,
                inicio=datetime(2099, 5, 27, 10), status='Reservado')
        barreira = threading.Barrier(2)
        resultados = []
        def criar():
            with self.sessions() as db:
                try:
                    barreira.wait(timeout=5)
                    agenda.criar_agendamento(payload, SimpleNamespace(), db, self.admin)
                    resultados.append(201)
                except agenda.HTTPException as erro:
                    resultados.append(erro.status_code)
                except Exception as erro:
                    resultados.append(type(erro).__name__)
        threads = [threading.Thread(target=criar, daemon=True) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        self.assertEqual(sorted(resultados, key=str), [201, 409])
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(text('SELECT count(*) FROM agendamentos')).scalar_one(), 1)
