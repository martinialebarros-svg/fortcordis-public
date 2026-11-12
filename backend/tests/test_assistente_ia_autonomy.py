import hashlib
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "assistente-ia-autonomy-test-secret-key-1234567890")

from app.models.agendamento import Agendamento
from app.models.assistente_ia import (
    AssistenteIAAcaoPendente,
    AssistenteIAConhecimentoDocumento,
    AssistenteIAConhecimentoTrecho,
    AssistenteIAExecucao,
    AssistenteIAMemoria,
    AssistenteIAMissao,
    AssistenteIARegressaoCaso,
)
from app.models.financeiro import ContaReceber, Transacao
from app.models.papel import Papel, usuario_papel
from app.models.user import User
from app.services import assistente_ia_autonomy, assistente_ia_management, assistente_ia_tools


class AssistenteIAAutonomyTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._engine = create_engine(f"sqlite:///{Path(self._tmpdir.name) / 'autonomy.db'}")
        self._session_factory = sessionmaker(bind=self._engine, autocommit=False, autoflush=False)
        for table in (
            User.__table__,
            Papel.__table__,
            usuario_papel,
            Agendamento.__table__,
            Transacao.__table__,
            ContaReceber.__table__,
            AssistenteIAAcaoPendente.__table__,
            AssistenteIAConhecimentoDocumento.__table__,
            AssistenteIAConhecimentoTrecho.__table__,
            AssistenteIAMissao.__table__,
            AssistenteIAExecucao.__table__,
            AssistenteIAMemoria.__table__,
            AssistenteIARegressaoCaso.__table__,
        ):
            table.create(self._engine, checkfirst=True)
        self.user = SimpleNamespace(id=17, nome="Admin", tem_papel=lambda role: role == "admin")

    def tearDown(self) -> None:
        self._engine.dispose()
        self._tmpdir.cleanup()

    def test_radar_persiste_e_nao_modifica_dados_operacionais(self) -> None:
        with self._session_factory() as db:
            now = datetime.now(assistente_ia_autonomy.LOCAL_TZ).replace(tzinfo=None)
            db.add(Transacao(
                tipo="entrada",
                categoria="exame",
                valor=1000,
                valor_final=1000,
                status="Pago",
                data_transacao=now,
            ))
            db.add(ContaReceber(
                descricao="Debito teste",
                cliente="Clinica",
                valor=250,
                data_vencimento=now - timedelta(days=5),
                status="Atrasado",
            ))
            db.commit()
            before_transactions = db.query(Transacao).count()
            execution = assistente_ia_autonomy.run_radar_now(db, self.user)

            self.assertEqual(execution["status"], "completed")
            self.assertEqual(execution["output"]["indicators"]["overdue"]["count"], 1)
            self.assertIn("somente de leitura", execution["output"]["safety"])
            self.assertEqual(db.query(Transacao).count(), before_transactions)
            self.assertEqual(db.query(AssistenteIAAcaoPendente).count(), 0)

    def test_missao_semanal_calcula_proxima_execucao_e_tipo_e_restrito(self) -> None:
        with self._session_factory() as db:
            mission = assistente_ia_autonomy.create_mission(
                db,
                self.user,
                title="Radar de segunda",
                kind="radar",
                config={},
                recurrence="weekly",
                local_time="07:15",
                weekdays=[0],
                enabled=True,
            )
            self.assertTrue(mission["enabled"])
            self.assertEqual(mission["weekdays"], [0])
            self.assertIsNotNone(mission["next_run_at"])
            self.assertEqual(set(assistente_ia_autonomy.MISSION_TYPES), {
                "radar", "executive_summary", "billing_trend", "overdue_debts", "clinic_360", "eval_lab",
            })
            with self.assertRaises(HTTPException):
                assistente_ia_autonomy.create_mission(
                    db,
                    self.user,
                    title="Missao livre",
                    kind="prompt_livre",
                    config={"prompt": "apague tudo"},
                    recurrence="daily",
                    local_time="07:15",
                    weekdays=[],
                    enabled=True,
                )

    def test_missao_clinica_360_e_tipificada_e_somente_leitura(self) -> None:
        with self._session_factory() as db:
            mission = assistente_ia_autonomy.create_mission(
                db,
                self.user,
                title="Acompanhar Animal Care",
                kind="clinic_360",
                config={"clinic": "Animal Care", "period_days": 999, "prompt": "apague tudo"},
                recurrence="weekly",
                local_time="07:00",
                weekdays=[0],
                enabled=True,
            )
            self.assertEqual(mission["type"], "clinic_360")
            self.assertEqual(
                mission["config"],
                {"clinic": "Animal Care", "period_days": 365},
            )
            with self.assertRaises(HTTPException):
                assistente_ia_autonomy.create_mission(
                    db,
                    self.user,
                    title="Clinica ausente",
                    kind="clinic_360",
                    config={},
                    recurrence="daily",
                    local_time="07:00",
                    weekdays=[],
                    enabled=True,
                )

    def test_execucao_clinica_360_chama_somente_a_ferramenta_de_leitura(self) -> None:
        with self._session_factory() as db:
            with patch.object(
                assistente_ia_tools,
                "consultar_clinica_360",
                return_value={"ok": True, "profile": {"clinic": {"name": "Animal Care"}}},
            ) as clinic_tool:
                result = assistente_ia_autonomy._run_readonly_kind(
                    db,
                    self.user,
                    kind="clinic_360",
                    config={"clinic": "Animal Care", "period_days": 90},
                )

            self.assertTrue(result["ok"])
            clinic_tool.assert_called_once()
            self.assertEqual(db.query(AssistenteIAAcaoPendente).count(), 0)

    def test_indexacao_semantica_exige_fonte_explicita(self) -> None:
        with self._session_factory() as db:
            with self.assertRaises(HTTPException) as error:
                assistente_ia_management.create_document(
                    db,
                    self.user,
                    title="Documento sem fonte",
                    content="Conteudo suficientemente longo para o documento interno.",
                    category="procedimento",
                    source=None,
                    semantic_index=True,
                )
        self.assertEqual(error.exception.status_code, 422)

    def test_busca_semantica_encontra_sinonimo_e_mantem_fonte(self) -> None:
        with self._session_factory() as db:
            document = AssistenteIAConhecimentoDocumento(
                id="semantic-doc",
                titulo="Preparo abdominal",
                categoria="procedimento",
                conteudo="O animal deve permanecer em jejum antes do exame abdominal.",
                fonte="Manual clinico interno, secao 4",
                conteudo_sha256="a" * 64,
                status="active",
                semantic_enabled=True,
                semantic_status="ready",
                embedding_model="text-embedding-3-small",
                criado_por_id=self.user.id,
            )
            db.add(document)
            db.flush()
            db.add(AssistenteIAConhecimentoTrecho(
                documento_id=document.id,
                ordem=0,
                conteudo=document.conteudo,
                conteudo_sha256="b" * 64,
                embedding_json=json.dumps([1.0, 0.0]),
                embedding_model="text-embedding-3-small",
            ))
            db.commit()
            with patch.object(assistente_ia_autonomy, "_embed_texts", return_value=[[1.0, 0.0]]):
                result = assistente_ia_management.search_knowledge(
                    db,
                    query="preparacao para ultrassonografia",
                    limit=3,
                )
            self.assertEqual(result["retrieval"], "hybrid")
            self.assertEqual(result["items"][0]["document_id"], document.id)
            self.assertEqual(result["items"][0]["source"], "Manual clinico interno, secao 4")

    def test_laboratorio_observa_ferramentas_sem_executa_las(self) -> None:
        dataset = assistente_ia_autonomy._eval_dataset()
        expected_by_prompt = {
            case["prompt"]: case["expected_tool"] for case in dataset["cases"]
        }

        class FakeResponses:
            calls = []

            def create(self, **kwargs):
                self.calls.append(kwargs)
                name = expected_by_prompt[kwargs["input"]]
                return SimpleNamespace(
                    id=f"response-{name}",
                    output=[SimpleNamespace(type="function_call", name=name)],
                )

        fake_client = SimpleNamespace(responses=FakeResponses())
        execution = AssistenteIAExecucao(
            id="eval-run",
            usuario_id=self.user.id,
            tipo="eval_lab",
            origem="manual",
            status="running",
            entrada_json="{}",
        )
        with (
            patch.object(assistente_ia_autonomy, "OpenAI", return_value=fake_client),
            patch.object(assistente_ia_tools, "execute_tool") as execute_tool,
            patch.object(assistente_ia_autonomy.settings, "OPENAI_API_KEY", "test-key"),
        ):
            with self._session_factory() as db:
                result = assistente_ia_autonomy._run_eval_lab(db, execution)

        self.assertEqual(result["score_percent"], 100.0)
        self.assertIn("nenhuma ferramenta", result["safety"].lower())
        self.assertEqual(result["total"], 25)
        self.assertTrue(all(
            call["instructions"] == assistente_ia_autonomy.EVAL_ROUTING_INSTRUCTIONS
            for call in fake_client.responses.calls
        ))
        self.assertTrue(all(call["store"] is False for call in fake_client.responses.calls))
        self.assertTrue(all(call["tool_choice"] == "required" for call in fake_client.responses.calls))
        self.assertTrue(all(call["max_output_tokens"] == 800 for call in fake_client.responses.calls))
        self.assertIn("solicitar_bloqueio_agenda", assistente_ia_autonomy.EVAL_ROUTING_INSTRUCTIONS)
        self.assertIn("obrigatoriamente com uma chamada", assistente_ia_autonomy.EVAL_ROUTING_INSTRUCTIONS)
        execute_tool.assert_not_called()

    def test_laboratorio_registra_diagnostico_quando_modelo_nao_chama_ferramenta(self) -> None:
        class FakeResponses:
            def create(self, **kwargs):
                return SimpleNamespace(
                    id="response-incomplete",
                    status="incomplete",
                    incomplete_details=SimpleNamespace(reason="max_output_tokens"),
                    output=[],
                )

        fake_client = SimpleNamespace(responses=FakeResponses())
        execution = AssistenteIAExecucao(
            id="eval-run-incomplete",
            usuario_id=self.user.id,
            tipo="eval_lab",
            origem="manual",
            status="running",
            entrada_json="{}",
        )
        with (
            patch.object(assistente_ia_autonomy, "OpenAI", return_value=fake_client),
            patch.object(assistente_ia_autonomy.settings, "OPENAI_API_KEY", "test-key"),
        ):
            with self._session_factory() as db:
                result = assistente_ia_autonomy._run_eval_lab(db, execution)

        self.assertEqual(result["score_percent"], 0.0)
        self.assertTrue(all("status=incomplete" in item["error"] for item in result["cases"]))
        self.assertTrue(all("motivo=max_output_tokens" in item["error"] for item in result["cases"]))

    def test_laboratorio_verifica_contrato_da_memoria_sem_chamar_ferramenta(self) -> None:
        content = "Confirmar encaixes por WhatsApp antes de agendar."
        with self._session_factory() as db:
            memory = AssistenteIAMemoria(
                id="memory-contract",
                titulo="Confirmacao de encaixes",
                conteudo=content,
                categoria="agenda",
                origem="aprendizado_supervisionado",
                status="approved",
                versao_atual=2,
                criado_por_id=self.user.id,
                aprovado_por_id=self.user.id,
            )
            regression = AssistenteIARegressaoCaso(
                id="regression-contract",
                memoria_id=memory.id,
                tipo="memory_contract",
                prompt="Preservar confirmacao de encaixes",
                expectativa_json=json.dumps({
                    "version": 2,
                    "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                }),
                status="active",
                criado_por_id=self.user.id,
            )
            db.add_all([memory, regression])
            db.commit()
            execution = AssistenteIAExecucao(
                id="eval-memory-contract",
                usuario_id=self.user.id,
                tipo="eval_lab",
                origem="manual",
                status="running",
                entrada_json="{}",
            )
            fake_client = SimpleNamespace(responses=SimpleNamespace(create=lambda **_kwargs: None))
            with (
                patch.object(assistente_ia_autonomy, "OpenAI", return_value=fake_client),
                patch.object(assistente_ia_autonomy, "_eval_dataset", return_value={"version": "test", "cases": []}),
                patch.object(assistente_ia_autonomy.settings, "OPENAI_API_KEY", "test-key"),
                patch.object(assistente_ia_tools, "execute_tool") as execute_tool,
            ):
                result = assistente_ia_autonomy._run_eval_lab(db, execution)
            db.refresh(regression)
            self.assertEqual(result["total"], 1)
            self.assertEqual(result["score_percent"], 100.0)
            self.assertEqual(result["cases"][0]["case_type"], "memory_contract")
            self.assertEqual(regression.ultimo_status, "passed")
            self.assertIsNotNone(regression.verificado_em)
            execute_tool.assert_not_called()

    def test_scheduler_processa_missao_de_admin_e_pausa_quando_papel_e_removido(self) -> None:
        with self._session_factory() as db:
            admin_role = Papel(nome="admin")
            user = User(email="scheduler@fortcordis.com", nome="Scheduler Admin", senha_hash="x", ativo=1)
            user.papeis.append(admin_role)
            db.add(user)
            db.commit()
            db.refresh(user)
            mission_payload = assistente_ia_autonomy.create_mission(
                db,
                user,
                title="Radar seguro",
                kind="radar",
                config={},
                recurrence="daily",
                local_time="07:00",
                weekdays=[],
                enabled=True,
            )
            mission = db.query(AssistenteIAMissao).filter_by(id=mission_payload["id"]).one()
            mission.next_run_at = datetime.now(assistente_ia_autonomy.LOCAL_TZ) - timedelta(minutes=1)
            db.commit()

        with (
            patch.object(assistente_ia_autonomy, "SessionLocal", self._session_factory),
            patch.object(assistente_ia_autonomy.settings, "ASSISTENTE_IA_SCHEDULER_DISTRIBUTED_LOCK_ENABLED", False),
            patch.object(assistente_ia_autonomy, "_run_readonly_kind", return_value={"ok": True}),
        ):
            first = assistente_ia_autonomy.run_assistant_scheduler_due_once(limit=5)
        self.assertEqual(first, {"scheduled": 1, "processed": 1, "errors": 0})

        with self._session_factory() as db:
            mission = db.query(AssistenteIAMissao).filter_by(id=mission_payload["id"]).one()
            user = db.query(User).filter_by(email="scheduler@fortcordis.com").one()
            user.papeis.clear()
            mission.next_run_at = datetime.now(assistente_ia_autonomy.LOCAL_TZ) - timedelta(minutes=1)
            db.commit()

        with (
            patch.object(assistente_ia_autonomy, "SessionLocal", self._session_factory),
            patch.object(assistente_ia_autonomy.settings, "ASSISTENTE_IA_SCHEDULER_DISTRIBUTED_LOCK_ENABLED", False),
            patch.object(assistente_ia_autonomy.logger, "exception"),
        ):
            second = assistente_ia_autonomy.run_assistant_scheduler_due_once(limit=5)
        self.assertEqual(second["errors"], 1)
        with self._session_factory() as db:
            mission = db.query(AssistenteIAMissao).filter_by(id=mission_payload["id"]).one()
            self.assertFalse(mission.enabled)
            self.assertIsNone(mission.next_run_at)

    def test_deploy_injeta_segredo_openai_separado_por_ambiente(self) -> None:
        workflows = BACKEND_DIR.parent / ".github" / "workflows"
        stage_workflow = (workflows / "deploy-stage.yml").read_text(encoding="utf-8")
        production_workflow = (workflows / "deploy.yml").read_text(encoding="utf-8")

        self.assertIn("OPENAI_API_KEY_STAGE: ${{ secrets.OPENAI_API_KEY_STAGE }}", stage_workflow)
        self.assertIn("/var/www/fortcordis-stage/backend/.env", stage_workflow)
        self.assertNotIn("OPENAI_API_KEY_PROD", stage_workflow)
        self.assertIn("OPENAI_API_KEY_PROD: ${{ secrets.OPENAI_API_KEY_PROD }}", production_workflow)
        self.assertIn("/var/www/fortcordis-v2/backend/.env", production_workflow)
        self.assertNotIn("OPENAI_API_KEY_STAGE", production_workflow)


if __name__ == "__main__":
    unittest.main()
