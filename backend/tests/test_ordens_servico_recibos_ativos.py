"""Regressao do recibo apos estorno e novo recebimento; somente SQLite sintetico."""
import asyncio
import os
import sys
import unittest
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from pypdf import PdfReader

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "recibo-ativo-test-secret-key-synthetic-1234567890")

from tests import test_ordens_servico_receber_lote as fixtures
from app.api.v1.endpoints import ordens_servico as endpoint, portal
from tests.test_portal_clinica_recibo import _portal_session
from app.models.clinica import Clinica
from app.models.paciente import Paciente
from app.models.servico import Servico
from app.models.tutor import Tutor
from app.models.configuracao import Configuracao, ConfiguracaoUsuario
from app.models.financeiro import CreditoFinanceiro, OrdemServicoPagamento, Transacao
from app.models.ordem_servico import OrdemServico


class RecibosRecebimentosAtivosTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.RecebimentoLoteTest("test_repeticao_retorna_conflito_sem_novos_movimentos")
        self.fixture.setUp()
        self.fixture._criar_ordens(["230.00", "230.00"])
        self.db = self.fixture.db
        self.ids = self.fixture.ids
        for model in (Configuracao, ConfiguracaoUsuario):
            model.__table__.create(self.fixture.engine, checkfirst=True)
        self.db.add_all([
            Tutor(id=1, nome="Tutor ficticio - teste de recibos", ativo=1),
            Paciente(id=1, nome="Pet ficticio A", especie="Canina", tutor_id=1, ativo=1),
            Paciente(id=2, nome="Pet ficticio B", especie="Canina", tutor_id=1, ativo=1),
            Clinica(id=1, nome="Clinica ficticia - teste de recibos", ativo=True, whatsapps=["5500000000000"]),
            Servico(id=1, nome="Servico ficticio de homologacao", preco=Decimal("230.00")),
        ])
        self.db.commit()
        self.audit = patch.object(endpoint, "registrar_auditoria")
        self.audit.start()
        self.addCleanup(self.audit.stop)

    def tearDown(self):
        self.fixture.tearDown()
        self.fixture.doCleanups()

    def _receber(self, os_id, **kwargs):
        return endpoint.receber_ordem(
            os_id, endpoint.OrdemServicoReceberInput(**kwargs), self.fixture.request,
            db=self.db, current_user=self.fixture.user,
        )

    def _desfazer(self, os_id):
        return endpoint.desfazer_recebimento_ordem(
            os_id, self.fixture.request, db=self.db, current_user=self.fixture.user,
        )

    def _individual_desfeito_e_lote(self):
        self._receber(self.ids[1], pagamentos=[{
            "forma_pagamento": "cartao_antigo", "valor": 230,
            "taxa_percentual": 2, "taxa_fixa": 1,
        }], data_recebimento=date(2026, 10, 10))
        self._desfazer(self.ids[1])
        # A data antiga cancelada e posterior a nova para detectar max indevido.
        self.fixture._receber(self.fixture._dados(
            pagamentos=[{"forma_pagamento": "pix", "valor": "460.00", "taxa_percentual": 1, "taxa_fixa": "0.40"}],
            data_recebimento=date(2026, 10, 9),
        ))

    def _pdf(self, *, agrupar, ids=None):
        return endpoint._gerar_pdf_recibos_para_ids(
            db=self.db, current_user=self.fixture.user, ids=ids or self.ids, agrupar=agrupar,
        )[0]

    @staticmethod
    def _texto_pdf(pdf):
        return "\n".join(page.extract_text() for page in PdfReader(BytesIO(pdf)).pages)

    def _adicionar_historico(self, *, os_id=None, transacao_id=None, status_transacao=None, tipo="entrada", bruto=230, nome="Pagamento sem prova"):
        if status_transacao:
            transacao = Transacao(
                tipo=tipo, categoria="consulta", valor=bruto, valor_final=bruto,
                status=status_transacao, data_pagamento=datetime(2026, 10, 8),
            )
            self.db.add(transacao)
            self.db.flush()
            transacao_id = transacao.id
        pagamento = OrdemServicoPagamento(
            ordem_servico_id=os_id or self.ids[0], transacao_id=transacao_id,
            forma_pagamento_codigo="historico", forma_pagamento_nome=nome,
            valor_bruto=bruto, valor_taxa=5, valor_liquido=bruto - 5,
            data_recebimento=datetime(2026, 10, 10),
        )
        self.db.add(pagamento)
        self.db.commit()
        return pagamento.id

    def test_receber_desfazer_e_receber_lote_preserva_historico_e_compoe_apenas_ativos(self):
        self._individual_desfeito_e_lote()
        recibos = endpoint._montar_recibos_os(self.db, self.ids)
        self.assertEqual(len(recibos), 2)
        for recibo in recibos:
            self.assertEqual(recibo["valor_final"], 230)
            self.assertEqual(len(recibo["pagamentos"]), 1)
            self.assertEqual(recibo["pagamentos"][0]["forma_pagamento_nome"], "Pix")
            self.assertEqual(recibo["valor_taxa_total"], 2.50)
            self.assertEqual(recibo["valor_liquido_total"], 227.50)
            self.assertEqual(recibo["valor_liquido_exibido"], 227.50)
            self.assertEqual(recibo["data_recebimento"].date(), date(2026, 10, 9))
        self.assertEqual(self.db.query(OrdemServicoPagamento).count(), 3)
        transacoes = self.db.query(Transacao).order_by(Transacao.id).all()
        self.assertEqual([t.status for t in transacoes], ["Cancelado", "Recebido", "Recebido"])
        self.assertEqual(Decimal(str(sum(t.valor for t in transacoes if t.status == "Recebido"))), Decimal("460.0"))

    def test_pdf_individual_e_consolidado_usam_mesma_composicao_ativa(self):
        self._individual_desfeito_e_lote()
        individual = self._texto_pdf(self._pdf(agrupar=False, ids=[self.ids[1]]))
        consolidado = self._texto_pdf(self._pdf(agrupar=True))
        for texto in (individual, consolidado):
            self.assertNotIn("Cartao Antigo", texto)
            self.assertNotIn("10/10/2026", texto)
        self.assertIn("R$ 227,50", individual)
        self.assertIn("R$ 2,50", individual)
        self.assertNotIn("R$ 460,00", individual)
        self.assertEqual(individual.count("Pix"), 1)
        self.assertEqual(consolidado.count("Pix"), 2)
        self.assertIn("R$ 460,00", consolidado)

    def test_pdf_do_portal_tambem_exclui_recebimento_desfeito(self):
        self._individual_desfeito_e_lote()
        response = portal.baixar_recibo_os_clinica_portal(
            self.ids[1], db=self.db, portal_session=_portal_session(clinica_id=1),
        )
        async def ler_corpo():
            return b"".join([chunk async for chunk in response.body_iterator])
        texto = self._texto_pdf(asyncio.run(ler_corpo()))
        self.assertNotIn("Cartao Antigo", texto)
        self.assertEqual(texto.count("Pix"), 1)
        self.assertIn("R$ 227,50", texto)
        self.assertNotIn("R$ 460,00", texto)

    def test_pdf_entregue_ao_adapter_whatsapp_usa_somente_recebimentos_ativos(self):
        self._individual_desfeito_e_lote()
        for ids in ([self.ids[1]], self.ids):
            with self.subTest(ids=ids), patch.object(endpoint, "send_approved_document_template", return_value={"message_id": "sintetico-sem-envio"}) as enviar:
                endpoint._enviar_recibo_pdf_whatsapp(
                    os_ids=ids,
                    payload=endpoint.OrdemServicoWhatsAppInput(idempotency_key="recibo-sintetico-sem-envio"),
                    request=self.fixture.request, db=self.db, current_user=self.fixture.user,
                )
                pdf = enviar.call_args.kwargs["document_bytes"]
                texto = self._texto_pdf(pdf)
                self.assertNotIn("Cartao Antigo", texto)
                self.assertEqual(texto.count("Pix"), len(ids))
                self.assertIn("R$ 460,00" if len(ids) > 1 else "R$ 227,50", texto)

    def test_credito_estornado_nao_reaparece_e_credito_ativo_compoe_recibo(self):
        self.db.add(CreditoFinanceiro(
            tipo_destino="cliente", paciente_id=self.ids[0], tutor_id=1, valor=200,
            status="Ativo", origem="manual", data_movimento=datetime(2026, 10, 1),
        ))
        self.db.commit()
        self._receber(self.ids[0], pagamentos=[{"forma_pagamento": "dinheiro", "valor": 130}], valor_credito_utilizado=100)
        self._desfazer(self.ids[0])
        self._receber(self.ids[0], pagamentos=[{"forma_pagamento": "pix", "valor": 30}], valor_credito_utilizado=200)
        recibo = endpoint._montar_recibos_os(self.db, [self.ids[0]])[0]
        self.assertEqual(recibo["valor_credito_utilizado"], 200)
        self.assertEqual(recibo["valor_liquido_exibido"], 230)
        self.assertEqual([p["valor_bruto"] for p in recibo["pagamentos"]], [30])
        creditos = self.db.query(CreditoFinanceiro).filter_by(origem="consumo_credito_os").order_by(CreditoFinanceiro.id).all()
        self.assertEqual([(c.valor, c.status) for c in creditos], [(-100, "Cancelado"), (-200, "Ativo")])

    def test_somente_credito_ativo_apos_estorno_e_recebimento_valido(self):
        self._receber(self.ids[0], forma_pagamento="dinheiro")
        self._desfazer(self.ids[0])
        self.db.add(CreditoFinanceiro(
            tipo_destino="cliente", paciente_id=self.ids[0], tutor_id=1, valor=230,
            status="Ativo", origem="manual", data_movimento=datetime(2026, 10, 1),
        ))
        self.db.commit()
        self._receber(self.ids[0], valor_credito_utilizado=230)
        recibo = endpoint._montar_recibos_os(self.db, [self.ids[0]])[0]
        self.assertEqual(recibo["pagamentos"], [])
        self.assertEqual(recibo["valor_credito_utilizado"], 230)
        self.assertEqual(recibo["valor_liquido_exibido"], 230)
        self.assertFalse(recibo["possui_detalhamento_legacy"])

    def test_exclui_historico_cancelado_pendente_e_saida_sem_apagar_linhas(self):
        self._receber(self.ids[0], forma_pagamento="pix")
        for status_transacao, tipo in (("Cancelado", "entrada"), ("Pendente", "entrada"), ("Recebido", "saida")):
            self._adicionar_historico(status_transacao=status_transacao, tipo=tipo)
        recibo = endpoint._montar_recibos_os(self.db, [self.ids[0]])[0]
        self.assertEqual(len(recibo["pagamentos"]), 1)
        self.assertEqual(recibo["valor_liquido_exibido"], 230)
        self.assertEqual(self.db.query(OrdemServicoPagamento).count(), 4)

    def test_transacao_pago_ainda_comprova_recebimento(self):
        self._receber(self.ids[0], forma_pagamento="pix")
        self.db.query(Transacao).one().status = "Pago"
        self.db.commit()
        recibo = endpoint._montar_recibos_os(self.db, [self.ids[0]])[0]
        self.assertEqual(len(recibo["pagamentos"]), 1)
        self.assertEqual(recibo["valor_liquido_exibido"], 230)

    def test_legado_sem_vinculo_nao_inventa_forma_taxas_ou_liquido(self):
        for com_historico in (False, True):
            with self.subTest(com_historico=com_historico):
                self.db.get(OrdemServico, self.ids[0]).status = "Pago"
                self.db.commit()
                if com_historico:
                    self._adicionar_historico(transacao_id=None)
                recibo = endpoint._montar_recibos_os(self.db, [self.ids[0]])[0]
                self.assertEqual(recibo["pagamentos"], [])
                self.assertTrue(recibo["possui_detalhamento_legacy"])
                self.assertEqual(recibo["valor_final"], 230)
                self.assertIsNone(recibo["valor_taxa_total"])
                self.assertIsNone(recibo["valor_liquido_exibido"])
                texto = self._texto_pdf(self._pdf(agrupar=False, ids=[self.ids[0]]))
                self.assertIn("Taxas e valor liquido nao informados", texto)
                self.assertNotIn("Pagamento sem prova", texto)

    def test_orfao_vinculado_bloqueia_recibo_mesmo_com_recebimento_ativo(self):
        self._receber(self.ids[0], forma_pagamento="pix")
        self._adicionar_historico(transacao_id=999999)
        with self.assertRaises(HTTPException) as raised:
            endpoint._montar_recibos_os(self.db, [self.ids[0]])
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(self.db.query(OrdemServicoPagamento).count(), 2)

    def test_historico_cancelado_nao_e_reinterpretado_como_legado(self):
        self._receber(self.ids[0], forma_pagamento="pix")
        self._desfazer(self.ids[0])
        # Simula inconsistencia anterior ao recibo; nao fabrica nova baixa.
        self.db.get(OrdemServico, self.ids[0]).status = "Pago"
        self.db.commit()
        with self.assertRaises(HTTPException) as raised:
            endpoint._montar_recibos_os(self.db, [self.ids[0]])
        self.assertEqual(raised.exception.status_code, 409)

    def test_cobertura_parcial_ativa_nao_emite_quitacao_integral(self):
        self._receber(self.ids[0], pagamentos=[
            {"forma_pagamento": "pix", "valor": 100},
            {"forma_pagamento": "dinheiro", "valor": 130},
        ])
        self.db.query(Transacao).filter_by(forma_pagamento="dinheiro").one().status = "Cancelado"
        self.db.commit()
        with self.assertRaises(HTTPException) as raised:
            endpoint._montar_recibos_os(self.db, [self.ids[0]])
        self.assertEqual(raised.exception.status_code, 409)

    def test_excedente_legitimo_nao_e_bloqueado(self):
        self._receber(self.ids[0], pagamentos=[{"forma_pagamento": "pix", "valor": 250}])
        recibo = endpoint._montar_recibos_os(self.db, [self.ids[0]])[0]
        self.assertEqual(recibo["valor_final"], 230)
        self.assertEqual(recibo["valor_liquido_exibido"], 250)
        self.assertEqual(self.db.query(CreditoFinanceiro).filter_by(origem="excedente_pagamento_os").one().valor, 20)


if __name__ == "__main__":
    unittest.main()
