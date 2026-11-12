import importlib.util
import os
import sys
import tempfile
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "tutores-rotina-local-test-secret-1234567890")

from app.api.v1.endpoints import pacientes, tutores
from app.models.agendamento import Agendamento
from app.models.paciente import Paciente
from app.models.tutor import Tutor
from app.models.tutor_mesclagem import TutorMesclagem
from app.models.tutor_mesclagem_reversao import TutorMesclagemReversao
from app.models.tutor_rotina import (
    TutorContato, TutorDuplicidadeDescarte, TutorIdentificacaoEvento,
    TutorOperacao, TutorOrigem,
)
from app.services import tutor_rotina_service as rotina


class TutoresRotinaAgilTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{self.tmp.name}/rotina.db", connect_args={"check_same_thread": False})
        for model in (Tutor, Paciente, Agendamento, TutorMesclagem, TutorContato, TutorOrigem,
                      TutorIdentificacaoEvento, TutorDuplicidadeDescarte, TutorOperacao):
            model.__table__.create(self.engine)
        self.sessions = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)
        self.db = self.sessions()
        self.user = SimpleNamespace(id=7, nome="Equipe de teste", tem_papel=lambda role: role == "admin")

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        self.tmp.cleanup()

    def criar(self, nome="Cristiane", **kwargs):
        return tutores.criar_tutor(tutores.TutorCreate(nome=nome, **kwargs), self.db, self.user)

    def confirmar(self, tutor_id):
        dado = tutores.obter_tutor(tutor_id, self.db, self.user)
        return tutores.confirmar_identificacao_tutor(tutor_id, tutores.IdentificacaoConfirmarPayload(
            metodo="Conferencia no atendimento", evidencia="Nome e contato conferidos presencialmente", versao=dado["versao"]), self.db, self.user)

    def test_apenas_primeiro_nome_e_pet_sem_contato_e_sem_dados_clinicos_inventados(self):
        result = pacientes.criar_paciente(pacientes.PacienteCreate(nome="Pingo", tutor="Cristiane"), self.db, self.user)
        self.assertEqual(result["tutor"], "Cristiane")
        self.assertTrue(result["tutor_identificacao_pendente"])
        self.assertFalse(result["especie"])
        self.assertFalse(result["sexo"])
        self.assertEqual(self.db.query(TutorIdentificacaoEvento).count(), 0)

    def test_idade_e_nascimento_independentes_persistem_sem_reancorar_outros_campos(self):
        result = pacientes.criar_paciente(pacientes.PacienteCreate(
            nome="QA idade", tutor="QA tutor", idade_informada="12 anos", idade_fonte="idade",
            idade_referencia="2025-01-31", data_nascimento="2020-05-03", observacoes="Nota preservada"), self.db, self.user)
        patient_id = result["id"]
        row = self.db.get(Paciente, patient_id)
        self.assertEqual(row.nascimento, "2020-05-03")
        self.assertEqual(row.idade_fonte, "idade")
        self.assertEqual(row.observacoes, "Idade: 12 anos\nNota preservada")
        anchor = row.idade_referencia
        updated = pacientes.atualizar_paciente(patient_id, pacientes.PacienteUpdate(peso_kg=4.2), self.db, self.user)
        self.assertEqual(updated["idade_referencia"], "2025-01-31")
        self.assertEqual(row.idade_referencia, anchor)
        updated = pacientes.atualizar_paciente(patient_id, pacientes.PacienteUpdate(
            idade_fonte="nascimento", data_nascimento="2014"), self.db, self.user)
        self.assertIn("estimada pelo ano", updated["idade"])
        self.assertEqual(updated["idade_informada"], "12 anos")
        self.assertEqual(updated["idade_referencia"], "2025-01-31")
        read = pacientes.obter_paciente(patient_id, self.db, self.user)
        self.assertEqual(read["idade"], updated["idade"])

    def test_booleano_legado_nao_confirma_identidade_no_cadastro_ou_edicao(self):
        result = self.criar(identificacao_pendente=False)
        self.assertTrue(result["identificacao_pendente"])
        updated = tutores.atualizar_tutor(result["id"], tutores.TutorUpdate(identificacao_pendente=False), self.db, self.user)
        self.assertTrue(updated["identificacao_pendente"])
        pet = pacientes.criar_paciente(pacientes.PacienteCreate(nome="Pingo", tutor_id=result["id"], tutor_identificacao_pendente=False), self.db, self.user)
        self.assertTrue(pet["tutor_identificacao_pendente"])

    def test_confirmacao_tem_autor_data_metodo_e_evidencia(self):
        tutor = self.criar()
        result = self.confirmar(tutor["id"])
        self.assertFalse(result["identificacao_pendente"])
        self.assertEqual(result["identificacao_confirmacao"]["usuario_nome"], self.user.nome)
        self.assertTrue(result["identificacao_confirmacao"]["created_at"])
        self.assertEqual(result["identificacao_confirmacao"]["metodo"], "Conferencia no atendimento")
        self.assertNotEqual(tutor["versao"], result["versao"])
        history = tutores.historico_identificacao_tutor(tutor["id"], self.db, self.user)["items"]
        self.assertEqual(history[0]["acao"], "confirmar")

    def test_confirmacao_obsoleta_recusada_apos_edicao(self):
        tutor = self.criar()
        tutores.atualizar_tutor(tutor["id"], tutores.TutorUpdate(nome="Cristiane Silva"), self.db, self.user)
        with self.assertRaises(HTTPException) as ctx:
            tutores.confirmar_identificacao_tutor(tutor["id"], tutores.IdentificacaoConfirmarPayload(
                metodo="Atendimento", evidencia="Nome conferido pessoalmente", versao=tutor["versao"]), self.db, self.user)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(self.db.query(TutorIdentificacaoEvento).count(), 0)

    def test_nome_cpf_e_contato_reabrem_confirmacao_com_historico(self):
        for campos in ({"nome": "Cristiane Silva"}, {"cpf": "52998224725"}, {"whatsapp": "85999990000"}):
            with self.subTest(campos=campos):
                tutor = self.criar()
                self.confirmar(tutor["id"])
                result = tutores.atualizar_tutor(tutor["id"], tutores.TutorUpdate(**campos), self.db, self.user)
                self.assertTrue(result["identificacao_pendente"])
                self.assertIsNone(result["identificacao_confirmacao"])
                history = tutores.historico_identificacao_tutor(tutor["id"], self.db, self.user)["items"]
                self.assertEqual([r["acao"] for r in history], ["invalidar", "confirmar"])
                self.assertEqual(history[0]["usuario_id"], self.user.id)

    def test_formatacao_equivalente_nao_invalida_confirmacao(self):
        tutor = self.criar(nome="Cristiane Silva", cpf="529.982.247-25", telefone="(85) 99999-0000")
        self.confirmar(tutor["id"])
        result = tutores.atualizar_tutor(tutor["id"], tutores.TutorUpdate(nome="CRISTIANE SILVA", cpf="52998224725", telefone="+55 85 99999-0000"), self.db, self.user)
        self.assertFalse(result["identificacao_pendente"])

    def test_edicao_de_identidade_pelo_paciente_tambem_reabre(self):
        tutor = self.criar()
        pet = pacientes.criar_paciente(pacientes.PacienteCreate(nome="Pingo", tutor_id=tutor["id"]), self.db, self.user)
        self.confirmar(tutor["id"])
        pacientes.atualizar_paciente(pet["id"], pacientes.PacienteUpdate(tutor="Cristiane Silva", tutor_identificacao_pendente=False), self.db, self.user)
        self.assertTrue(self.db.get(Tutor, tutor["id"]).identificacao_pendente)
        history = tutores.historico_identificacao_tutor(tutor["id"], self.db, self.user)["items"]
        self.assertEqual(history[0]["acao"], "invalidar")

    def test_nome_isolado_nao_sugere_duplicidade_e_contato_exibe_ressalva(self):
        a = self.criar()
        b = self.criar()
        self.assertEqual(tutores.duplicidades_tutor(a["id"], self.db, self.user)["items"], [])
        for row in (a, b):
            tutores.atualizar_tutor(row["id"], tutores.TutorUpdate(telefone="85999990000"), self.db, self.user)
        items = tutores.duplicidades_tutor(a["id"], self.db, self.user)["items"]
        self.assertEqual([r["id"] for r in items], [b["id"]])
        self.assertIn("compartilhado", items[0]["motivos"][0])
        self.assertEqual(self.db.query(Tutor).count(), 2)

    def test_descarte_resiste_repeticao_mas_e_reavaliado_apos_mudar_evidencia(self):
        a, b = self.criar(telefone="85999990000"), self.criar(whatsapp="+55 (85) 99999-0000")
        tutores.descartar_duplicidade_tutor(a["id"], b["id"], tutores.MotivoIdentificacaoPayload(motivo="Familia compartilha o telefone"), self.db, self.user)
        self.assertEqual(tutores.duplicidades_tutor(a["id"], self.db, self.user)["items"], [])
        self.assertEqual(tutores.duplicidades_tutor(b["id"], self.db, self.user)["items"], [])
        tutores.atualizar_tutor(b["id"], tutores.TutorUpdate(cpf="52998224725"), self.db, self.user)
        self.assertEqual(len(tutores.duplicidades_tutor(a["id"], self.db, self.user)["items"]), 1)

    def test_contatos_alternativos_preservam_principal_e_ajudam_busca(self):
        tutor = self.criar(telefone="85911110000")
        payload = tutores.ContatoTutorPayload(tipo="whatsapp", valor="+55 (85) 99999-0000", rotulo="Celular pessoal")
        tutores.adicionar_contato_tutor(tutor["id"], payload, self.db, self.user)
        tutores.adicionar_contato_tutor(tutor["id"], payload, self.db, self.user)
        self.assertEqual(self.db.query(TutorContato).count(), 1)
        self.assertEqual(self.db.get(Tutor, tutor["id"]).telefone, "85911110000")
        self.assertEqual(self.db.get(Tutor, tutor["id"]).whatsapp, "85911110000")
        items = tutores.listar_tutores(busca="85999990000", db=self.db, current_user=self.user)["items"]
        self.assertEqual([r["id"] for r in items], [tutor["id"]])

    def test_origem_alternativa_filtra_sem_substituir_original(self):
        tutor = self.criar(origem_cadastro="Clinica Alfa")
        tutores.adicionar_origem_tutor(tutor["id"], tutores.OrigemTutorPayload(descricao="Clinica Beta"), self.db, self.user)
        self.assertEqual(self.db.get(Tutor, tutor["id"]).origem_cadastro, "Clinica Alfa")
        result = tutores.listar_tutores(origem="beta", db=self.db, current_user=self.user)
        self.assertEqual([r["id"] for r in result["items"]], [tutor["id"]])

    def test_busca_id_cpf_e_telefone_normalizados(self):
        a, b = self.criar(cpf="529.982.247-25", telefone="(85) 99999-0000"), self.criar()
        for term in (f'#{a["id"]}', "52998224725", "85999990000", "+55 (85) 99999-0000"):
            result = tutores.listar_tutores(busca=term, db=self.db, current_user=self.user)
            self.assertEqual([r["id"] for r in result["items"]], [a["id"]], term)

    def test_filtro_pendentes_e_ordem_proximo_atendimento(self):
        a, b, c = self.criar(nome="A"), self.criar(nome="B"), self.criar(nome="C")
        now = datetime.now(timezone.utc)
        self.db.add_all([Agendamento(tutor_id=a["id"], inicio=now + timedelta(days=2), status="Agendado"),
                         Agendamento(tutor_id=b["id"], inicio=now + timedelta(days=1), status="Agendado"),
                         Agendamento(tutor_id=c["id"], inicio=now + timedelta(hours=1), status="Cancelado")])
        self.db.commit()
        self.confirmar(c["id"])
        result = tutores.listar_tutores(pendentes=True, ordenar="proximo_atendimento", db=self.db, current_user=self.user)
        self.assertEqual([r["id"] for r in result["items"]], [b["id"], a["id"]])
        self.assertTrue(result["items"][0]["proximo_atendimento"])

    def test_idempotencia_criacao_mesma_chave_nao_duplica_e_mudanca_e_recusada(self):
        key = "cadastro-operacao-01"
        a = self.criar(chave_operacao=key)
        b = self.criar(chave_operacao=key)
        self.assertEqual(a, b)
        self.assertEqual(self.db.query(Tutor).count(), 1)
        with self.assertRaises(HTTPException) as ctx:
            self.criar(nome="Outra pessoa", chave_operacao=key)
        self.assertEqual(ctx.exception.status_code, 409)

    def test_idempotencia_paciente_inclui_tutor_inline(self):
        payload = pacientes.PacienteCreate(nome="Pingo", tutor="Cristiane", chave_operacao="pet-operacao-01")
        a = pacientes.criar_paciente(payload, self.db, self.user)
        b = pacientes.criar_paciente(payload, self.db, self.user)
        self.assertEqual(a, b)
        self.assertEqual(self.db.query(Tutor).count(), 1)
        self.assertEqual(self.db.query(Paciente).count(), 1)

    def test_falha_no_commit_reverte_tutor_e_reserva_idempotente(self):
        with patch.object(self.db, "commit", side_effect=RuntimeError("falha simulada")):
            with self.assertRaises(RuntimeError):
                self.criar(chave_operacao="cadastro-falha-01")
        self.assertEqual(self.db.query(Tutor).count(), 0)
        self.assertEqual(self.db.query(TutorOperacao).count(), 0)

    def test_duas_requisicoes_concorrentes_com_mesma_chave_criam_so_uma_pessoa(self):
        barrier = threading.Barrier(2)
        def criar():
            with self.sessions() as session:
                barrier.wait(timeout=5)
                return tutores.criar_tutor(tutores.TutorCreate(nome="Cristiane", chave_operacao="mesma-chave-concorrente"), session, self.user)
        with ThreadPoolExecutor(max_workers=2) as pool:
            a, b = list(pool.map(lambda _: criar(), range(2)))
        self.assertEqual(a["id"], b["id"])
        self.assertEqual(self.db.query(Tutor).count(), 1)

    def test_preservacao_antes_de_mesclar_e_aditiva_e_repetivel(self):
        tutor = self.criar(telefone="85911110000", email="teste@example.invalid", origem_cadastro="Clinica Alfa")
        row = self.db.get(Tutor, tutor["id"])
        first = rotina.preservar_contatos_originais(self.db, row)
        second = rotina.preservar_contatos_originais(self.db, row)
        self.assertEqual(len(first["tutores_contatos"]), 3)
        self.assertEqual(len(first["tutores_origens"]), 1)
        self.assertEqual(second, {"tutores_contatos": [], "tutores_origens": []})
        self.assertEqual(row.telefone, "85911110000")

    def test_historico_exclui_pessoa_separada_por_reversao(self):
        TutorMesclagemReversao.__table__.create(self.engine)
        a, b = self.criar(nome="Pessoa A"), self.criar(nome="Pessoa B")
        self.confirmar(a["id"])
        self.confirmar(b["id"])
        merge = TutorMesclagem(principal_id=a["id"], secundario_id=b["id"], usuario_id=self.user.id, motivo="Confirmacao incorreta", detalhes_json="{}")
        self.db.add(merge)
        self.db.commit()
        self.assertEqual(len(rotina.historico_identificacao(self.db, a["id"])), 2)
        self.db.add(TutorMesclagemReversao(mesclagem_id=merge.id, usuario_id=self.user.id, motivo="Pessoas diferentes", detalhes_json="{}"))
        self.db.commit()
        self.assertEqual([r["cadastro_id"] for r in rotina.historico_identificacao(self.db, a["id"])], [a["id"]])


class MigracaoRotinaTest(unittest.TestCase):
    def test_migracao_aditiva_idempotente_preserva_tutor_e_fecha_historicos(self):
        module_path = BACKEND_DIR / "migrations/versions/20261027_103_tutores_rotina_agil.py"
        spec = importlib.util.spec_from_file_location("migracao_tutores_rotina", module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        engine = create_engine("sqlite://")
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE tutores (id INTEGER PRIMARY KEY, nome TEXT)"))
            conn.execute(text("INSERT INTO tutores (id,nome) VALUES (1,'Cristiane')"))
            module.upgrade(conn, "sqlite")
            module.upgrade(conn, "sqlite")
            self.assertEqual(conn.execute(text("SELECT nome FROM tutores WHERE id=1")).scalar(), "Cristiane")
            self.assertIn("tutores_operacoes", inspect(conn).get_table_names())
            self.assertIn("cadastro_id", {c["name"] for c in inspect(conn).get_columns("tutores_identificacao_eventos")})
            self.assertNotIn("tutor_id", {c["name"] for c in inspect(conn).get_columns("tutores_identificacao_eventos")})
        engine.dispose()


@unittest.skipUnless(os.environ.get("TUTORES_TEST_POSTGRES_URL"), "PostgreSQL temporario local nao configurado")
class TutoresRotinaAgilPostgresTest(TutoresRotinaAgilTest):
    def setUp(self):
        self.base_engine = create_engine(os.environ["TUTORES_TEST_POSTGRES_URL"])
        assert self.base_engine.url.database == "fortcordis_tutores_test"
        assert str(self.base_engine.url.query.get("host", "")).startswith("/tmp/fortcordis-tutores-pg.")
        self.schema = "teste_rotina_" + uuid.uuid4().hex
        with self.base_engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        self.engine = create_engine(os.environ["TUTORES_TEST_POSTGRES_URL"], connect_args={"options": f"-csearch_path={self.schema}"})
        for model in (Tutor, Paciente, Agendamento, TutorMesclagem, TutorContato, TutorOrigem,
                      TutorIdentificacaoEvento, TutorDuplicidadeDescarte, TutorOperacao):
            model.__table__.create(self.engine)
        self.sessions = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)
        self.db = self.sessions()
        self.user = SimpleNamespace(id=7, nome="Equipe de teste", tem_papel=lambda role: role == "admin")

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        with self.base_engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))
        self.base_engine.dispose()

    def test_migracao_postgres_repetivel_protege_todos_complementos_e_historicos(self):
        spec = importlib.util.spec_from_file_location("migracao_rotina_pg", BACKEND_DIR / "migrations/versions/20261027_103_tutores_rotina_agil.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        tutor = self.criar()
        self.db.rollback()
        with self.engine.begin() as conn:
            module.upgrade(conn, "postgresql")
            module.upgrade(conn, "postgresql")
            for model in (TutorIdentificacaoEvento, TutorContato, TutorOrigem, TutorDuplicidadeDescarte, TutorOperacao):
                self.assertTrue(conn.execute(text("SELECT relrowsecurity FROM pg_class WHERE oid=CAST(:name AS regclass)"), {"name": model.__tablename__}).scalar())
            self.assertEqual(conn.execute(text("SELECT nome FROM tutores WHERE id=:id"), {"id": tutor["id"]}).scalar(), "Cristiane")
