import importlib.util
import os
import sys
import tempfile
import unittest
import uuid
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "tutores-identidade-local-test-secret-1234567890")

from app.api.v1.endpoints import pacientes, tutores
from app.core.security import get_current_user
from app.db.database import get_db
from app.models.agendamento import Agendamento
from app.models.atendimento_clinico import AtendimentoClinico
from app.models.financeiro import CreditoFinanceiro
from app.models.paciente import Paciente
from app.models.tutor import Tutor
from app.models.tutor_mesclagem import TutorMesclagem
from app.models.tutor_rotina import TutorIdentificacaoEvento
from app.services.tutor_identidade_service import exigir_tutor_utilizavel
from app.services import tutor_mesclagem_service


class TutoresIdentidadeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{self.tmp.name}/identidade.db", connect_args={"check_same_thread": False})
        for model in (Tutor, Paciente, Agendamento, AtendimentoClinico, CreditoFinanceiro, TutorMesclagem):
            model.__table__.create(self.engine)
        self.db = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)()
        self.user = SimpleNamespace(id=7, nome="Administrador de teste", tem_papel=lambda role: role == "admin")

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        self.tmp.cleanup()

    def tutor(self, nome="Cristiane", **kwargs):
        tutor = Tutor(nome=nome, nome_key=tutores._gerar_nome_key(nome), ativo=1, **kwargs)
        self.db.add(tutor)
        self.db.commit()
        return tutor

    def previa(self, a, b):
        return tutores.previa_mesclagem(tutores.MesclagemPreviaPayload(principal_id=a.id, secundario_id=b.id), self.db, self.user)

    def payload(self, a, b, **overrides):
        previa = self.previa(a, b)
        dados = {"principal_id": a.id, "secundario_id": b.id, "token_previa": previa["token_previa"],
                 "escolhas": {campo: "principal" for campo in previa["conflitos"]},
                 "confirmar": True, "motivo": "Identidade confirmada pela clinica informante"}
        return tutores.MesclagemPayload(**{**dados, **overrides})

    def test_post_cria_homonimos_separados_sem_modificar_contatos_existentes(self):
        a = self.tutor(telefone="85911111111")
        resposta = tutores.criar_tutor(tutores.TutorCreate(nome="CRISTIANE", telefone="85922222222"), self.db, self.user)
        self.assertNotEqual(resposta["id"], a.id)
        self.assertTrue(resposta["identificacao_pendente"])
        self.db.refresh(a)
        self.assertEqual(a.telefone, "85911111111")
        self.assertEqual(self.db.query(Tutor).count(), 2)

    def test_paciente_sem_tutor_id_cria_outra_pessoa_mesmo_com_nome_igual(self):
        original = self.tutor(telefone="85911111111")
        resultado = pacientes.criar_paciente(pacientes.PacienteCreate(nome="Pingo", tutor="Cristiane", tutor_telefone="85922222222"), self.db, self.user)
        self.assertNotEqual(resultado["tutor_id"], original.id)
        self.db.refresh(original)
        self.assertEqual(original.telefone, "85911111111")

    def test_pendente_persiste_e_so_muda_com_decisao_explicita(self):
        TutorIdentificacaoEvento.__table__.create(self.engine, checkfirst=True)
        resultado = tutores.criar_tutor(tutores.TutorCreate(nome="Cristiane Silva", cpf="11111111111", origem_cadastro="Clinica Alfa"), self.db, self.user)
        self.assertTrue(resultado["identificacao_pendente"])
        tutores.atualizar_tutor(resultado["id"], tutores.TutorUpdate(identificacao_pendente=False), self.db, self.user)
        salvo = tutores.obter_tutor(resultado["id"], self.db, self.user)
        self.assertTrue(salvo["identificacao_pendente"])
        tutores.confirmar_identificacao_tutor(resultado["id"], tutores.IdentificacaoConfirmarPayload(
            metodo="Conferencia presencial", evidencia="Nome conferido no atendimento", versao=salvo["versao"]), self.db, self.user)
        salvo = tutores.obter_tutor(resultado["id"], self.db, self.user)
        self.assertFalse(salvo["identificacao_pendente"])
        self.assertEqual(salvo["origem_cadastro"], "Clinica Alfa")

    def test_id_invalido_nunca_faz_fallback_para_nome(self):
        self.tutor()
        with self.assertRaises(HTTPException) as ctx:
            pacientes.criar_paciente(pacientes.PacienteCreate(nome="Pingo", tutor="Cristiane", tutor_id=99999), self.db, self.user)
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(self.db.query(Paciente).count(), 0)

    def test_previa_nao_muda_dados_e_mesclagem_transfere_todos_vinculos_sem_fundir_pets(self):
        a = self.tutor(telefone="85911111111", endereco="Rua A", cidade="Fortaleza", latitude=-3.7, longitude=-38.5)
        b = self.tutor(telefone="85922222222", endereco="Rua B", cidade="Caucaia", latitude=-3.8, longitude=-38.6)
        pet_a = Paciente(nome="Pingo", nome_key="pingo", tutor_id=a.id, ativo=1)
        pet_b = Paciente(nome="Pingo", nome_key="pingo", tutor_id=b.id, ativo=1)
        self.db.add_all([pet_a, pet_b]); self.db.flush()
        ag = Agendamento(tutor_id=b.id, paciente_id=pet_b.id, inicio=datetime(2026, 10, 29, 10), tutor="Cristiane originalmente informada")
        atendimento = AtendimentoClinico(tutor_id=b.id, paciente_id=pet_b.id, veterinario_id=1, status="Concluido", data_atendimento=datetime(2026, 10, 28))
        credito = CreditoFinanceiro(tutor_id=b.id, paciente_id=pet_b.id, tipo_destino="cliente", valor=75, status="Ativo")
        self.db.add_all([ag, atendimento, credito]); self.db.commit()
        previa = self.previa(a, b)
        self.assertTrue(previa["avisos"])
        self.assertEqual(previa["vinculos"]["creditos_financeiros"]["secundario"], 1)
        self.assertEqual(pet_b.tutor_id, b.id)
        self.assertEqual(self.db.query(TutorMesclagem).count(), 0)
        payload = self.payload(a, b, escolhas={"telefone": "secundario", "endereco": "secundario"})
        resultado = tutores.confirmar_mesclagem(payload, self.db, self.user)
        self.assertEqual(resultado["principal_id"], a.id)
        for registro in (pet_b, ag, atendimento, credito):
            self.db.refresh(registro)
            self.assertEqual(registro.tutor_id, a.id)
        self.db.refresh(a); self.db.refresh(b)
        self.assertEqual(a.telefone, "85922222222")
        self.assertEqual((a.endereco, a.latitude, a.longitude), ("Rua B", -3.8, -38.6))
        self.assertEqual(b.mesclado_em_id, a.id)
        self.assertEqual(b.ativo, 0)
        self.assertEqual(self.db.query(Paciente).count(), 2)
        self.assertEqual(ag.tutor, "Cristiane originalmente informada")
        self.assertEqual(credito.valor, 75)
        historico = tutores.historico_mesclagens(a.id, self.db, self.user)["items"][0]
        self.assertEqual(historico["usuario_id"], self.user.id)
        self.assertEqual(historico["detalhes"]["antes"]["principal"]["telefone"], "85911111111")
        self.assertEqual(historico["detalhes"]["vinculos_movidos"]["pacientes"], [pet_b.id])
        with self.assertRaises(HTTPException):
            exigir_tutor_utilizavel(self.db, b.id)
        with self.assertRaises(HTTPException):
            tutores.reativar_tutor(b.id, tutores.ReativacaoPayload(confirmar=True), self.db, self.user)

    def test_confirmacao_obrigatoria_conflitos_e_cpfs_divergentes(self):
        a = self.tutor(telefone="1111")
        b = self.tutor(telefone="2222")
        for overrides in ({"confirmar": False}, {"escolhas": {}}):
            with self.assertRaises(HTTPException) as ctx:
                tutores.confirmar_mesclagem(self.payload(a, b, **overrides), self.db, self.user)
            self.assertEqual(ctx.exception.status_code, 422)
        a.cpf = "111.111.111-11"; b.cpf = "22222222222"; self.db.commit()
        with self.assertRaises(HTTPException) as ctx:
            tutores.confirmar_mesclagem(self.payload(a, b), self.db, self.user)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(self.db.query(TutorMesclagem).count(), 0)

    def test_previa_antiga_rejeitada_se_cadastro_ou_vinculo_mudar(self):
        a, b = self.tutor(), self.tutor()
        payload = self.payload(a, b)
        self.db.add(Paciente(nome="Outro animal", tutor_id=b.id, ativo=1)); self.db.commit()
        with self.assertRaises(HTTPException) as ctx:
            tutores.confirmar_mesclagem(payload, self.db, self.user)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(self.db.query(TutorMesclagem).count(), 0)
        self.db.refresh(b); self.assertEqual(b.ativo, 1)

    def test_erro_na_gravacao_do_historico_reverte_toda_mesclagem(self):
        a, b = self.tutor(), self.tutor()
        pet = Paciente(nome="Pingo", tutor_id=b.id, ativo=1); self.db.add(pet); self.db.commit()
        payload = self.payload(a, b)
        with patch.object(self.db, "commit", side_effect=RuntimeError("falha simulada")):
            with self.assertRaises(RuntimeError):
                tutores.confirmar_mesclagem(payload, self.db, self.user)
        self.db.refresh(pet); self.db.refresh(b)
        self.assertEqual(pet.tutor_id, b.id)
        self.assertIsNone(b.mesclado_em_id)
        self.assertEqual(b.ativo, 1)

    def test_endpoints_de_mesclagem_exigem_admin_inclusive_historico(self):
        app = FastAPI(); app.include_router(tutores.router, prefix="/tutores")
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(tem_papel=lambda _: False)
        client = TestClient(app)
        for path in ("/tutores/mesclagens/previa", "/tutores/mesclagens"):
            self.assertEqual(client.post(path, json={}).status_code, 403)
        self.assertEqual(client.get("/tutores/1/mesclagens").status_code, 403)

    def test_mesclagens_sucessivas_preservam_historico_completo_e_redirecionamento(self):
        a, b, c = self.tutor(), self.tutor(), self.tutor()
        tutores.confirmar_mesclagem(self.payload(a, b), self.db, self.user)
        tutores.confirmar_mesclagem(self.payload(c, a), self.db, self.user)
        historico = tutores.historico_mesclagens(c.id, self.db, self.user)["items"]
        self.assertEqual(len(historico), 2)
        with self.assertRaises(HTTPException) as ctx:
            exigir_tutor_utilizavel(self.db, b.id)
        self.assertEqual(ctx.exception.detail["tutor_principal_id"], c.id)

    def test_laudo_com_paciente_conhecido_nao_recria_tutor_pelo_nome(self):
        from app.api.v1.endpoints.laudos import _resolver_ou_criar_paciente
        a = self.tutor()
        pet = Paciente(nome="Pingo", nome_key="pingo", tutor_id=a.id, especie="Canina", ativo=1)
        self.db.add(pet); self.db.commit()
        resultado = _resolver_ou_criar_paciente({"id": pet.id, "nome": "Pingo", "tutor": "Cristiane Silva"}, self.db)
        self.assertEqual(resultado, pet.id)
        self.assertEqual(self.db.query(Tutor).count(), 1)
        self.assertEqual(pet.tutor_id, a.id)
        self.assertEqual(a.nome, "Cristiane")

    def test_laudo_novo_nao_reutiliza_homonimo_e_assistente_exige_id_para_escrita(self):
        from app.api.v1.endpoints.laudos import _resolver_ou_criar_paciente
        from app.services.assistente_ia_tools import _resolve_named_record
        a = self.tutor()
        pet_id = _resolver_ou_criar_paciente({"nome": "Pingo", "tutor": "Cristiane"}, self.db)
        self.assertNotEqual(self.db.get(Paciente, pet_id).tutor_id, a.id)
        found, error = _resolve_named_record(self.db, Tutor, "Cristiane", entity_label="tutor", exigir_id=True)
        self.assertIsNone(found)
        self.assertFalse(error["ok"])
        found, error = _resolve_named_record(self.db, Tutor, f"#{a.id}", entity_label="tutor", exigir_id=True)
        self.assertEqual(found.id, a.id)
        self.assertIsNone(error)


class TutoresIdentidadeMigrationTest(unittest.TestCase):
    def test_legado_unique_vira_busca_e_preserva_dados_indices_e_idempotencia(self):
        path = BACKEND_DIR / "migrations/versions/20261027_102_tutores_identidade_mesclagem.py"
        spec = importlib.util.spec_from_file_location("migration_tutores_identidade", path)
        migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
        for unicidade in ("nome_key TEXT UNIQUE", "nome_key TEXT"):
            with self.subTest(unicidade=unicidade), tempfile.TemporaryDirectory() as tmp:
                engine = create_engine(f"sqlite:///{tmp}/migration.db")
                with engine.begin() as conn:
                    conn.execute(text(f"CREATE TABLE tutores (id INTEGER PRIMARY KEY, nome TEXT, {unicidade}, ativo INTEGER, email TEXT UNIQUE)"))
                    conn.execute(text("CREATE INDEX ix_tutor_nome_preservado ON tutores(nome)"))
                    if "UNIQUE" not in unicidade:
                        conn.execute(text("CREATE UNIQUE INDEX ux_tutores_nome_key ON tutores(nome_key)"))
                    conn.execute(text("INSERT INTO tutores VALUES (7, 'Cristiane', 'cristiane', 1, 'a@example.com')"))
                    migration.upgrade(conn, "sqlite"); migration.upgrade(conn, "sqlite")
                    conn.execute(text("INSERT INTO tutores (nome, nome_key, email) VALUES ('Cristiane', 'cristiane', 'b@example.com')"))
                    self.assertEqual(conn.execute(text("SELECT COUNT(*) FROM tutores")).scalar(), 2)
                    self.assertEqual(conn.execute(text("SELECT nome FROM tutores WHERE id=7")).scalar(), "Cristiane")
                    self.assertTrue(conn.execute(text("SELECT identificacao_pendente FROM tutores WHERE id=7")).scalar())
                indexes = inspect(engine).get_indexes("tutores")
                self.assertIn("ix_tutor_nome_preservado", {i["name"] for i in indexes})
                self.assertIn("tutores_mesclagens", inspect(engine).get_table_names())
                self.assertTrue(any(c["column_names"] == ["email"] for c in inspect(engine).get_unique_constraints("tutores")))
                engine.dispose()


@unittest.skipUnless(os.environ.get("TUTORES_TEST_POSTGRES_URL"), "PostgreSQL temporario local nao configurado")
class TutoresIdentidadePostgresTest(TutoresIdentidadeTest):
    """Repete o contrato em PostgreSQL real, apenas em instancia descartavel."""
    def setUp(self):
        self.base_engine = create_engine(os.environ["TUTORES_TEST_POSTGRES_URL"])
        assert self.base_engine.url.database == "fortcordis_tutores_test"
        assert str(self.base_engine.url.query.get("host", "")).startswith("/tmp/fortcordis-tutores-pg.")
        self.schema = "teste_" + uuid.uuid4().hex
        with self.base_engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        self.engine = create_engine(os.environ["TUTORES_TEST_POSTGRES_URL"], connect_args={"options": f"-csearch_path={self.schema}"})
        for model in (Tutor, Paciente, Agendamento, AtendimentoClinico, CreditoFinanceiro, TutorMesclagem):
            model.__table__.create(self.engine)
        self.db = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)()
        self.user = SimpleNamespace(id=7, nome="Administrador de teste", tem_papel=lambda role: role == "admin")

    def tearDown(self):
        self.db.close(); self.engine.dispose()
        with self.base_engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))
        self.base_engine.dispose()

    def test_migracao_postgres_remove_unicidade_preserva_registro_e_fecha_historico(self):
        spec = importlib.util.spec_from_file_location("migration_tutores_pg", BACKEND_DIR / "migrations/versions/20261027_102_tutores_identidade_mesclagem.py")
        migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
        with self.engine.begin() as conn:
            conn.execute(text("ALTER TABLE tutores ADD CONSTRAINT uq_legado_nome_key UNIQUE (nome_key)"))
            conn.execute(text("INSERT INTO tutores (id,nome,nome_key,ativo) VALUES (100,'Cristiane','cristiane',1)"))
            for field in ("identificacao_pendente", "origem_cadastro", "identificacao_observacoes", "mesclado_em_id"):
                conn.execute(text(f"ALTER TABLE tutores DROP COLUMN {field}"))
            migration.upgrade(conn, "postgresql"); migration.upgrade(conn, "postgresql")
            conn.execute(text("INSERT INTO tutores (nome,nome_key,ativo) VALUES ('Cristiane','cristiane',1)"))
            self.assertEqual(conn.execute(text("SELECT COUNT(*) FROM tutores")).scalar(), 2)
            self.assertEqual(conn.execute(text("SELECT nome FROM tutores WHERE id=100")).scalar(), "Cristiane")
            self.assertTrue(conn.execute(text("SELECT relrowsecurity FROM pg_class WHERE oid='tutores_mesclagens'::regclass")).scalar())

    def test_escrita_concorrente_nao_reintroduz_tutor_ja_mesclado(self):
        a, b = self.tutor(), self.tutor()
        payload = self.payload(a, b)
        locked, writer_started = threading.Event(), threading.Event()
        preparar_original = tutor_mesclagem_service._preparar

        def preparar_com_barreira(*args):
            locked.set()
            if not writer_started.wait(5):
                raise AssertionError("Escrita concorrente nao iniciou")
            return preparar_original(*args)

        def merge():
            with sessionmaker(bind=self.engine, autoflush=False)() as db:
                return tutores.confirmar_mesclagem(payload, db, self.user)

        def writer():
            if not locked.wait(5):
                raise AssertionError("Mesclagem nao iniciou")
            with sessionmaker(bind=self.engine, autoflush=False)() as db:
                writer_started.set()
                try:
                    return pacientes.criar_paciente(pacientes.PacienteCreate(nome="Pingo", tutor_id=b.id), db, self.user)
                except HTTPException as exc:
                    return exc.status_code

        with patch.object(tutor_mesclagem_service, "_preparar", side_effect=preparar_com_barreira), ThreadPoolExecutor(max_workers=2) as pool:
            merge_future = pool.submit(merge)
            write_future = pool.submit(writer)
            self.assertEqual(merge_future.result(timeout=15)["principal_id"], a.id)
            self.assertEqual(write_future.result(timeout=15), 409)
        self.db.expire_all()
        self.assertEqual(self.db.query(Paciente).filter(Paciente.tutor_id == b.id).count(), 0)

    def test_escrita_iniciada_antes_da_mesclagem_invalida_previa_sem_vinculo_orfao(self):
        a, b = self.tutor(), self.tutor()
        payload = self.payload(a, b)
        selected, release_writer, merge_started = threading.Event(), threading.Event(), threading.Event()
        resolver = pacientes._obter_ou_criar_tutor

        def resolver_com_barreira(*args, **kwargs):
            result = resolver(*args, **kwargs)
            selected.set()
            if not release_writer.wait(5):
                raise AssertionError("Escrita nao foi liberada")
            return result

        def writer():
            with sessionmaker(bind=self.engine, autoflush=False)() as db:
                return pacientes.criar_paciente(pacientes.PacienteCreate(nome="Pingo", tutor_id=b.id), db, self.user)

        def merge():
            if not selected.wait(5):
                raise AssertionError("Selecao de tutor nao iniciou")
            with sessionmaker(bind=self.engine, autoflush=False)() as db:
                merge_started.set()
                try:
                    return tutores.confirmar_mesclagem(payload, db, self.user)
                except HTTPException as exc:
                    return exc.status_code

        with patch.object(pacientes, "_obter_ou_criar_tutor", side_effect=resolver_com_barreira), ThreadPoolExecutor(max_workers=2) as pool:
            write_future = pool.submit(writer)
            merge_future = pool.submit(merge)
            self.assertTrue(merge_started.wait(5))
            release_writer.set()
            self.assertEqual(write_future.result(timeout=15)["tutor_id"], b.id)
            self.assertEqual(merge_future.result(timeout=15), 409)
        self.db.expire_all()
        self.assertIsNone(self.db.get(Tutor, b.id).mesclado_em_id)
        self.assertEqual(self.db.query(TutorMesclagem).count(), 0)
        self.assertEqual(self.db.query(Paciente).filter(Paciente.tutor_id == b.id).count(), 1)
