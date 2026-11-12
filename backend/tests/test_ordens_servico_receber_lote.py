"""Recebimento atomico em banco temporario; nenhum dado/servico externo real."""
import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "receber-lote-test-secret-key-synthetic-1234567890")

from app.api.v1.endpoints import ordens_servico
from app.core.security import _authorize_request_by_matrix
from app.models.auditoria_evento import AuditoriaEvento
from app.models.clinica import Clinica
from app.models.financeiro import (
    BandeiraCartao, CreditoFinanceiro, FormaPagamentoConfiguracao,
    OrdemServicoPagamento, Transacao,
)
from app.models.ordem_servico import OrdemServico
from app.models.paciente import Paciente
from app.models.push_scheduled_notification import PushScheduledNotification
from app.models.servico import Servico
from app.models.tutor import Tutor
from app.services.push_scheduler_service import (
    PUSH_SCHEDULE_KIND_PENDING_OS, PUSH_SCHEDULE_STATUS_CANCELLED,
    PUSH_SCHEDULE_STATUS_PENDING,
)


class RecebimentoLoteTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{Path(self.tmpdir.name) / 'lote.db'}")
        for model in (
            Tutor, Paciente, Clinica, Servico, OrdemServico, Transacao,
            OrdemServicoPagamento, CreditoFinanceiro, FormaPagamentoConfiguracao,
            BandeiraCartao, AuditoriaEvento, PushScheduledNotification,
        ):
            model.__table__.create(self.engine, checkfirst=True)
        self.Session = sessionmaker(bind=self.engine, autoflush=False)
        self.db = self.Session()
        self.user = SimpleNamespace(id=17, nome="Operadora Sintetica", email="teste@example.invalid")
        self.request = Request({
            "type": "http", "method": "PATCH", "path": "/api/v1/ordens-servico/receber-lote",
            "headers": [], "client": ("127.0.0.1", 1234), "server": ("testserver", 80),
            "scheme": "http", "query_string": b"",
        })
        self.push_patch = patch.object(ordens_servico, "send_financeiro_push_notification")
        self.push = self.push_patch.start()
        self.addCleanup(self.push_patch.stop)
        self.ids = []
        self._criar_ordens(["10.01", "20.02", "30.03"])

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        self.tmpdir.cleanup()

    def _criar_ordens(self, valores):
        self.db.query(OrdemServico).delete()
        self.db.commit()
        self.ids = []
        for indice, valor in enumerate(valores, 1):
            ordem = OrdemServico(
                numero_os=f"OS-SINTETICA-{indice}", paciente_id=indice,
                clinica_id=1, servico_id=1, status="Pendente",
                valor_servico=Decimal(valor) + Decimal("1.00"),
                desconto=Decimal("1.00"), valor_final=Decimal(valor),
                data_atendimento=datetime(2026, 10, 1, 10),
                updated_at=datetime(2026, 10, 1, 10),
            )
            self.db.add(ordem)
            self.db.flush()
            self.ids.append(ordem.id)
        self.db.commit()
        self.valores = list(valores)

    def _dados(self, **overrides):
        total = sum(Decimal(valor) for valor in self.valores)
        dados = {
            "ordens": [{"os_id": os_id, "valor_final_esperado": valor}
                       for os_id, valor in zip(self.ids, self.valores)],
            "pagamentos": [{"forma_pagamento": "pix", "valor": str(total)}],
            "data_recebimento": date(2026, 10, 9),
        }
        dados.update(overrides)
        return ordens_servico.OrdensServicoReceberLoteInput(**dados)

    def _receber(self, dados=None):
        return ordens_servico.receber_ordens_lote(
            dados or self._dados(), self.request, db=self.db, current_user=self.user,
        )

    def _verificar_sem_recebimento(self):
        # Nova conexao prova rollback persistido, independente do identity map.
        with self.Session() as db:
            self.assertEqual(db.query(Transacao).count(), 0)
            self.assertEqual(db.query(OrdemServicoPagamento).count(), 0)
            self.assertEqual(db.query(CreditoFinanceiro).count(), 0)
            self.assertEqual(db.query(AuditoriaEvento).count(), 0)
        self.push.assert_not_called()

    def test_sucesso_unico_commit_preserva_desconto_audita_e_notifica_apos_commit(self):
        def conferir_push(*_args, **_kwargs):
            with self.Session() as db:
                self.assertEqual({item.status for item in db.query(OrdemServico)}, {"Pago"})
                self.assertEqual(db.query(AuditoriaEvento).count(), 3)
        self.push.side_effect = conferir_push
        with patch.object(self.db, "commit", wraps=self.db.commit) as commit:
            resposta = self._receber()
        self.assertEqual(commit.call_count, 1)
        self.assertEqual(resposta["os_ids"], self.ids)
        self.assertEqual(self.push.call_count, 3)
        with self.Session() as db:
            for ordem, esperado in zip(db.query(OrdemServico).order_by(OrdemServico.id), self.valores):
                self.assertEqual(ordem.valor_final, Decimal(esperado))
                self.assertEqual(ordem.desconto, Decimal("1.00"))
            self.assertEqual(db.query(CreditoFinanceiro).count(), 0)
            self.assertEqual(db.query(OrdemServicoPagamento).count(), 3)
            for evento in db.query(AuditoriaEvento):
                self.assertEqual(evento.acao, "ORDEM_SERVICO_RECEBIDA")
                self.assertEqual(evento.usuario_id, 17)
                self.assertTrue(json.loads(evento.detalhes_json)["recebimento_lote"])
            for pagamento in db.query(OrdemServicoPagamento):
                self.assertEqual(pagamento.data_recebimento.date(), date(2026, 10, 9))

    def test_os_paga_cancelada_ou_valor_alterado_rejeita_lote_completo(self):
        for mudanca in ("Pago", "Cancelado", "valor"):
            with self.subTest(mudanca=mudanca):
                ordem = self.db.get(OrdemServico, self.ids[-1])
                ordem.status = mudanca if mudanca != "valor" else "Pendente"
                ordem.valor_final = Decimal("30.04") if mudanca == "valor" else Decimal("30.03")
                self.db.commit()
                with self.assertRaises(HTTPException) as raised:
                    self._receber()
                self.assertEqual(raised.exception.status_code, 409)
                self._verificar_sem_recebimento()
                self.assertEqual(self.db.get(OrdemServico, self.ids[0]).status, "Pendente")

    def test_os_removida_rejeita_todo_lote(self):
        self.db.delete(self.db.get(OrdemServico, self.ids[-1]))
        self.db.commit()
        with self.assertRaises(HTTPException) as raised:
            self._receber()
        self.assertEqual(raised.exception.status_code, 409)
        self._verificar_sem_recebimento()

    def test_falha_tardia_desfaz_os_transacoes_pagamentos_auditoria_e_lembrete(self):
        lembrete = PushScheduledNotification(
            kind=PUSH_SCHEDULE_KIND_PENDING_OS, status=PUSH_SCHEDULE_STATUS_PENDING,
            module="financeiro", action="payment_pending", resource_type="ordem_servico",
            resource_id=self.ids[0], send_at=datetime(2026, 10, 15), payload_json="{}",
        )
        self.db.add(lembrete)
        self.db.commit()
        original = ordens_servico._preparar_recebimento_ordem
        preparadas = []
        def falhar_depois_de_gravar(*args, **kwargs):
            resultado = original(*args, **kwargs)
            preparadas.append(args[0][0].id)
            if len(preparadas) == 2:
                self.assertGreater(self.db.query(Transacao).count(), 0)
                raise RuntimeError("Falha sintetica depois da segunda OS")
            return resultado
        with patch.object(ordens_servico, "_preparar_recebimento_ordem", side_effect=falhar_depois_de_gravar):
            with self.assertRaisesRegex(RuntimeError, "Falha sintetica"):
                self._receber()
        self.assertEqual(preparadas, self.ids[:2])
        self._verificar_sem_recebimento()
        with self.Session() as db:
            self.assertEqual({os.status for os in db.query(OrdemServico)}, {"Pendente"})
            self.assertEqual(db.query(PushScheduledNotification).one().status, PUSH_SCHEDULE_STATUS_PENDING)

    def test_lembretes_cancelados_na_mesma_transacao(self):
        self.db.add(PushScheduledNotification(
            kind=PUSH_SCHEDULE_KIND_PENDING_OS, status=PUSH_SCHEDULE_STATUS_PENDING,
            module="financeiro", action="payment_pending", resource_type="ordem_servico",
            resource_id=self.ids[0], send_at=datetime(2026, 10, 15), payload_json="{}",
        ))
        self.db.commit()
        self._receber()
        with self.Session() as db:
            self.assertEqual(db.query(PushScheduledNotification).one().status, PUSH_SCHEDULE_STATUS_CANCELLED)

    def test_falha_no_commit_desfaz_lote_e_nao_notifica(self):
        with patch.object(self.db, "commit", side_effect=RuntimeError("Commit indisponivel")):
            with self.assertRaisesRegex(RuntimeError, "Commit indisponivel"):
                self._receber()
        self._verificar_sem_recebimento()

    def test_repeticao_retorna_conflito_sem_novos_movimentos(self):
        self._receber()
        self.push.reset_mock()
        with self.assertRaises(HTTPException) as raised:
            self._receber()
        self.assertEqual(raised.exception.status_code, 409)
        with self.Session() as db:
            self.assertEqual(db.query(Transacao).count(), 3)
            self.assertEqual(db.query(OrdemServicoPagamento).count(), 3)
            self.assertEqual(db.query(AuditoriaEvento).count(), 3)
        self.push.assert_not_called()

    def test_ids_duplicados_rejeitados(self):
        dados = self._dados()
        dados.ordens.append(dados.ordens[0])
        with self.assertRaises(HTTPException) as raised:
            self._receber(dados)
        self.assertEqual(raised.exception.status_code, 422)
        self._verificar_sem_recebimento()

    def test_pagamentos_insuficientes_ou_excedentes_rejeitados_sem_credito(self):
        for valor in ("60.05", "60.07"):
            with self.subTest(valor=valor), self.assertRaises(HTTPException) as raised:
                self._receber(self._dados(pagamentos=[{"forma_pagamento": "pix", "valor": valor}]))
            self.assertEqual(raised.exception.status_code, 422)
            self._verificar_sem_recebimento()

    def test_rateio_preserva_centavos_por_os_e_por_forma(self):
        self._criar_ordens(["0.01", "0.01", "0.01"])
        self._receber(self._dados(pagamentos=[
            {"forma_pagamento": "pix", "valor": "0.01"},
            {"forma_pagamento": "dinheiro", "valor": "0.02"},
        ]))
        with self.Session() as db:
            pagamentos = db.query(OrdemServicoPagamento).all()
            for os_id in self.ids:
                self.assertEqual(sum(Decimal(str(p.valor_bruto)) for p in pagamentos if p.ordem_servico_id == os_id), Decimal("0.01"))
            for codigo, valor in (("pix", "0.01"), ("dinheiro", "0.02")):
                self.assertEqual(sum(Decimal(str(p.valor_bruto)) for p in pagamentos if p.forma_pagamento_codigo == codigo), Decimal(valor))
            self.assertEqual(db.query(CreditoFinanceiro).count(), 0)

    def test_rateio_taxas_configuradas_nao_repete_taxa_fixa(self):
        self._criar_ordens(["33.33", "33.33", "33.34"])
        config = FormaPagamentoConfiguracao(nome="Cartao", codigo="cartao", tipo="cartao_credito", taxa_percentual=2.99, taxa_fixa=0.30)
        self.db.add(config)
        self.db.commit()
        self._receber(self._dados(pagamentos=[{
            "forma_pagamento_config_id": config.id, "valor": "100.00",
            "data_recebimento": "2026-10-08",
        }]))
        with self.Session() as db:
            pagamentos = db.query(OrdemServicoPagamento).all()
            self.assertEqual(sum(Decimal(str(p.taxa_fixa_aplicada)) for p in pagamentos), Decimal("0.30"))
            self.assertEqual(sum(Decimal(str(p.valor_taxa)) for p in pagamentos), Decimal("3.29"))
            self.assertEqual(sum(Decimal(str(p.valor_liquido)) for p in pagamentos), Decimal("96.71"))
            self.assertTrue(all(p.data_recebimento.date() == date(2026, 10, 8) for p in pagamentos))

    def test_taxa_invalida_ou_forma_inexistente_rejeita_sem_efeitos(self):
        for pagamento in (
            {"forma_pagamento_config_id": 999, "valor": "60.06"},
            {"forma_pagamento": "pix", "valor": "60.06", "taxa_fixa": "60.07"},
            {"forma_pagamento": "pix", "valor": "60.06", "taxa_fixa": "0.001"},
        ):
            with self.subTest(pagamento=pagamento), self.assertRaises(HTTPException):
                self._receber(self._dados(pagamentos=[pagamento]))
            self._verificar_sem_recebimento()

    def test_contrato_rejeita_credito_desconto_valor_fracionario_e_nao_finito(self):
        for adicional in ({"desconto": 1}, {"valor_credito_utilizado": 1}, {"destino_credito_excedente": "cliente"}):
            with self.subTest(adicional=adicional), self.assertRaises(ValidationError):
                self._dados(**adicional)
        for valor in ("0.001", "NaN", "Infinity", "-1", "0"):
            with self.subTest(valor=valor), self.assertRaises(ValidationError):
                self._dados(pagamentos=[{"forma_pagamento": "pix", "valor": valor}])

    def test_bloqueia_todas_em_ordem_canonica_antes_de_preparar_primeira(self):
        ordem_locks = []
        original_lock = ordens_servico._bloquear_os_para_escrita
        original_preparar = ordens_servico._preparar_recebimento_ordem
        def bloquear(db, os_id):
            ordem_locks.append(os_id)
            return original_lock(db, os_id)
        def preparar(*args, **kwargs):
            self.assertEqual(ordem_locks, sorted(self.ids))
            return original_preparar(*args, **kwargs)
        dados = self._dados()
        dados.ordens.reverse()
        with patch.object(ordens_servico, "_bloquear_os_para_escrita", side_effect=bloquear), patch.object(ordens_servico, "_preparar_recebimento_ordem", side_effect=preparar):
            resposta = self._receber(dados)
        self.assertEqual(resposta["os_ids"], list(reversed(self.ids)))

    def test_recebimento_individual_rejeitado_tardiamente_tambem_faz_rollback(self):
        with self.assertRaises(HTTPException):
            ordens_servico.receber_ordem(
                self.ids[0], ordens_servico.OrdemServicoReceberInput(
                    pagamentos=[{"forma_pagamento": "pix", "valor": 1}],
                ), self.request, db=self.db, current_user=self.user,
            )
        self._verificar_sem_recebimento()
        self.assertEqual(self.db.get(OrdemServico, self.ids[0]).status, "Pendente")

    def test_cancelamento_e_exclusao_nao_sobrescrevem_os_paga(self):
        self._receber()
        for operacao in (
            lambda: ordens_servico.atualizar_ordem(self.ids[0], ordens_servico.OrdemServicoUpdate(status="Cancelado"), self.request, db=self.db, current_user=self.user),
            lambda: ordens_servico.deletar_ordem(self.ids[0], self.request, db=self.db, current_user=self.user),
        ):
            with self.assertRaises(HTTPException) as raised:
                operacao()
            self.assertEqual(raised.exception.status_code, 409)
            self.db.rollback()
        self.assertEqual(self.db.get(OrdemServico, self.ids[0]).status, "Pago")

    def test_recebimento_ativo_inconsistente_na_ultima_os_desfaz_anteriores(self):
        self.db.add(Transacao(
            tipo="entrada", categoria="consulta", valor=30.03, valor_final=30.03,
            status="Recebido", observacoes=f"OS_ID={self.ids[-1]};TIPO=RECEBIMENTO_OS",
        ))
        self.db.commit()
        with self.assertRaises(HTTPException) as raised:
            self._receber()
        self.assertEqual(raised.exception.status_code, 409)
        with self.Session() as db:
            self.assertEqual({item.status for item in db.query(OrdemServico)}, {"Pendente"})
            self.assertEqual(db.query(Transacao).count(), 1)
            self.assertEqual(db.query(OrdemServicoPagamento).count(), 0)
            self.assertEqual(db.query(CreditoFinanceiro).count(), 0)
            self.assertEqual(db.query(AuditoriaEvento).count(), 0)
        self.push.assert_not_called()

    def test_falha_de_persistencia_na_auditoria_desfaz_recebimento(self):
        AuditoriaEvento.__table__.drop(self.engine)
        with self.assertRaises(Exception):
            self._receber()
        with self.Session() as db:
            self.assertEqual({item.status for item in db.query(OrdemServico)}, {"Pendente"})
            self.assertEqual(db.query(Transacao).count(), 0)
            self.assertEqual(db.query(OrdemServicoPagamento).count(), 0)
            self.assertEqual(db.query(CreditoFinanceiro).count(), 0)
        self.push.assert_not_called()

    def test_rateio_varias_formas_preserva_taxas_e_brutos_sem_parcelas_negativas(self):
        self._criar_ordens(["0.01", "0.02", "99.98"])
        self._receber(self._dados(pagamentos=[
            {"forma_pagamento": "pix", "valor": "0.01", "taxa_percentual": 100},
            {"forma_pagamento": "debito", "valor": "50.00", "taxa_percentual": 1.99, "taxa_fixa": "0.20"},
            {"forma_pagamento": "credito", "valor": "50.00", "taxa_percentual": 2.99, "taxa_fixa": "0.30"},
        ]))
        with self.Session() as db:
            pagamentos = db.query(OrdemServicoPagamento).all()
            for os_id, valor in zip(self.ids, self.valores):
                self.assertEqual(sum(Decimal(str(p.valor_bruto)) for p in pagamentos if p.ordem_servico_id == os_id), Decimal(valor))
            for codigo, bruto, taxa in (("pix", "0.01", "0.01"), ("debito", "50.00", "1.20"), ("credito", "50.00", "1.80")):
                da_forma = [p for p in pagamentos if p.forma_pagamento_codigo == codigo]
                self.assertEqual(sum(Decimal(str(p.valor_bruto)) for p in da_forma), Decimal(bruto))
                self.assertEqual(sum(Decimal(str(p.valor_taxa)) for p in da_forma), Decimal(taxa))
            self.assertTrue(all(p.valor_bruto > 0 and p.valor_taxa >= 0 and p.valor_liquido >= 0 for p in pagamentos))
            self.assertEqual(db.query(CreditoFinanceiro).count(), 0)

    def test_rota_exige_edicao_de_os(self):
        usuario = SimpleNamespace(tem_papel=lambda _papel: False)
        with patch("app.core.security._user_has_matrix_permission", return_value=False) as permitido:
            with self.assertRaises(HTTPException) as raised:
                _authorize_request_by_matrix(self.request, self.db, usuario)
        self.assertEqual(raised.exception.status_code, 403)
        permitido.assert_called_once_with(self.db, usuario, "ordens_servico", "editar")

    def test_rota_http_estatica_entrega_contrato_e_conflito(self):
        app = FastAPI()
        app.include_router(ordens_servico.router, prefix="/api/v1/ordens-servico")
        def db_isolado():
            with self.Session() as db:
                yield db
        app.dependency_overrides[ordens_servico.get_db] = db_isolado
        app.dependency_overrides[ordens_servico.get_current_user] = lambda: self.user
        with TestClient(app) as client:
            payload = self._dados().model_dump(mode="json")
            resposta = client.patch("/api/v1/ordens-servico/receber-lote", json=payload)
            self.assertEqual(resposta.status_code, 200, resposta.text)
            self.assertEqual(resposta.json()["os_ids"], self.ids)
            repetida = client.patch("/api/v1/ordens-servico/receber-lote", json=payload)
            self.assertEqual(repetida.status_code, 409, repetida.text)


if __name__ == "__main__":
    unittest.main()
