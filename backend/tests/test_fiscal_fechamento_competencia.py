import hashlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import threading
import unittest
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "fiscal-fechamento-local-test-secret-key-1234567890")

from app.models.clinica import Clinica
from app.models.configuracao import Configuracao
from app.models.fiscal import FiscalFechamento, FiscalFechamentoOS, NotaFiscal, RelatorioFiscalEmissao
from app.models.ordem_servico import OrdemServico
from app.models.paciente import Paciente
from app.models.servico import Servico
from app.models.tutor import Tutor
from app.schemas.fiscal import FiscalFechamentoCreate
from app.api.v1.endpoints import fiscal as fiscal_api
from app.core.security import get_current_user
from app.db.database import get_db
from app.services import fiscal_export_service, fiscal_fechamento_service as fiscal, fiscal_service

TABLES = [Clinica.__table__, Tutor.__table__, Paciente.__table__, Servico.__table__, OrdemServico.__table__, Configuracao.__table__, NotaFiscal.__table__, RelatorioFiscalEmissao.__table__, FiscalFechamento.__table__, FiscalFechamentoOS.__table__]


def _migration():
    path = BACKEND_DIR / "migrations/versions/20261014_97_fiscal_fechamento_competencia.py"
    spec = importlib.util.spec_from_file_location("fiscal_migration_97", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FiscalFechamentoTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{self.tmpdir.name}/fiscal.db")
        for table in TABLES:
            table.create(self.engine, checkfirst=True)
        self.sessions = sessionmaker(bind=self.engine)
        self.db = self.sessions()
        self._cadastros()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        self.tmpdir.cleanup()

    def _cadastros(self):
        self.db.add_all([
            Clinica(id=1, nome="Clínica parceira histórica", razao_social="Clínica Teste Ltda", cnpj="11.222.333/0001-81", endereco="Rua Teste", numero="10", bairro="Centro", cidade="Fortaleza", estado="CE", cep="60000-000", telefone="85999999999", ativo=False),
            Clinica(id=2, nome="Clínica incompleta", cnpj="123", ativo=True),
            Tutor(id=1, nome="Tomador A", cpf="529.982.247-25", endereco="Rua A", numero="20", complemento="Apto 1", bairro="Centro", cidade="Fortaleza", estado="CE", cep="60000-000", telefone="85999999999", email="a@example.test"),
            Tutor(id=2, nome="Tomador B", cpf="111.444.777-35", endereco="Rua B", bairro="Centro", cidade="Fortaleza", estado="CE", cep="60000-000"),
            Paciente(id=1, nome="DADO CLINICO NAO EXPORTAR", tutor_id=1),
            Paciente(id=2, nome="OUTRO PACIENTE PRIVADO", tutor_id=2),
            Servico(id=1, nome="Ecocardiograma"),
            Configuracao(nome_empresa="Fort Cordis teste"),
        ])
        self.db.commit()

    def _os(self, os_id, *, data="2026-08-31T10:00:00", clinica_id=1, paciente_id=1, status="Pendente", valor="100.00"):
        data_atendimento = datetime.fromisoformat(data) if data else None
        if data_atendimento is not None and data_atendimento.tzinfo is None:
            # A fixture descreve a prestação local; TIMESTAMPTZ interpreta valores
            # naive pelo fuso da sessão, que no CI é UTC. Declare o offset de origem.
            data_atendimento = data_atendimento.replace(tzinfo=ZoneInfo("America/Fortaleza"))
        row = OrdemServico(id=os_id, numero_os=f"OS-{os_id}", agendamento_id=os_id, paciente_id=paciente_id, clinica_id=clinica_id, servico_id=1, origem_atendimento="domiciliar" if clinica_id is None else "clinica_parceira", data_atendimento=data_atendimento, valor_servico=Decimal(valor), desconto=Decimal("0"), valor_final=Decimal(valor), status=status)
        self.db.add(row)
        self.db.commit()
        return row

    def _prepare(self, ids, *, key=None, **kwargs):
        with patch.object(fiscal_export_service, "gerar_pacote_contador", return_value=(b"PK-pacote-persistido", "contador.zip"), create=True):
            return fiscal.preparar_fechamento(self.db, competencia=kwargs.pop("competencia", "2026-08"), os_ids=ids, chave_idempotencia=key or uuid4(), confirmar_datas_prestacao=kwargs.pop("confirmar_datas_prestacao", True), usuario_id=7, usuario_nome="Equipe Fiscal", **kwargs)

    def test_previa_preserva_inativas_pendente_pagamento_e_expoe_motivos(self):
        self._os(1)
        self._os(2, status="Cancelado", valor="200.00")
        self._os(3, clinica_id=2, valor="300.00")
        self._os(4, data="2026-09-01T00:00:00")
        self._os(5, clinica_id=None)
        self._os(6, data=None)
        previa = fiscal.previa_fechamento(self.db, "2026-08")
        by_id = {item["os_id"]: item for item in previa["items"]}
        self.assertEqual(set(by_id), {1, 2, 3, 5, 6})
        self.assertTrue(by_id[1]["elegivel"])
        self.assertTrue(by_id[5]["elegivel"])
        self.assertFalse(by_id[2]["elegivel"])
        self.assertIn("OS cancelada.", by_id[2]["motivos_pendencia"])
        self.assertFalse(by_id[3]["elegivel"])
        self.assertFalse(by_id[6]["elegivel"])
        self.assertEqual(by_id[5]["cliente_nome"], "Tomador A")
        self.assertEqual(by_id[5]["cliente_endereco"], "Rua A, 20, Apto 1")
        self.assertNotIn("paciente_nome", by_id[5])
        self.assertNotIn("tutor_nome", by_id[5])
        self.assertEqual(previa["resumo"]["valor_apto"], Decimal("200.00"))
        self.assertEqual(previa["resumo"]["valor_total"], Decimal("600.00"))

    def _endereco_fiscal(self, **changes):
        payload = dict(cnpj="11222333000181", endereco="Rua Fiscal Sintética", numero="500", complemento="",
                       bairro="Bairro Fiscal", cidade="Fortaleza", estado="CE", cep="60763730",
                       fonte_url="https://example.test/cartao-cnpj", conferido_em="2026-10-25T10:00:00-03:00", conferido_por=7)
        payload.update(changes)
        self.db.get(Clinica, 1).endereco_fiscal = payload
        self.db.commit()

    def test_endereco_fiscal_no_zip_preserva_endereco_e_pin_operacionais(self):
        from openpyxl import load_workbook
        from pypdf import PdfReader
        clinic = self.db.get(Clinica, 1)
        clinic.latitude, clinic.longitude, clinic.place_id = -3.75, -38.5, "pin-operacional"
        self.db.commit()
        before = {c.name: getattr(clinic, c.name) for c in Clinica.__table__.columns if c.name not in {"endereco_fiscal", "updated_at"}}
        self._endereco_fiscal()
        self._os(1)
        previa = fiscal.previa_fechamento(self.db, "2026-08")["items"][0]
        self.assertTrue(previa["elegivel"])
        self.assertEqual(previa["cliente_endereco"], "Rua Fiscal Sintética, 500")
        self.assertEqual(previa["cliente_bairro"], "Bairro Fiscal")
        self.assertEqual(previa["cliente_cep"], "60763730")
        self.assertEqual(previa["cliente_endereco_origem"], "cadastro_cnpj")
        with patch.object(fiscal_export_service, "_get_configuracao", return_value={}):
            pacote = fiscal.preparar_fechamento(self.db, competencia="2026-08", os_ids=[1], chave_idempotencia=uuid4(), confirmar_datas_prestacao=True, usuario_id=7, usuario_nome="Fiscal")
        with zipfile.ZipFile(io.BytesIO(pacote.pacote_bytes)) as archive:
            manifest = json.loads(archive.read("manifesto.json"))
            tomador = manifest["tomadores"][0]
            self.assertEqual(tomador["cliente_cep"], "60763730")
            self.assertEqual(tomador["cliente_endereco_fonte"], "https://example.test/cartao-cnpj")
            workbook = load_workbook(io.BytesIO(archive.read("servicos_contador.xlsx")))
            cells = [str(c.value) for sheet in workbook for row in sheet for c in row]
            self.assertIn("60763730", cells)
            self.assertNotIn("60000-000", cells)
            pdf = "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(archive.read("conferencia_contador.pdf"))).pages)
            self.assertIn("Rua Fiscal Sintética", pdf)
            self.assertIn("60763730", pdf)
            self.assertNotIn("60000-000", pdf)
        self.db.refresh(clinic)
        self.assertEqual(before, {c.name: getattr(clinic, c.name) for c in Clinica.__table__.columns if c.name in before})
        self.assertEqual(self.db.query(NotaFiscal).count(), 0)
        # Uma mudança fiscal futura não reescreve a segunda via persistida.
        old_bytes = pacote.pacote_bytes
        self._endereco_fiscal(cep="60100100")
        self.db.refresh(pacote)
        self.assertEqual(pacote.pacote_bytes, old_bytes)
        self.assertIn("60763730", pacote.snapshot_json)

    def test_fiscal_incompleto_ou_cnpj_trocado_fica_pendente_sem_misturar_enderecos(self):
        self._os(1)
        for changes in ({"cep": ""}, {"cnpj": "12345678000195"}, {"complemento": "", "bairro": ""}):
            self._endereco_fiscal(**changes)
            row = fiscal.previa_fechamento(self.db, "2026-08")["items"][0]
            self.assertFalse(row["elegivel"])
            self.assertEqual(row["cliente_cep"], "")
            self.assertEqual(row["cliente_endereco"], "")
            self.assertIn("Endereço fiscal incompleto", row["motivos_pendencia"][0])
            with self.assertRaises(fiscal.FiscalFechamentoError):
                self._prepare([1])
        self.assertEqual(self.db.query(FiscalFechamento).count(), 0)

    def test_sem_endereco_fiscal_e_pf_preservam_contrato_anterior(self):
        self._endereco_fiscal()
        self._os(1, clinica_id=None)
        self._os(2, clinica_id=2)
        items = {r["os_id"]: r for r in fiscal.previa_fechamento(self.db, "2026-08")["items"]}
        self.assertEqual(items[1]["cliente_endereco"], "Rua A, 20, Apto 1")
        self.assertEqual(items[1]["cliente_endereco_origem"], "cadastro_operacional")
        self.assertEqual(items[2]["cliente_endereco_origem"], "cadastro_operacional")

    def test_timezone_competencia_no_limite_e_naive_local(self):
        self.assertEqual(fiscal._data_local(datetime(2026, 9, 1, 2, 59, tzinfo=timezone.utc)).strftime("%Y-%m"), "2026-08")
        self.assertEqual(fiscal._data_local(datetime(2026, 9, 1, 3, 0, tzinfo=timezone.utc)).strftime("%Y-%m"), "2026-09")
        self.assertEqual(fiscal._data_local(datetime(2026, 8, 31, 23, 59)).strftime("%Y-%m"), "2026-08")

    def test_selecao_invalida_nao_prepara_parcial(self):
        self._os(1)
        self._os(2, status="Cancelado")
        self._os(3, data="2026-09-01T00:00:00")
        for ids in ([1, 999], [1, 2], [1, 3], [1, 1], [-1], []):
            with self.subTest(ids=ids):
                with self.assertRaises(fiscal.FiscalFechamentoError) as context:
                    self._prepare(ids)
                self.assertEqual(context.exception.status_code, 422)
                self.assertEqual(self.db.query(FiscalFechamento).count(), 0)
                self.assertEqual(self.db.query(FiscalFechamentoOS).count(), 0)
        with self.assertRaises(fiscal.FiscalFechamentoError):
            self._prepare([1], confirmar_datas_prestacao=False)

    def test_retry_preserva_bytes_snapshot_valores_e_nao_cria_nf(self):
        row = self._os(1, valor="100.10")
        key = uuid4()
        pacote = self._prepare([1], key=key)
        original_snapshot = pacote.snapshot_json
        row.valor_servico = Decimal("250")
        row.valor_final = Decimal("250")
        row.status = "Cancelado"
        self.db.commit()
        retry = self._prepare([1], key=key)
        self.assertEqual(retry.id, pacote.id)
        self.assertEqual(retry.pacote_bytes, b"PK-pacote-persistido")
        self.assertEqual(retry.snapshot_json, original_snapshot)
        self.assertEqual(retry.valor_total, Decimal("100.10"))
        self.assertEqual(retry.checksum, hashlib.sha256(retry.pacote_bytes).hexdigest())
        self.assertEqual(self.db.query(FiscalFechamento).count(), 1)
        self.assertEqual(self.db.query(FiscalFechamentoOS).count(), 1)
        self.assertEqual(self.db.query(NotaFiscal).count(), 0)
        self.assertNotIn("DADO CLINICO", retry.snapshot_json)
        self.assertNotIn("tutor_nome", retry.snapshot_json)
        with self.assertRaises(fiscal.FiscalFechamentoError) as context:
            self._prepare([1], key=key, confirmar_exportacoes_anteriores=True)
        self.assertEqual(context.exception.status_code, 409)
        self.assertEqual(context.exception.detail["fechamento_id"], pacote.id)

    def test_segundo_pacote_claim_e_legacy_export_nao_bypass(self):
        self._os(1)
        pacote = self._prepare([1])
        previa = fiscal.previa_fechamento(self.db, "2026-08")
        self.assertEqual(previa["items"][0]["fechamento_id"], pacote.id)
        self.assertFalse(previa["items"][0]["elegivel"])
        with self.assertRaises(fiscal.FiscalFechamentoError) as context:
            self._prepare([1])
        self.assertEqual(context.exception.status_code, 409)
        self.assertEqual(context.exception.detail["fechamento_id"], pacote.id)
        with self.assertRaises(ValueError):
            fiscal_service.buscar_os_por_ids_para_exportacao(self.db, [1])
        self.assertEqual(self.db.query(FiscalFechamento).count(), 1)

    def test_exportacao_anterior_exige_reconhecimento_e_historico_corrupto_falha(self):
        self._os(1)
        self.db.add(RelatorioFiscalEmissao(formato="xlsx", modo="uma_clinica", os_ids_json="[1,1]", quantidade_os=1, valor_total=100))
        self.db.commit()
        self.assertEqual(fiscal.previa_fechamento(self.db, "2026-08")["items"][0]["exportacoes_anteriores"], 1)
        with self.assertRaises(fiscal.FiscalFechamentoError):
            self._prepare([1])
        self._prepare([1], confirmar_exportacoes_anteriores=True)
        self.db.add(RelatorioFiscalEmissao(formato="xlsx", modo="uma_clinica", os_ids_json="registro inválido", quantidade_os=1, valor_total=100))
        self.db.commit()
        with self.assertRaises(fiscal.FiscalFechamentoError) as context:
            fiscal.previa_fechamento(self.db, "2026-08")
        self.assertEqual(context.exception.status_code, 503)

    def test_falha_geracao_rollback_sem_claims(self):
        self._os(1)
        with patch.object(fiscal_export_service, "gerar_pacote_contador", side_effect=RuntimeError("gerador falhou"), create=True):
            with self.assertRaises(RuntimeError):
                fiscal.preparar_fechamento(self.db, competencia="2026-08", os_ids=[1], chave_idempotencia=uuid4(), confirmar_datas_prestacao=True)
        self.assertEqual(self.db.query(FiscalFechamento).count(), 0)
        self.assertEqual(self.db.query(FiscalFechamentoOS).count(), 0)
        self._prepare([1])

    def test_download_checksum_e_historico_sem_mutacao(self):
        self._os(1)
        pacote = self._prepare([1])
        self.assertEqual(fiscal.buscar_fechamento(self.db, pacote.id).pacote_bytes, pacote.pacote_bytes)
        history = fiscal.listar_fechamentos(self.db, competencia="2026-08")
        self.assertEqual(history["total"], 1)
        self.assertNotIn("pacote_bytes", history["items"][0])
        pacote.pacote_bytes = b"corrompido"
        self.db.commit()
        with self.assertRaises(fiscal.FiscalFechamentoError) as context:
            fiscal.buscar_fechamento(self.db, pacote.id)
        self.assertEqual(context.exception.status_code, 503)

    def test_schema_recusa_ids_repetidos_invalidos_e_tipo_coercivo(self):
        base = {"competencia": "2026-08", "chave_idempotencia": uuid4(), "confirmar_datas_prestacao": True}
        for ids in ([1, 1], [0], [-1], [True], ["1"], [1.0]):
            with self.subTest(ids=ids), self.assertRaises(ValidationError):
                FiscalFechamentoCreate(**base, os_ids=ids)

    def test_cnpj_alfanumerico_cadastrado_preserva_letras_e_valida_dv(self):
        self._os(1)
        clinica = self.db.get(Clinica, 1)
        clinica.cnpj = "12.abc.345/01de-35"
        self.db.commit()
        item = fiscal.previa_fechamento(self.db, "2026-08")["items"][0]
        self.assertEqual(item["cliente_documento"], "12ABC34501DE35")
        self.assertTrue(item["elegivel"])
        self.assertTrue(fiscal._documento_valido("00000000E08G12", "PJ"))
        self.assertFalse(fiscal._documento_valido("12ABC34501DE36", "PJ"))
        self.assertFalse(fiscal._documento_valido("12ABC34501DE35", "PF"))
        pacote = self._prepare([1])
        self.assertEqual(json.loads(pacote.snapshot_json)["items"][0]["cliente_documento"], "12ABC34501DE35")

    def test_export_legacy_exclui_canceladas_e_nao_soma_ids_repetidos(self):
        self._os(1)
        self._os(2, status="Cancelado")
        items, total = fiscal_service.buscar_os_para_fiscal(self.db, data_inicio="2026-08-01", data_fim="2026-08-31")
        self.assertEqual(total, 1)
        self.assertEqual(items[0]["os_id"], 1)
        self.assertEqual(fiscal_service.buscar_os_por_ids_para_exportacao(self.db, [2]), [])
        with self.assertRaises(ValueError):
            fiscal_service.buscar_os_por_ids_para_exportacao(self.db, [1, 1])

    def test_migration_sqlite_idempotente_claim_unico_e_preserva_legado(self):
        migration = _migration()
        with create_engine("sqlite:///:memory:").begin() as connection:
            connection.execute(text("CREATE TABLE notas_fiscais (id INTEGER PRIMARY KEY, numero TEXT)"))
            connection.execute(text("INSERT INTO notas_fiscais VALUES (1, 'NFO-LEGADO')"))
            migration.upgrade(connection, "sqlite")
            migration.upgrade(connection, "sqlite")
            self.assertIn("fiscal_fechamentos_os", inspect(connection).get_table_names())
            self.assertEqual(connection.execute(text("SELECT numero FROM notas_fiscais")).scalar(), "NFO-LEGADO")
            pk = inspect(connection).get_pk_constraint("fiscal_fechamentos_os")
            self.assertEqual(pk["constrained_columns"], ["os_id"])
            self.assertTrue(inspect(connection).get_foreign_keys("fiscal_fechamentos_os"))

    def test_api_autenticada_contrato_zip_real_e_segunda_via(self):
        self._os(1, clinica_id=None, valor="100.10")
        self._os(2, clinica_id=None, paciente_id=2, valor="200.20")
        self._os(3, status="Cancelado")
        app = FastAPI()
        app.include_router(fiscal_api.router, prefix="/api/v1/fiscal")
        app.dependency_overrides[get_db] = lambda: self.db
        client = TestClient(app)
        self.assertEqual(client.get("/api/v1/fiscal/fechamentos/previa?competencia=2026-08").status_code, 401)
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=7, nome="Equipe Fiscal")
        previa = client.get("/api/v1/fiscal/fechamentos/previa?competencia=2026-08")
        self.assertEqual(previa.status_code, 200)
        self.assertEqual(previa.json()["resumo"]["valor_apto"], 300.3)
        body = {"competencia": "2026-08", "os_ids": [1, 2], "chave_idempotencia": str(uuid4()), "confirmar_datas_prestacao": True}
        response = client.post("/api/v1/fiscal/fechamentos", json=body)
        self.assertEqual(response.status_code, 200, response.text[:200])
        self.assertEqual(response.headers["content-type"], "application/zip")
        pacote_id = int(response.headers["X-Fechamento-Id"])
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            self.assertEqual(set(archive.namelist()), {"servicos_contador.xlsx", "conferencia_contador.pdf", "mensagem_contador.txt", "manifesto.json"})
            manifest = json.loads(archive.read("manifesto.json"))
            self.assertEqual(manifest["totais"]["valor_final"], "300.30")
            self.assertEqual(manifest["quantidade_tomadores"], 2)
            self.assertEqual(manifest["quantidade_pendencias"], 1)
            self.assertNotIn("DADO CLINICO", archive.read("mensagem_contador.txt").decode())
        segunda_via = client.get(f"/api/v1/fiscal/fechamentos/{pacote_id}/download")
        self.assertEqual(segunda_via.content, response.content)
        retry = client.post("/api/v1/fiscal/fechamentos", json=body)
        self.assertEqual(retry.content, response.content)
        self.assertEqual(self.db.query(NotaFiscal).count(), 0)
        self.assertEqual(self.db.query(FiscalFechamento).count(), 1)


@unittest.skipUnless(os.environ.get("FISCAL_TEST_POSTGRES_URL"), "PostgreSQL isolado não configurado")
class FiscalFechamentoPostgresTest(FiscalFechamentoTest):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.schema = f"fiscal_test_{uuid4().hex}"
        self.admin = create_engine(os.environ["FISCAL_TEST_POSTGRES_URL"])
        with self.admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        self.engine = create_engine(os.environ["FISCAL_TEST_POSTGRES_URL"], connect_args={"options": f"-csearch_path={self.schema} -ctimezone=UTC"})
        for table in TABLES:
            table.create(self.engine, checkfirst=True)
        self.sessions = sessionmaker(bind=self.engine)
        self.db = self.sessions()
        self._cadastros()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        with self.admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))
        self.admin.dispose()
        self.tmpdir.cleanup()

    def test_previa_utc_respeita_mudanca_mes_fortaleza(self):
        self.assertEqual(self.db.execute(text("SHOW TIME ZONE")).scalar(), "UTC")
        self._os(1, data="2026-09-01T02:59:59+00:00")
        self._os(2, data="2026-09-01T03:00:00+00:00")
        self.assertEqual([item["os_id"] for item in fiscal.previa_fechamento(self.db, "2026-08")["items"]], [1])
        self.assertEqual([item["os_id"] for item in fiscal.previa_fechamento(self.db, "2026-09")["items"]], [2])

    def _corrida(self, keys):
        barrier = threading.Barrier(2)
        def work(key):
            db = self.sessions()
            try:
                barrier.wait(timeout=10)
                return fiscal.preparar_fechamento(db, competencia="2026-08", os_ids=[1], chave_idempotencia=key, confirmar_datas_prestacao=True).id
            except fiscal.FiscalFechamentoError as exc:
                return exc
            finally:
                db.close()
        with patch.object(fiscal_export_service, "gerar_pacote_contador", return_value=(b"PK-concorrente", "concorrente.zip"), create=True), ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(work, keys))
        self.db.expire_all()
        self.assertEqual(self.db.query(FiscalFechamento).count(), 1)
        self.assertEqual(self.db.query(FiscalFechamentoOS).count(), 1)
        return results

    def test_corrida_mesma_chave_retorna_mesmo_pacote(self):
        self._os(1)
        key = uuid4()
        results = self._corrida([key, key])
        self.assertIsInstance(results[0], int)
        self.assertEqual(results[0], results[1])

    def test_corrida_chaves_distintas_nao_duplica_os(self):
        self._os(1)
        results = self._corrida([uuid4(), uuid4()])
        self.assertEqual(sum(isinstance(value, int) for value in results), 1)
        conflicts = [value for value in results if isinstance(value, fiscal.FiscalFechamentoError)]
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].status_code, 409)

    def test_migration_pg_rls_e_revokes_roles_quando_presentes(self):
        with self.engine.begin() as connection:
            for table in ("fiscal_fechamentos_os", "fiscal_fechamentos"):
                connection.execute(text(f"DROP TABLE {table}"))
            migration = _migration()
            migration.upgrade(connection, "postgresql")
            for table in ("fiscal_fechamentos", "fiscal_fechamentos_os"):
                connection.execute(text(f"GRANT SELECT ON TABLE {table} TO PUBLIC"))
                for role in ("anon", "authenticated"):
                    exists = connection.execute(text("SELECT 1 FROM pg_roles WHERE rolname=:role"), {"role": role}).scalar()
                    if exists:
                        connection.execute(text(f"GRANT ALL ON TABLE {table} TO {role}"))
            migration.upgrade(connection, "postgresql")
            for table in ("fiscal_fechamentos", "fiscal_fechamentos_os"):
                rls = connection.execute(text("SELECT relrowsecurity FROM pg_class WHERE oid = CAST(:table AS regclass)"), {"table": table}).scalar()
                self.assertTrue(rls)
                acl = connection.execute(text("SELECT COALESCE(relacl::text, '') FROM pg_class WHERE oid = CAST(:table AS regclass)"), {"table": table}).scalar()
                self.assertNotIn("=r/", acl)
                for role in ("anon", "authenticated"):
                    exists = connection.execute(text("SELECT 1 FROM pg_roles WHERE rolname=:role"), {"role": role}).scalar()
                    if exists:
                        allowed = connection.execute(text("SELECT has_table_privilege(:role, :table, 'SELECT')"), {"role": role, "table": table}).scalar()
                        self.assertFalse(allowed)
                        with self.assertRaises(ProgrammingError) as context:
                            with connection.begin_nested():
                                connection.execute(text(f"SET LOCAL ROLE {role}"))
                                connection.execute(text(f'SELECT * FROM "{self.schema}".{table}'))
                        self.assertEqual(context.exception.orig.pgcode, "42501")
                self.assertEqual(connection.execute(text(f"SELECT count(*) FROM {table}")).scalar(), 0)

    def test_corrida_selecoes_sobrepostas_nao_persiste_parcial(self):
        for os_id in (1, 2, 3):
            self._os(os_id)
        results = self._corrida_selecoes(([1, 2], uuid4()), ([2, 3], uuid4()))
        self.assertEqual(sum(isinstance(result, int) for result in results), 1)
        self.assertEqual(self.db.query(FiscalFechamento).count(), 1)
        claims = self.db.query(FiscalFechamentoOS.os_id).all()
        self.assertIn({row.os_id for row in claims}, ({1, 2}, {2, 3}))

    def test_corrida_mesma_chave_payload_diferente_reverte_claim_perdedor(self):
        self._os(1)
        self._os(2)
        key = uuid4()
        results = self._corrida_selecoes(([1], key), ([2], key))
        self.assertEqual(sum(isinstance(result, int) for result in results), 1)
        conflicts = [result for result in results if isinstance(result, fiscal.FiscalFechamentoError)]
        self.assertEqual(conflicts[0].status_code, 409)
        self.assertEqual(self.db.query(FiscalFechamento).count(), 1)
        self.assertEqual(self.db.query(FiscalFechamentoOS).count(), 1)

    def _corrida_selecoes(self, *requests):
        barrier = threading.Barrier(2)
        def work(request):
            ids, key = request
            db = self.sessions()
            try:
                barrier.wait(timeout=10)
                return fiscal.preparar_fechamento(db, competencia="2026-08", os_ids=ids, chave_idempotencia=key, confirmar_datas_prestacao=True).id
            except fiscal.FiscalFechamentoError as exc:
                return exc
            finally:
                db.close()
        with patch.object(fiscal_export_service, "gerar_pacote_contador", return_value=(b"PK-concorrente", "concorrente.zip")), ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(work, requests))
        self.db.expire_all()
        return results


if __name__ == "__main__":
    unittest.main()
