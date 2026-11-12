import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "assistente-ia-clinics360-test-secret-key-1234567890")

from app.models.agendamento import Agendamento
from app.models.assistente_ia import AssistenteIAConversa, AssistenteIAMemoria
from app.models.clinica import Clinica
from app.models.financeiro import ContaReceber, Transacao
from app.models.ordem_servico import OrdemServico
from app.models.servico import Servico
from app.services import assistente_ia_clinics360, assistente_ia_tools


class AssistenteIAClinics360Test(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self._tmpdir.name) / "clinics360.db"
        self._engine = create_engine(f"sqlite:///{db_path}")
        self._session_factory = sessionmaker(bind=self._engine, autocommit=False, autoflush=False)
        for table in (
            Clinica.__table__,
            Servico.__table__,
            Agendamento.__table__,
            Transacao.__table__,
            OrdemServico.__table__,
            ContaReceber.__table__,
            AssistenteIAConversa.__table__,
            AssistenteIAMemoria.__table__,
        ):
            table.create(self._engine, checkfirst=True)

    def tearDown(self) -> None:
        self._engine.dispose()
        self._tmpdir.cleanup()

    def _seed(self, db):
        now = datetime.now(assistente_ia_clinics360.LOCAL_TZ)
        animal = Clinica(
            nome="Animal Care",
            razao_social="Animal Care LTDA",
            ativo=True,
            telefone="(85) 3333-4444",
            whatsapps=["85999990000"],
            email="animal@example.com",
            cidade="Fortaleza",
            estado="CE",
            endereco="Rua A",
            numero="10",
        )
        vet = Clinica(nome="Vet World", ativo=True, cidade="Fortaleza", estado="CE")
        service = Servico(nome="Ecocardiograma", duracao_minutos=30, ativo=True)
        conversation = AssistenteIAConversa(
            id="clinics360-conversation",
            usuario_id=7,
            titulo="Teste",
            ativa=True,
        )
        db.add_all([animal, vet, service, conversation])
        db.flush()

        statuses = ["Realizado", "Realizado", "Cancelado", "Cancelado", "Faltou"]
        for index, status in enumerate(statuses):
            start = now - timedelta(days=10 + index)
            db.add(
                Agendamento(
                    clinica_id=animal.id,
                    servico_id=service.id,
                    inicio=start,
                    fim=start + timedelta(minutes=30),
                    status=status,
                    data=start.date().isoformat(),
                    hora=start.strftime("%H:%M"),
                )
            )
        for days in (100, 105):
            start = now - timedelta(days=days)
            db.add(
                Agendamento(
                    clinica_id=animal.id,
                    servico_id=service.id,
                    inicio=start,
                    fim=start + timedelta(minutes=30),
                    status="Realizado",
                )
            )
        next_start = now + timedelta(days=2)
        db.add(
            Agendamento(
                clinica_id=animal.id,
                servico_id=service.id,
                inicio=next_start,
                fim=next_start + timedelta(minutes=30),
                status="Confirmado",
            )
        )

        db.add_all(
            [
                Transacao(
                    tipo="entrada",
                    categoria="exame",
                    valor=1000,
                    valor_final=1000,
                    valor_taxa=50,
                    status="Pago",
                    clinica_id=animal.id,
                    data_transacao=now - timedelta(days=5),
                ),
                Transacao(
                    tipo="entrada",
                    categoria="exame",
                    valor=2000,
                    valor_final=2000,
                    valor_taxa=100,
                    status="Recebido",
                    clinica_id=animal.id,
                    data_transacao=now - timedelta(days=100),
                ),
                Transacao(
                    tipo="entrada",
                    categoria="exame",
                    valor=3000,
                    valor_final=3000,
                    status="Pago",
                    clinica_id=vet.id,
                    data_transacao=now - timedelta(days=3),
                ),
            ]
        )
        db.add(
            OrdemServico(
                numero_os="OS-360-1",
                agendamento_id=1,
                paciente_id=99,
                clinica_id=animal.id,
                servico_id=service.id,
                data_atendimento=now - timedelta(days=4),
                valor_final=300,
                status="Pendente",
            )
        )
        db.add(
            ContaReceber(
                descricao="Debito Animal Care",
                cliente="Nao deve sair no perfil",
                valor=400,
                data_vencimento=now - timedelta(days=20),
                status="Atrasado",
                clinica_id=animal.id,
            )
        )
        db.add(
            AssistenteIAMemoria(
                id="memory-animal-care",
                titulo="Preferencia Animal Care",
                conteudo="Na Animal Care, confirmar a agenda pela manha.",
                categoria="clinica",
                origem="admin",
                status="approved",
                criado_por_id=7,
                aprovado_por_id=7,
                aprovado_em=now - timedelta(days=1),
            )
        )
        db.commit()
        return animal, vet, conversation

    def test_profile_consolidates_live_metrics_alerts_and_provenance(self) -> None:
        with self._session_factory() as db:
            animal, _, _ = self._seed(db)
            result = assistente_ia_clinics360.clinic_360_profile(db, animal.id, period_days=90)

        self.assertTrue(result["ok"])
        profile = result["profile"]
        self.assertEqual(profile["clinic"]["name"], "Animal Care")
        self.assertEqual(profile["appointments"]["total"], 5)
        self.assertEqual(profile["appointments"]["cancelled"], 2)
        self.assertEqual(profile["appointments"]["cancellation_rate"], 40.0)
        self.assertEqual(profile["appointments"]["top_services"][0]["name"], "Ecocardiograma")
        self.assertEqual(profile["finance"]["revenue"], 1000.0)
        self.assertEqual(profile["finance"]["previous_revenue"], 2000.0)
        self.assertEqual(profile["finance"]["revenue_change_percent"], -50.0)
        self.assertEqual(profile["debts"]["overdue_receivables"]["total"], 400.0)
        self.assertEqual(len(profile["relationship"]["approved_preferences"]), 1)
        self.assertTrue(profile["provenance"]["read_only"])
        self.assertFalse(profile["provenance"]["contains_patient_or_tutor_data"])
        self.assertEqual(
            {item["key"] for item in profile["alerts"]},
            {"revenue_drop", "cancellation_rate", "overdue_debt"},
        )
        plans = profile["action_plan"]
        self.assertEqual(plans["status"], "attention")
        self.assertTrue(plans["requires_admin_approval"])
        self.assertFalse(plans["automatic_execution"])
        self.assertFalse(plans["external_send"])
        self.assertEqual(
            {item["source_alert"] for item in plans["items"]},
            {"revenue_drop", "cancellation_rate", "overdue_debt"},
        )
        debt_plan = next(item for item in plans["items"] if item["source_alert"] == "overdue_debt")
        self.assertEqual(debt_plan["priority"], "critical")
        mission_step = next(
            item for item in debt_plan["steps"] if item["kind"] == "read_only_mission"
        )
        self.assertEqual(mission_step["mission_template"]["type"], "clinic_360")
        self.assertTrue(mission_step["mission_template"]["read_only"])
        self.assertTrue(mission_step["requires_admin_approval"])
        self.assertTrue(all(not item["external_send"] for item in debt_plan["steps"]))
        self.assertTrue(all(not item["automatic_business_write"] for item in debt_plan["steps"]))
        serialized = str(profile).lower()
        self.assertNotIn("paciente_id", serialized)
        self.assertNotIn("tutor_id", serialized)
        self.assertNotIn("nao deve sair no perfil", serialized)

    def test_portfolio_and_comparison_use_same_deterministic_contract(self) -> None:
        with self._session_factory() as db:
            animal, vet, _ = self._seed(db)
            portfolio = assistente_ia_clinics360.list_clinics_360(db, period_days=90)
            comparison = assistente_ia_clinics360.compare_clinics_360(
                db,
                [animal.id, vet.id],
                period_days=90,
            )

        self.assertEqual(portfolio["portfolio"]["clinics"], 2)
        self.assertEqual(portfolio["portfolio"]["revenue"], 4000.0)
        self.assertIn("items_count", portfolio["items"][0]["action_plan"])
        self.assertNotIn("items", portfolio["items"][0]["action_plan"])
        self.assertEqual(comparison["insights"][0]["clinic_name"], "Vet World")
        self.assertEqual(comparison["insights"][1]["clinic_name"], "Animal Care")
        self.assertTrue(comparison["provenance"]["read_only"])

    def test_assistant_tools_resolve_names_and_remain_read_only(self) -> None:
        with self._session_factory() as db:
            _, _, conversation = self._seed(db)
            context = assistente_ia_tools.AssistenteIAToolContext(
                db=db,
                current_user=SimpleNamespace(id=7, nome="Admin"),
                conversa=conversation,
            )
            profile = assistente_ia_tools.consultar_clinica_360(
                context,
                clinica="animal care",
                periodo_dias=90,
            )
            comparison = assistente_ia_tools.comparar_clinicas_360(
                context,
                clinicas=["Animal Care", "Vet World"],
                periodo_dias=90,
            )

        self.assertTrue(profile["ok"])
        self.assertEqual(len(comparison["items"]), 2)
        definitions = {item["name"]: item for item in assistente_ia_tools.TOOL_DEFINITIONS}
        self.assertTrue(definitions["consultar_clinica_360"]["strict"])
        self.assertTrue(definitions["comparar_clinicas_360"]["strict"])


if __name__ == "__main__":
    unittest.main()
