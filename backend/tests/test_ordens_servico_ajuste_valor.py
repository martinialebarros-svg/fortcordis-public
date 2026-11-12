import json
import os
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from threading import Event, current_thread
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "ordens-ajuste-valor-test-secret-key-1234567890")

from app.api.v1.endpoints import ordens_servico, portal
from app.core.security import _authorize_request_by_matrix
from app.models.agendamento import Agendamento
from app.models.atendimento_clinico import AtendimentoClinico
from app.models.auditoria_evento import AuditoriaEvento
from app.models.clinica import Clinica
from app.models.configuracao import Configuracao, ConfiguracaoUsuario
from app.models.financeiro import CreditoFinanceiro, FormaPagamentoConfiguracao, OrdemServicoPagamento, Transacao
from app.models.ordem_servico import OrdemServico
from app.models.paciente import Paciente
from app.models.push_scheduled_notification import PushScheduledNotification
from app.models.servico import Servico
from app.models.tutor import Tutor
from app.services import push_scheduler_service


class OrdemServicoAjusteValorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{Path(self.tmpdir.name) / 'ajuste-valor.db'}")
        for model in (
            Tutor, Paciente, Clinica, Servico, Agendamento, AtendimentoClinico,
            OrdemServico, Transacao, OrdemServicoPagamento, CreditoFinanceiro,
            FormaPagamentoConfiguracao, AuditoriaEvento, PushScheduledNotification,
            Configuracao, ConfiguracaoUsuario,
        ):
            model.__table__.create(self.engine, checkfirst=True)
        self.SessionFactory = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        self.db = self.SessionFactory()
        self.user = SimpleNamespace(id=17, nome="Operadora Teste", email="operadora@example.com")
        self.request = Request({
            "type": "http", "method": "PATCH", "path": "/api/v1/ordens-servico/1/ajustar-valor",
            "headers": [], "client": ("127.0.0.1", 1234), "server": ("testserver", 80),
            "scheme": "http", "query_string": b"",
        })
        tutor = Tutor(nome="Tutora", ativo=1)
        paciente = Paciente(nome="Paciente", especie="Canina", ativo=1)
        clinica = Clinica(nome="Clinica")
        servico = Servico(nome="Consulta + Eco", preco=Decimal("480.00"))
        self.db.add_all([tutor, paciente, clinica, servico])
        self.db.flush()
        paciente.tutor_id = tutor.id
        agendamento = Agendamento(
            paciente_id=paciente.id, tutor_id=tutor.id, clinica_id=clinica.id,
            servico_id=servico.id, inicio=datetime(2026, 10, 1, 10), status="Realizado",
        )
        self.db.add(agendamento)
        self.db.flush()
        atendimento = AtendimentoClinico(
            paciente_id=paciente.id, tutor_id=tutor.id, clinica_id=clinica.id,
            agendamento_id=agendamento.id, veterinario_id=17,
            data_atendimento=agendamento.inicio, status="Concluido",
        )
        ordem = OrdemServico(
            numero_os="OS2099010001", agendamento_id=agendamento.id,
            paciente_id=paciente.id, clinica_id=clinica.id, servico_id=servico.id,
            data_atendimento=agendamento.inicio, tipo_horario="comercial",
            valor_servico=Decimal("480.00"), desconto=Decimal("20.00"),
            valor_final=Decimal("460.00"), status="Pendente",
            observacoes="OS sintetica gerada pela finalizacao de atendimento de teste",
            updated_at=datetime(2026, 10, 1, 10),
        )
        self.db.add_all([atendimento, ordem])
        self.db.commit()
        self.ids = (ordem.id, agendamento.id, atendimento.id, paciente.id, clinica.id, servico.id)

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()
        self.tmpdir.cleanup()

    def _ajustar(self, *, esperado="460.00", novo="380.00", motivo="Correcao do valor combinado"):
        return ordens_servico.ajustar_valor_ordem(
            self.ids[0], ordens_servico.OrdemServicoAjustarValorInput(
                valor_final_esperado=esperado, novo_valor_final=novo, motivo=motivo,
            ), self.request, db=self.db, current_user=self.user,
        )

    def _ordem(self) -> OrdemServico:
        self.db.expire_all()
        return self.db.get(OrdemServico, self.ids[0])

    def _executar_corrida(self, segunda_operacao):
        primeira_pronta = Event()
        segunda_tentando_lock = Event()
        liberar_primeira = Event()
        request_meta_original = ordens_servico._request_meta

        def request_meta_com_pausa(request):
            if current_thread().name == "primeira_operacao":
                primeira_pronta.set()
                if not liberar_primeira.wait(5):
                    raise AssertionError("A segunda sessao nao tentou acessar a OS.")
            return request_meta_original(request)

        def observar_sql(_conn, _cursor, statement, _params, _context, _many):
            if (current_thread().name == "segunda_operacao"
                    and statement.lower().startswith("update ordens_servico set id = id")):
                segunda_tentando_lock.set()

        def executar(nome, operacao):
            current_thread().name = nome
            db = self.SessionFactory()
            try:
                # Simula a transacao ja aberta pelas leituras de autenticacao.
                db.query(OrdemServico.id).filter(OrdemServico.id == self.ids[0]).first()
                try:
                    operacao(db)
                    return 200
                except HTTPException as exc:
                    return exc.status_code
            finally:
                db.close()

        def ajustar_primeira(db):
            ordens_servico.ajustar_valor_ordem(
                self.ids[0], ordens_servico.OrdemServicoAjustarValorInput(
                    valor_final_esperado="460.00", novo_valor_final="380.00", motivo="Ajuste concorrente",
                ), self.request, db=db, current_user=self.user,
            )

        event.listen(self.engine, "before_cursor_execute", observar_sql)
        try:
            with patch.object(ordens_servico, "_request_meta", side_effect=request_meta_com_pausa):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    primeira = pool.submit(executar, "primeira_operacao", ajustar_primeira)
                    self.assertTrue(primeira_pronta.wait(5))
                    segunda = pool.submit(executar, "segunda_operacao", segunda_operacao)
                    self.assertTrue(segunda_tentando_lock.wait(5))
                    liberar_primeira.set()
                    return primeira.result(timeout=10), segunda.result(timeout=10)
        finally:
            liberar_primeira.set()
            event.remove(self.engine, "before_cursor_execute", observar_sql)

    def test_ajuste_preserva_vinculos_desconto_e_grava_auditoria_na_mesma_transacao(self) -> None:
        resposta = self._ajustar(motivo="  Valor acordado com a clinica  ")

        ordem = self._ordem()
        self.assertEqual(resposta["valor_final"], 380.0)
        self.assertEqual((ordem.id, ordem.agendamento_id, ordem.paciente_id, ordem.clinica_id, ordem.servico_id),
                         (self.ids[0], self.ids[1], self.ids[3], self.ids[4], self.ids[5]))
        self.assertEqual(ordem.status, "Pendente")
        self.assertEqual(ordem.desconto, Decimal("20.00"))
        self.assertEqual(ordem.valor_servico, Decimal("400.00"))
        self.assertEqual(ordem.valor_final, Decimal("380.00"))
        self.assertEqual(self.db.get(AtendimentoClinico, self.ids[2]).status, "Concluido")
        evento = self.db.query(AuditoriaEvento).one()
        self.assertEqual(evento.acao, "ORDEM_SERVICO_VALOR_AJUSTADO")
        self.assertEqual((evento.usuario_id, evento.usuario_nome, evento.metodo), (17, "Operadora Teste", "PATCH"))
        detalhes = json.loads(evento.detalhes_json)
        self.assertEqual(detalhes["motivo"], "Valor acordado com a clinica")
        self.assertEqual((detalhes["valor_final_anterior"], detalhes["valor_final_novo"]), ("460.00", "380.00"))
        self.assertEqual((detalhes["valor_servico_anterior"], detalhes["valor_servico_novo"]), ("480.00", "400.00"))
        resumo = ordens_servico.listar_ordens(
            db=self.db, current_user=self.user, tipo_horario=None, incluir_resumo=True,
        )["resumo"]
        self.assertEqual(resumo["valor_pendente"], 380.0)

    def test_rota_patch_exige_permissao_de_editar_os(self) -> None:
        usuario_sem_permissao = SimpleNamespace(tem_papel=lambda _papel: False)
        with patch("app.core.security._user_has_matrix_permission", return_value=False) as permitido:
            with self.assertRaises(HTTPException) as raised:
                _authorize_request_by_matrix(self.request, self.db, usuario_sem_permissao)
        self.assertEqual(raised.exception.status_code, 403)
        permitido.assert_called_once_with(self.db, usuario_sem_permissao, "ordens_servico", "editar")

    def test_portal_da_clinica_le_valor_ajustado_sem_expor_motivo(self) -> None:
        self._ajustar(motivo="Acerto financeiro interno")
        clinica = self.db.get(Clinica, self.ids[4])
        with patch.object(portal, "_exigir_sessao_clinica_portal", return_value=clinica):
            resposta = portal.obter_financeiro_clinica_portal(
                db=self.db, portal_session=SimpleNamespace(),
            )
        self.assertEqual(resposta.summary.total_pendente, 380.0)
        self.assertEqual(resposta.pendentes[0].valor, 380.0)
        self.assertNotIn("Acerto financeiro interno", resposta.model_dump_json())

    def test_relatorio_pendente_recebe_valor_ajustado_sem_motivo(self) -> None:
        self._ajustar(motivo="Acerto financeiro interno")
        with patch.object(ordens_servico, "_gerar_pdf_cobranca_pendencias", return_value=b"%PDF-teste") as render:
            resposta = ordens_servico.gerar_relatorio_pendencias_pdf(
                status="Pendente", tipo_horario=None, db=self.db, current_user=self.user,
            )
        self.assertEqual(resposta.media_type, "application/pdf")
        itens = render.call_args.kwargs["itens"]
        self.assertEqual(len(itens), 1)
        self.assertEqual(itens[0]["valor_final"], 380.0)
        self.assertNotIn("Acerto financeiro interno", json.dumps(itens, default=str))

    def test_repeticao_com_valor_esperado_antigo_nao_sobrescreve_ajuste(self) -> None:
        self._ajustar()
        with self.assertRaises(HTTPException) as raised:
            self._ajustar(novo="350.00")
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(self._ordem().valor_final, Decimal("380.00"))
        self.assertEqual(self.db.query(AuditoriaEvento).count(), 1)

    def test_duas_sessoes_nao_aceitam_o_mesmo_valor_esperado(self) -> None:
        def ajustar_segunda(db):
            ordens_servico.ajustar_valor_ordem(
                self.ids[0], ordens_servico.OrdemServicoAjustarValorInput(
                    valor_final_esperado="460.00", novo_valor_final="350.00", motivo="Outro ajuste",
                ), self.request, db=db, current_user=self.user,
            )

        self.assertEqual(self._executar_corrida(ajustar_segunda), (200, 409))
        self.assertEqual(self._ordem().valor_final, Decimal("380.00"))
        self.assertEqual(self.db.query(AuditoriaEvento).count(), 1)

    def test_ajuste_concorrente_com_recebimento_nao_diverge_transacao(self) -> None:
        def receber_segunda(db):
            with (
                patch.object(ordens_servico, "registrar_auditoria"),
                patch.object(ordens_servico, "send_financeiro_push_notification"),
                patch.object(ordens_servico, "cancel_pending_os_payment_reminder"),
            ):
                ordens_servico.receber_ordem(
                    self.ids[0], ordens_servico.OrdemServicoReceberInput(forma_pagamento="dinheiro"),
                    self.request, db=db, current_user=self.user,
                )

        primeira, segunda = self._executar_corrida(receber_segunda)
        self.assertEqual(primeira, 200)
        self.assertIn(segunda, (200, 409))
        ordem = self._ordem()
        self.assertEqual(ordem.valor_final, Decimal("380.00"))
        transacoes = self.db.query(Transacao).filter(Transacao.status == "Recebido").all()
        if ordem.status == "Pago":
            self.assertEqual(len(transacoes), 1)
            self.assertEqual(Decimal(str(transacoes[0].valor)), ordem.valor_final)
        else:
            self.assertEqual(ordem.status, "Pendente")
            self.assertEqual(transacoes, [])

    def test_put_de_observacoes_preserva_valor_ajustado(self) -> None:
        self._ajustar()
        with patch.object(ordens_servico, "registrar_auditoria"):
            ordens_servico.atualizar_ordem(
                self.ids[0], ordens_servico.OrdemServicoUpdate(observacoes="Conferencia financeira"),
                self.request, db=self.db, current_user=self.user,
            )
        ordem = self._ordem()
        self.assertEqual(ordem.observacoes, "Conferencia financeira")
        self.assertEqual((ordem.valor_servico, ordem.desconto, ordem.valor_final),
                         (Decimal("400.00"), Decimal("20.00"), Decimal("380.00")))

    def test_motivo_vazio_valor_igual_e_valor_desatualizado_nao_alteram_os(self) -> None:
        for dados, status_code in (
            ({"motivo": "   "}, 422), ({"novo": "460.00"}, 422), ({"esperado": "459.99"}, 409),
        ):
            with self.subTest(dados=dados), self.assertRaises(HTTPException) as raised:
                self._ajustar(**dados)
            self.assertEqual(raised.exception.status_code, status_code)
        self.assertEqual(self._ordem().valor_final, Decimal("460.00"))
        self.assertEqual(self._ordem().updated_at, datetime(2026, 10, 1, 10))
        self.assertEqual(self.db.query(AuditoriaEvento).count(), 0)

    def test_status_pago_ou_cancelado_bloqueia_ajuste(self) -> None:
        for status_os in ("Pago", "Cancelado"):
            with self.subTest(status=status_os):
                ordem = self.db.get(OrdemServico, self.ids[0])
                ordem.status = status_os
                self.db.commit()
                with self.assertRaises(HTTPException) as raised:
                    self._ajustar()
                self.assertEqual(raised.exception.status_code, 409)
                self.assertEqual(self._ordem().valor_final, Decimal("460.00"))
        self.assertEqual(self.db.query(AuditoriaEvento).count(), 0)

    def test_centavos_valor_positivo_e_limite_do_bruto(self) -> None:
        for novo in ("1.001", "0", "-1"):
            with self.subTest(novo=novo), self.assertRaises(ValidationError):
                ordens_servico.OrdemServicoAjustarValorInput(
                    valor_final_esperado="460.00", novo_valor_final=novo, motivo="Correcao",
                )
        with self.assertRaises(ValidationError):
            ordens_servico.OrdemServicoAjustarValorInput(
                valor_final_esperado="460.001", novo_valor_final="1.00", motivo="Correcao",
            )
        with self.assertRaises(HTTPException) as raised:
            self._ajustar(novo="99999999.99")
        self.assertEqual(raised.exception.status_code, 422)
        self.assertEqual(self._ordem().valor_final, Decimal("460.00"))

    def test_recebimento_ativo_inconsistente_bloqueia_ajuste(self) -> None:
        self.db.add(Transacao(
            tipo="entrada", categoria="consulta", valor=460, valor_final=460,
            status="Recebido", observacoes=f"OS_ID={self.ids[0]};TIPO=RECEBIMENTO_OS",
        ))
        self.db.commit()
        with self.assertRaises(HTTPException) as raised:
            self._ajustar()
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(self._ordem().valor_final, Decimal("460.00"))

    def test_falha_na_auditoria_desfaz_o_ajuste(self) -> None:
        AuditoriaEvento.__table__.drop(self.engine)
        with self.assertRaises(Exception):
            self._ajustar()
        self.assertEqual(self._ordem().valor_final, Decimal("460.00"))
        self.assertEqual(self._ordem().valor_servico, Decimal("480.00"))

    def test_recebimento_apos_ajuste_usa_valor_novo(self) -> None:
        self._ajustar()
        with (
            patch.object(ordens_servico, "registrar_auditoria"),
            patch.object(ordens_servico, "send_financeiro_push_notification"),
            patch.object(ordens_servico, "cancel_pending_os_payment_reminder"),
        ):
            resposta = ordens_servico.receber_ordem(
                self.ids[0], ordens_servico.OrdemServicoReceberInput(
                    forma_pagamento="dinheiro", valor_final_esperado="380.00",
                ),
                self.request, db=self.db, current_user=self.user,
            )
        self.assertEqual(resposta["valor_os"], 380.0)
        self.assertEqual(self._ordem().status, "Pago")
        transacao = self.db.query(Transacao).one()
        self.assertEqual(transacao.valor, 380.0)

    def test_recebimento_legado_sem_valor_esperado_permanece_compativel(self) -> None:
        with (
            patch.object(ordens_servico, "registrar_auditoria"),
            patch.object(ordens_servico, "send_financeiro_push_notification"),
            patch.object(ordens_servico, "cancel_pending_os_payment_reminder"),
        ):
            resposta = ordens_servico.receber_ordem(
                self.ids[0], ordens_servico.OrdemServicoReceberInput(forma_pagamento="dinheiro"),
                self.request, db=self.db, current_user=self.user,
            )
        self.assertEqual(resposta["valor_os"], 460.0)
        self.assertEqual(self.db.query(Transacao).one().valor, 460.0)

    def test_recebimento_com_preco_antigo_nao_gera_credito_excedente(self) -> None:
        self._ajustar()
        dados = ordens_servico.OrdemServicoReceberInput(
            valor_final_esperado="460.00",
            pagamentos=[ordens_servico.OrdemServicoPagamentoItemInput(
                forma_pagamento="dinheiro", valor=460,
            )],
            destino_credito_excedente="cliente",
        )
        with self.assertRaises(HTTPException) as raised:
            ordens_servico.receber_ordem(
                self.ids[0], dados, self.request, db=self.db, current_user=self.user,
            )
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual((self._ordem().status, self._ordem().valor_final),
                         ("Pendente", Decimal("380.00")))
        self.assertEqual(self.db.query(Transacao).count(), 0)
        self.assertEqual(self.db.query(OrdemServicoPagamento).count(), 0)
        self.assertEqual(self.db.query(CreditoFinanceiro).count(), 0)

    def test_lembrete_usa_valor_atual_apesar_do_snapshot_antigo(self) -> None:
        self._ajustar()
        lembrete = PushScheduledNotification(
            kind=push_scheduler_service.PUSH_SCHEDULE_KIND_PENDING_OS,
            status=push_scheduler_service.PUSH_SCHEDULE_STATUS_PENDING,
            module="financeiro", action="payment_pending", resource_type="ordem_servico",
            resource_id=self.ids[0], send_at=datetime(2026, 10, 2),
            payload_json=json.dumps({"valor_final": "460.00", "lembrete_horas": "6"}),
        )
        self.db.add(lembrete)
        self.db.commit()
        with patch("app.services.push_notifications.send_financeiro_push_notification", return_value={"sent": 1}) as send:
            push_scheduler_service._process_pending_os_row(self.db, lembrete)
        self.assertEqual(send.call_args.kwargs["data"]["valor_final"], "380.00")
        self.assertEqual(send.call_args.kwargs["data"]["lembrete_horas"], "6")


if __name__ == "__main__":
    unittest.main()
