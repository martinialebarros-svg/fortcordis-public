"""Offline contract tests for durable, draft-only clinical batch processing."""
import copy
import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "test-batch-secret")
os.environ.setdefault("FORTCORDIS_PROCESS_ROLE", "api")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from app.api.v1.endpoints import atendimento_assistente as original
from app.api.v1.endpoints import atendimento_assistente_lotes as endpoint
from app.core.security import get_current_user
from app.db.database import get_db
from app.models.atendimento_assistente_lote import AtendimentoAssistenteLote as Lote, AtendimentoAssistenteLoteArquivo as Arquivo
from app.models.papel import Papel, usuario_papel
from app.models.papel_permissao import PapelPermissao
from app.models.user import User
from app.services import atendimento_assistente_lotes as service
from app.services.atendimento_assistente import AssistenteError
from migrations import runner as migration_runner

CONTEXT = {"atendimento_id": 8, "paciente": {"id": 17, "nome": "Paciente Fictício", "especie": "Canina"}, "consulta": {"anamnese": ""}}
AUDIO = b"RIFF" + b"\0" * 4 + b"WAVEsynthetic"


def pdf():
    out = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(out)
    return out.getvalue()


class BatchActorAuthorizationTests(unittest.TestCase):
    """Exercise the actual ASGI Request and permission matrix used by workers."""
    def setUp(self):
        self.engine=create_engine("sqlite://")
        for table in (User.__table__,Papel.__table__,usuario_papel,PapelPermissao.__table__):
            table.create(self.engine)
        self.db=sessionmaker(self.engine)()
        admin=Papel(id=1,nome="admin")
        reader=Papel(id=2,nome="recepcao")
        editor=Papel(id=3,nome="medico")
        self.db.add_all([
            User(id=11,email="admin@example.test",ativo=1,papeis=[admin]),
            User(id=12,email="reader@example.test",ativo=1,papeis=[reader]),
            User(id=13,email="editor@example.test",ativo=1,papeis=[editor]),
            PapelPermissao(papel=reader,modulo="atendimento_clinico",visualizar=1,editar=0),
            PapelPermissao(papel=reader,modulo="agenda",visualizar=1,editar=1),
            PapelPermissao(papel=editor,modulo="atendimento_clinico",visualizar=1,editar=1),
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_active_admin_passes_real_matrix_with_worker_request(self):
        service._authorize_actor(self.db,SimpleNamespace(usuario_id=11,atendimento_id=8))

    def test_read_only_attendance_role_cannot_process_even_with_other_edit_permission(self):
        with self.assertRaises(HTTPException) as captured:
            service._authorize_actor(self.db,SimpleNamespace(usuario_id=12,atendimento_id=8))
        self.assertEqual(captured.exception.status_code,403)
        self.assertEqual(captured.exception.detail,"Acesso negado: sem permissao de editar em atendimento_clinico.")

    def test_attendance_edit_permission_is_rechecked_after_revocation(self):
        job=SimpleNamespace(usuario_id=13,atendimento_id=8)
        service._authorize_actor(self.db,job)
        permission=self.db.query(PapelPermissao).filter_by(papel_id=3,modulo="atendimento_clinico").one()
        permission.editar=0
        self.db.commit()
        with self.assertRaises(HTTPException) as captured:
            service._authorize_actor(self.db,job)
        self.assertEqual(captured.exception.status_code,403)

    def test_inactive_admin_and_missing_actor_are_rejected(self):
        self.db.get(User,11).ativo=0
        self.db.commit()
        for actor_id in (11,99):
            with self.subTest(actor_id=actor_id),self.assertRaises(HTTPException) as captured:
                service._authorize_actor(self.db,SimpleNamespace(usuario_id=actor_id,atendimento_id=8))
            self.assertEqual(captured.exception.status_code,403)


class BatchMigrationSequenceTests(unittest.TestCase):
    def test_applied_patient_merge_108_does_not_skip_batch_tables(self):
        # Stage already applied 108 for patient merging. Discover both versions
        # through the real runner so duplicate IDs and silent skips regress.
        with tempfile.TemporaryDirectory() as directory:
            versions=Path(directory)/"versions"
            versions.mkdir()
            (versions/"20261106_108_pacientes_mesclagens.py").write_text(
                'VERSION = "20261106_108"\n'
                'DESCRIPTION = "Already applied patient merge migration"\n'
                'def upgrade(connection, dialect):\n'
                '    raise AssertionError("Applied patient migration must not run again")\n',
                encoding="utf-8",
            )
            source=Path(__file__).resolve().parents[1]/"migrations/versions/20261108_109_atendimento_assistente_lotes.py"
            shutil.copyfile(source,versions/source.name)
            engine=create_engine("sqlite://")
            try:
                with engine.begin() as connection:
                    migration_runner._ensure_schema_migrations_table(connection)
                    connection.execute(text("INSERT INTO schema_migrations(version,description) VALUES (:version,:description)"),
                        {"version":"20261106_108","description":"Already applied patient merge migration"})
                with patch.object(migration_runner,"VERSIONS_DIR",versions),patch.object(migration_runner,"engine",engine):
                    self.assertEqual(migration_runner.run_migrations(),1)
                    self.assertEqual(migration_runner.run_migrations(),0)
                    status=migration_runner.get_migration_status()
                self.assertEqual(status["current_version"],"20261108_109")
                self.assertEqual(status["latest_version"],"20261108_109")
                self.assertEqual(status["pending_count"],0)
                self.assertEqual(status["applied_count"],2)
                self.assertEqual(set(inspect(engine).get_table_names()),
                    {"schema_migrations",Lote.__tablename__,Arquivo.__tablename__})
            finally:
                engine.dispose()


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.engine = create_engine("sqlite:///" + self.directory.name + "/jobs.db", connect_args={"check_same_thread": False})
        for model in (Lote, Arquivo):
            model.__table__.create(self.engine)
        self.session = sessionmaker(self.engine, expire_on_commit=False)
        self.context = copy.deepcopy(CONTEXT)
        self.actor = SimpleNamespace(id=3, nome="Tester", email="tester@example.test")
        self.patches = [
            patch.object(service, "SessionLocal", self.session),
            patch.object(service, "storage_root", return_value=Path(self.directory.name)),
            patch.object(service, "require_enabled"),
            patch.object(service, "_authorize_actor"),
            patch.object(service.settings, "ATENDIMENTO_IA_ENABLED", True),
            patch.object(original, "_contexto", side_effect=lambda *args: copy.deepcopy(self.context)),
            patch.object(endpoint, "_contexto", side_effect=lambda *args: copy.deepcopy(self.context)),
            patch.object(endpoint, "_preparar", side_effect=lambda db, aid, consent, user: (copy.deepcopy(self.context), self.actor) if consent else (_ for _ in ()).throw(endpoint.HTTPException(422,"Consentimento obrigatório"))),
            patch.object(endpoint, "_auditar"),
        ]
        for p in self.patches:
            p.start()
        def db():
            with self.session() as session:
                yield session
        app = FastAPI()
        app.include_router(endpoint.router, prefix="/api/v1/atendimentos")
        app.dependency_overrides[get_db] = db
        app.dependency_overrides[get_current_user] = lambda: self.actor
        self.client = TestClient(app)
        self.base = "/api/v1/atendimentos/8/assistente/lotes"
        self.pdf = pdf()

    def tearDown(self):
        self.client.close()
        for p in reversed(self.patches):
            p.stop()
        self.engine.dispose()
        self.directory.cleanup()

    def manifest(self, audios=1, docs=1):
        files = []
        for kind, count, content, mime, extension in (("audio",audios,AUDIO,"audio/wav","wav"),("exame",docs,self.pdf,"application/pdf","pdf")):
            for index in range(count):
                files.append({"id":str(uuid4()),"nome":f"{kind}-{index}.{extension}","tipo":kind,"tamanho":len(content),"mime":mime})
        return {"request_id":str(uuid4()),"transcricao":"Texto revisado.","consentimento":True,"arquivos":files}

    def create(self, manifest):
        response = self.client.post(self.base, json=manifest)
        self.assertEqual(response.status_code,201,response.text)
        return response.json()

    def upload(self, job, manifest):
        for item in manifest["arquivos"]:
            response = self.client.put(f'{self.base}/{job["id"]}/arquivos/{item["id"]}',files={"arquivo":(item["nome"],AUDIO if item["tipo"]=="audio" else self.pdf,item["mime"])})
            self.assertEqual(response.status_code,200,response.text)

    def test_three_audios_five_documents_resume_only_failure_then_synthesize(self):
        self._assert_file_failure_resumes_independently("exame-2.pdf")

    def test_audio_failure_resumes_only_failed_audio_then_synthesizes(self):
        self._assert_file_failure_resumes_independently("audio-1.wav")

    def test_four_pdfs_resume_first_and_fourth_preserving_completed_serialized_results(self):
        manifest = self.manifest(audios=0, docs=4)
        manifest["transcricao"] = ""
        job = self.create(manifest)
        self.upload(job, manifest)
        self.assertEqual(self.client.post(f'{self.base}/{job["id"]}/iniciar').status_code, 200)
        failed_names = {"exame-0.pdf", "exame-3.pdf"}
        preserved_names = {"exame-1.pdf", "exame-2.pdf"}
        calls = []
        limit_message = "A IA atingiu o limite de geração antes de concluir a resposta."

        def extract(**kwargs):
            name = kwargs["nome"]
            calls.append(name)
            if name in failed_names and calls.count(name) == 1:
                raise AssistenteError(limit_message, 502)
            return {
                "arquivo": {"nome": name, "mime": kwargs["mime"], "paginas": 1},
                "analise": {"fontes": [], "achados_exames": [], "avisos": [f"Fonte sintética: {name}"]},
            }

        def preserved_results():
            with self.session() as db:
                rows = db.query(Arquivo).filter(Arquivo.lote_id == job["id"], Arquivo.nome.in_(preserved_names)).all()
                return {item.nome: {
                    "status": item.status, "serialized": item.resultado_json,
                    "result_sha256": hashlib.sha256(item.resultado_json.encode()).hexdigest(),
                    "source_sha256": item.sha256,
                } for item in rows}

        def synthesize(**kwargs):
            with self.session() as db:
                rows = db.query(Arquivo).filter_by(lote_id=job["id"]).order_by(Arquivo.ordem).all()
                self.assertEqual([item.status for item in rows], ["completed"] * 4)
                self.assertEqual(kwargs["exames"], [json.loads(item.resultado_json) for item in rows])
            self.assertEqual(len(kwargs["exames"]), 4)
            return {"campos": [], "achados_exames": [], "revisao_obrigatoria": True}

        synthesis = Mock(side_effect=synthesize)
        module = "app.services.atendimento_assistente_lote_provider."
        with patch(module + "processar_audio") as audio, patch(module + "processar_exame", side_effect=extract), patch(module + "sintetizar_lote", synthesis):
            service.run_once()
            state = self.client.get(f'{self.base}/{job["id"]}').json()
            self.assertEqual(state["status"], "failed")
            self.assertEqual([item["status"] for item in state["arquivos"]], ["failed", "completed", "completed", "failed"])
            self.assertEqual([item["erro"] for item in state["arquivos"] if item["status"] == "failed"], [limit_message] * 2)
            self.assertIsNone(state["resultado"])
            synthesis.assert_not_called()
            original_results = preserved_results()
            self.assertEqual(set(original_results), preserved_names)
            self.assertTrue(all(item["status"] == "completed" for item in original_results.values()))
            initial_calls = list(calls)
            self.assertEqual(initial_calls, [item["nome"] for item in manifest["arquivos"]])

            resumed = self.client.post(f'{self.base}/{job["id"]}/retomar')
            self.assertEqual(resumed.status_code, 200, resumed.text)
            self.assertEqual(preserved_results(), original_results)
            synthesis.assert_not_called()
            service.run_once()
            state = self.client.get(f'{self.base}/{job["id"]}').json()
            self.assertEqual(state["status"], "completed")
            self.assertEqual([item["status"] for item in state["arquivos"]], ["completed"] * 4)
            self.assertTrue(state["resultado"]["revisao_obrigatoria"])
            self.assertEqual(calls[len(initial_calls):], ["exame-0.pdf", "exame-3.pdf"])
            self.assertEqual(preserved_results(), original_results)
            synthesis.assert_called_once()
            audio.assert_not_called()
            self.assertEqual(set(inspect(self.engine).get_table_names()), {Lote.__tablename__, Arquivo.__tablename__})

    def _assert_file_failure_resumes_independently(self, failed_name):
        manifest = self.manifest(3,5)
        job = self.create(manifest)
        self.upload(job,manifest)
        self.assertEqual(self.client.post(f'{self.base}/{job["id"]}/iniciar').status_code,200)
        calls = {}
        def record_call(nome):
            calls[nome] = calls.get(nome,0)+1
            if nome==failed_name and calls[nome]==1:
                raise AssistenteError("Falha simulada",502)
        def audio(**kw):
            record_call(kw["nome"])
            return {"texto":kw["nome"],"modelo":"test","avisos":["Confira a transcrição com o áudio."]}
        def exame(**kw):
            record_call(kw["nome"])
            return {"arquivo":{"nome":kw["nome"],"mime":kw["mime"],"paginas":1},"analise":{"fontes":[],"achados_exames":[]}}
        synthesis = Mock(return_value={"campos":[],"achados_exames":[],"revisao_obrigatoria":True})
        module="app.services.atendimento_assistente_lote_provider."
        with patch(module+"processar_audio",side_effect=audio),patch(module+"processar_exame",side_effect=exame),patch(module+"sintetizar_lote",synthesis):
            service.run_once()
            state=self.client.get(f'{self.base}/{job["id"]}').json()
            self.assertEqual(state["status"],"failed")
            self.assertEqual([x["status"] for x in state["arquivos"]].count("completed"),7)
            self.assertEqual([x["nome"] for x in state["arquivos"] if x["status"]=="failed"],[failed_name])
            self.assertIsNone(state["resultado"])
            synthesis.assert_not_called()
            self.assertEqual(self.client.post(f'{self.base}/{job["id"]}/retomar').status_code,200)
            service.run_once()
            state=self.client.get(f'{self.base}/{job["id"]}').json()
            self.assertEqual(state["status"],"completed")
            self.assertIn("Confira a transcrição com o áudio.", state["resultado"]["avisos"])
            self.assertEqual(state["transcricao"],"Texto revisado.\n\naudio-0.wav\n\naudio-1.wav\n\naudio-2.wav")
            self.assertEqual(calls[failed_name],2)
            self.assertEqual(len(calls),8)
            self.assertTrue(all(value==1 for key,value in calls.items() if key!=failed_name))
            synthesis.assert_called_once()
            self.assertEqual(len(synthesis.call_args.kwargs["exames"]),5)
            # This isolated DB has no clinical tables: the complete pipeline writes drafts only.
            self.assertEqual(set(inspect(self.engine).get_table_names()),{Lote.__tablename__,Arquivo.__tablename__})

    def test_synthesis_failure_resumes_only_synthesis_with_all_sources_cached(self):
        manifest=self.manifest(3,5)
        job=self.create(manifest)
        self.upload(job,manifest)
        self.assertEqual(self.client.post(f'{self.base}/{job["id"]}/iniciar').status_code,200)
        audio=Mock(side_effect=lambda **kw: {"texto":kw["nome"],"modelo":"test","avisos":[]})
        exame=Mock(side_effect=lambda **kw: {"arquivo":{"nome":kw["nome"],"mime":kw["mime"],"paginas":1},"analise":{"fontes":[],"achados_exames":[]}})
        synthesis=Mock(side_effect=[AssistenteError("Síntese temporariamente indisponível",502),{"campos":[],"achados_exames":[],"revisao_obrigatoria":True}])
        module="app.services.atendimento_assistente_lote_provider."
        with patch(module+"processar_audio",audio),patch(module+"processar_exame",exame),patch(module+"sintetizar_lote",synthesis):
            service.run_once()
            state=self.client.get(f'{self.base}/{job["id"]}').json()
            self.assertEqual(state["status"],"failed")
            self.assertEqual([item["status"] for item in state["arquivos"]],["completed"]*8)
            self.assertIsNone(state["resultado"])
            self.assertIn("Síntese temporariamente indisponível",state["erro"])
            self.assertEqual(audio.call_count,3)
            self.assertEqual(exame.call_count,5)
            synthesis.assert_called_once()
            first_synthesis_args=copy.deepcopy(synthesis.call_args.kwargs)
            self.assertEqual(len(first_synthesis_args["exames"]),5)
            self.assertEqual(self.client.post(f'{self.base}/{job["id"]}/retomar').status_code,200)
            service.run_once()
            state=self.client.get(f'{self.base}/{job["id"]}').json()
            self.assertEqual(state["status"],"completed")
            self.assertTrue(state["resultado"]["revisao_obrigatoria"])
            self.assertEqual(state["transcricao"],"Texto revisado.\n\naudio-0.wav\n\naudio-1.wav\n\naudio-2.wav")
            self.assertEqual(audio.call_count,3)
            self.assertEqual(exame.call_count,5)
            self.assertEqual(synthesis.call_count,2)
            self.assertEqual(synthesis.call_args.kwargs,first_synthesis_args)

    def test_create_upload_and_start_are_idempotent_and_reject_changed_request(self):
        manifest=self.manifest()
        job=self.create(manifest)
        self.assertEqual(self.create(manifest)["id"],job["id"])
        changed=copy.deepcopy(manifest)
        changed["transcricao"]="Outro relato"
        self.assertEqual(self.client.post(self.base,json=changed).status_code,409)
        self.assertEqual(self.client.post(f'{self.base}/{job["id"]}/iniciar').status_code,409)
        self.upload(job,manifest)
        self.upload(job,manifest)
        for _ in range(2):
            self.assertEqual(self.client.post(f'{self.base}/{job["id"]}/iniciar').status_code,200)
        first=service._claim()
        self.assertIsNotNone(first)
        self.assertIsNone(service._claim())

    def test_owner_patient_expiry_and_private_original(self):
        manifest=self.manifest()
        job=self.create(manifest)
        self.upload(job,manifest)
        url=f'{self.base}/{job["id"]}/arquivos/{manifest["arquivos"][0]["id"]}/original'
        response=self.client.get(url)
        self.assertEqual(response.content,AUDIO)
        self.assertIn("no-store",response.headers["cache-control"])
        self.actor.id=4
        self.assertEqual(self.client.get(url).status_code,404)
        self.assertIsNone(self.client.get(self.base+"/atual").json())
        self.actor.id=3
        self.context["paciente"]["id"]=99
        self.assertEqual(self.client.get(url).status_code,409)
        self.context=copy.deepcopy(CONTEXT)
        with self.session() as db:
            db.get(Lote,job["id"]).expires_at=datetime.utcnow()-timedelta(seconds=1)
            db.commit()
        self.assertEqual(self.client.get(url).status_code,410)
        service.cleanup_expired()
        with self.session() as db:
            self.assertEqual(db.query(Lote).count(),0)
            self.assertEqual(db.query(Arquivo).count(),0)
        self.assertFalse((Path(self.directory.name)/job["id"]).exists())

    def test_expired_lease_is_reclaimed_and_old_result_is_fenced(self):
        job=self.create(self.manifest(0,0))
        self.client.post(f'{self.base}/{job["id"]}/iniciar')
        first=service._claim()
        with self.session() as db:
            db.get(Lote,job["id"]).lease_until=datetime.utcnow()-timedelta(seconds=1)
            db.commit()
        second=service._claim()
        self.assertEqual(first[0],second[0])
        self.assertNotEqual(first[1],second[1])
        with self.session() as db:
            self.assertIsNone(service._lease_job(db,*first))
            self.assertIsNotNone(service._lease_job(db,*second))
        self.assertEqual(self.client.delete(f'{self.base}/{job["id"]}').status_code,204)
        with self.session() as db:
            self.assertIsNone(service._lease_job(db,*second))

    def test_disabled_worker_keeps_queued_job_without_provider_calls(self):
        job=self.create(self.manifest(0,0))
        self.client.post(f'{self.base}/{job["id"]}/iniciar')
        with patch.object(service.settings,"ATENDIMENTO_IA_ENABLED",False),patch.object(service,"process_job") as process:
            service.run_once()
            process.assert_not_called()
        self.assertEqual(self.client.get(f'{self.base}/{job["id"]}').json()["status"],"queued")

    def test_changed_saved_context_prevents_reusing_cached_processing(self):
        job=self.create(self.manifest(0,0))
        with self.session() as db:
            db.get(Lote,job["id"]).status="failed"
            db.commit()
        self.context["consulta"]["anamnese"]="Relato atualizado"
        self.assertEqual(self.client.post(f'{self.base}/{job["id"]}/retomar').status_code,409)
        self.assertEqual(self.client.post(f'{self.base}/{job["id"]}/iniciar').status_code,409)

    def test_revoked_permission_stops_processing_before_provider(self):
        job=self.create(self.manifest(0,0))
        self.client.post(f'{self.base}/{job["id"]}/iniciar')
        module="app.services.atendimento_assistente_lote_provider."
        with patch.object(service,"_authorize_actor",side_effect=endpoint.HTTPException(403,"Permissão revogada")), patch(module+"sintetizar_lote") as synthesis:
            service.run_once()
            synthesis.assert_not_called()
        self.assertEqual(self.client.get(f'{self.base}/{job["id"]}').json()["status"],"failed")

    def test_changed_patient_job_can_be_discarded_without_exposing_results(self):
        job=self.create(self.manifest())
        self.context["paciente"]["id"]=29
        self.assertIsNone(self.client.get(self.base+"/atual").json())
        self.assertEqual(self.client.get(f'{self.base}/{job["id"]}').status_code,409)
        self.assertEqual(self.client.delete(f'{self.base}/{job["id"]}').status_code,204)

    def test_delete_failure_retains_tombstone_and_cleanup_retries(self):
        manifest=self.manifest()
        job=self.create(manifest)
        self.upload(job,manifest)
        directory=Path(self.directory.name)/job["id"]
        with patch.object(service.shutil,"rmtree",side_effect=PermissionError("simulated")):
            self.assertEqual(self.client.delete(f'{self.base}/{job["id"]}').status_code,503)
            with self.session() as db:
                retained=db.get(Lote,job["id"])
                self.assertEqual(retained.status,"deleting")
                self.assertIsNone(retained.lease_token)
                self.assertEqual(db.query(Arquivo).count(),2)
            service.cleanup_expired()
        self.assertTrue(directory.exists())
        self.assertEqual(self.client.post(f'{self.base}/{job["id"]}/retomar').status_code,410)
        self.assertEqual(self.client.get(f'{self.base}/{job["id"]}').status_code,410)
        self.assertIsNone(self.client.get(self.base+"/atual").json())
        service.cleanup_expired()
        with self.session() as db:
            self.assertIsNone(db.get(Lote,job["id"]))
            self.assertEqual(db.query(Arquivo).count(),0)
        self.assertFalse(directory.exists())

    def test_orphan_directory_cleanup_is_scoped_and_retryable(self):
        import time
        orphan=Path(self.directory.name)/str(uuid4())
        orphan.mkdir()
        (orphan/"private-source").write_bytes(AUDIO)
        old=time.time()-25*3600
        os.utime(orphan,(old,old))
        unrelated=Path(self.directory.name)/"unrelated"
        unrelated.mkdir()
        os.utime(unrelated,(old,old))
        with patch.object(service.shutil,"rmtree",side_effect=PermissionError("simulated")):
            service.cleanup_expired()
        self.assertTrue(orphan.exists())
        service.cleanup_expired()
        self.assertFalse(orphan.exists())
        self.assertTrue(unrelated.exists())

    def test_context_change_during_synthesis_rejects_stale_result(self):
        job=self.create(self.manifest(0,0))
        self.client.post(f'{self.base}/{job["id"]}/iniciar')
        def synthesize(**kwargs):
            self.context["consulta"]["anamnese"]="Relato novo salvo durante a análise"
            return {"campos":[],"avisos":[]}
        with patch("app.services.atendimento_assistente_lote_provider.sintetizar_lote",side_effect=synthesize):
            service.run_once()
        state=self.client.get(f'{self.base}/{job["id"]}').json()
        self.assertEqual(state["status"],"failed")
        self.assertIn("mudou durante",state["erro"])
        self.assertIsNone(state["resultado"])
        self.assertEqual(self.client.post(f'{self.base}/{job["id"]}/retomar').status_code,409)

    def test_manifest_size_duplicates_and_consent_are_checked(self):
        data=self.manifest(1,1)
        data["arquivos"].append(data["arquivos"][0])
        self.assertEqual(self.client.post(self.base,json=data).status_code,422)
        data=self.manifest(0,1)
        data["arquivos"][0]["tamanho"]=10*1024*1024+1
        self.assertEqual(self.client.post(self.base,json=data).status_code,422)
        data=self.manifest(1,0)
        data["consentimento"]=False
        self.assertEqual(self.client.post(self.base,json=data).status_code,422)


if __name__ == "__main__":
    unittest.main()
