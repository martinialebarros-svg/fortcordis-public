"""Contrato HTTP independente, com PostgreSQL local e schemas descartáveis."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import threading
import unittest
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pypdf import PdfReader
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "fiscal-rotina-independent-test-secret-key-1234567890")

canary_spec = importlib.util.spec_from_file_location("fiscal_rotina_canary_guard", ROOT / "scripts/fiscal_rotina_stage_canary.py")
canary = importlib.util.module_from_spec(canary_spec)
canary_spec.loader.exec_module(canary)
FORTALEZA = ZoneInfo("America/Fortaleza")


class FiscalRotinaCanaryGuardTest(unittest.TestCase):
    def test_allowlist_stage_host_e_pooler_sem_abrir_conexao(self):
        for url in (
            "postgresql://postgres:synthetic@db.dtguubpzjrkvqjryazjq.supabase.co/postgres",
            "postgresql://postgres.dtguubpzjrkvqjryazjq:synthetic@aws-0-us-east-1.pooler.supabase.com/postgres",
        ):
            canary._validar_destino(Path("/var/www/fortcordis-stage"), "stage", url)

    def test_producao_unknown_path_e_ambiente_sao_recusados_sem_expor_url(self):
        cases = [
            ("/var/www/fortcordis-v2", "stage", "postgresql://postgres:synthetic@db.dtguubpzjrkvqjryazjq.supabase.co/postgres"),
            ("/var/www/fortcordis-stage", "production", "postgresql://postgres:synthetic@db.dtguubpzjrkvqjryazjq.supabase.co/postgres"),
            ("/var/www/fortcordis-stage", "stage", "postgresql://postgres:synthetic@db.wycxoueogfxdhyouhfhw.supabase.co/postgres"),
            ("/var/www/fortcordis-stage", "stage", "postgresql://postgres.wycxoueogfxdhyouhfhw:synthetic@aws-0-us-east-1.pooler.supabase.com/postgres"),
            ("/var/www/fortcordis-stage", "stage", "postgresql://postgres.wycxoueogfxdhyouhfhw:synthetic@db.dtguubpzjrkvqjryazjq.supabase.co/postgres"),
            ("/var/www/fortcordis-stage", "stage", "postgresql://postgres:synthetic@127.0.0.1:55439/fiscal_test"),
            ("/var/www/fortcordis-stage", "stage", "https://postgres:synthetic@db.dtguubpzjrkvqjryazjq.supabase.co/postgres"),
            ("/var/www/fortcordis-stage", "stage", "postgresql://postgres:synthetic@db.abcdefghijklmnopqrst.supabase.co/postgres"),
        ]
        for root, env, url in cases:
            with self.subTest(root=root, env=env), self.assertRaises(RuntimeError) as context:
                canary._validar_destino(Path(root), env, url)
            self.assertNotIn("synthetic", str(context.exception))


@unittest.skipUnless(os.environ.get("FISCAL_TEST_POSTGRES_URL"), "PostgreSQL local descartável não configurado")
class FiscalRotinaPostgresTest(unittest.TestCase):
    def setUp(self):
        from app.api.v1.endpoints import fiscal as fiscal_api
        from app.core.security import get_current_user
        from app.db.database import get_db
        from app.models.agendamento import Agendamento
        from app.models.atendimento_clinico import AtendimentoClinico
        from app.models.clinica import Clinica
        from app.models.configuracao import Configuracao
        from app.models.fiscal import FiscalAndamentoEvento, FiscalFechamento, FiscalFechamentoOS, FiscalRotinaPreferencia, NotaFiscal, RelatorioFiscalEmissao
        from app.models.laudo import Laudo
        from app.models.ordem_servico import OrdemServico
        from app.models.paciente import Paciente
        from app.models.servico import Servico
        from app.models.tutor import Tutor
        from app.services import fiscal_rotina_service

        self.models = SimpleNamespace(**{model.__name__: model for model in (
            Clinica, Tutor, Paciente, Servico, Agendamento, AtendimentoClinico, Laudo, OrdemServico,
            Configuracao, NotaFiscal, RelatorioFiscalEmissao, FiscalFechamento, FiscalFechamentoOS,
            FiscalRotinaPreferencia, FiscalAndamentoEvento,
        )})
        self.rotina = fiscal_rotina_service
        url = os.environ["FISCAL_TEST_POSTGRES_URL"]
        parsed = make_url(url)
        if parsed.host not in {"localhost", "127.0.0.1", "::1"} or parsed.database != "fiscal_test":
            raise RuntimeError("Estes testes exigem o PostgreSQL local descartável fiscal_test.")
        self.schema = "fiscal_rotina_test_" + uuid4().hex
        self.admin = create_engine(url)
        self.addCleanup(self.admin.dispose)
        with self.admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        self.addCleanup(self._drop_schema)
        self.engine = create_engine(url, connect_args={"options": f"-csearch_path={self.schema} -ctimezone=UTC"})
        self.addCleanup(self.engine.dispose)
        for model in vars(self.models).values():
            model.__table__.create(self.engine, checkfirst=True)
        self.sessions = sessionmaker(bind=self.engine)
        self.db = self.sessions()
        self.addCleanup(self.db.close)
        self._seed()
        self.app = FastAPI()
        self.app.include_router(fiscal_api.router, prefix="/api/v1/fiscal")

        def isolated_db():
            with self.sessions() as db:
                yield db

        self.app.dependency_overrides[get_db] = isolated_db
        self.auth_dependency = get_current_user
        self.app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=7, nome="Equipe Fiscal Sintética")
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def _drop_schema(self):
        with self.admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{self.schema}" CASCADE'))

    def _seed(self):
        m = self.models
        self.db.add_all([
            m.Clinica(id=1, nome="Clínica Sintética A", razao_social="Clínica A Ltda", cnpj="11222333000181", endereco="Rua A", numero="1", bairro="Centro", cidade="Fortaleza", estado="CE", cep="60000-000", ativo=False),
            m.Clinica(id=2, nome="OUTRO TOMADOR PRIVADO", razao_social="OUTRO TOMADOR PRIVADO", cnpj="123", ativo=False),
            # CNPJ real somente neste schema PostgreSQL local descartável.
            m.Clinica(id=3, nome="QA Regra específica", razao_social="QA Regra específica", cnpj="14.986.833/0001-88", endereco="Rua C", bairro="Centro", cidade="Fortaleza", estado="CE", cep="60000-000", ativo=False),
            m.Tutor(id=1, nome="TUTOR PRIVADO SENTINELA", nome_key="tutorprivadosentinela", cpf="52998224725", ativo=0),
            m.Paciente(id=1, nome="PACIENTE PRIVADO SENTINELA", nome_key="pacienteprivadosentinela", tutor_id=1, especie="Canina", ativo=0),
            m.Servico(id=1, nome="Ecocardiograma", ativo=False),
            m.Configuracao(nome_empresa="Fort Cordis teste isolado"),
        ])
        self.db.commit()

    def _os(self, os_id, *, data="2026-08-01T10:00:00-03:00", clinica_id=1, proof="agenda", status="Pendente"):
        m = self.models
        when = datetime.fromisoformat(data)
        agenda_id = None
        laudo_id = None
        if proof in {"agenda", "atendimento", "agendado"}:
            agenda_id = 1000 + os_id
            self.db.add(m.Agendamento(id=agenda_id, paciente_id=1, tutor_id=1, clinica_id=clinica_id, servico_id=1,
                                     inicio=when, fim=when + timedelta(minutes=30),
                                     updated_at=when,
                                     status="Realizado" if proof == "agenda" else "Agendado"))
        if proof == "atendimento":
            self.db.add(m.AtendimentoClinico(id=2000 + os_id, paciente_id=1, tutor_id=1, clinica_id=clinica_id,
                                             agendamento_id=agenda_id, veterinario_id=7, data_atendimento=when,
                                             status="Concluido", especie="Canina"))
        if proof == "laudo":
            laudo_id = 3000 + os_id
            self.db.add(m.Laudo(id=laudo_id, paciente_id=1, veterinario_id=7, clinic_id=clinica_id,
                                tipo="eletrocardiograma", titulo="Laudo sintético", status="Finalizado", data_exame=when))
        self.db.add(m.OrdemServico(id=os_id, numero_os=f"QA-ROTINA-{os_id}", paciente_id=1, clinica_id=clinica_id,
                                   servico_id=1, agendamento_id=agenda_id, laudo_id=laudo_id,
                                   data_atendimento=when, valor_servico=Decimal("100.10"), desconto=Decimal("0.00"),
                                   valor_final=Decimal("100.10"), status=status, origem_atendimento="clinica_parceira"))
        self.db.commit()

    def _preview(self, *, modo="semanal", competencia="2026-08", clinica_id=1, data_corte="2026-08-30"):
        params = {"competencia": competencia, "modo": modo}
        if clinica_id is not None:
            params["clinica_id"] = clinica_id
        if data_corte is not None:
            params["data_corte"] = data_corte
        response = self.client.get("/api/v1/fiscal/rotinas/previa", params=params)
        self.assertEqual(response.status_code, 200, response.text[:300])
        return response.json()

    def _preference(self, *, clinic_id=1, modo="por_servico", version=0, depends=True):
        return self.client.put(f"/api/v1/fiscal/rotinas/clinicas/{clinic_id}", json={
            "modo": modo, "pagamento_depende_nf": depends, "versao_esperada": version,
        })

    def _prepare(self, ids, *, modo="semanal", clinic_id=1, key=None):
        payload = {"competencia": "2026-08", "modo": modo, "clinica_id": clinic_id, "os_ids": ids,
                   "chave_idempotencia": str(key or uuid4()), "confirmar_datas_prestacao": True}
        if modo == "semanal":
            payload["data_corte"] = "2026-08-30"
        return self.client.post("/api/v1/fiscal/rotinas/preparar", json=payload)

    def _event(self, os_id, destination, version, *, key=None, reference=None, confirmed=True):
        payload = {"destino": destination, "versao_esperada": version,
                   "chave_idempotencia": str(key or uuid4()), "confirmar_acao_manual": confirmed}
        if reference is not None:
            payload["referencia_nota"] = reference
        return self.client.post(f"/api/v1/fiscal/os/{os_id}/andamento", json=payload)

    def _fresh_counts(self):
        with self.sessions() as db:
            return tuple(db.query(model).count() for model in (self.models.FiscalFechamento, self.models.FiscalFechamentoOS, self.models.FiscalAndamentoEvento, self.models.NotaFiscal))

    def test_get_sem_mutacao_defaults_vet_fauna_e_override_cas(self):
        response = self.client.get("/api/v1/fiscal/rotinas")
        self.assertEqual(response.status_code, 200)
        rows = {row["clinica_id"]: row for row in response.json()["clinicas"]}
        self.assertEqual((rows[1]["modo"], rows[1]["pagamento_depende_nf"], rows[1]["versao"]), ("semanal", False, 0))
        self.assertEqual((rows[3]["modo"], rows[3]["pagamento_depende_nf"], rows[3]["versao"]), ("por_servico", True, 0))
        with self.sessions() as db:
            self.assertEqual(db.query(self.models.FiscalRotinaPreferencia).count(), 0)
        updated = self._preference(clinic_id=3, modo="semanal", depends=False)
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["versao"], 1)
        stale = self._preference(clinic_id=3, version=0)
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()["detail"]["versao_atual"], 1)

    def test_proximo_domingo_17_fortaleza_antes_e_exatamente_no_corte(self):
        for now, expected in [("2026-10-18T16:59:59-03:00", "2026-10-18T17:00:00-03:00"),
                              ("2026-10-18T17:00:00-03:00", "2026-10-18T17:00:00-03:00"),
                              ("2026-10-18T17:00:00.000001-03:00", "2026-10-25T17:00:00-03:00")]:
            with self.subTest(now=now), patch.object(self.rotina, "_agora_local", return_value=datetime.fromisoformat(now)):
                preview = self._preview(competencia="2026-10", data_corte=None)
                self.assertEqual(preview["rotina"]["corte_em"], expected)
                self.assertEqual(preview["rotina"]["timezone"], "America/Fortaleza")
                self.assertEqual(preview["rotina"]["horario"], "17:00")
                self.assertIs(preview["rotina"]["automatico"], False)

    def test_backlog_direto_futuro_e_mes_nao_misturam_com_pg_em_utc(self):
        self.assertEqual(self.db.execute(text("SHOW TIME ZONE")).scalar(), "UTC")
        self._os(1, data="2026-08-01T10:00:00-03:00")
        self._os(2, data="2026-08-30T20:00:00+00:00")
        self._os(3, data="2026-08-30T20:00:01+00:00")
        self._os(4, data="2026-09-01T03:00:00+00:00")
        self._os(5, data="2026-08-10T10:00:00-03:00", proof="agendado", status="Pago")
        with patch.object(self.rotina, "_agora_local", return_value=datetime.fromisoformat("2026-08-30T19:00:00-03:00")):
            items = {row["os_id"]: row for row in self._preview()["items"]}
        self.assertNotIn(4, items)
        self.assertTrue(items[1]["elegivel"])
        self.assertTrue(items[2]["elegivel"])
        self.assertNotIn(3, items)
        self.assertFalse(items[5]["elegivel"])
        self.assertFalse(items[5]["realizacao_confirmada"])

    def test_prestacao_futura_dentro_do_proximo_corte_fica_pendente(self):
        self._os(1, data="2026-08-30T16:30:00-03:00")
        with patch.object(self.rotina, "_agora_local", return_value=datetime.fromisoformat("2026-08-30T16:00:00-03:00")):
            items = self._preview()["items"]
        self.assertEqual(len(items), 1)
        self.assertFalse(items[0]["elegivel"])
        self.assertTrue(any("futura" in reason for reason in items[0]["motivos_pendencia"]))

    def test_limite_competencia_utc_local_recusa_pacote_misto(self):
        self._os(1, data="2026-09-01T02:59:59+00:00")
        self._os(2, data="2026-09-01T03:00:00+00:00")
        preview = self._preview(data_corte="2026-09-06")
        self.assertEqual([item["os_id"] for item in preview["items"]], [1])
        response = self.client.post("/api/v1/fiscal/rotinas/preparar", json={
            "competencia": "2026-08", "modo": "semanal", "clinica_id": 1,
            "data_corte": "2026-09-06", "os_ids": [1, 2],
            "chave_idempotencia": str(uuid4()), "confirmar_datas_prestacao": True,
        })
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self._fresh_counts(), (0, 0, 0, 0))

    def test_provas_exigem_vinculo_e_nunca_paciente_data(self):
        for os_id, proof in [(1, "agenda"), (2, "atendimento"), (3, "laudo"), (4, "sem_evidencia")]:
            self._os(os_id, proof=proof)
        self.db.add(self.models.Laudo(paciente_id=1, veterinario_id=7, clinic_id=1, tipo="eletrocardiograma", titulo="Mesmo paciente e data", status="Finalizado", data_exame=datetime.fromisoformat("2026-08-01T10:00:00-03:00")))
        self.db.commit()
        items = {row["os_id"]: row for row in self._preview()["items"]}
        for os_id, source in [(1, "agenda"), (2, "atendimento"), (3, "laudo")]:
            self.assertTrue(items[os_id]["realizacao_confirmada"])
            self.assertEqual(items[os_id]["fonte_realizacao"], source)
        self.assertFalse(items[4]["elegivel"])
        self.assertEqual(items[4]["fonte_realizacao"], "sem_evidencia")

    def test_por_servico_uma_os_mesmo_servico_scope_e_parametros(self):
        self._os(1)
        self._os(2, proof="laudo")
        self.assertEqual(self._preference().status_code, 200)
        self.assertEqual(self._prepare([1, 2], modo="por_servico").status_code, 422)
        self.assertEqual(self._fresh_counts(), (0, 0, 0, 0))
        response = self._prepare([1], modo="por_servico")
        self.assertEqual(response.status_code, 200, response.text[:200] if response.status_code != 200 else "")
        self.assertEqual(self._fresh_counts(), (1, 1, 0, 0))
        preview = self._preview(modo="por_servico", data_corte=None)
        self.assertIsNone(preview["rotina"]["data_corte"])
        self.assertIsNone(preview["rotina"]["corte_em"])
        self.assertIsNone(preview["rotina"]["proxima_preparacao_em"])
        self.assertEqual(self.client.get("/api/v1/fiscal/rotinas/previa", params={"competencia": "2026-08", "modo": "por_servico", "data_corte": "2026-08-30"}).status_code, 422)
        self.assertEqual(self._prepare([2], modo="semanal").status_code, 409)

    def test_snapshot_single_clinic_omite_outros_cadastros_e_clinica(self):
        self._os(1)
        self._os(2, proof="sem_evidencia")
        self._os(3, clinica_id=2)
        self.assertEqual(self._preference().status_code, 200)
        preview = self._preview(modo="por_servico", data_corte=None)
        self.assertEqual({row["os_id"] for row in preview["items"]}, {1, 2})
        response = self._prepare([1], modo="por_servico")
        self.assertEqual(response.status_code, 200)
        with self.sessions() as db:
            package = db.get(self.models.FiscalFechamento, int(response.headers["X-Fechamento-Id"]))
            self.assertNotIn("OUTRO TOMADOR PRIVADO", package.snapshot_json)
            self.assertNotIn("PACIENTE PRIVADO", package.snapshot_json)
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            texts = [archive.read("manifesto.json").decode(), archive.read("mensagem_contador.txt").decode()]
            texts += [page.extract_text() for page in PdfReader(io.BytesIO(archive.read("conferencia_contador.pdf"))).pages]
            with zipfile.ZipFile(io.BytesIO(archive.read("servicos_contador.xlsx"))) as workbook:
                texts += [workbook.read(name).decode(errors="replace") for name in workbook.namelist() if name.endswith(".xml")]
            for private in ("OUTRO TOMADOR PRIVADO", "PACIENTE PRIVADO", "TUTOR PRIVADO"):
                self.assertNotIn(private, "\n".join(texts))

    def test_andamento_manual_sequencial_retry_sem_nf_e_zip_imutavel(self):
        self._os(1)
        key = uuid4()
        prepared = self._prepare([1], key=key)
        self.assertEqual(prepared.status_code, 200)
        package_id = int(prepared.headers["X-Fechamento-Id"])
        self.assertEqual(self._event(1, "nota_recebida", 0, reference="QA-123").status_code, 422)
        self.assertEqual(self._event(1, "enviado_contador", 0, confirmed=False).status_code, 422)
        first_key = uuid4()
        first = self._event(1, "enviado_contador", 0, key=first_key)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(self._event(1, "enviado_contador", 0, key=first_key).status_code, 200)
        self.assertEqual(self._event(1, "nota_recebida", 1).status_code, 422)
        self.assertEqual(self._event(1, "nota_recebida", 1, reference="QA-123").status_code, 200)
        self.assertEqual(self._event(1, "nota_encaminhada", 2).status_code, 200)
        states = self.client.get(f"/api/v1/fiscal/fechamentos/{package_id}/andamentos").json()["items"]
        self.assertEqual(len(states), 1)
        self.assertEqual((states[0]["etapa"], states[0]["versao"]), ("nota_encaminhada", 3))
        self.assertEqual([event["versao"] for event in states[0]["eventos"]], [1, 2, 3])
        self.assertTrue(all(event["usuario_id"] == 7 for event in states[0]["eventos"]))
        self.assertEqual(self._fresh_counts(), (1, 1, 3, 0))
        self.assertEqual(self._preference(modo="por_servico").status_code, 200)
        self.db.get(self.models.OrdemServico, 1).valor_final = Decimal("999.00")
        self.db.commit()
        download = self.client.get(f"/api/v1/fiscal/fechamentos/{package_id}/download")
        self.assertEqual(download.content, prepared.content)
        self.assertEqual(self._prepare([1], key=key).content, prepared.content)
        with self.sessions() as db:
            package = db.get(self.models.FiscalFechamento, package_id)
            self.assertEqual(package.checksum, hashlib.sha256(prepared.content).hexdigest())
            self.assertEqual(db.get(self.models.OrdemServico, 1).status, "Pendente")

    def _race(self, action):
        barrier = threading.Barrier(2)
        def work(unused):
            with TestClient(self.app) as client:
                barrier.wait(timeout=10)
                return action(client)
        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(work, range(2)))

    def test_pg_cas_preferencia_primeira_escrita_concorrente(self):
        results = self._race(lambda client: client.put("/api/v1/fiscal/rotinas/clinicas/1", json={"modo": "por_servico", "pagamento_depende_nf": True, "versao_esperada": 0}))
        self.assertEqual(sorted(response.status_code for response in results), [200, 409])
        with self.sessions() as db:
            self.assertEqual(db.query(self.models.FiscalRotinaPreferencia).count(), 1)
            self.assertEqual(db.get(self.models.FiscalRotinaPreferencia, 1).versao, 1)

    def test_pg_cas_andamento_duas_chaves_uma_versao_sem_evento_perdedor(self):
        self._os(1)
        self.assertEqual(self._prepare([1]).status_code, 200)
        results = self._race(lambda client: client.post("/api/v1/fiscal/os/1/andamento", json={"destino": "enviado_contador", "versao_esperada": 0, "chave_idempotencia": str(uuid4()), "confirmar_acao_manual": True}))
        self.assertEqual(sorted(response.status_code for response in results), [200, 409])
        self.assertEqual(self._fresh_counts(), (1, 1, 1, 0))

    def test_pg_retry_andamento_mesma_chave_nao_duplica(self):
        self._os(1)
        self.assertEqual(self._prepare([1]).status_code, 200)
        key = str(uuid4())
        results = self._race(lambda client: client.post("/api/v1/fiscal/os/1/andamento", json={"destino": "enviado_contador", "versao_esperada": 0, "chave_idempotencia": key, "confirmar_acao_manual": True}))
        self.assertEqual([response.status_code for response in results], [200, 200])
        self.assertEqual(self._fresh_counts(), (1, 1, 1, 0))

    def test_pg_retry_semanal_concorrente_cruzando_corte_reusa_primeiro_pacote(self):
        from app.services import fiscal_export_service
        self._os(1)
        key = str(uuid4())
        payload = {"competencia": "2026-08", "modo": "semanal", "clinica_id": 1,
                   "os_ids": [1], "chave_idempotencia": key, "confirmar_datas_prestacao": True}
        first_generating = threading.Event()
        second_context = threading.Event()
        release = threading.Event()
        original_context = self.rotina._contexto

        def clock():
            value = "2026-10-18T17:00:00.000001-03:00" if first_generating.is_set() else "2026-10-18T16:59:59-03:00"
            return datetime.fromisoformat(value)

        def context(*args, **kwargs):
            result = original_context(*args, **kwargs)
            if result["corte_em"] == "2026-10-25T17:00:00-03:00":
                second_context.set()
            return result

        def generate(*args, **kwargs):
            first_generating.set()
            if not release.wait(timeout=10):
                raise RuntimeError("A segunda requisição não chegou ao corte no teste.")
            return b"PK-pacote-concorrente-fronteira", "fronteira.zip"

        def request():
            with TestClient(self.app) as client:
                return client.post("/api/v1/fiscal/rotinas/preparar", json=payload)

        with patch.object(self.rotina, "_agora_local", side_effect=clock), patch.object(self.rotina, "_contexto", side_effect=context), patch.object(fiscal_export_service, "gerar_pacote_contador", side_effect=generate), ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(request)
            try:
                self.assertTrue(first_generating.wait(timeout=10))
                second = pool.submit(request)
                self.assertTrue(second_context.wait(timeout=10))
            finally:
                release.set()
            responses = [first.result(timeout=10), second.result(timeout=10)]
        self.assertEqual([response.status_code for response in responses], [200, 200])
        self.assertEqual(responses[0].content, responses[1].content)
        self.assertEqual(self._fresh_counts(), (1, 1, 0, 0))

    def test_rotas_sem_autenticacao_401_e_sem_writes(self):
        self.app.dependency_overrides.pop(self.auth_dependency)
        for path in ("/rotinas", "/rotinas/previa?competencia=2026-08&modo=semanal", "/fechamentos/1/andamentos"):
            self.assertEqual(self.client.get("/api/v1/fiscal" + path).status_code, 401)
        self.assertEqual(self._event(1, "enviado_contador", 0).status_code, 401)
        self.assertEqual(self._preference().status_code, 401)
        self.assertEqual(self._prepare([1]).status_code, 401)
        self.assertEqual(self._fresh_counts(), (0, 0, 0, 0))

    def test_migracao_98_aditiva_idempotente_rls_e_revokes(self):
        paths = list((ROOT / "backend/migrations/versions").glob("*_98_*.py"))
        self.assertEqual(len(paths), 1)
        spec = importlib.util.spec_from_file_location("fiscal_rotina_migration_98", paths[0])
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        tables = ("fiscal_andamento_eventos", "fiscal_rotinas_clinicas")
        with self.engine.begin() as connection:
            for table in tables:
                connection.execute(text(f"DROP TABLE {table}"))
            migration.upgrade(connection, "postgresql")
            for table in tables:
                connection.execute(text(f"GRANT ALL ON TABLE {table} TO PUBLIC, anon, authenticated"))
            migration.upgrade(connection, "postgresql")
            for table in tables:
                self.assertTrue(connection.execute(text("SELECT relrowsecurity FROM pg_class WHERE oid = CAST(:table AS regclass)"), {"table": table}).scalar())
                for role in ("anon", "authenticated"):
                    self.assertFalse(connection.execute(text("SELECT has_table_privilege(:role, :table, 'SELECT,INSERT,UPDATE,DELETE')"), {"role": role, "table": table}).scalar())
            self.assertIn("fiscal_fechamentos", inspect(connection).get_table_names())
            self.assertEqual(connection.execute(text("SELECT count(*) FROM notas_fiscais")).scalar(), 0)


if __name__ == "__main__":
    unittest.main()
