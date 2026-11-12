"""Rotina consultiva, seleção atômica e confirmações humanas sem emitir notas."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "fiscal-rotina-unit-tests-secret-1234567890")

from app.api.v1.endpoints import fiscal as api
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
from app.services import fiscal_export_service as export, fiscal_fechamento_service as core, fiscal_rotina_service as rotina

FUSO = ZoneInfo("America/Fortaleza")
TABLES = [Clinica, Tutor, Paciente, Servico, Agendamento, AtendimentoClinico, Laudo, OrdemServico, Configuracao, NotaFiscal, RelatorioFiscalEmissao, FiscalFechamento, FiscalFechamentoOS, FiscalRotinaPreferencia, FiscalAndamentoEvento]


class FiscalRotinaServiceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{self.tmp.name}/rotina.db")

        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

        for model in TABLES:
            model.__table__.create(self.engine, checkfirst=True)
        self.sessions = sessionmaker(bind=self.engine)
        self.db = self.sessions()
        self.db.add_all([
            Clinica(id=1, nome="Clínica histórica", razao_social="Empresa A", cnpj="11.222.333/0001-81", endereco="Rua A", numero="1", bairro="Centro", cidade="Fortaleza", estado="CE", cep="60000-000", ativo=False),
            Clinica(id=2, nome="Qualquer nome", cnpj="14.986.833/0001-88", endereco="Rua B", bairro="Centro", cidade="Fortaleza", estado="CE", cep="60000-000", ativo=True),
            Clinica(id=3, nome="Vet Fauna nome sem regra", cnpj="12.ABC.345/01DE-35", endereco="Rua C", bairro="Centro", cidade="Fortaleza", estado="CE", cep="60000-000", ativo=True),
            Clinica(id=4, nome="Sentinela incompleta", cnpj="123", ativo=True),
            Tutor(id=1, nome="Pessoa tomadora", cpf="529.982.247-25", endereco="Rua Pessoa", numero="10", bairro="Centro", cidade="Fortaleza", estado="CE", cep="60000-000"),
            Paciente(id=1, nome="NAO EXPORTAR DADO CLINICO", nome_key="nao exportar", especie="", tutor_id=1),
            Paciente(id=2, nome="OUTRO DADO PRIVADO", nome_key="outro", especie="", tutor_id=1),
            Servico(id=1, nome="Ecocardiograma"),
            Configuracao(nome_empresa="Fort Cordis teste"),
        ])
        self.db.commit()
        self.clock = patch.object(rotina, "_agora_local", return_value=datetime(2026, 10, 14, 12, tzinfo=FUSO))
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        self.tmp.cleanup()

    def _os(self, ident, *, data="2026-08-20T10:00:00-03:00", clinica=1, paciente=1, fonte="agenda", status="Pendente", status_fonte=None):
        instante = datetime.fromisoformat(data) if data else None
        if fonte in {"agenda", "atendimento"}:
            self.db.add(Agendamento(id=ident, paciente_id=paciente, clinica_id=clinica, servico_id=1, inicio=instante or datetime(2026, 8, 20, 10, tzinfo=FUSO), fim=(instante or datetime(2026, 8, 20, 10, tzinfo=FUSO)) + timedelta(minutes=30), status=status_fonte or ("Realizado" if fonte == "agenda" else "Em atendimento")))
        if fonte == "atendimento":
            self.db.add(AtendimentoClinico(id=ident, agendamento_id=ident, paciente_id=paciente, clinica_id=clinica, veterinario_id=1, status="Concluido", data_atendimento=instante))
        if fonte == "laudo":
            self.db.add(Laudo(id=ident, paciente_id=paciente, clinic_id=clinica, veterinario_id=1, tipo="exame", titulo="SEGREDO CLINICO", diagnostico="NAO EXPORTAR", status=status_fonte or "Finalizado", data_exame=instante))
        row = OrdemServico(id=ident, numero_os=f"OS-PREFIXO-IGNORADO-{ident}", paciente_id=paciente, clinica_id=clinica, servico_id=1, agendamento_id=ident if fonte in {"agenda", "atendimento"} else None, laudo_id=ident if fonte == "laudo" else None, data_atendimento=instante, valor_servico=Decimal("100.10"), desconto=Decimal("0.10"), valor_final=Decimal("100.00"), status=status)
        self.db.add(row)
        self.db.commit()
        return row

    def _prepare(self, ids, *, real=False, **kwargs):
        args = dict(competencia="2026-08", modo="semanal", data_corte="2026-08-30", os_ids=ids, chave_idempotencia=uuid4(), confirmar_datas_prestacao=True, usuario_id=7, usuario_nome="Fiscal humano")
        args.update(kwargs)
        if real:
            return rotina.preparar_rotina(self.db, **args)
        with patch.object(export, "gerar_pacote_contador", return_value=(b"PK-byte-preservado", "contador.zip")):
            return rotina.preparar_rotina(self.db, **args)

    def _error(self, status, function, *args, **kwargs):
        with self.assertRaises(rotina.FiscalRotinaError) as context:
            function(*args, **kwargs)
        self.assertEqual(context.exception.status_code, status, context.exception.detail)
        return context.exception.detail

    def _advance(self, os_id, destino, versao, **kwargs):
        args = dict(destino=destino, versao_esperada=versao, chave_idempotencia=uuid4(), confirmar_acao_manual=True, usuario_id=7, usuario_nome="Fiscal humano")
        args.update(kwargs)
        return rotina.atualizar_andamento(self.db, os_id, **args)

    def test_defaults_por_documento_sem_seed_nome_ou_ativo(self):
        result = rotina.listar_rotinas(self.db)
        self.assertEqual(result["padrao"], {"modo": "semanal", "dia_semana": "domingo", "horario": "17:00", "timezone": "America/Fortaleza", "automatico": False})
        clinicas = {row["clinica_id"]: row for row in result["clinicas"]}
        self.assertEqual(clinicas[2]["modo"], "por_servico")
        self.assertTrue(clinicas[2]["pagamento_depende_nf"])
        self.assertEqual(clinicas[2]["origem"], "vet_fauna")
        self.assertEqual(clinicas[3]["modo"], "semanal")
        self.assertEqual(clinicas[1]["versao"], 0)
        self.assertEqual(self.db.query(FiscalRotinaPreferencia).count(), 0)

    def test_preferencia_override_cas_e_confirmacao_estrita(self):
        item = rotina.atualizar_preferencia(self.db, 2, modo="semanal", pagamento_depende_nf=False, versao_esperada=0, usuario_id=7, usuario_nome="Fiscal humano")
        self.assertEqual((item["modo"], item["origem"], item["versao"]), ("semanal", "personalizada", 1))
        detail = self._error(409, rotina.atualizar_preferencia, self.db, 2, modo="por_servico", pagamento_depende_nf=True, versao_esperada=0)
        self.assertEqual(detail["versao_atual"], 1)
        self._error(422, rotina.atualizar_preferencia, self.db, 1, modo="semanal", pagamento_depende_nf="false", versao_esperada=0)
        self._error(404, rotina.atualizar_preferencia, self.db, 999, modo="semanal", pagamento_depende_nf=False, versao_esperada=0)
        self.assertEqual(self.db.query(FiscalRotinaPreferencia).count(), 1)

    def test_corte_antes_no_e_depois_domingo_17_com_fuso(self):
        for horario, expected in (("16:59:59", "2026-10-18"), ("17:00:00", "2026-10-18"), ("17:00:01", "2026-10-25")):
            with self.subTest(horario=horario), patch.object(rotina, "_agora_local", return_value=datetime.fromisoformat(f"2026-10-18T{horario}-03:00")):
                meta = rotina.previa_rotina(self.db, "2026-08")["rotina"]
                self.assertEqual(meta["data_corte"], expected)
                self.assertEqual(meta["corte_em"], expected + "T17:00:00-03:00")
                self.assertEqual(meta["proxima_preparacao_em"], meta["corte_em"])

    def test_corte_explicito_so_domingo_e_so_modo_semanal(self):
        for cutoff in ("2026-08-27", "2026-08-28", "2026-08-29", "2026-02-30", "2026-8-30", "bad"):
            self._error(422, rotina.previa_rotina, self.db, "2026-08", "semanal", cutoff)
        for modo in ("por_servico", "mensal"):
            self._error(422, rotina.previa_rotina, self.db, "2026-08", modo, "2026-08-30")
            meta = rotina.previa_rotina(self.db, "2026-08", modo)["rotina"]
            self.assertIsNone(meta["data_corte"])
            self.assertIsNone(meta["corte_em"])
            self.assertIsNone(meta["proxima_preparacao_em"])

    def test_sabado_e_domingo_ate_17_entram_e_documentos_conservam_corte(self):
        from openpyxl import load_workbook
        from pypdf import PdfReader

        for ident, data in enumerate(("2026-10-16T19:00:00-03:00", "2026-10-17T16:30:00-03:00", "2026-10-18T17:00:00-03:00", "2026-10-18T17:00:01-03:00", "2026-10-19T09:00:00-03:00"), 1):
            self._os(ident, data=data)
        with patch.object(rotina, "_agora_local", return_value=datetime.fromisoformat("2026-10-18T18:00:00-03:00")):
            previa = rotina.previa_rotina(self.db, "2026-10", "semanal", "2026-10-18")
            self.assertEqual({item["os_id"] for item in previa["items"]}, {1, 2, 3})
            self.assertTrue(all(item["elegivel"] for item in previa["items"]))
            pacote = self._prepare([1, 2, 3], competencia="2026-10", data_corte="2026-10-18", real=True)
        self.assertEqual(json.loads(pacote.snapshot_json)["rotina"]["corte_em"], "2026-10-18T17:00:00-03:00")
        with zipfile.ZipFile(io.BytesIO(pacote.pacote_bytes)) as archive:
            manifesto = json.loads(archive.read("manifesto.json"))
            self.assertEqual(manifesto["rotina"]["corte_em"], "2026-10-18T17:00:00-03:00")
            self.assertEqual(set(manifesto["os_ids"]), {1, 2, 3})
            self.assertIn("2026-10-18T17:00:00-03:00", archive.read("mensagem_contador.txt").decode())
            workbook = load_workbook(io.BytesIO(archive.read("servicos_contador.xlsx")), data_only=True)
            self.assertIn(("Corte da rotina (Fortaleza)", "2026-10-18T17:00:00-03:00"), list(workbook["Prestador e lote"].values))
            pdf_text = "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(archive.read("conferencia_contador.pdf"))).pages)
            self.assertIn("2026-10-18T17:00:00-03:00", pdf_text)
        self.assertEqual(self.db.query(NotaFiscal).count(), 0)
        self.assertEqual(self.db.query(FiscalAndamentoEvento).count(), 0)

    def test_fim_de_mes_conserva_competencias_separadas_no_domingo_seguinte(self):
        self._os(1, data="2026-10-31T16:00:00-03:00")
        self._os(2, data="2026-11-01T09:00:00-03:00")
        with patch.object(rotina, "_agora_local", return_value=datetime.fromisoformat("2026-11-01T16:00:00-03:00")):
            for competencia, expected in (("2026-10", [1]), ("2026-11", [2])):
                previa = rotina.previa_rotina(self.db, competencia, "semanal", "2026-11-01")
                self.assertEqual([item["os_id"] for item in previa["items"]], expected)
                self.assertTrue(previa["items"][0]["elegivel"])

    def test_retry_pacote_sexta_historico_preserva_bytes_e_nao_aceita_nova_operacao(self):
        self._os(1)
        key = uuid4()
        contexto = {"modo": "semanal", "competencia": "2026-08", "data_corte": "2026-08-28", "corte_em": "2026-08-28T18:00:00-03:00", "clinica_id": None}
        with patch.object(export, "gerar_pacote_contador", return_value=(b"PK-historico-sexta", "sexta.zip")):
            pacote = core.preparar_fechamento(self.db, competencia="2026-08", os_ids=[1], chave_idempotencia=key, confirmar_datas_prestacao=True, contexto_rotina=contexto)
        original = (pacote.pacote_bytes, pacote.snapshot_json, pacote.checksum, pacote.fingerprint)
        for corte in (None, "2026-08-28"):
            retry = self._prepare([1], chave_idempotencia=key, data_corte=corte)
            self.assertEqual((retry.pacote_bytes, retry.snapshot_json, retry.checksum, retry.fingerprint), original)
        for ids, changes in (([2], {}), ([1], {"confirmar_datas_prestacao": False}), ([1], {"confirmar_exportacoes_anteriores": True})):
            detail = self._error(409, self._prepare, ids, chave_idempotencia=key, data_corte=None, **changes)
            self.assertEqual(detail["fechamento_id"], pacote.id)
        self._error(409, self._prepare, [1], chave_idempotencia=key, data_corte="2026-08-30")
        self._error(409, self._prepare, [2], chave_idempotencia=key, data_corte="2026-08-28")
        self._error(409, self._prepare, [1], chave_idempotencia=key, data_corte="2026-08-28", clinica_id=3)
        self._error(422, self._prepare, [1], data_corte="2026-08-28")
        self.assertEqual(self.db.query(FiscalFechamento).count(), 1)

    def test_backlog_mes_inclui_os_anteriores_sem_usar_prefixo(self):
        self._os(1, data="2026-08-01T10:00:00-03:00")
        self._os(2, data="2026-08-27T10:00:00-03:00")
        self._os(3, data="2026-08-30T17:00:01-03:00")
        self._os(4, data="2026-07-31T10:00:00-03:00")
        result = rotina.previa_rotina(self.db, "2026-08", "semanal", "2026-08-30")
        self.assertEqual([item["os_id"] for item in result["items"]], [1, 2])
        self.assertTrue(all(item["elegivel"] for item in result["items"]))
        self.assertEqual(result["items"][0]["prazo_preparacao"], "2026-08-02T17:00:00-03:00")

    def test_fontes_exatas_sem_heuristica_e_sem_informacao_clinica(self):
        self._os(1)
        self._os(2, fonte="atendimento")
        self._os(3, fonte="laudo")
        self._os(4, fonte="nenhuma", status="Pago")
        result = rotina.previa_rotina(self.db, "2026-08", "semanal", "2026-08-30")
        by_id = {item["os_id"]: item for item in result["items"]}
        self.assertEqual([by_id[i]["fonte_realizacao"] for i in (1, 2, 3, 4)], ["agenda", "atendimento", "laudo", "sem_evidencia"])
        self.assertTrue(all(by_id[i]["realizacao_confirmada"] for i in (1, 2, 3)))
        self.assertFalse(by_id[4]["elegivel"])
        serialized = json.dumps(result, default=str)
        for private in ("NAO EXPORTAR", "SEGREDO", "paciente_id", "agendamento_id", "laudo_id", "diagnostico"):
            self.assertNotIn(private, serialized)

    def test_agenda_terminal_bloqueia_mesmo_atendimento_concluido(self):
        for ident, status in enumerate(("Cancelado", "Faltou", "Expirado"), 1):
            self._os(ident, fonte="atendimento", status_fonte=status)
        self.assertTrue(all(not row["elegivel"] for row in rotina.previa_rotina(self.db, "2026-08")["items"]))
        self._error(422, self._prepare, [1])
        self.assertEqual(self.db.query(FiscalFechamentoOS).count(), 0)

    def test_vinculo_incoerente_agenda_atendimento_laudo_rejeitado(self):
        self._os(1)
        self._os(2, fonte="atendimento")
        self._os(3, fonte="laudo")
        self.db.get(Agendamento, 1).clinica_id = 3
        self.db.get(AtendimentoClinico, 2).paciente_id = 2
        self.db.get(Laudo, 3).clinic_id = 3
        self.db.commit()
        result = rotina.previa_rotina(self.db, "2026-08")
        self.assertEqual(result["resumo"]["quantidade_aptas"], 0)

    def test_laudo_reaberto_com_finalizacao_imutavel_e_futuro(self):
        self._os(1, fonte="laudo")
        self.db.get(Laudo, 1).status = "Rascunho"
        self._os(2, data="2026-10-15T10:00:00-03:00")
        self.db.commit()
        self.assertTrue(rotina.previa_rotina(self.db, "2026-08")["items"][0]["elegivel"])
        future = rotina.previa_rotina(self.db, "2026-10")["items"][0]
        self.assertTrue(future["realizacao_confirmada"])
        self.assertFalse(future["elegivel"])
        self.assertTrue(any("futura" in motivo for motivo in future["motivos_pendencia"]))

    def test_modos_banner_sem_claim_canceladas_e_prioridade_depende_nf(self):
        self._os(1)
        self._os(2, clinica=2)
        self._os(3, clinica=2, status="Cancelado")
        self._os(4, clinica=3)
        rotina.atualizar_preferencia(self.db, 3, modo="por_servico", pagamento_depende_nf=False, versao_esperada=0)
        weekly = rotina.previa_rotina(self.db, "2026-08")
        self.assertEqual([item["os_id"] for item in weekly["items"]], [1])
        self.assertEqual(weekly["resumo"]["quantidade_por_servico"], 2)
        self.assertEqual(weekly["resumo"]["quantidade_pagamento_depende_nf"], 1)
        individual = rotina.previa_rotina(self.db, "2026-08", "por_servico")
        self.assertEqual([item["os_id"] for item in individual["items"]], [2, 3, 4])
        self._prepare([2], modo="por_servico", data_corte=None)
        self.assertEqual(rotina.previa_rotina(self.db, "2026-08")["resumo"]["quantidade_por_servico"], 1)

    def test_domiciliar_pf_usa_tomador_cadastro_e_agenda(self):
        self._os(1, clinica=None)
        item = rotina.previa_rotina(self.db, "2026-08")["items"][0]
        self.assertEqual(item["tipo_cliente"], "PF")
        self.assertTrue(item["elegivel"])
        self.assertEqual(item["modo_preparacao"], "semanal")

    def test_preparar_revalida_modo_e_nao_cria_parcial(self):
        self._os(1)
        self._os(2, clinica=2)
        self._error(409, self._prepare, [1, 2])
        self.assertEqual(self.db.query(FiscalFechamento).count(), 0)
        self.assertEqual(self.db.query(FiscalFechamentoOS).count(), 0)
        self.assertEqual(self.db.get(OrdemServico, 1).status, "Pendente")

    def test_preparar_por_servico_exatamente_uma_e_corte_nao_permitido(self):
        self._os(1, clinica=2)
        self._os(2, clinica=2)
        self._error(422, self._prepare, [1, 2], modo="por_servico", data_corte=None)
        self._error(422, self._prepare, [1], modo="por_servico")
        self._error(422, self._prepare, [1], modo="por_servico", data_corte=None, clinica_id=1)
        self._error(422, self._prepare, [1], modo="mensal", data_corte=None)
        self.assertEqual(self.db.query(FiscalFechamentoOS).count(), 0)

    def test_preparar_impede_futuro_sem_evidencia_e_fora_corte(self):
        self._os(1, fonte="nenhuma")
        self._os(2, data="2026-08-31T10:00:00-03:00")
        self._os(3, data="2026-10-15T10:00:00-03:00")
        self._error(422, self._prepare, [1])
        self._error(422, self._prepare, [2])
        self._error(422, self._prepare, [3], competencia="2026-10", data_corte="2026-10-18")
        self.assertEqual(self.db.query(FiscalFechamentoOS).count(), 0)

    def test_snapshot_pendencias_escopo_e_export_contexto_sem_clinica_privada(self):
        self._os(1, clinica=2)
        self._os(2, clinica=2, fonte="nenhuma")
        self._os(3, clinica=4)
        pacote = self._prepare([1], modo="por_servico", data_corte=None, real=True)
        snapshot = json.loads(pacote.snapshot_json)
        self.assertEqual(snapshot["rotina"]["clinica_id"], 2)
        self.assertEqual([item["os_id"] for item in snapshot["pendencias"]], [2])
        self.assertTrue(snapshot["items"][0]["pagamento_depende_nf"])
        with zipfile.ZipFile(io.BytesIO(pacote.pacote_bytes)) as archive:
            manifesto = json.loads(archive.read("manifesto.json"))
            self.assertEqual(manifesto["rotina"], {"modo": "por_servico", "data_corte": None, "corte_em": None, "timezone": "America/Fortaleza", "automatico": False})
            self.assertEqual(manifesto["quantidade_pendencias"], 1)
            self.assertIn("Preparação: por_servico", archive.read("mensagem_contador.txt").decode())
        self.assertEqual(self.db.query(NotaFiscal).count(), 0)
        self.assertNotIn("Sentinela", pacote.snapshot_json)
        self.assertNotIn("NAO EXPORTAR", pacote.snapshot_json)

    def test_semanal_multiclinica_um_pacote_flag_atual_e_retry_estavel(self):
        self._os(1)
        self._os(2, clinica=3)
        key = uuid4()
        with patch.object(rotina, "_agora_local", return_value=datetime(2026, 8, 21, 10, tzinfo=FUSO)):
            pacote = self._prepare([1, 2], chave_idempotencia=key, data_corte=None)
        original = (pacote.pacote_bytes, pacote.snapshot_json, pacote.fingerprint)
        rotina.atualizar_preferencia(self.db, 1, modo="por_servico", pagamento_depende_nf=True, versao_esperada=0)
        self.db.get(OrdemServico, 1).status = "Cancelado"
        self.db.commit()
        retry = self._prepare([2, 1], chave_idempotencia=key, data_corte=None)
        self.assertEqual((retry.pacote_bytes, retry.snapshot_json, retry.fingerprint), original)
        self.assertEqual(json.loads(retry.snapshot_json)["rotina"]["data_corte"], "2026-08-23")
        self._error(409, self._prepare, [1, 2], chave_idempotencia=key, data_corte="2026-08-30")
        self.assertEqual(self.db.query(FiscalFechamento).count(), 1)

    def test_flag_nf_atual_na_preparacao_sem_exigir_versao_preview(self):
        self._os(1)
        rotina.previa_rotina(self.db, "2026-08")
        rotina.atualizar_preferencia(self.db, 1, modo="semanal", pagamento_depende_nf=True, versao_esperada=0)
        pacote = self._prepare([1])
        self.assertTrue(json.loads(pacote.snapshot_json)["items"][0]["pagamento_depende_nf"])

    def test_pacote_legacy_retry_fingerprint_e_chamada_export_inalterados(self):
        self._os(1, fonte="nenhuma")
        key = uuid4()
        original_payload = {"competencia": "2026-08", "os_ids": [1], "confirmar_datas_prestacao": True, "confirmar_exportacoes_anteriores": False}
        expected = hashlib.sha256(json.dumps(original_payload, sort_keys=True).encode()).hexdigest()
        with patch.object(export, "gerar_pacote_contador", return_value=(b"PK-legacy", "legacy.zip")) as gerar:
            pacote = core.preparar_fechamento(self.db, competencia="2026-08", os_ids=[1], chave_idempotencia=key, confirmar_datas_prestacao=True)
            self.assertNotIn("contexto_rotina", gerar.call_args.kwargs)
        self.assertEqual(pacote.fingerprint, expected)
        self.assertNotIn("rotina", json.loads(pacote.snapshot_json))
        self.assertNotIn("modo_preparacao", json.loads(pacote.snapshot_json)["items"][0])
        self._error(409, self._prepare, [1], chave_idempotencia=key)

    def test_failure_export_atomica_sem_claim(self):
        self._os(1)
        with patch.object(export, "gerar_pacote_contador", side_effect=RuntimeError("falha de geração")), self.assertRaises(RuntimeError):
            rotina.preparar_rotina(self.db, competencia="2026-08", modo="semanal", os_ids=[1], chave_idempotencia=uuid4(), confirmar_datas_prestacao=True, data_corte="2026-08-30")
        self.assertEqual(self.db.query(FiscalFechamento).count(), 0)
        self.assertEqual(self.db.query(FiscalFechamentoOS).count(), 0)

    def test_andamentos_get_sem_backfill_independente_por_os(self):
        self._os(1)
        self._os(2, clinica=3)
        pacote = self._prepare([1, 2])
        result = rotina.listar_andamentos(self.db, pacote.id)
        self.assertEqual([item["etapa"] for item in result["items"]], ["preparado", "preparado"])
        self.assertTrue(all(item["versao"] == 0 and item["eventos"] == [] for item in result["items"]))
        self.assertEqual(self.db.query(FiscalAndamentoEvento).count(), 0)
        self._advance(1, "enviado_contador", 0)
        result = rotina.listar_andamentos(self.db, pacote.id)
        self.assertEqual([item["etapa"] for item in result["items"]], ["enviado_contador", "preparado"])

    def test_andamentos_lineares_ref_nf_manual_e_auditoria(self):
        self._os(1)
        pacote = self._prepare([1])
        self._error(422, self._advance, 1, "nota_recebida", 0, referencia_nota="NF1")
        self._error(422, self._advance, 1, "enviado_contador", 0, confirmar_acao_manual=False)
        self._error(422, self._advance, 1, "enviado_contador", 0, confirmar_acao_manual="true")
        enviado = self._advance(1, "enviado_contador", 0, observacao="Enviei manualmente")
        self.assertEqual(enviado["versao"], 1)
        self._error(422, self._advance, 1, "nota_recebida", 1)
        recebido = self._advance(1, "nota_recebida", 1, referencia_nota="NF-2026-10")
        self.assertEqual(recebido["referencia_nota"], "NF-2026-10")
        self._error(422, self._advance, 1, "nota_encaminhada", 2, referencia_nota="OUTRA")
        final = self._advance(1, "nota_encaminhada", 2)
        self.assertEqual((final["etapa"], final["versao"], final["referencia_nota"]), ("nota_encaminhada", 3, "NF-2026-10"))
        self.assertEqual([item["versao"] for item in final["eventos"]], [1, 2, 3])
        self.assertTrue(all(item["usuario_id"] == 7 and item["usuario_nome"] == "Fiscal humano" for item in final["eventos"]))
        self._error(422, self._advance, 1, "enviado_contador", 3)
        self.assertEqual(self.db.query(NotaFiscal).count(), 0)
        self.assertEqual(core.buscar_fechamento(self.db, pacote.id).pacote_bytes, b"PK-byte-preservado")

    def test_andamento_cas_retry_diferente_payload_e_cross_os(self):
        self._os(1)
        self._os(2)
        self._prepare([1, 2])
        key = uuid4()
        self._advance(1, "enviado_contador", 0, chave_idempotencia=key)
        detail = self._error(409, self._advance, 1, "nota_recebida", 0, referencia_nota="NF1")
        self.assertEqual(detail["versao_atual"], 1)
        self._advance(1, "nota_recebida", 1, referencia_nota="NF1")
        retry = self._advance(1, "enviado_contador", 0, chave_idempotencia=key)
        self.assertEqual((retry["etapa"], retry["versao"]), ("nota_recebida", 2))
        self._error(409, self._advance, 1, "enviado_contador", 0, chave_idempotencia=key, observacao="mudou")
        self._error(409, self._advance, 2, "enviado_contador", 0, chave_idempotencia=key)
        self.assertEqual(self.db.query(FiscalAndamentoEvento).count(), 2)

    def test_andamento_sobrevive_exclusao_fisica_os(self):
        row = self._os(1)
        pacote = self._prepare([1])
        self.db.delete(row)
        self.db.commit()
        item = self._advance(1, "enviado_contador", 0)
        self.assertEqual(item["numero_os"], "OS-PREFIXO-IGNORADO-1")
        self.assertEqual(rotina.listar_andamentos(self.db, pacote.id)["items"][0]["versao"], 1)
        self._error(404, self._advance, 999, "enviado_contador", 0)
        self._error(404, rotina.listar_andamentos, self.db, 999)

    def test_api_contrato_strict_cas_download_e_andamento(self):
        self._os(1)
        app = FastAPI()
        app.include_router(api.router, prefix="/fiscal")
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=7, nome="Fiscal humano")
        with TestClient(app) as client:
            self.assertEqual(client.get("/fiscal/rotinas").status_code, 200)
            self.assertEqual(client.put("/fiscal/rotinas/clinicas/1", json={"modo": "semanal", "pagamento_depende_nf": "false", "versao_esperada": 0}).status_code, 422)
            request = {"competencia": "2026-08", "modo": "semanal", "data_corte": "2026-08-30", "os_ids": [1], "chave_idempotencia": str(uuid4()), "confirmar_datas_prestacao": True}
            with patch.object(export, "gerar_pacote_contador", return_value=(b"PK-http", "http.zip")):
                prepared = client.post("/fiscal/rotinas/preparar", json=request)
            self.assertEqual(prepared.status_code, 200, prepared.text)
            ident = prepared.headers["X-Fechamento-Id"]
            self.assertEqual(client.get(f"/fiscal/fechamentos/{ident}/download").content, b"PK-http")
            self.assertEqual(client.get(f"/fiscal/fechamentos/{ident}/andamentos").json()["items"][0]["versao"], 0)
            action = {"destino": "enviado_contador", "versao_esperada": 0, "chave_idempotencia": str(uuid4()), "confirmar_acao_manual": True}
            self.assertEqual(client.post("/fiscal/os/1/andamento", json=action).status_code, 200)
            self.assertEqual(client.post("/fiscal/os/1/andamento", json={**action, "chave_idempotencia": str(uuid4())}).status_code, 409)
            self.assertEqual(client.post("/fiscal/os/1/andamento", json={**action, "versao_esperada": True}).status_code, 422)


class FiscalRotinaMigrationTest(unittest.TestCase):
    def test_migracao_aditiva_idempotente_sem_seed_e_com_constraints(self):
        path = BACKEND / "migrations/versions/20261014_98_fiscal_rotina_e_andamento.py"
        spec = importlib.util.spec_from_file_location("fiscal_rotina_migration_98", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        engine = create_engine("sqlite:///:memory:")
        try:
            with engine.begin() as connection:
                connection.execute(text("CREATE TABLE clinicas (id INTEGER PRIMARY KEY, nome TEXT)"))
                connection.execute(text("CREATE TABLE fiscal_fechamentos_os (os_id INTEGER PRIMARY KEY)"))
                connection.execute(text("INSERT INTO clinicas VALUES (1, 'preservada')"))
                migration.upgrade(connection, "sqlite")
                migration.upgrade(connection, "sqlite")
                self.assertEqual(connection.execute(text("SELECT nome FROM clinicas")).scalar(), "preservada")
                self.assertEqual(connection.execute(text("SELECT count(*) FROM fiscal_rotinas_clinicas")).scalar(), 0)
                self.assertEqual(connection.execute(text("SELECT count(*) FROM fiscal_andamento_eventos")).scalar(), 0)
                self.assertEqual(len(inspect(connection).get_foreign_keys("fiscal_andamento_eventos")), 1)
                # SQLite não reflete consistentemente constraints compostas.
                # Exercite a unicidade e os checks pelo comportamento do banco.
                connection.execute(text("INSERT INTO fiscal_fechamentos_os VALUES (10), (11)"))
                insert = text("""INSERT INTO fiscal_andamento_eventos
                    (os_id, versao, etapa_anterior, destino, chave_idempotencia, fingerprint, registrado_em)
                    VALUES (:os_id, :versao, :anterior, :destino, :chave, 'hash', '2026-10-14T17:00:00-03:00')""")
                base = {"os_id": 10, "versao": 1, "anterior": "preparado", "destino": "enviado_contador", "chave": str(uuid4())}
                connection.execute(insert, base)
                for invalid in ({**base, "os_id": 11}, {**base, "chave": str(uuid4())}, {**base, "os_id": 11, "chave": str(uuid4()), "destino": "nota_recebida"}, {**base, "os_id": 11, "versao": 0, "chave": str(uuid4())}):
                    with self.assertRaises(IntegrityError), connection.begin_nested():
                        connection.execute(insert, invalid)
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
