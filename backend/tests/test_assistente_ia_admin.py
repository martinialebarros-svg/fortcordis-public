import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
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
os.environ.setdefault("SECRET_KEY", "assistente-ia-admin-test-secret-key-1234567890")

from app.core.security import require_papel
from app.api.v1.endpoints import assistente_ia as assistente_ia_endpoint
from app.models.agendamento import Agendamento
from app.models.agenda_bloqueio import AgendaBloqueio
from app.models.assistente_ia import (
    AssistenteIAAcaoPendente,
    AssistenteIAAprendizado,
    AssistenteIAConhecimentoDocumento,
    AssistenteIAConversa,
    AssistenteIAFeedback,
    AssistenteIAMemoria,
    AssistenteIAMemoriaVersao,
    AssistenteIAMensagem,
    AssistenteIARegressaoCaso,
    AssistenteIARascunhoClinico,
)
from app.models.clinica import Clinica
from app.models.configuracao import Configuracao
from app.models.financeiro import ContaReceber, Transacao
from app.models.laudo import Laudo
from app.models.ordem_servico import OrdemServico
from app.models.paciente import Paciente
from app.models.servico import Servico
from app.models.tabela_preco import PrecoServico, PrecoServicoClinica, TabelaPreco
from app.models.tutor import Tutor
from app.services import assistente_ia_management, assistente_ia_service, assistente_ia_tools


class AssistenteIAAdminTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self._tmpdir.name) / "assistente-ia-admin.db"
        self._engine = create_engine(f"sqlite:///{db_path}")
        self._session_factory = sessionmaker(bind=self._engine, autocommit=False, autoflush=False)
        for table in (
            Configuracao.__table__,
            Tutor.__table__,
            Paciente.__table__,
            Clinica.__table__,
            Servico.__table__,
            TabelaPreco.__table__,
            PrecoServico.__table__,
            PrecoServicoClinica.__table__,
            Agendamento.__table__,
            Transacao.__table__,
            OrdemServico.__table__,
            ContaReceber.__table__,
            Laudo.__table__,
            AssistenteIAConversa.__table__,
            AssistenteIAMensagem.__table__,
            AssistenteIAAcaoPendente.__table__,
            AssistenteIAMemoria.__table__,
            AssistenteIAAprendizado.__table__,
            AssistenteIAMemoriaVersao.__table__,
            AssistenteIARegressaoCaso.__table__,
            AssistenteIAConhecimentoDocumento.__table__,
            AssistenteIAFeedback.__table__,
            AssistenteIARascunhoClinico.__table__,
            AgendaBloqueio.__table__,
        ):
            table.create(self._engine, checkfirst=True)

        self.user = SimpleNamespace(
            id=7,
            nome="Administrador",
            email="admin@fortcordis.com",
            tem_papel=lambda role: str(role).lower() == "admin",
        )

    def tearDown(self) -> None:
        self._engine.dispose()
        self._tmpdir.cleanup()

    def _seed_base(self, db):
        clinic = Clinica(
            nome="Animal Care",
            ativo=True,
            telefone="(85) 98894-6484",
            whatsapps=["85988946484", "85999998888"],
            endereco="Rua Teste",
            numero="100",
            cidade="Fortaleza",
            estado="CE",
            latitude=-3.7319,
            longitude=-38.5267,
        )
        service = Servico(nome="Ecocardiograma", duracao_minutos=30, ativo=True)
        tutor = Tutor(nome="Ana Oliveira", telefone="(85) 98765-4321", whatsapp="85987654321", ativo=1)
        db.add(tutor)
        db.flush()
        patient = Paciente(nome="Luna Oliveira", tutor_id=tutor.id, ativo=1)
        conversation = AssistenteIAConversa(
            id="conversation-test",
            usuario_id=self.user.id,
            titulo="Nova conversa",
            ativa=True,
        )
        db.add_all([clinic, service, patient, conversation])
        db.commit()
        for item in (clinic, service, patient, conversation):
            db.refresh(item)
        return clinic, service, patient, conversation

    def _appointment(self, db, clinic, service, patient, *, hour=10):
        reference = datetime.now(assistente_ia_tools.LOCAL_TZ).replace(
            hour=hour,
            minute=0,
            second=0,
            microsecond=0,
        )
        appointment = Agendamento(
            paciente_id=patient.id,
            clinica_id=clinic.id,
            servico_id=service.id,
            inicio=reference,
            fim=reference + timedelta(minutes=30),
            data=reference.date().isoformat(),
            hora=reference.strftime("%H:%M"),
            status="Agendado",
        )
        db.add(appointment)
        db.commit()
        db.refresh(appointment)
        return appointment

    def _context(self, db, conversation):
        return assistente_ia_tools.AssistenteIAToolContext(
            db=db,
            current_user=self.user,
            conversa=conversation,
            request=SimpleNamespace(headers={}),
        )

    def _agenda_config(self, db, *, exceptions=None):
        config = Configuracao(
            agenda_excecoes=json.dumps(exceptions or []),
            agenda_semanal=None,
            agenda_feriados=None,
        )
        db.add(config)
        db.commit()
        db.refresh(config)
        return config

    def test_rotas_exigem_papel_admin(self) -> None:
        protected_routes = 0
        for route in assistente_ia_endpoint.router.routes:
            dependencies = getattr(getattr(route, "dependant", None), "dependencies", [])
            guards = [dependency.call for dependency in dependencies]
            has_admin_guard = any(
                any(cell.cell_contents == "admin" for cell in (guard.__closure__ or ()))
                for guard in guards
            )
            self.assertTrue(has_admin_guard, f"Rota sem guard admin: {getattr(route, 'path', '')}")
            protected_routes += 1
        self.assertGreaterEqual(protected_routes, 17)

        guard = require_papel("admin")
        non_admin = SimpleNamespace(tem_papel=lambda _role: False)

        with self.assertRaises(HTTPException) as error:
            guard(non_admin)

        self.assertEqual(error.exception.status_code, 403)

    def test_localiza_agendamento_sem_expor_dados_do_tutor(self) -> None:
        with self._session_factory() as db:
            clinic, service, patient, conversation = self._seed_base(db)
            appointment = self._appointment(db, clinic, service, patient)
            result = assistente_ia_tools.localizar_agendamentos(
                self._context(db, conversation),
                data=appointment.data,
                horario="10:00",
                clinica="animal care",
                servico=None,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["matches"][0]["agendamento_id"], appointment.id)
        self.assertEqual(result["matches"][0]["paciente_primeiro_nome"], "Luna")
        self.assertNotIn("telefone", str(result).lower())
        self.assertNotIn("tutor", str(result).lower())

    def test_resolve_erro_evidente_no_nome_da_clinica_sem_assumir_ambiguidade(self) -> None:
        with self._session_factory() as db:
            animal_care, _service, _patient, _conversation = self._seed_base(db)
            db.add_all(
                [
                    Clinica(nome="Animal Clinic", ativo=True),
                    Clinica(nome="Vet World", ativo=True),
                ]
            )
            db.commit()

            resolved_typo, typo_error = assistente_ia_tools._resolve_named_record(
                db,
                Clinica,
                "Animla Care",
                entity_label="clinica",
            )
            resolved_voice, voice_error = assistente_ia_tools._resolve_named_record(
                db,
                Clinica,
                "Vet Wrold",
                entity_label="clinica",
            )
            ambiguous, ambiguous_error = assistente_ia_tools._resolve_named_record(
                db,
                Clinica,
                "Animal",
                entity_label="clinica",
            )

        self.assertEqual(resolved_typo.id, animal_care.id)
        self.assertIsNone(typo_error)
        self.assertEqual(resolved_voice.nome, "Vet World")
        self.assertIsNone(voice_error)
        self.assertIsNone(ambiguous)
        self.assertIn("ambiguo", ambiguous_error["error"].lower())
        self.assertEqual(
            {item["nome"] for item in ambiguous_error["matches"]},
            {"Animal Care", "Animal Clinic"},
        )

    def test_excecao_de_funcionamento_fica_pendente_sem_alterar_configuracao(self) -> None:
        with self._session_factory() as db:
            _clinic, _service, _patient, conversation = self._seed_base(db)
            config = self._agenda_config(db)
            future = datetime.now(assistente_ia_tools.LOCAL_TZ).date() + timedelta(days=7)
            before_raw = config.agenda_excecoes
            with patch.object(assistente_ia_tools, "registrar_auditoria"):
                prepared = assistente_ia_tools.solicitar_excecao_funcionamento_agenda(
                    self._context(db, conversation),
                    data=future.isoformat(),
                    ativo=True,
                    inicio=None,
                    fim="18:00",
                    motivo="Ampliar atendimento",
                )

            db.refresh(config)
            self.assertTrue(prepared["ok"])
            self.assertTrue(prepared["requires_approval"])
            self.assertEqual(prepared["pending_action"]["type"], "update_agenda_exception")
            self.assertEqual(prepared["pending_action"]["target"]["depois"]["fim"], "18:00")
            self.assertTrue(prepared["pending_action"]["target"]["depois"]["ativo"])
            provider_result = assistente_ia_tools.tool_result_for_model(
                "solicitar_excecao_funcionamento_agenda",
                prepared,
            )
            self.assertNotIn("agenda_excecoes_antes", str(provider_result))
            self.assertEqual(config.agenda_excecoes, before_raw)

    def test_excecao_de_funcionamento_aplica_somente_apos_aprovacao(self) -> None:
        with self._session_factory() as db:
            _clinic, _service, _patient, conversation = self._seed_base(db)
            config = self._agenda_config(db)
            future = datetime.now(assistente_ia_tools.LOCAL_TZ).date() + timedelta(days=8)
            with patch.object(assistente_ia_tools, "registrar_auditoria") as audit:
                prepared = assistente_ia_tools.solicitar_excecao_funcionamento_agenda(
                    self._context(db, conversation),
                    data=future.isoformat(),
                    ativo=True,
                    inicio=None,
                    fim="18:00",
                    motivo="Agenda estendida pela gestao",
                )["pending_action"]
                executed = assistente_ia_tools.decide_pending_action(
                    db=db,
                    current_user=self.user,
                    request=SimpleNamespace(headers={}),
                    action_id=prepared["id"],
                    decision="approve",
                )

            db.refresh(config)
            exceptions = json.loads(config.agenda_excecoes)
            created = next(item for item in exceptions if item["data"] == future.isoformat())
            self.assertEqual(executed["status"], "executed")
            self.assertEqual(executed["result"]["agenda_excecao"]["fim"], "18:00")
            self.assertTrue(created["ativo"])
            self.assertEqual(created["fim"], "18:00")
            self.assertTrue(
                any(
                    call.kwargs.get("acao") == "ASSISTENTE_IA_ACAO_EXECUTADA"
                    for call in audit.call_args_list
                )
            )

    def test_excecao_de_funcionamento_rejeitada_ou_desatualizada_nao_e_aplicada(self) -> None:
        with self._session_factory() as db:
            _clinic, _service, _patient, conversation = self._seed_base(db)
            config = self._agenda_config(db)
            first_date = datetime.now(assistente_ia_tools.LOCAL_TZ).date() + timedelta(days=9)
            second_date = first_date + timedelta(days=1)
            with patch.object(assistente_ia_tools, "registrar_auditoria"):
                rejected_action = assistente_ia_tools.solicitar_excecao_funcionamento_agenda(
                    self._context(db, conversation),
                    data=first_date.isoformat(),
                    ativo=True,
                    inicio=None,
                    fim="18:00",
                    motivo=None,
                )["pending_action"]
                rejected = assistente_ia_tools.decide_pending_action(
                    db=db,
                    current_user=self.user,
                    request=SimpleNamespace(headers={}),
                    action_id=rejected_action["id"],
                    decision="reject",
                )
                self.assertEqual(rejected["status"], "rejected")
                self.assertEqual(json.loads(config.agenda_excecoes), [])

                changed_action = assistente_ia_tools.solicitar_excecao_funcionamento_agenda(
                    self._context(db, conversation),
                    data=second_date.isoformat(),
                    ativo=True,
                    inicio="08:00",
                    fim="18:00",
                    motivo=None,
                )["pending_action"]
                config.agenda_excecoes = json.dumps(
                    [
                        {
                            "data": first_date.isoformat(),
                            "ativo": False,
                            "inicio": "08:00",
                            "fim": "18:00",
                            "motivo": "Mudanca concorrente",
                        }
                    ]
                )
                db.add(config)
                db.commit()
                with self.assertRaises(HTTPException) as changed:
                    assistente_ia_tools.decide_pending_action(
                        db=db,
                        current_user=self.user,
                        request=SimpleNamespace(headers={}),
                        action_id=changed_action["id"],
                        decision="approve",
                    )

            self.assertEqual(changed.exception.status_code, 409)
            stored = db.query(AssistenteIAAcaoPendente).filter_by(id=changed_action["id"]).one()
            self.assertEqual(stored.status, "invalidated")

    def test_reserva_preparada_nao_cria_horario_antes_da_confirmacao(self) -> None:
        with self._session_factory() as db:
            clinic, service, _patient, conversation = self._seed_base(db)
            future = datetime.now(assistente_ia_tools.LOCAL_TZ) + timedelta(days=7)
            with (
                patch.object(assistente_ia_tools, "_validate_appointment_candidate"),
                patch.object(assistente_ia_tools, "registrar_auditoria"),
            ):
                prepared = assistente_ia_tools.solicitar_criacao_agendamento(
                    self._context(db, conversation),
                    tipo="reserva",
                    origem_atendimento="clinica_parceira",
                    clinica=clinic.nome,
                    tutor=None,
                    paciente=None,
                    servico=service.nome,
                    data=future.date().isoformat(),
                    horario="10:00",
                    destinatario_mensagem="clinica",
                    prazo_confirmacao_horas=3,
                    observacoes="Aguardando confirmacao da clinica",
                )

            self.assertTrue(prepared["ok"])
            self.assertTrue(prepared["requires_approval"])
            self.assertEqual(prepared["pending_action"]["type"], "create_appointment")
            self.assertEqual(prepared["pending_action"]["target"]["status"], "Reservado")
            self.assertEqual(
                prepared["pending_action"]["target"]["destinatario_mensagem"]["telefones"],
                ["85988946484", "85999998888"],
            )
            provider_result = assistente_ia_tools.tool_result_for_model(
                "solicitar_criacao_agendamento",
                prepared,
            )
            self.assertNotIn("85988946484", str(provider_result))
            self.assertNotIn("telefones", str(provider_result))
            self.assertEqual(
                provider_result["pending_action"]["target"]["destinatario_mensagem"]["quantidade_contatos"],
                2,
            )
            self.assertEqual(db.query(Agendamento).count(), 0)

    def test_criacao_so_executa_endpoint_oficial_apos_aprovacao(self) -> None:
        with self._session_factory() as db:
            clinic, service, patient, conversation = self._seed_base(db)
            future = datetime.now(assistente_ia_tools.LOCAL_TZ) + timedelta(days=8)
            with (
                patch.object(assistente_ia_tools, "_validate_appointment_candidate"),
                patch.object(assistente_ia_tools, "registrar_auditoria"),
            ):
                prepared = assistente_ia_tools.solicitar_criacao_agendamento(
                    self._context(db, conversation),
                    tipo="agendamento",
                    origem_atendimento="clinica_parceira",
                    clinica=clinic.nome,
                    tutor=f"#{patient.tutor_id}",
                    paciente=patient.nome,
                    servico=service.nome,
                    data=future.date().isoformat(),
                    horario="11:00",
                    destinatario_mensagem="tutor",
                    prazo_confirmacao_horas=None,
                    observacoes="Primeiro atendimento",
                )["pending_action"]

                self.assertEqual(db.query(Agendamento).count(), 0)
                with patch.object(
                    assistente_ia_tools.agenda,
                    "criar_agendamento",
                    return_value={
                        "id": 321,
                        "status": "Agendado",
                        "inicio": prepared["target"]["inicio"],
                    },
                ) as create_appointment:
                    executed = assistente_ia_tools.decide_pending_action(
                        db=db,
                        current_user=self.user,
                        request=SimpleNamespace(headers={}),
                        action_id=prepared["id"],
                        decision="approve",
                    )

            self.assertEqual(executed["status"], "executed")
            self.assertEqual(executed["result"]["agendamento"]["id"], 321)
            self.assertEqual(executed["result"]["comunicacao"]["destinatario_nome"], "Ana Oliveira")
            self.assertIn("Ecocardiograma", executed["result"]["comunicacao"]["mensagem"])
            self.assertTrue(executed["result"]["comunicacao"]["envio_manual"])
            payload = create_appointment.call_args.kwargs["agendamento"]
            self.assertIsInstance(payload, assistente_ia_tools.AgendamentoCreate)
            self.assertEqual(payload.status, "Agendado")
            self.assertEqual(payload.paciente_id, patient.id)

    def test_paciente_com_tutor_legado_ativo_nulo_e_resolvido(self) -> None:
        with self._session_factory() as db:
            clinic, service, _patient, conversation = self._seed_base(db)
            tutor_legado = Tutor(
                nome="Marcos Pereira",
                telefone="(85) 98888-1122",
                whatsapp="85988881122",
                ativo=None,
            )
            db.add(tutor_legado)
            db.flush()
            patient_legado = Paciente(nome="Bolt", tutor_id=tutor_legado.id, ativo=1)
            db.add(patient_legado)
            db.commit()
            db.refresh(patient_legado)

            future = datetime.now(assistente_ia_tools.LOCAL_TZ) + timedelta(days=10)
            with (
                patch.object(assistente_ia_tools, "_validate_appointment_candidate"),
                patch.object(assistente_ia_tools, "registrar_auditoria"),
            ):
                prepared = assistente_ia_tools.solicitar_criacao_agendamento(
                    self._context(db, conversation),
                    tipo="agendamento",
                    origem_atendimento="clinica_parceira",
                    clinica=clinic.nome,
                    tutor=None,
                    paciente=patient_legado.nome,
                    servico=service.nome,
                    data=future.date().isoformat(),
                    horario="13:00",
                    destinatario_mensagem="tutor",
                    prazo_confirmacao_horas=None,
                    observacoes=None,
                )

            self.assertTrue(prepared["ok"])
            target = prepared["pending_action"]["target"]
            self.assertEqual(target["tutor_id"], tutor_legado.id)
            self.assertEqual(target["tutor_nome"], "Marcos Pereira")

    def test_rejeitar_criacao_preserva_agenda(self) -> None:
        with self._session_factory() as db:
            clinic, service, _patient, conversation = self._seed_base(db)
            future = datetime.now(assistente_ia_tools.LOCAL_TZ) + timedelta(days=9)
            with (
                patch.object(assistente_ia_tools, "_validate_appointment_candidate"),
                patch.object(assistente_ia_tools, "registrar_auditoria"),
            ):
                prepared = assistente_ia_tools.solicitar_criacao_agendamento(
                    self._context(db, conversation),
                    tipo="reserva",
                    origem_atendimento="clinica_parceira",
                    clinica=clinic.nome,
                    tutor=None,
                    paciente=None,
                    servico=service.nome,
                    data=future.date().isoformat(),
                    horario="12:00",
                    destinatario_mensagem="clinica",
                    prazo_confirmacao_horas=None,
                    observacoes=None,
                )["pending_action"]
                with patch.object(assistente_ia_tools.agenda, "criar_agendamento") as create_appointment:
                    rejected = assistente_ia_tools.decide_pending_action(
                        db=db,
                        current_user=self.user,
                        request=SimpleNamespace(headers={}),
                        action_id=prepared["id"],
                        decision="reject",
                    )

            self.assertEqual(rejected["status"], "rejected")
            self.assertEqual(db.query(Agendamento).count(), 0)
            create_appointment.assert_not_called()

    def test_criacao_e_invalidada_quando_referencia_muda(self) -> None:
        with self._session_factory() as db:
            clinic, service, _patient, conversation = self._seed_base(db)
            future = datetime.now(assistente_ia_tools.LOCAL_TZ) + timedelta(days=10)
            with (
                patch.object(assistente_ia_tools, "_validate_appointment_candidate"),
                patch.object(assistente_ia_tools, "registrar_auditoria"),
            ):
                prepared = assistente_ia_tools.solicitar_criacao_agendamento(
                    self._context(db, conversation),
                    tipo="reserva",
                    origem_atendimento="clinica_parceira",
                    clinica=clinic.nome,
                    tutor=None,
                    paciente=None,
                    servico=service.nome,
                    data=future.date().isoformat(),
                    horario="13:00",
                    destinatario_mensagem="clinica",
                    prazo_confirmacao_horas=3,
                    observacoes=None,
                )["pending_action"]

                service.updated_at = datetime.now() + timedelta(minutes=5)
                db.add(service)
                db.commit()
                with patch.object(assistente_ia_tools.agenda, "criar_agendamento") as create_appointment:
                    with self.assertRaises(HTTPException) as changed:
                        assistente_ia_tools.decide_pending_action(
                            db=db,
                            current_user=self.user,
                            request=SimpleNamespace(headers={}),
                            action_id=prepared["id"],
                            decision="approve",
                        )

            self.assertEqual(changed.exception.status_code, 409)
            stored = db.query(AssistenteIAAcaoPendente).filter_by(id=prepared["id"]).one()
            self.assertEqual(stored.status, "invalidated")
            self.assertEqual(db.query(Agendamento).count(), 0)
            create_appointment.assert_not_called()

    def test_localizacao_com_multiplos_candidatos_exige_desambiguacao(self) -> None:
        with self._session_factory() as db:
            clinic, service, patient, conversation = self._seed_base(db)
            first = self._appointment(db, clinic, service, patient)
            self._appointment(db, clinic, service, patient)
            result = assistente_ia_tools.localizar_agendamentos(
                self._context(db, conversation),
                data=first.data,
                horario="10:00",
                clinica="Animal Care",
                servico="Ecocardiograma",
            )

        self.assertEqual(result["total"], 2)
        self.assertIn("desambiguacao", result["orientacao"])

    def test_faturamento_gera_serie_mensal_e_filtro_por_clinica(self) -> None:
        with self._session_factory() as db:
            clinic, _service, _patient, conversation = self._seed_base(db)
            first_month = assistente_ia_tools._first_day_shifted(
                datetime.now(assistente_ia_tools.LOCAL_TZ).date().replace(day=1),
                -4,
            )
            for offset, value in enumerate((100.0, 120.0, 90.0, 150.0, 180.0)):
                transaction_date = assistente_ia_tools._first_day_shifted(first_month, offset)
                db.add(
                    Transacao(
                        tipo="entrada",
                        categoria="exame",
                        valor=value,
                        valor_final=value,
                        valor_taxa=0,
                        status="Pago",
                        clinica_id=clinic.id,
                        data_transacao=datetime.combine(transaction_date, datetime.min.time()),
                    )
                )
            db.commit()

            result = assistente_ia_tools.analisar_faturamento(
                self._context(db, conversation),
                meses=5,
                clinica="Animal Care",
            )

        self.assertTrue(result["ok"])
        self.assertEqual(len(result["serie_mensal"]), 5)
        self.assertEqual(result["resumo"]["faturamento_total"], 640.0)
        self.assertEqual(result["serie_mensal"][-1]["faturamento_liquido"], 180.0)

    def test_servicos_realizados_soma_todas_as_os_do_periodo_independente_de_pagamento(self) -> None:
        with self._session_factory() as db:
            clinic, service, patient, conversation = self._seed_base(db)
            other_clinic = Clinica(nome="Vet World", ativo=True)
            db.add(other_clinic)
            db.flush()
            reference = datetime.now(assistente_ia_tools.LOCAL_TZ)
            db.add_all(
                [
                    OrdemServico(
                        numero_os="OS-REALIZADA-1",
                        agendamento_id=101,
                        paciente_id=patient.id,
                        clinica_id=clinic.id,
                        servico_id=service.id,
                        data_atendimento=reference,
                        valor_final=250,
                        status="Pendente",
                    ),
                    OrdemServico(
                        numero_os="OS-REALIZADA-2",
                        agendamento_id=102,
                        paciente_id=patient.id,
                        clinica_id=other_clinic.id,
                        servico_id=service.id,
                        data_atendimento=reference,
                        valor_final=300,
                        status="Pago",
                    ),
                    OrdemServico(
                        numero_os="OS-CANCELADA",
                        agendamento_id=103,
                        paciente_id=patient.id,
                        clinica_id=clinic.id,
                        servico_id=service.id,
                        data_atendimento=reference,
                        valor_final=900,
                        status="Cancelado",
                    ),
                ]
            )
            db.commit()
            result = assistente_ia_tools.analisar_servicos_realizados(
                self._context(db, conversation),
                data_inicio=reference.date().isoformat(),
                data_fim=reference.date().isoformat(),
                clinica=None,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["resumo"]["ordens_servico"], 2)
        self.assertEqual(result["resumo"]["valor_servicos_realizados"], 550.0)
        self.assertEqual({item["nome"] for item in result["por_status"]}, {"Pago", "Pendente"})
        self.assertIn("independentemente", result["aviso"])

    def test_previsao_da_agenda_aplica_preco_negociado_e_tabela_regional_sem_dados_pessoais(self) -> None:
        with self._session_factory() as db:
            fortaleza, service, patient, conversation = self._seed_base(db)
            fortaleza.tabela_preco_id = 1
            service.preco_fortaleza_comercial = 180
            service.preco_rm_comercial = 200
            metropolitana = Clinica(
                nome="Pet Sanus Caucaia",
                ativo=True,
                tabela_preco_id=2,
            )
            db.add_all(
                [
                    metropolitana,
                    TabelaPreco(id=1, nome="Clinicas Fortaleza", ativo=1),
                    TabelaPreco(id=2, nome="Regiao Metropolitana", ativo=1),
                ]
            )
            db.flush()
            db.add(
                PrecoServicoClinica(
                    clinica_id=fortaleza.id,
                    servico_id=service.id,
                    preco_comercial=150,
                    preco_plantao=220,
                    ativo=1,
                )
            )
            reference_date = datetime.now(assistente_ia_tools.LOCAL_TZ).date() + timedelta(days=1)
            scheduled_start = datetime.combine(
                reference_date,
                datetime.min.time(),
                tzinfo=assistente_ia_tools.LOCAL_TZ,
            ).replace(hour=9)
            db.add_all(
                [
                    Agendamento(
                        paciente_id=patient.id,
                        tutor_id=patient.tutor_id,
                        clinica_id=fortaleza.id,
                        servico_id=service.id,
                        inicio=scheduled_start,
                        fim=scheduled_start + timedelta(minutes=30),
                        data=reference_date.isoformat(),
                        hora="09:00",
                        status="Agendado",
                    ),
                    Agendamento(
                        paciente_id=patient.id,
                        tutor_id=patient.tutor_id,
                        clinica_id=metropolitana.id,
                        servico_id=service.id,
                        inicio=scheduled_start.replace(hour=10),
                        fim=scheduled_start.replace(hour=10, minute=30),
                        data=reference_date.isoformat(),
                        hora="10:00",
                        status="Reservado",
                    ),
                    Agendamento(
                        paciente_id=patient.id,
                        tutor_id=patient.tutor_id,
                        clinica_id=metropolitana.id,
                        servico_id=service.id,
                        inicio=scheduled_start.replace(hour=11),
                        fim=scheduled_start.replace(hour=11, minute=30),
                        data=reference_date.isoformat(),
                        hora="11:00",
                        status="Cancelado",
                    ),
                ]
            )
            db.commit()

            result = assistente_ia_tools.projetar_faturamento_agenda(
                self._context(db, conversation),
                data=reference_date.isoformat(),
                clinica=None,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["resumo"]["agendamentos_considerados"], 2)
        self.assertEqual(result["resumo"]["valor_agendado"], 150.0)
        self.assertEqual(result["resumo"]["valor_reservado"], 200.0)
        self.assertEqual(result["resumo"]["valor_total_previsto"], 350.0)
        self.assertEqual(result["resumo"]["sem_valor_configurado"], 0)
        self.assertEqual(
            {item["tabela_preco"] for item in result["itens"]},
            {"Clinicas Fortaleza", "Regiao Metropolitana"},
        )
        serialized = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("Luna", serialized)
        self.assertNotIn("Ana Oliveira", serialized)
        self.assertFalse(result["dados_pessoais_incluidos"])
        self.assertIn("nao valor ja recebido", result["premissas"][-1])

    def test_pedido_de_previsao_forca_uma_unica_ferramenta_e_depois_resposta_final(self) -> None:
        with self._session_factory() as db:
            _clinic, _service, _patient, conversation = self._seed_base(db)
            tool_call = SimpleNamespace(
                type="function_call",
                name="projetar_faturamento_agenda",
                arguments='{"data": "2026-07-25", "clinica": null}',
                call_id="call-forecast",
            )
            responses = [
                SimpleNamespace(id="resp-forecast-tool", output=[tool_call], output_text=""),
                SimpleNamespace(
                    id="resp-forecast-final",
                    output=[],
                    output_text="A agenda de amanha soma R$ 1.590,00.",
                ),
            ]
            provider_calls = []

            def provider_request(*_args, **kwargs):
                provider_calls.append(kwargs)
                return responses[len(provider_calls) - 1]

            with (
                patch.object(assistente_ia_service, "ensure_assistant_available"),
                patch.object(assistente_ia_service, "OpenAI", return_value=SimpleNamespace()),
                patch.object(
                    assistente_ia_service,
                    "_local_today",
                    return_value=date(2026, 7, 23),
                ),
                patch.object(
                    assistente_ia_service,
                    "_provider_request",
                    side_effect=provider_request,
                ),
                patch.object(
                    assistente_ia_service,
                    "execute_tool",
                    return_value={
                        "ok": True,
                        "resumo": {
                            "agendamentos_considerados": 8,
                            "valor_total_previsto": 1590.0,
                        },
                    },
                ) as executor,
                patch.object(assistente_ia_service, "registrar_auditoria"),
            ):
                result = assistente_ia_service.run_assistant_turn(
                    db=db,
                    current_user=self.user,
                    request=SimpleNamespace(headers={}),
                    message=(
                        "Verifique pra mim amanhã qual o previsto pra faturamento "
                        "do que tem de agendado."
                    ),
                    conversation=conversation,
                )

        self.assertEqual(result["assistant_message"]["content"], responses[-1].output_text)
        self.assertEqual(len(provider_calls[0]["tool_definitions"]), 1)
        self.assertEqual(
            provider_calls[0]["tool_choice"]["name"],
            "projetar_faturamento_agenda",
        )
        self.assertEqual(provider_calls[1]["tool_definitions"], [])
        executor.assert_called_once()
        self.assertEqual(
            executor.call_args.kwargs["arguments"]["data"],
            "2026-07-24",
        )

    def test_detector_de_previsao_cobre_a_solicitacao_e_a_correcao_reais(self) -> None:
        self.assertTrue(
            assistente_ia_service._is_agenda_revenue_forecast_request(
                "Verifique pra mim amanhã qual o previsto pra faturamento do que tem de agendado."
            )
        )
        self.assertTrue(
            assistente_ia_service._is_agenda_revenue_forecast_request(
                "Olhe a tabela da clínica e some os valores dos serviços previstos para executar."
            )
        )
        self.assertFalse(
            assistente_ia_service._is_agenda_revenue_forecast_request(
                "Analise o faturamento recebido dos últimos cinco meses."
            )
        )

    def test_data_da_previsao_usa_fuso_operacional_e_recupera_data_da_conversa(self) -> None:
        with self._session_factory() as db:
            _clinic, _service, _patient, conversation = self._seed_base(db)
            previous = AssistenteIAMensagem(
                conversa_id=conversation.id,
                usuario_id=self.user.id,
                papel="assistant",
                conteudo="A agenda prevista para 24/07/2026 possui oito atendimentos.",
                provider_status="completed",
            )
            current = AssistenteIAMensagem(
                conversa_id=conversation.id,
                usuario_id=self.user.id,
                papel="user",
                conteudo="Olhe a tabela da clínica e some os serviços previstos.",
                provider_status="retrying",
            )
            db.add_all([previous, current])
            db.commit()
            db.refresh(current)
            with patch.object(
                assistente_ia_service,
                "_local_today",
                return_value=date(2026, 7, 23),
            ):
                direct = assistente_ia_service._relative_date_from_text(
                    "Qual o valor previsto para amanhã?",
                    reference=assistente_ia_service._local_today(),
                )
                inherited = assistente_ia_service._resolve_forecast_date(
                    db,
                    conversation,
                    message=current.conteudo,
                    current_message_id=current.id,
                )

        self.assertEqual(direct, date(2026, 7, 24))
        self.assertEqual(inherited, date(2026, 7, 24))

    def test_consulta_funcionamento_geral_sem_exigir_clinica_ou_servico(self) -> None:
        with self._session_factory() as db:
            _clinic, _service, _patient, conversation = self._seed_base(db)
            reference = datetime.now(assistente_ia_tools.LOCAL_TZ).date() + timedelta(days=4)
            self._agenda_config(
                db,
                exceptions=[
                    {
                        "data": reference.isoformat(),
                        "ativo": True,
                        "inicio": "08:00",
                        "fim": "18:30",
                        "motivo": "Extensao administrativa",
                    }
                ],
            )
            result = assistente_ia_tools.consultar_funcionamento_agenda(
                self._context(db, conversation),
                data=reference.isoformat(),
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["funcionamento"]["fim"], "18:30")
        self.assertEqual(result["funcionamento"]["fonte"], "excecao")
        self.assertEqual(result["escopo"], "agenda geral da FortCordis")

    def test_deslocamento_entre_clinicas_reutiliza_matriz_logistica(self) -> None:
        with self._session_factory() as db:
            clinic, _service, _patient, conversation = self._seed_base(db)
            destination = Clinica(nome="Vet World", ativo=True)
            db.add(destination)
            db.commit()
            with (
                patch.object(
                    assistente_ia_tools,
                    "obter_ou_criar_deslocamento",
                    return_value=SimpleNamespace(id=44),
                ) as route_lookup,
                patch.object(
                    assistente_ia_tools,
                    "serialize_deslocamento",
                    return_value={
                        "distancia_km": 12.4,
                        "duracao_min": 28,
                        "fonte": "google_routes_api",
                        "updated_at": "2026-07-23 12:00:00",
                    },
                ),
            ):
                result = assistente_ia_tools.consultar_deslocamento_clinicas(
                    self._context(db, conversation),
                    origem=clinic.nome,
                    destino="Vet Wrold",
                    perfil="comercial",
                )

        self.assertTrue(result["ok"])
        self.assertEqual(result["destino"]["nome"], "Vet World")
        self.assertEqual(result["duracao_min"], 28)
        self.assertEqual(result["distancia_km"], 12.4)
        route_lookup.assert_called_once_with(
            db,
            origem_clinica_id=clinic.id,
            destino_clinica_id=destination.id,
            perfil="comercial",
        )

    def test_relatorio_mantem_ordens_e_contas_em_subtotais_separados(self) -> None:
        with self._session_factory() as db:
            clinic, service, patient, conversation = self._seed_base(db)
            appointment = self._appointment(db, clinic, service, patient)
            db.add_all(
                [
                    OrdemServico(
                        numero_os="OS-IA-1",
                        agendamento_id=appointment.id,
                        paciente_id=patient.id,
                        clinica_id=clinic.id,
                        servico_id=service.id,
                        data_atendimento=appointment.inicio,
                        valor_final=250,
                        status="Pendente",
                    ),
                    ContaReceber(
                        descricao="Fatura mensal",
                        cliente=clinic.nome,
                        valor=300,
                        data_vencimento=datetime.now() - timedelta(days=3),
                        status="Atrasado",
                        clinica_id=clinic.id,
                    ),
                ]
            )
            db.commit()
            result = assistente_ia_tools.relatorio_debitos_pendentes(
                self._context(db, conversation),
                clinica="Animal Care",
                somente_vencidos=False,
            )

        self.assertEqual(result["ordens_servico_pendentes"]["total"], 250.0)
        self.assertEqual(result["contas_receber_pendentes"]["total"], 300.0)
        self.assertEqual(result["total_estimado_sem_deduplicacao"], 550.0)
        self.assertIn("fontes separadas", result["aviso"])

    def test_disponibilidade_reutiliza_motor_real_da_agenda(self) -> None:
        with self._session_factory() as db:
            _clinic, _service, _patient, conversation = self._seed_base(db)
            suggestion = {
                "items": [
                    {
                        "inicio": "2099-01-10T09:00:00-03:00",
                        "fim": "2099-01-10T09:30:00-03:00",
                        "risco": "baixo",
                        "score": 92,
                        "tempo_deslocamento_total_min": 20,
                        "destino_operacional": "Animal Care",
                        "telefone": "nao-deve-sair",
                    }
                ]
            }
            with patch.object(assistente_ia_tools.agenda, "sugerir_horarios_agenda", return_value=suggestion):
                result = assistente_ia_tools.verificar_disponibilidade(
                    self._context(db, conversation),
                    clinica="Animal Care",
                    servico="Ecocardiograma",
                    data_inicio="2099-01-10",
                    dias=1,
                )

        self.assertTrue(result["ok"])
        self.assertEqual(len(result["slots"]), 1)
        self.assertNotIn("telefone", str(result).lower())

    def test_disponibilidade_preferencia_governa_datas_e_chega_antes_do_ranking(self) -> None:
        with self._session_factory() as db:
            _clinic, _service, _patient, conversation = self._seed_base(db)
            preferencia = {'data_inicio': '2099-01-10', 'data_fim': '2099-01-11', 'turno': 'tarde'}

            def suggest(*, payload, **_kwargs):
                self.assertEqual(payload.preferencia.model_dump(exclude_none=True), preferencia)
                self.assertEqual(payload.intervalo_minutos, 15)
                return {'items': [
                    {'inicio': f'{payload.data}T09:00:00-03:00', 'fim': f'{payload.data}T09:30:00-03:00'},
                    {'inicio': f'{payload.data}T13:00:00-03:00', 'fim': f'{payload.data}T13:30:00-03:00', 'paciente': 'Não expor'},
                    {'inicio': f'{payload.data}T17:45:00-03:00', 'fim': f'{payload.data}T18:15:00-03:00'},
                    {'inicio': '2099-01-12T13:00:00-03:00', 'fim': '2099-01-12T13:30:00-03:00'},
                ]}

            with patch.object(assistente_ia_tools.agenda, 'sugerir_horarios_agenda', side_effect=suggest) as engine:
                result = assistente_ia_tools.execute_tool(self._context(db, conversation), name='verificar_disponibilidade', arguments={
                    'clinica': 'Animal Care', 'servico': 'Ecocardiograma',
                    'data_inicio': '2099-01-01', 'dias': 1, 'preferencia': preferencia,
                })
        self.assertEqual([call.kwargs['payload'].data for call in engine.call_args_list], ['2099-01-10', '2099-01-11'])
        self.assertEqual(result['periodo'], {'inicio': '2099-01-10', 'fim': '2099-01-11', 'dias_solicitados': 2})
        self.assertEqual([item['inicio'] for item in result['slots']], ['2099-01-10T13:00:00-03:00', '2099-01-11T13:00:00-03:00'])
        self.assertNotIn('Não expor', str(result))

    def test_disponibilidade_nao_amplia_preferencia_sem_resultado_ou_invalida(self) -> None:
        with self._session_factory() as db:
            _clinic, _service, _patient, conversation = self._seed_base(db)
            ctx = self._context(db, conversation)
            with patch.object(assistente_ia_tools.agenda, 'sugerir_horarios_agenda', return_value={'items': []}) as engine:
                result = assistente_ia_tools.verificar_disponibilidade(ctx, clinica='Animal Care', servico='Ecocardiograma',
                    data_inicio=None, dias=7, preferencia={'data_inicio': '2099-01-10', 'data_fim': '2099-01-11', 'turno': 'tarde'})
                self.assertEqual(engine.call_count, 2)
                self.assertEqual(result['slots'], [])
                self.assertIn('antes de ampliar', result['orientacao'])
                engine.reset_mock()
                for preferencia in ({'data_inicio': '2099-01-10', 'turno': 'manha'},
                                    {'data_inicio': '2099-01-10', 'data_fim': '2099-03-01'},
                                    {'hora_fim': '15:00', 'turno': 'tarde'},
                                    {'hora_inicio': '12:00', 'turno': 'manha'},
                                    {'turno': 'tarde', 'hora_inicio': '08:00', 'hora_fim': '10:00'}):
                    with self.subTest(preferencia=preferencia):
                        result = assistente_ia_tools.verificar_disponibilidade(ctx, clinica='Animal Care', servico='Ecocardiograma',
                            data_inicio=None, dias=7, preferencia=preferencia)
                        self.assertFalse(result['ok'])
                engine.assert_not_called()

    def test_disponibilidade_a_partir_de_chega_ao_motor_sem_ampliar_data_ou_horario(self) -> None:
        with self._session_factory() as db:
            _clinic, _service, _patient, conversation = self._seed_base(db)
            preferencia = {'data_inicio': '2099-01-10', 'data_fim': '2099-01-10',
                           'turno': 'tarde', 'hora_inicio': '14:00'}

            def suggest(*, payload, **_kwargs):
                self.assertEqual(payload.preferencia.model_dump(exclude_none=True), preferencia)
                return {'items': [
                    {'inicio': '2099-01-10T13:45:00-03:00', 'fim': '2099-01-10T14:15:00-03:00'},
                    {'inicio': '2099-01-10T14:00:00-03:00', 'fim': '2099-01-10T14:30:00-03:00'},
                    {'inicio': '2099-01-10T17:45:00-03:00', 'fim': '2099-01-10T18:15:00-03:00'},
                    {'inicio': '2099-01-11T14:00:00-03:00', 'fim': '2099-01-11T14:30:00-03:00'},
                ]}

            with patch.object(assistente_ia_tools.agenda, 'sugerir_horarios_agenda', side_effect=suggest) as engine:
                result = assistente_ia_tools.verificar_disponibilidade(
                    self._context(db, conversation), clinica='Animal Care', servico='Ecocardiograma',
                    data_inicio='2099-01-01', dias=7, preferencia=preferencia)

        self.assertEqual([call.kwargs['payload'].data for call in engine.call_args_list], ['2099-01-10'])
        self.assertEqual(result['periodo'], {'inicio': '2099-01-10', 'fim': '2099-01-10', 'dias_solicitados': 1})
        self.assertEqual([item['inicio'] for item in result['slots']], ['2099-01-10T14:00:00-03:00'])
        self.assertEqual(result['preferencia'], preferencia)

    def test_disponibilidade_tool_schema_preserva_contrato_estrito(self) -> None:
        definition = next(item for item in assistente_ia_tools.TOOL_DEFINITIONS if item['name'] == 'verificar_disponibilidade')
        schema = definition['parameters']
        preferencia = schema['properties']['preferencia']
        self.assertTrue(definition['strict'])
        self.assertEqual(set(schema['required']), set(schema['properties']))
        self.assertEqual(set(preferencia['required']), set(preferencia['properties']))
        self.assertFalse(preferencia['additionalProperties'])

    def test_exclusao_fica_pendente_e_pode_ser_rejeitada_sem_apagar(self) -> None:
        with self._session_factory() as db:
            clinic, service, patient, conversation = self._seed_base(db)
            appointment = self._appointment(db, clinic, service, patient)
            with patch.object(assistente_ia_tools, "registrar_auditoria") as audit:
                prepared = assistente_ia_tools.solicitar_exclusao_agendamento(
                    self._context(db, conversation),
                    agendamento_id=appointment.id,
                    motivo="Solicitado pelo administrador",
                )
                self.assertIsNotNone(db.query(Agendamento).filter_by(id=appointment.id).first())
                rejected = assistente_ia_tools.decide_pending_action(
                    db=db,
                    current_user=self.user,
                    request=SimpleNamespace(headers={}),
                    action_id=prepared["pending_action"]["id"],
                    decision="reject",
                    observation="Cancelar operacao",
                )

            self.assertEqual(rejected["status"], "rejected")
            self.assertIsNotNone(db.query(Agendamento).filter_by(id=appointment.id).first())

    def test_exclusao_so_executa_apos_aprovacao_e_revalida_snapshot(self) -> None:
        with self._session_factory() as db:
            clinic, service, patient, conversation = self._seed_base(db)
            first = self._appointment(db, clinic, service, patient, hour=10)
            second = self._appointment(db, clinic, service, patient, hour=11)
            with patch.object(assistente_ia_tools, "registrar_auditoria") as audit:
                first_action = assistente_ia_tools.solicitar_exclusao_agendamento(
                    self._context(db, conversation),
                    agendamento_id=first.id,
                    motivo="Excluir agenda duplicada",
                )["pending_action"]
                second_action = assistente_ia_tools.solicitar_exclusao_agendamento(
                    self._context(db, conversation),
                    agendamento_id=second.id,
                    motivo="Excluir agenda incorreta",
                )["pending_action"]

                second.status = "Confirmado"
                db.add(second)
                db.commit()
                with self.assertRaises(HTTPException) as changed:
                    assistente_ia_tools.decide_pending_action(
                        db=db,
                        current_user=self.user,
                        request=SimpleNamespace(headers={}),
                        action_id=second_action["id"],
                        decision="approve",
                    )
                self.assertEqual(changed.exception.status_code, 409)

                def delete_appointment(*, agendamento_id, db, **_kwargs):
                    db.query(Agendamento).filter(Agendamento.id == agendamento_id).delete()
                    db.commit()
                    return {"message": "ok"}

                with patch.object(
                    assistente_ia_tools.agenda,
                    "deletar_agendamento",
                    side_effect=delete_appointment,
                ):
                    executed = assistente_ia_tools.decide_pending_action(
                        db=db,
                        current_user=self.user,
                        request=SimpleNamespace(headers={}),
                        action_id=first_action["id"],
                        decision="approve",
                    )

            self.assertEqual(executed["status"], "executed")
            self.assertIsNone(db.query(Agendamento).filter_by(id=first.id).first())
            self.assertIsNotNone(db.query(Agendamento).filter_by(id=second.id).first())
            self.assertTrue(
                any(
                    call.kwargs.get("acao") == "ASSISTENTE_IA_ACAO_EXECUTADA"
                    for call in audit.call_args_list
                )
            )

    def test_acao_expirada_ou_ja_decidida_nao_pode_ser_executada(self) -> None:
        with self._session_factory() as db:
            clinic, service, patient, conversation = self._seed_base(db)
            first = self._appointment(db, clinic, service, patient, hour=12)
            second = self._appointment(db, clinic, service, patient, hour=13)
            with patch.object(assistente_ia_tools, "registrar_auditoria"):
                expired_action = assistente_ia_tools.solicitar_exclusao_agendamento(
                    self._context(db, conversation),
                    agendamento_id=first.id,
                    motivo="Teste de validade da aprovacao",
                )["pending_action"]
                action_record = db.query(AssistenteIAAcaoPendente).filter_by(id=expired_action["id"]).one()
                action_record.expires_at = datetime.now() - timedelta(minutes=1)
                db.commit()

                with self.assertRaises(HTTPException) as expired:
                    assistente_ia_tools.decide_pending_action(
                        db=db,
                        current_user=self.user,
                        request=SimpleNamespace(headers={}),
                        action_id=expired_action["id"],
                        decision="approve",
                    )
                self.assertEqual(expired.exception.status_code, 409)
                self.assertEqual(action_record.status, "expired")
                self.assertIsNotNone(db.query(Agendamento).filter_by(id=first.id).first())

                rejected_action = assistente_ia_tools.solicitar_exclusao_agendamento(
                    self._context(db, conversation),
                    agendamento_id=second.id,
                    motivo="Teste de protecao contra repeticao",
                )["pending_action"]
                assistente_ia_tools.decide_pending_action(
                    db=db,
                    current_user=self.user,
                    request=SimpleNamespace(headers={}),
                    action_id=rejected_action["id"],
                    decision="reject",
                )
                with self.assertRaises(HTTPException) as replay:
                    assistente_ia_tools.decide_pending_action(
                        db=db,
                        current_user=self.user,
                        request=SimpleNamespace(headers={}),
                        action_id=rejected_action["id"],
                        decision="approve",
                    )

            self.assertEqual(replay.exception.status_code, 409)
            self.assertIsNotNone(db.query(Agendamento).filter_by(id=second.id).first())

    def test_memoria_so_orienta_depois_de_aprovada(self) -> None:
        with self._session_factory() as db:
            pending = assistente_ia_management.create_memory(
                db,
                self.user,
                title="Prioridade proposta",
                content="Priorizar a clinica Animal Care nas terca-feiras.",
                category="agenda",
                source="assistant",
                approve_immediately=False,
            )
            self.assertNotIn("Animal Care", assistente_ia_management.approved_memory_context(db))
            with patch.object(assistente_ia_management, "registrar_auditoria"):
                assistente_ia_management.decide_memory(
                    db,
                    self.user,
                    SimpleNamespace(headers={}),
                    memory_id=pending["id"],
                    decision="approve",
                )
            self.assertIn("Animal Care", assistente_ia_management.approved_memory_context(db))

    def test_conhecimento_interno_e_pesquisavel_sem_expor_toda_a_base(self) -> None:
        with self._session_factory() as db:
            assistente_ia_management.create_document(
                db,
                self.user,
                title="Procedimento de ecocardiograma",
                content="Antes do ecocardiograma, confirmar identificacao do paciente e peso atualizado.",
                category="procedimento",
                source="Manual interno",
            )
            result = assistente_ia_management.search_knowledge(db, query="peso ecocardiograma", limit=3)
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["title"], "Procedimento de ecocardiograma")
        self.assertLessEqual(len(result["items"][0]["excerpt"]), 1600)

    def test_bloqueio_so_afeta_disponibilidade_depois_da_aprovacao(self) -> None:
        with self._session_factory() as db:
            _clinic, _service, _patient, conversation = self._seed_base(db)
            reference = datetime.now(assistente_ia_tools.LOCAL_TZ) + timedelta(days=12)
            with patch.object(assistente_ia_tools, "registrar_auditoria"):
                prepared = assistente_ia_tools.solicitar_bloqueio_agenda(
                    self._context(db, conversation),
                    data=reference.date().isoformat(),
                    inicio="14:00",
                    fim="15:00",
                    motivo="Reuniao administrativa",
                )["pending_action"]
                self.assertEqual(db.query(AgendaBloqueio).count(), 0)
                executed = assistente_ia_tools.decide_pending_action(
                    db=db,
                    current_user=self.user,
                    request=SimpleNamespace(headers={}),
                    action_id=prepared["id"],
                    decision="approve",
                )
            self.assertEqual(executed["status"], "executed")
            self.assertEqual(db.query(AgendaBloqueio).filter_by(ativo=True).count(), 1)
            candidate = Agendamento(
                inicio=datetime.combine(reference.date(), datetime.min.time()).replace(
                    hour=14,
                    minute=30,
                    tzinfo=assistente_ia_tools.LOCAL_TZ,
                ),
                fim=datetime.combine(reference.date(), datetime.min.time()).replace(
                    hour=15,
                    minute=0,
                    tzinfo=assistente_ia_tools.LOCAL_TZ,
                ),
                status="Agendado",
            )
            with self.assertRaises(HTTPException) as blocked:
                assistente_ia_tools.agenda._validar_slot_disponivel(db, candidate)
            self.assertEqual(blocked.exception.status_code, 409)

    def test_feedback_fica_vinculado_a_resposta_do_admin(self) -> None:
        with self._session_factory() as db:
            _clinic, _service, _patient, conversation = self._seed_base(db)
            message = AssistenteIAMensagem(
                conversa_id=conversation.id,
                usuario_id=self.user.id,
                papel="assistant",
                conteudo="Resposta de teste",
            )
            db.add(message)
            db.commit()
            db.refresh(message)
            feedback = assistente_ia_management.create_feedback(
                db,
                self.user,
                message_id=message.id,
                rating="negative",
                category="correcao",
                comment=None,
                expected_correction="Usar a clinica correta.",
            )
        self.assertEqual(feedback["rating"], "negative")
        self.assertEqual(feedback["expected_correction"], "Usar a clinica correta.")
        self.assertEqual(feedback["learning_suggestion"]["status"], "pending")

    def test_correcao_so_altera_memoria_depois_de_aprovada_e_cria_regressao(self) -> None:
        with self._session_factory() as db:
            _clinic, _service, _patient, conversation = self._seed_base(db)
            user_message = AssistenteIAMensagem(
                conversa_id=conversation.id,
                usuario_id=self.user.id,
                papel="user",
                conteudo="Como devo confirmar um encaixe?",
            )
            db.add(user_message)
            db.flush()
            assistant_message = AssistenteIAMensagem(
                conversa_id=conversation.id,
                usuario_id=self.user.id,
                papel="assistant",
                conteudo="Confirme automaticamente.",
            )
            db.add(assistant_message)
            db.commit()
            db.refresh(assistant_message)
            with patch.object(assistente_ia_management, "registrar_auditoria"):
                feedback = assistente_ia_management.create_feedback(
                    db,
                    self.user,
                    message_id=assistant_message.id,
                    rating="negative",
                    category="agenda",
                    comment="Precisa de aprovacao.",
                    expected_correction="Todo encaixe deve ser confirmado pelo administrador.",
                )
                learning_id = feedback["learning_suggestion"]["id"]
                self.assertNotIn("Todo encaixe", assistente_ia_management.approved_memory_context(db))
                learning = assistente_ia_management.decide_learning(
                    db,
                    self.user,
                    None,
                    learning_id=learning_id,
                    decision="approve",
                )
            memory = db.query(AssistenteIAMemoria).filter_by(id=learning["memory_id"]).one()
            versions = db.query(AssistenteIAMemoriaVersao).filter_by(memoria_id=memory.id).all()
            regressions = db.query(AssistenteIARegressaoCaso).filter_by(memoria_id=memory.id, status="active").all()
            self.assertIn("Todo encaixe", assistente_ia_management.approved_memory_context(db))
            self.assertEqual(memory.versao_atual, 1)
            self.assertEqual(len(versions), 1)
            self.assertEqual(len(regressions), 1)

    def test_ajuste_rejeicao_e_reversao_preservam_historico(self) -> None:
        with self._session_factory() as db:
            with patch.object(assistente_ia_management, "registrar_auditoria"):
                original = assistente_ia_management.create_learning(
                    db,
                    self.user,
                    None,
                    title="Confirmacao de encaixes",
                    content="Confirmar encaixes pelo telefone.",
                    category="agenda",
                )
                approved = assistente_ia_management.decide_learning(
                    db,
                    self.user,
                    None,
                    learning_id=original["id"],
                    decision="approve",
                )
                rejected = assistente_ia_management.create_learning(
                    db,
                    self.user,
                    None,
                    title="Regra descartada",
                    content="Aplicar sem confirmacao.",
                    category="agenda",
                    target_memory_id=approved["memory_id"],
                )
                assistente_ia_management.decide_learning(
                    db,
                    self.user,
                    None,
                    learning_id=rejected["id"],
                    decision="reject",
                )
                adjustment = assistente_ia_management.create_learning(
                    db,
                    self.user,
                    None,
                    title="Confirmacao de encaixes",
                    content="Confirmar encaixes por WhatsApp.",
                    category="agenda",
                    target_memory_id=approved["memory_id"],
                )
                assistente_ia_management.decide_learning(
                    db,
                    self.user,
                    None,
                    learning_id=adjustment["id"],
                    decision="approve",
                )
                restored = assistente_ia_management.rollback_memory(
                    db,
                    self.user,
                    None,
                    memory_id=approved["memory_id"],
                    target_version=1,
                )
            versions = assistente_ia_management.list_memory_versions(db, memory_id=approved["memory_id"])
            self.assertEqual(restored["current_version"], 3)
            self.assertEqual([item["version"] for item in versions], [3, 2, 1])
            self.assertEqual(versions[0]["change_type"], "rollback")
            self.assertEqual(versions[0]["content"], "Confirmar encaixes pelo telefone.")
            self.assertEqual(
                db.query(AssistenteIARegressaoCaso).filter_by(memoria_id=approved["memory_id"], status="active").count(),
                1,
            )

    def test_remarcacao_revalida_e_chama_fluxo_oficial_so_na_aprovacao(self) -> None:
        with self._session_factory() as db:
            clinic, service, patient, conversation = self._seed_base(db)
            appointment = self._appointment(db, clinic, service, patient)
            future = datetime.now(assistente_ia_tools.LOCAL_TZ) + timedelta(days=15)
            with (
                patch.object(assistente_ia_tools.agenda, "_validar_agendamento_no_funcionamento"),
                patch.object(assistente_ia_tools.agenda, "_validar_slot_disponivel"),
                patch.object(assistente_ia_tools, "registrar_auditoria"),
            ):
                prepared = assistente_ia_tools.solicitar_remarcacao_agendamento(
                    self._context(db, conversation),
                    agendamento_id=appointment.id,
                    data=future.date().isoformat(),
                    horario="15:30",
                    motivo="Solicitacao da clinica",
                )["pending_action"]
                with patch.object(
                    assistente_ia_tools.agenda,
                    "atualizar_agendamento",
                    return_value={"id": appointment.id, "inicio": prepared["target"]["after"]["inicio"]},
                ) as official_update:
                    executed = assistente_ia_tools.decide_pending_action(
                        db=db,
                        current_user=self.user,
                        request=SimpleNamespace(headers={}),
                        action_id=prepared["id"],
                        decision="approve",
                    )
            self.assertEqual(executed["status"], "executed")
            official_update.assert_called_once()
            self.assertEqual(official_update.call_args.kwargs["agendamento_id"], appointment.id)
            self.assertEqual(official_update.call_args.kwargs["agendamento"].inicio.hour, 15)

    def test_atualizacao_whatsapps_preserva_outros_dados_da_clinica(self) -> None:
        with self._session_factory() as db:
            clinic, _service, _patient, conversation = self._seed_base(db)
            original_email = "animalcare@example.com"
            clinic.email = original_email
            db.commit()
            with patch.object(assistente_ia_tools, "registrar_auditoria"):
                prepared = assistente_ia_tools.solicitar_atualizacao_whatsapps_clinica(
                    self._context(db, conversation),
                    clinica="Animal Care",
                    whatsapps=["85912345678"],
                    motivo="Numero atualizado",
                )["pending_action"]
                executed = assistente_ia_tools.decide_pending_action(
                    db=db,
                    current_user=self.user,
                    request=SimpleNamespace(headers={}),
                    action_id=prepared["id"],
                    decision="approve",
                )
            db.refresh(clinic)
            self.assertEqual(executed["status"], "executed")
            self.assertEqual(clinic.whatsapps, ["85912345678"])
            self.assertEqual(clinic.email, original_email)

    def test_vinculo_de_paciente_a_reserva_exige_aprovacao_e_preserva_horario(self) -> None:
        with self._session_factory() as db:
            clinic, service, patient, conversation = self._seed_base(db)
            tutor = db.query(Tutor).filter(Tutor.id == patient.tutor_id).one()
            patient_id = int(patient.id)
            tutor_id = int(tutor.id)
            start = datetime.now(assistente_ia_tools.LOCAL_TZ) + timedelta(days=5)
            reservation = Agendamento(
                paciente_id=None,
                tutor_id=None,
                clinica_id=clinic.id,
                servico_id=service.id,
                inicio=start,
                fim=start + timedelta(minutes=30),
                data=start.date().isoformat(),
                hora=start.strftime("%H:%M"),
                status="Reservado",
                reserva_expira_em=datetime.now(timezone.utc) + timedelta(hours=2),
            )
            db.add(reservation)
            db.commit()
            db.refresh(reservation)
            with patch.object(assistente_ia_tools, "registrar_auditoria"):
                prepared = assistente_ia_tools.solicitar_vinculo_paciente_reserva(
                    self._context(db, conversation),
                    agendamento_id=reservation.id,
                    tutor=f"#{tutor.id}",
                    paciente=patient.nome,
                )["pending_action"]
                self.assertEqual(prepared["type"], "attach_patient_to_reservation")
                self.assertIsNone(reservation.paciente_id)
                with patch.object(
                    assistente_ia_tools.agenda,
                    "atualizar_agendamento",
                    return_value={
                        "id": reservation.id,
                        "inicio": start.isoformat(),
                        "status": "Reservado",
                        "paciente_id": patient.id,
                    },
                ) as official_update:
                    executed = assistente_ia_tools.decide_pending_action(
                        db=db,
                        current_user=self.user,
                        request=SimpleNamespace(headers={}),
                        action_id=prepared["id"],
                        decision="approve",
                    )

        self.assertEqual(executed["status"], "executed")
        payload = official_update.call_args.kwargs["agendamento"]
        self.assertEqual(payload.paciente_id, patient_id)
        self.assertEqual(payload.tutor_id, tutor_id)
        self.assertNotIn("inicio", payload.model_dump(exclude_unset=True))

    def test_rascunho_clinico_nunca_altera_laudo_oficial(self) -> None:
        with self._session_factory() as db:
            _clinic, _service, patient, conversation = self._seed_base(db)
            report = Laudo(
                paciente_id=patient.id,
                veterinario_id=self.user.id,
                tipo="ecocardiograma",
                titulo="Ecocardiograma",
                descricao="Descricao oficial",
                diagnostico="Diagnostico oficial",
                status="Rascunho",
            )
            db.add(report)
            db.commit()
            db.refresh(report)
            draft = assistente_ia_management.save_clinical_draft(
                db,
                self.user,
                conversation_id=conversation.id,
                report_id=report.id,
                title="Sugestao comparativa",
                content="Texto sugerido para revisao do medico veterinario.",
                alerts=["Confirmar medida antes de finalizar."],
                source_report_ids=[],
            )
            db.refresh(report)
            self.assertFalse(draft["official_report_modified"])
            self.assertEqual(report.descricao, "Descricao oficial")
            self.assertEqual(report.diagnostico, "Diagnostico oficial")
            self.assertEqual(report.status, "Rascunho")

    def test_motor_de_sugestoes_remove_intervalo_bloqueado(self) -> None:
        with self._session_factory() as db:
            clinic, service, _patient, _conversation = self._seed_base(db)
            reference = datetime.now(assistente_ia_tools.LOCAL_TZ).date() + timedelta(days=10)
            while reference.isoweekday() > 5:
                reference += timedelta(days=1)
            start = datetime.combine(reference, datetime.min.time()).replace(
                hour=8,
                tzinfo=assistente_ia_tools.LOCAL_TZ,
            )
            db.add(
                AgendaBloqueio(
                    id="block-full-day-test",
                    inicio=start,
                    fim=start.replace(hour=18),
                    motivo="Treinamento interno",
                    ativo=True,
                    criado_por_id=self.user.id,
                )
            )
            db.commit()
            result = assistente_ia_tools.agenda.sugerir_horarios_agenda(
                payload=assistente_ia_tools.agenda.SugestaoHorarioPayload(
                    data=reference.isoformat(),
                    origem_atendimento="clinica_parceira",
                    clinica_id=clinic.id,
                    servico_id=service.id,
                    duracao_minutos=30,
                    intervalo_minutos=30,
                    limite=6,
                    perfil_deslocamento="comercial",
                ),
                db=db,
                current_user=self.user,
            )
            self.assertEqual(result["items"], [])

    def test_turno_da_ia_executa_tool_loop_e_persiste_historico(self) -> None:
        with self._session_factory() as db:
            _clinic, _service, _patient, conversation = self._seed_base(db)
            tool_call = SimpleNamespace(
                type="function_call",
                name="analisar_faturamento",
                arguments='{"meses": 5, "clinica": null}',
                call_id="call-1",
            )
            first_response = SimpleNamespace(id="resp-1", output=[tool_call], output_text="")
            final_response = SimpleNamespace(
                id="resp-2",
                output=[],
                output_text="O faturamento cresceu no periodo analisado.",
            )
            tool_result = {"ok": True, "periodo": {"meses": 5}, "serie_mensal": []}

            with (
                patch.object(assistente_ia_service, "ensure_assistant_available"),
                patch.object(assistente_ia_service, "OpenAI", return_value=SimpleNamespace()),
                patch.object(
                    assistente_ia_service,
                    "_provider_request",
                    side_effect=[first_response, final_response],
                ) as provider,
                patch.object(assistente_ia_service, "execute_tool", return_value=tool_result) as executor,
                patch.object(assistente_ia_service, "registrar_auditoria"),
            ):
                result = assistente_ia_service.run_assistant_turn(
                    db=db,
                    current_user=self.user,
                    request=SimpleNamespace(headers={}),
                    message="Analise os ultimos cinco meses",
                    conversation=conversation,
                )

            self.assertEqual(provider.call_count, 2)
            executor.assert_called_once()
            self.assertEqual(result["assistant_message"]["content"], final_response.output_text)
            self.assertEqual(conversation.previous_response_id, "resp-2")
            self.assertEqual(db.query(AssistenteIAMensagem).count(), 2)

    def test_retentativa_reutiliza_comando_sem_resposta_em_vez_de_duplica_lo(self) -> None:
        with self._session_factory() as db:
            _clinic, _service, _patient, conversation = self._seed_base(db)
            failed_message = AssistenteIAMensagem(
                conversa_id=conversation.id,
                usuario_id=self.user.id,
                papel="user",
                conteudo="Agora realize o agendamento",
                provider_status="failed",
            )
            db.add(failed_message)
            db.commit()
            final_response = SimpleNamespace(
                id="resp-retry",
                output=[],
                output_text="Vou preparar o próximo passo com os dados disponíveis.",
            )
            with (
                patch.object(assistente_ia_service, "ensure_assistant_available"),
                patch.object(assistente_ia_service, "OpenAI", return_value=SimpleNamespace()),
                patch.object(assistente_ia_service, "_provider_request", return_value=final_response),
                patch.object(assistente_ia_service, "registrar_auditoria"),
            ):
                result = assistente_ia_service.run_assistant_turn(
                    db=db,
                    current_user=self.user,
                    request=SimpleNamespace(headers={}),
                    message="Agora realize o agendamento",
                    conversation=conversation,
                )

            self.assertEqual(db.query(AssistenteIAMensagem).count(), 2)
            self.assertEqual(result["user_message"]["id"], failed_message.id)
            self.assertEqual(failed_message.provider_status, "completed")


if __name__ == "__main__":
    unittest.main()
