"""Correcao de identidade exercitada somente em dados sinteticos e SQLite isolado."""
import importlib.util
import json
import os
import sys
import tempfile
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "tutor-mesclagem-reversao-local-test-secret-1234567890")

from app.api.v1.endpoints import tutores, tutor_mesclagem_reversao
from app.core.security import get_current_user
from app.db.database import get_db
from app.models.agendamento import Agendamento
from app.models.atendimento_clinico import AtendimentoClinico
from app.models.financeiro import CreditoFinanceiro
from app.models.paciente import Paciente
from app.models.tutor import Tutor
from app.models.tutor_mesclagem import TutorMesclagem
from app.models.tutor_mesclagem_reversao import TutorMesclagemReversao
from app.models.tutor_rotina import (
    TutorContato, TutorDuplicidadeDescarte, TutorIdentificacaoEvento, TutorOperacao, TutorOrigem,
)
from app.services import tutor_mesclagem_reversao_service as reversao
from app.services import tutor_mesclagem_service as mesclagem
from app.services import tutor_rotina_service as rotina


class TutorMesclagemReversaoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{self.tmp.name}/reversao.db", connect_args={"check_same_thread": False})
        for model in (Tutor, Paciente, Agendamento, AtendimentoClinico, CreditoFinanceiro, TutorMesclagem,
                      TutorMesclagemReversao, TutorContato, TutorOrigem, TutorIdentificacaoEvento,
                      TutorDuplicidadeDescarte, TutorOperacao):
            model.__table__.create(self.engine)
        self.db = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)()
        self.user = SimpleNamespace(id=7, nome="Administrador sintetico", tem_papel=lambda role: role == "admin")

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        self.tmp.cleanup()

    def tutor(self, nome="Cristiane", **kwargs):
        tutor = Tutor(nome=nome, nome_key=tutores._gerar_nome_key(nome), ativo=1, **kwargs)
        self.db.add(tutor)
        self.db.commit()
        return tutor

    def mesclar(self, principal, secundario, *, chave="mesclagem-sintetica-01", **overrides):
        previa = mesclagem.obter_previa(self.db, principal.id, secundario.id)
        payload = tutores.MesclagemPayload(**{
            "principal_id": principal.id, "secundario_id": secundario.id,
            "token_previa": previa["token_previa"], "escolhas": {c: "principal" for c in previa["conflitos"]},
            "motivo": "Conferencia sintetica antes da mesclagem", "confirmar": True,
            "chave_operacao": chave, **overrides,
        })
        return mesclagem.mesclar(self.db, payload, self.user), payload

    def payload_reversao(self, mesclagem_id, **overrides):
        previa = reversao.obter_previa_reversao(self.db, mesclagem_id)
        return tutor_mesclagem_reversao.ReversaoPayload(**{
            "token_previa": previa["token_previa"], "motivo": "Pessoas distintas confirmadas no atendimento",
            "confirmar": True, "chave_operacao": "reversao-sintetica-01", **overrides,
        })

    def test_previa_nao_promete_confirmacao_de_identidade_apos_mesclar(self):
        principal = self.tutor(identificacao_pendente=False)
        secundario = self.tutor(identificacao_pendente=False)
        previa = mesclagem.obter_previa(self.db, principal.id, secundario.id)
        self.assertNotIn("identificacao_pendente", previa["campos"])
        self.assertTrue(any("identificacao ficara pendente" in aviso for aviso in previa["avisos"]))
        self.mesclar(principal, secundario)
        self.db.refresh(principal)
        self.assertTrue(principal.identificacao_pendente)

    def test_ida_e_volta_preservam_animais_distintos_valores_e_textos_historicos(self):
        principal = self.tutor(telefone="85911110000", endereco="Rua A", cidade="Fortaleza", latitude=-3.7)
        secundario = self.tutor(telefone="85922220000", endereco="Rua B", cidade="Caucaia", latitude=-3.8)
        pet_a = Paciente(nome="Pingo", nome_key="pingo", tutor_id=principal.id, ativo=1)
        pet_b = Paciente(nome="Pingo", nome_key="pingo", tutor_id=secundario.id, ativo=1)
        self.db.add_all([pet_a, pet_b]); self.db.flush()
        ag = Agendamento(tutor_id=secundario.id, paciente_id=pet_b.id, inicio=datetime(2026, 10, 29, 10), tutor="Nome historico")
        atendimento = AtendimentoClinico(tutor_id=secundario.id, paciente_id=pet_b.id, veterinario_id=1,
                                         status="Concluido", data_atendimento=datetime(2026, 10, 28))
        credito = CreditoFinanceiro(tutor_id=secundario.id, paciente_id=pet_b.id, tipo_destino="cliente", valor=75, status="Ativo")
        self.db.add_all([ag, atendimento, credito]); self.db.commit()
        result, _ = self.mesclar(principal, secundario, escolhas={"telefone": "secundario", "endereco": "secundario"})
        original_history = self.db.get(TutorMesclagem, result["id"]).detalhes_json
        previa = reversao.obter_previa_reversao(self.db, result["id"])
        self.assertEqual(previa["bloqueios"], [])
        self.assertEqual(previa["vinculos"]["pacientes"], 1)
        self.assertEqual(self.db.query(TutorMesclagemReversao).count(), 0)
        answer = reversao.reverter_mesclagem(self.db, result["id"], self.payload_reversao(result["id"]), self.user)
        for row in (pet_b, ag, atendimento, credito):
            self.db.refresh(row)
            self.assertEqual(row.tutor_id, secundario.id)
        self.db.refresh(principal); self.db.refresh(secundario); self.db.refresh(pet_a)
        self.assertEqual(pet_a.tutor_id, principal.id)
        self.assertEqual(self.db.query(Paciente).count(), 2)
        self.assertEqual(credito.valor, 75)
        self.assertEqual(ag.tutor, "Nome historico")
        self.assertEqual((principal.telefone, principal.endereco, principal.latitude), ("85911110000", "Rua A", -3.7))
        self.assertEqual((secundario.telefone, secundario.endereco, secundario.latitude), ("85922220000", "Rua B", -3.8))
        self.assertEqual(secundario.ativo, 1)
        self.assertIsNone(secundario.mesclado_em_id)
        self.assertEqual(self.db.get(TutorMesclagem, result["id"]).detalhes_json, original_history)
        audit = self.db.get(TutorMesclagemReversao, answer["id"])
        self.assertEqual(audit.usuario_id, self.user.id)
        self.assertTrue(audit.created_at)
        self.assertEqual(json.loads(audit.detalhes_json)["vinculos_restaurados"]["pacientes"], [pet_b.id])

    def test_contatos_e_origens_existentes_e_gerados_voltam_a_pessoa_original(self):
        a = self.tutor(telefone="85911110000", origem_cadastro="Clinica A")
        b = self.tutor(telefone="85922220000", email="b@example.test", origem_cadastro="Clinica B")
        contato, _ = rotina.adicionar_contato(self.db, b, tipo="whatsapp", valor="85933330000", rotulo="Celular pessoal")
        origem, _ = rotina.adicionar_origem(self.db, b, descricao="Clinica C")
        self.db.commit()
        result, _ = self.mesclar(a, b)
        self.db.refresh(contato); self.db.refresh(origem)
        self.assertEqual(contato.tutor_id, a.id)
        self.assertEqual(origem.tutor_id, a.id)
        before_count = self.db.query(TutorContato).count()
        reversao.reverter_mesclagem(self.db, result["id"], self.payload_reversao(result["id"]), self.user)
        self.db.refresh(contato); self.db.refresh(origem)
        self.assertEqual(contato.tutor_id, b.id)
        self.assertEqual(origem.tutor_id, b.id)
        self.assertEqual(self.db.query(TutorContato).count(), before_count)
        self.assertEqual({r.valor for r in self.db.query(TutorContato).filter_by(tutor_id=b.id)},
                         {"85922220000", "85933330000", "b@example.test"})
        self.assertEqual({r.descricao for r in self.db.query(TutorOrigem).filter_by(tutor_id=b.id)}, {"Clinica B", "Clinica C"})

    def test_alteracao_de_vinculo_ou_novo_vinculo_bloqueia_reversao_sem_perda(self):
        for new_link in (False, True):
            with self.subTest(new_link=new_link):
                a, b = self.tutor(), self.tutor()
                pet = Paciente(nome="Pingo", tutor_id=b.id, ativo=1)
                self.db.add(pet); self.db.commit()
                result, _ = self.mesclar(a, b, chave=f"mesclagem-mudanca-{new_link}")
                payload = self.payload_reversao(result["id"], chave_operacao=f"reversao-mudanca-{new_link}")
                if new_link:
                    self.db.add(Paciente(nome="Novo animal apos mesclagem", tutor_id=a.id, ativo=1))
                else:
                    pet.nome = "Pingo corrigido"
                self.db.commit()
                self.assertTrue(reversao.obter_previa_reversao(self.db, result["id"])["bloqueios"])
                with self.assertRaises(HTTPException) as ctx:
                    reversao.reverter_mesclagem(self.db, result["id"], payload, self.user)
                self.assertEqual(ctx.exception.status_code, 409)
                self.db.refresh(pet); self.db.refresh(b)
                self.assertEqual(pet.tutor_id, a.id)
                self.assertEqual(b.mesclado_em_id, a.id)
                self.assertFalse(self.db.query(TutorMesclagemReversao).filter_by(mesclagem_id=result["id"]).first())

    def test_edicao_do_tutor_apos_mesclagem_bloqueia_mesmo_com_previa_nova(self):
        a, b = self.tutor(), self.tutor()
        result, _ = self.mesclar(a, b)
        a.telefone = "85999990000"
        self.db.commit()
        with self.assertRaises(HTTPException) as ctx:
            reversao.reverter_mesclagem(self.db, result["id"], self.payload_reversao(result["id"]), self.user)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(self.db.query(TutorMesclagemReversao).count(), 0)

    def test_replay_apos_resposta_perdida_devolve_mesmo_resultado(self):
        a, b = self.tutor(), self.tutor()
        merge, merge_payload = self.mesclar(a, b)
        self.assertEqual(mesclagem.mesclar(self.db, merge_payload, self.user), merge)
        payload = self.payload_reversao(merge["id"])
        first = reversao.reverter_mesclagem(self.db, merge["id"], payload, self.user)
        self.assertEqual(reversao.reverter_mesclagem(self.db, merge["id"], payload, self.user), first)
        self.assertEqual(self.db.query(TutorMesclagem).count(), 1)
        self.assertEqual(self.db.query(TutorMesclagemReversao).count(), 1)
        self.assertEqual(self.db.query(TutorOperacao).count(), 2)

    def test_reusar_chave_com_payload_diferente_recusa_sem_nova_correcao(self):
        a, b = self.tutor(), self.tutor()
        result, _ = self.mesclar(a, b)
        payload = self.payload_reversao(result["id"])
        reversao.reverter_mesclagem(self.db, result["id"], payload, self.user)
        alterado = payload.model_copy(update={"motivo": "Outro motivo informado depois"})
        with self.assertRaises(HTTPException) as ctx:
            reversao.reverter_mesclagem(self.db, result["id"], alterado, self.user)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(self.db.query(TutorMesclagemReversao).count(), 1)

    def test_falha_no_commit_reverte_toda_correcao_inclusive_chave(self):
        a, b = self.tutor(), self.tutor()
        pet = Paciente(nome="Pingo", tutor_id=b.id, ativo=1)
        self.db.add(pet); self.db.commit()
        result, _ = self.mesclar(a, b)
        payload = self.payload_reversao(result["id"])
        with patch.object(self.db, "commit", side_effect=RuntimeError("falha sintetica")):
            with self.assertRaises(RuntimeError):
                reversao.reverter_mesclagem(self.db, result["id"], payload, self.user)
        self.db.refresh(pet); self.db.refresh(b)
        self.assertEqual(pet.tutor_id, a.id)
        self.assertEqual(b.ativo, 0)
        self.assertEqual(b.mesclado_em_id, a.id)
        self.assertEqual(self.db.query(TutorMesclagemReversao).count(), 0)
        self.assertEqual(self.db.query(TutorOperacao).filter_by(tipo="reverter_mesclagem").count(), 0)
        self.assertFalse(reversao.obter_previa_reversao(self.db, result["id"])["bloqueios"])

    def test_dois_ciclos_com_mesmo_secundario_mantem_os_dois_historicos(self):
        a, b = self.tutor(), self.tutor()
        for n in (1, 2):
            merged, _ = self.mesclar(a, b, chave=f"mesclagem-ciclo-{n}")
            payload = self.payload_reversao(merged["id"], chave_operacao=f"reversao-ciclo-{n}")
            reversao.reverter_mesclagem(self.db, merged["id"], payload, self.user)
        self.assertEqual(self.db.query(TutorMesclagem).count(), 2)
        self.assertEqual(self.db.query(TutorMesclagemReversao).count(), 2)
        self.db.refresh(b)
        self.assertIsNone(b.mesclado_em_id)

    def test_reversao_reabre_identidade_e_nao_reativa_acesso_portal(self):
        a, b = self.tutor(identificacao_pendente=False), self.tutor(identificacao_pendente=False)
        with self.engine.begin() as conn:
            conn.execute(text("CREATE TABLE portal_access_challenges (id INTEGER PRIMARY KEY, actor_type TEXT, actor_id INTEGER, status TEXT)"))
            conn.execute(text("INSERT INTO portal_access_challenges VALUES (1,'tutor',:id,'pending')"), {"id": b.id})
        result, _ = self.mesclar(a, b)
        self.assertEqual(self.db.execute(text("SELECT status FROM portal_access_challenges WHERE id=1")).scalar(), "revoked")
        eventos_antes = self.db.query(TutorIdentificacaoEvento).filter_by(acao="reabrir").count()
        reversao.reverter_mesclagem(self.db, result["id"], self.payload_reversao(result["id"]), self.user)
        self.db.refresh(a); self.db.refresh(b)
        self.assertTrue(a.identificacao_pendente)
        self.assertTrue(b.identificacao_pendente)
        self.assertEqual(self.db.execute(text("SELECT status FROM portal_access_challenges WHERE id=1")).scalar(), "revoked")
        self.assertEqual(self.db.query(TutorIdentificacaoEvento).filter_by(acao="reabrir").count(), eventos_antes + 2)

    def test_previa_antiga_sem_snapshot_e_mesclagem_encadeada_exigem_revisao(self):
        a, b, c = self.tutor(), self.tutor(), self.tutor()
        result, _ = self.mesclar(a, b)
        self.mesclar(c, a, chave="mesclagem-cadeia-02")
        self.assertTrue(reversao.obter_previa_reversao(self.db, result["id"])["bloqueios"])
        historico = self.db.get(TutorMesclagem, result["id"])
        detalhes = json.loads(historico.detalhes_json)
        detalhes.pop("estado_reversivel_sha256")
        historico.detalhes_json = json.dumps(detalhes)
        self.db.commit()
        self.assertTrue(any("antiga" in b for b in reversao.obter_previa_reversao(self.db, result["id"])["bloqueios"]))

    def test_endpoints_recusam_nao_admin_antes_de_operar(self):
        app = FastAPI()
        app.include_router(tutores.router, prefix="/tutores")
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(tem_papel=lambda _: False)
        with TestClient(app) as client:
            for path in ("/tutores/mesclagens/1/reversao/previa", "/tutores/mesclagens/1/reversao"):
                self.assertEqual(client.post(path, json={}).status_code, 403)
        self.assertEqual(self.db.query(TutorMesclagemReversao).count(), 0)


class TutorReversaoMigrationTest(unittest.TestCase):
    def test_migracao104_idempotente_preserva_historico_legado_e_outros_indices(self):
        path = BACKEND_DIR / "migrations/versions/20261027_104_tutores_mesclagem_reversao.py"
        spec = importlib.util.spec_from_file_location("migration_tutor_reversao", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        engine = create_engine("sqlite://")
        try:
            with engine.begin() as conn:
                conn.execute(text("CREATE TABLE tutores_mesclagens (id INTEGER PRIMARY KEY, principal_id INTEGER NOT NULL, "
                                  "secundario_id INTEGER NOT NULL UNIQUE, usuario_id INTEGER NOT NULL, usuario_nome TEXT, "
                                  "motivo TEXT NOT NULL, detalhes_json TEXT NOT NULL, created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL)"))
                conn.execute(text("CREATE INDEX ix_legado_motivo ON tutores_mesclagens (motivo)"))
                conn.execute(text("INSERT INTO tutores_mesclagens (id,principal_id,secundario_id,usuario_id,motivo,detalhes_json) "
                                  "VALUES (7,1,2,9,'Historico preservado','{\"snapshot\":\"original\"}')"))
                before = dict(conn.execute(text("SELECT * FROM tutores_mesclagens WHERE id=7")).mappings().one())
                migration.upgrade(conn, "sqlite")
                migration.upgrade(conn, "sqlite")
                after = dict(conn.execute(text("SELECT * FROM tutores_mesclagens WHERE id=7")).mappings().one())
                self.assertEqual(after, before)
                self.assertIn("tutores_mesclagens_reversoes", inspect(conn).get_table_names())
                self.assertIn("ix_legado_motivo", {i["name"] for i in inspect(conn).get_indexes("tutores_mesclagens")})
                conn.execute(text("INSERT INTO tutores_mesclagens (principal_id,secundario_id,usuario_id,motivo,detalhes_json) "
                                  "VALUES (1,2,9,'Segundo ciclo','{}')"))
                self.assertEqual(conn.execute(text("SELECT COUNT(*) FROM tutores_mesclagens")).scalar(), 2)
        finally:
            engine.dispose()


@unittest.skipUnless(os.environ.get("TUTORES_TEST_POSTGRES_URL"), "PostgreSQL temporario local nao configurado")
class TutorMesclagemReversaoPostgresTest(TutorMesclagemReversaoTest):
    """Mesmo contrato em PostgreSQL real; jamais aceita base ou host operacionais."""
    def setUp(self):
        url = make_url(os.environ["TUTORES_TEST_POSTGRES_URL"])
        assert url.database == "fortcordis_tutores_test"
        assert not url.host
        assert str(url.query.get("host", "")).startswith("/tmp/fortcordis-tutores-pg.")
        self.schema = "reversao_" + uuid.uuid4().hex
        self.base_engine = create_engine(url, poolclass=NullPool)
        self.addCleanup(self.base_engine.dispose)
        with self.base_engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{self.schema}"'))

        def drop_schema():
            with self.base_engine.begin() as conn:
                conn.execute(text(f'DROP SCHEMA IF EXISTS "{self.schema}" CASCADE'))

        self.addCleanup(drop_schema)
        self.engine = create_engine(url, poolclass=NullPool, connect_args={"options": f"-csearch_path={self.schema} -ctimezone=UTC"})
        self.addCleanup(self.engine.dispose)
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(text("SELECT current_schema()")).scalar(), self.schema)
        for model in (Tutor, Paciente, Agendamento, AtendimentoClinico, CreditoFinanceiro, TutorMesclagem,
                      TutorMesclagemReversao, TutorContato, TutorOrigem, TutorIdentificacaoEvento,
                      TutorDuplicidadeDescarte, TutorOperacao):
            model.__table__.create(self.engine)
        self.sessions = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)
        self.db = self.sessions()
        self.addCleanup(self.db.close)
        self.user = SimpleNamespace(id=7, nome="Administrador sintetico", tem_papel=lambda role: role == "admin")

    def tearDown(self):
        # addCleanup tambem roda quando setUp falha, sem deixar schema/conexao.
        pass

    def test_duas_requisicoes_com_mesma_chave_mesclam_e_revertem_uma_vez(self):
        a, b = self.tutor(), self.tutor()
        a_id, b_id = a.id, b.id
        previa = mesclagem.obter_previa(self.db, a_id, b_id)
        payload = tutores.MesclagemPayload(principal_id=a_id, secundario_id=b_id,
            token_previa=previa["token_previa"], escolhas={}, confirmar=True,
            motivo="Mesclagem sintetica concorrente", chave_operacao="mesclagem-concorrente-01")
        self.db.rollback()
        barrier = threading.Barrier(2)

        def merge_once():
            with self.sessions() as db:
                barrier.wait(timeout=5)
                return mesclagem.mesclar(db, payload, self.user)

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(merge_once) for _ in range(2)]
            merged = [f.result(timeout=15) for f in futures]
        self.assertEqual(merged[0], merged[1])
        self.assertEqual(self.db.query(TutorMesclagem).count(), 1)
        rollback_payload = self.payload_reversao(merged[0]["id"], chave_operacao="reversao-concorrente-01")
        self.db.rollback()
        barrier = threading.Barrier(2)

        def undo_once():
            with self.sessions() as db:
                barrier.wait(timeout=5)
                return reversao.reverter_mesclagem(db, merged[0]["id"], rollback_payload, self.user)

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(undo_once) for _ in range(2)]
            undone = [f.result(timeout=15) for f in futures]
        self.assertEqual(undone[0], undone[1])
        self.assertEqual(self.db.query(TutorMesclagemReversao).count(), 1)
        self.assertEqual(self.db.query(TutorOperacao).count(), 2)

    def test_hash_reversao_independe_do_fuso_da_sessao_postgres(self):
        a, b = self.tutor(), self.tutor()
        self.db.execute(text("SET TIME ZONE 'America/Fortaleza'"))
        result, _ = self.mesclar(a, b)
        self.db.close()
        self.db = self.sessions()
        self.addCleanup(self.db.close)
        self.db.execute(text("SET TIME ZONE 'UTC'"))
        previa = reversao.obter_previa_reversao(self.db, result["id"])
        self.assertEqual(previa["bloqueios"], [])
        self.db.rollback()
        self.db.execute(text("SET TIME ZONE 'Asia/Tokyo'"))
        payload = tutor_mesclagem_reversao.ReversaoPayload(token_previa=previa["token_previa"], confirmar=True,
            motivo="Correcao sintetica com fuso distinto", chave_operacao="reversao-fuso-01")
        reversao.reverter_mesclagem(self.db, result["id"], payload, self.user)
        self.assertEqual(self.db.query(TutorMesclagemReversao).count(), 1)

    def test_migracoes103_104_repetiveis_preservam_historico_e_revogam_data_api(self):
        a, b = self.tutor(), self.tutor()
        result, _ = self.mesclar(a, b)
        original = self.db.get(TutorMesclagem, result["id"]).detalhes_json
        self.db.rollback()
        for version, filename in ((103, "20261027_103_tutores_rotina_agil.py"),
                                  (104, "20261027_104_tutores_mesclagem_reversao.py")):
            spec = importlib.util.spec_from_file_location(f"migration_tutores_pg_{version}", BACKEND_DIR / "migrations/versions" / filename)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            with self.engine.begin() as conn:
                for role in ("anon", "authenticated"):
                    conn.execute(text(f"DO $$ BEGIN CREATE ROLE {role} NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$"))
                if version == 104:
                    conn.execute(text("ALTER TABLE tutores_mesclagens ADD CONSTRAINT uq_reversao_legado_secundario UNIQUE (secundario_id)"))
                module.upgrade(conn, "postgresql")
                tables = (["tutores_identificacao_eventos", "tutores_contatos", "tutores_origens",
                           "tutores_duplicidades_descartes", "tutores_operacoes"] if version == 103
                          else ["tutores_mesclagens_reversoes"])
                for table in tables:
                    conn.execute(text(f'GRANT SELECT, INSERT, UPDATE, DELETE ON "{table}" TO anon, authenticated'))
                module.upgrade(conn, "postgresql")
                for table in tables:
                    self.assertTrue(conn.execute(text("SELECT relrowsecurity FROM pg_class WHERE oid=CAST(:table AS regclass)"),
                                                 {"table": table}).scalar())
                    for role in ("anon", "authenticated"):
                        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                            self.assertFalse(conn.execute(text("SELECT has_table_privilege(:role,:table,:privilege)"),
                                {"role": role, "table": table, "privilege": privilege}).scalar())
        self.assertEqual(self.db.get(TutorMesclagem, result["id"]).detalhes_json, original)
        self.assertFalse(any(c["column_names"] == ["secundario_id"] for c in inspect(self.engine).get_unique_constraints("tutores_mesclagens")))
