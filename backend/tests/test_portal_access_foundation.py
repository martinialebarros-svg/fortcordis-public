import os
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "portal-access-foundation-test-secret-key-1234567890")

from app.api.v1.endpoints import portal, portal_clinic_auth
from app.core.config import settings
from app.core.portal_security import (
    PORTAL_DOWNLOAD_TOKEN_HEADER,
    PortalSessionContext,
    decode_portal_session_token,
)
from app.core.portal_release import PORTAL_RELEASED_STATUS
from app.models.atendimento_clinico import AnexoAtendimento, AtendimentoClinico
from app.models.clinica import Clinica
from app.models.laudo import Exame, Laudo
from app.models.paciente import Paciente
from app.models.portal_access import PortalAccessChallenge
from app.models.tutor import Tutor
from app.schemas.portal import (
    PortalClinicActivationRequest,
    PortalClinicaSessionLinkRequest,
    PortalCodeVerifyRequest,
    PortalPasswordResetConfirmRequest,
    PortalTutorSessionLinkRequest,
)


def _make_request(
    *,
    authorization: str | None = None,
    headers: dict[str, str] | None = None,
) -> Request:
    raw_headers: list[tuple[bytes, bytes]] = []
    if authorization:
        raw_headers.append((b"authorization", authorization.encode("utf-8")))
    for key, value in (headers or {}).items():
        raw_headers.append((key.lower().encode("utf-8"), value.encode("utf-8")))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/portal/test",
        "raw_path": b"/api/v1/portal/test",
        "query_string": b"",
        "headers": raw_headers,
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "scheme": "http",
        "http_version": "1.1",
    }
    return Request(scope)


class PortalAccessFoundationTest(unittest.TestCase):
    def test_portal_clinic_password_min_length_accepts_8_and_rejects_7(self) -> None:
        activation_payload = {
            "invite_token": "tokentokentokentoken",
            "email": "clinica@example.com",
            "responsavel_nome": "Responsavel Teste",
            "password": "Senha123",
            "password_confirmation": "Senha123",
        }
        reset_payload = {
            "reset_token": "resettokenresettoken",
            "password": "Senha123",
            "password_confirmation": "Senha123",
        }

        activation = PortalClinicActivationRequest(**activation_payload)
        reset = PortalPasswordResetConfirmRequest(**reset_payload)

        self.assertEqual(activation.password, "Senha123")
        self.assertEqual(reset.password_confirmation, "Senha123")

        with self.assertRaises(ValidationError):
            PortalClinicActivationRequest(
                **{
                    **activation_payload,
                    "password": "Senha12",
                    "password_confirmation": "Senha12",
                }
            )

        with self.assertRaises(ValidationError):
            PortalPasswordResetConfirmRequest(
                **{
                    **reset_payload,
                    "password": "Senha12",
                    "password_confirmation": "Senha12",
                }
            )

    def _build_session(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "portal-access-foundation.db"
        engine = create_engine(f"sqlite:///{db_path}")
        for table in (
            Tutor.__table__,
            Paciente.__table__,
            Clinica.__table__,
            AtendimentoClinico.__table__,
            Laudo.__table__,
            Exame.__table__,
            AnexoAtendimento.__table__,
            PortalAccessChallenge.__table__,
        ):
            table.create(engine, checkfirst=True)
        session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
        return tmpdir, session, engine

    def _seed_portal_data(self, db: sessionmaker, tmpdir: tempfile.TemporaryDirectory):
        tutor = Tutor(
            nome="Maria Tutora",
            email="maria@example.com",
            whatsapp="(85) 99999-0000",
            telefone="85999990000",
            ativo=1,
        )
        paciente = Paciente(
            nome="Luna",
            especie="Canina",
            tutor_id=1,
            ativo=1,
        )
        clinica = Clinica(nome="Clinica Parceira A", email="parceira@example.com", ativo=True)
        clinica_outra = Clinica(nome="Clinica Parceira B", email="outra@example.com", ativo=True)
        db.add_all([tutor, paciente, clinica, clinica_outra])
        db.flush()
        paciente.tutor_id = tutor.id

        atendimento = AtendimentoClinico(
            paciente_id=paciente.id,
            tutor_id=tutor.id,
            clinica_id=clinica.id,
            agendamento_id=None,
            veterinario_id=77,
            especie="Canina",
            data_atendimento=datetime(2026, 6, 16, 9, 30),
            status="Concluido",
            criado_por_id=77,
            criado_por_nome="Vet Teste",
        )
        db.add(atendimento)
        db.flush()

        exame = Exame(
            atendimento_id=atendimento.id,
            paciente_id=paciente.id,
            tipo_exame="Ecocardiograma",
            categoria_exame="Cardiologia",
            prioridade="Rotina",
            status=PORTAL_RELEASED_STATUS,
            data_solicitacao=datetime(2026, 6, 16, 9, 0),
            data_resultado=datetime(2026, 6, 16, 10, 0),
            observacoes="Exame liberado para portal.",
        )
        db.add(exame)
        db.flush()

        exame_interno = Exame(
            atendimento_id=atendimento.id,
            paciente_id=paciente.id,
            tipo_exame="Eletrocardiograma",
            categoria_exame="Cardiologia",
            prioridade="Rotina",
            status="Concluido",
            data_solicitacao=datetime(2026, 6, 16, 9, 15),
            data_resultado=datetime(2026, 6, 16, 10, 15),
            observacoes="Exame concluido internamente, ainda nao liberado no portal.",
        )
        db.add(exame_interno)
        db.flush()

        file_path = Path(tmpdir.name) / "eco-luna.pdf"
        file_path.write_bytes(b"%PDF-1.4\nportal test pdf\n")
        anexo = AnexoAtendimento(
            atendimento_id=atendimento.id,
            exame_id=exame.id,
            tipo="documento",
            descricao="Laudo PDF",
            url=f"/api/v1/atendimentos/anexos/{1}/arquivo",
            nome_original="eco-luna.pdf",
            tamanho=file_path.stat().st_size,
            mime_type="application/pdf",
            caminho_arquivo=str(file_path),
            origem="upload",
        )
        db.add(anexo)
        db.commit()
        db.refresh(tutor)
        db.refresh(paciente)
        db.refresh(clinica)
        db.refresh(clinica_outra)
        db.refresh(exame)
        db.refresh(anexo)
        return tutor, paciente, clinica, clinica_outra, exame, anexo

    def test_tutor_challenge_and_code_verification_issue_scoped_token(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            tutor, paciente, *_ = self._seed_portal_data(db, tmpdir)
            payload = PortalTutorSessionLinkRequest(
                tutor_id=tutor.id,
                paciente_id=paciente.id,
                canal="email",
                contato=tutor.email,
            )

            with patch.object(settings, "PORTAL_DEBUG_EXPOSE_CODE", True), patch.object(
                portal, "registrar_auditoria", return_value=None
            ), patch.object(
                portal,
                "send_portal_access_code",
                return_value=SimpleNamespace(provider="smtp", channel="email"),
            ) as send_mock:
                challenge_response = portal.solicitar_sessao_tutor(
                    payload,
                    request=_make_request(),
                    db=db,
                )

                self.assertTrue(challenge_response.accepted)
                self.assertEqual(
                    db.query(PortalAccessChallenge).count(),
                    1,
                )
                self.assertIsNotNone(challenge_response.debug_code)
                send_mock.assert_called_once()
                delivery_payload = send_mock.call_args.args[0]
                self.assertEqual(delivery_payload.channel, "email")
                self.assertEqual(delivery_payload.destination, tutor.email)

                token_response = portal.verificar_codigo_portal(
                    PortalCodeVerifyRequest(
                        challenge_id=challenge_response.challenge_id,
                        codigo=challenge_response.debug_code,
                    ),
                    request=_make_request(),
                    db=db,
                )

            decoded = decode_portal_session_token(token_response.access_token)
            self.assertEqual(decoded.actor_type, "tutor")
            self.assertEqual(decoded.actor_id, tutor.id)
            self.assertEqual(decoded.paciente_id, paciente.id)
            self.assertEqual(token_response.scope, portal.PORTAL_SCOPE_TUTOR)

            challenge = db.query(PortalAccessChallenge).first()
            self.assertEqual(challenge.status, portal.PORTAL_CHALLENGE_STATUS_CONSUMED)
            self.assertIsNotNone(challenge.consumed_at)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_invalid_tutor_request_keeps_generic_response_without_creating_challenge(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            tutor, paciente, *_ = self._seed_portal_data(db, tmpdir)
            payload = PortalTutorSessionLinkRequest(
                tutor_id=tutor.id,
                paciente_id=paciente.id,
                canal="email",
                contato="invalido@example.com",
            )

            with patch.object(portal, "registrar_auditoria", return_value=None), patch.object(
                portal,
                "send_portal_access_code",
                return_value=SimpleNamespace(provider="smtp", channel="email"),
            ) as send_mock:
                response = portal.solicitar_sessao_tutor(
                    payload,
                    request=_make_request(),
                    db=db,
                )

            self.assertTrue(response.accepted)
            self.assertIn("codigo temporario", response.message)
            self.assertEqual(db.query(PortalAccessChallenge).count(), 0)
            send_mock.assert_not_called()
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_invalid_code_locks_challenge_when_attempt_limit_is_reached(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            tutor, paciente, *_ = self._seed_portal_data(db, tmpdir)
            with patch.object(settings, "PORTAL_DEBUG_EXPOSE_CODE", True), patch.object(
                portal, "registrar_auditoria", return_value=None
            ), patch.object(
                portal,
                "send_portal_access_code",
                return_value=SimpleNamespace(provider="smtp", channel="email"),
            ) as send_mock:
                challenge_response = portal.solicitar_sessao_tutor(
                    PortalTutorSessionLinkRequest(
                        tutor_id=tutor.id,
                        paciente_id=paciente.id,
                        canal="email",
                        contato=tutor.email,
                    ),
                    request=_make_request(),
                    db=db,
                )
                send_mock.assert_called_once()
                delivery_payload = send_mock.call_args.args[0]
                self.assertEqual(delivery_payload.channel, "email")
                self.assertEqual(delivery_payload.destination, tutor.email)

                challenge = db.query(PortalAccessChallenge).filter(
                    PortalAccessChallenge.challenge_id == challenge_response.challenge_id
                ).first()
                challenge.max_attempts = 1
                db.commit()

                with self.assertRaises(HTTPException) as ctx:
                    portal.verificar_codigo_portal(
                        PortalCodeVerifyRequest(
                            challenge_id=challenge.challenge_id,
                            codigo="000000",
                        ),
                        request=_make_request(),
                        db=db,
                    )

            self.assertEqual(ctx.exception.status_code, 401)
            db.refresh(challenge)
            self.assertEqual(challenge.status, portal.PORTAL_CHALLENGE_STATUS_LOCKED)
            self.assertEqual(challenge.failed_attempts, 1)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_whatsapp_tutor_request_is_disabled_by_default(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            tutor, paciente, *_ = self._seed_portal_data(db, tmpdir)
            with patch.object(portal, "send_portal_access_code") as send_mock:
                with self.assertRaises(HTTPException) as ctx:
                    portal.solicitar_sessao_tutor(
                        PortalTutorSessionLinkRequest(
                            tutor_id=tutor.id,
                            paciente_id=paciente.id,
                            canal="whatsapp",
                            contato=tutor.whatsapp,
                        ),
                        request=_make_request(),
                        db=db,
                    )

            self.assertEqual(ctx.exception.status_code, 400)
            self.assertIn("WhatsApp", ctx.exception.detail)
            self.assertEqual(db.query(PortalAccessChallenge).count(), 0)
            send_mock.assert_not_called()
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_tutor_can_list_only_scoped_pet_exams(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            tutor, paciente, *_ = self._seed_portal_data(db, tmpdir)
            session = PortalSessionContext(
                actor_type="tutor",
                actor_id=tutor.id,
                paciente_id=paciente.id,
                clinica_id=None,
                challenge_id="challenge-tutor",
                display_name=tutor.nome,
                channel="email",
                scope=tuple(portal.PORTAL_SCOPE_TUTOR),
                expires_at=datetime.utcnow(),
            )

            response = portal.listar_exames_pet_portal(
                paciente.id,
                db=db,
                portal_session=session,
            )

            self.assertEqual(db.query(Exame).count(), 2)
            self.assertEqual(response.total, 1)
            self.assertEqual(response.items[0].paciente_id, paciente.id)
            self.assertEqual(len(response.items[0].anexos), 1)

            with self.assertRaises(HTTPException) as ctx:
                portal.listar_exames_pet_portal(
                    paciente.id + 999,
                    db=db,
                    portal_session=session,
                )

            self.assertEqual(ctx.exception.status_code, 403)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_clinica_session_filters_exam_list_and_generates_download_token(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            _, paciente, clinica, clinica_outra, exame, anexo = self._seed_portal_data(db, tmpdir)
            clinic_session = PortalSessionContext(
                actor_type="clinica",
                actor_id=clinica.id,
                paciente_id=None,
                clinica_id=clinica.id,
                challenge_id="challenge-clinica",
                display_name="Responsavel Clinica",
                channel="email",
                scope=tuple(portal.PORTAL_SCOPE_CLINICA),
                expires_at=datetime.utcnow(),
            )
            clinic_other_session = PortalSessionContext(
                actor_type="clinica",
                actor_id=clinica_outra.id,
                paciente_id=None,
                clinica_id=clinica_outra.id,
                challenge_id="challenge-outra",
                display_name="Outra Clinica",
                channel="email",
                scope=tuple(portal.PORTAL_SCOPE_CLINICA),
                expires_at=datetime.utcnow(),
            )

            list_response = portal.listar_exames_pet_portal(
                paciente.id,
                db=db,
                portal_session=clinic_session,
            )
            self.assertEqual(list_response.total, 1)

            list_response_other = portal.listar_exames_pet_portal(
                paciente.id,
                db=db,
                portal_session=clinic_other_session,
            )
            self.assertEqual(list_response_other.total, 0)

            download_response = portal.gerar_download_url_exame_portal(
                exame.id,
                db=db,
                portal_session=clinic_session,
            )
            self.assertEqual(len(download_response.items), 1)
            self.assertEqual(download_response.items[0].anexo_id, anexo.id)
            self.assertEqual(
                download_response.items[0].download_token_header,
                PORTAL_DOWNLOAD_TOKEN_HEADER,
            )

            with patch.object(portal, "registrar_auditoria", return_value=None):
                file_response = portal.baixar_arquivo_anexo_portal(
                    anexo.id,
                    request=_make_request(
                        headers={
                            PORTAL_DOWNLOAD_TOKEN_HEADER: download_response.items[0].download_token,
                        }
                    ),
                    db=db,
                )

            self.assertEqual(file_response.path, anexo.caminho_arquivo)
            self.assertEqual(file_response.filename, "eco-luna.pdf")

            with self.assertRaises(HTTPException) as ctx:
                portal.gerar_download_url_exame_portal(
                    exame.id,
                    db=db,
                    portal_session=clinic_other_session,
                )

            self.assertEqual(ctx.exception.status_code, 403)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_clinica_date_filter_uses_exam_execution_date_not_release_date(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            tutor, paciente, clinica, *_ = self._seed_portal_data(db, tmpdir)
            laudo = Laudo(
                paciente_id=paciente.id,
                veterinario_id=77,
                tipo="ecocardiograma",
                titulo="Eco Luna",
                status=PORTAL_RELEASED_STATUS,
                clinic_id=clinica.id,
                data_exame=datetime(2026, 6, 14, 9, 30),
                criado_por_id=77,
                criado_por_nome="Vet Teste",
            )
            db.add(laudo)
            db.flush()
            exame = Exame(
                laudo_id=laudo.id,
                paciente_id=paciente.id,
                tipo_exame="Ecocardiograma controle",
                categoria_exame="Cardiologia",
                prioridade="Rotina",
                status=PORTAL_RELEASED_STATUS,
                data_solicitacao=datetime(2026, 6, 14, 9, 30),
                data_resultado=datetime(2026, 6, 18, 16, 0),
                observacoes="Laudo liberado depois da realizacao.",
            )
            db.add(exame)
            db.commit()

            clinic_session = PortalSessionContext(
                actor_type="clinica",
                actor_id=clinica.id,
                paciente_id=None,
                clinica_id=clinica.id,
                challenge_id="challenge-clinica",
                display_name="Responsavel Clinica",
                channel="email",
                scope=tuple(portal.PORTAL_SCOPE_CLINICA),
                expires_at=datetime.utcnow(),
            )

            same_day_response = portal.listar_exames_clinica_portal(
                q=None,
                pet=None,
                tutor=None,
                especie=None,
                tipo_exame="controle",
                status_exame=None,
                data_inicio=date(2026, 6, 14),
                data_fim=None,
                sort_by="data",
                sort_dir="desc",
                limit=100,
                offset=0,
                db=db,
                portal_session=clinic_session,
            )
            self.assertEqual(same_day_response.total, 1)
            self.assertEqual(same_day_response.items[0].laudo_id, laudo.id)
            self.assertEqual(
                same_day_response.items[0].data_exame,
                "2026-06-14T09:30:00",
            )

            release_day_response = portal.listar_exames_clinica_portal(
                q=None,
                pet=None,
                tutor=None,
                especie=None,
                tipo_exame="controle",
                status_exame=None,
                data_inicio=date(2026, 6, 18),
                data_fim=None,
                sort_by="data",
                sort_dir="desc",
                limit=100,
                offset=0,
                db=db,
                portal_session=clinic_session,
            )
            self.assertEqual(release_day_response.total, 0)

            period_response = portal.listar_exames_clinica_portal(
                q=None,
                pet=None,
                tutor=None,
                especie=None,
                tipo_exame="controle",
                status_exame=None,
                data_inicio=date(2026, 6, 14),
                data_fim=date(2026, 6, 18),
                sort_by="data",
                sort_dir="desc",
                limit=100,
                offset=0,
                db=db,
                portal_session=clinic_session,
            )
            self.assertEqual(period_response.total, 1)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_clinica_exam_list_includes_operational_panel(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            _, paciente, clinica, _, released_exam, _ = self._seed_portal_data(db, tmpdir)
            # 02:30 UTC on 17/06 is still 23:30 on 16/06 in Fortaleza.
            released_exam.data_resultado = datetime(2026, 6, 17, 2, 30)
            laudo_pendente = Laudo(
                paciente_id=paciente.id,
                veterinario_id=77,
                tipo="ecocardiograma",
                titulo="Eco pendente",
                status="Rascunho",
                clinic_id=clinica.id,
                data_exame=datetime(2026, 6, 16, 11, 30),
                criado_por_id=77,
                criado_por_nome="Vet Teste",
            )
            laudo_aguardando = Laudo(
                paciente_id=paciente.id,
                veterinario_id=77,
                tipo="eletrocardiograma",
                titulo="Eletro finalizado",
                status="Finalizado",
                clinic_id=clinica.id,
                data_exame=datetime(2026, 6, 15, 14, 0),
                criado_por_id=77,
                criado_por_nome="Vet Teste",
            )
            db.add_all([laudo_pendente, laudo_aguardando])
            db.commit()

            clinic_session = PortalSessionContext(
                actor_type="clinica",
                actor_id=clinica.id,
                paciente_id=None,
                clinica_id=clinica.id,
                challenge_id="challenge-clinica",
                display_name="Responsavel Clinica",
                channel="email",
                scope=tuple(portal.PORTAL_SCOPE_CLINICA),
                expires_at=datetime.utcnow(),
            )

            with patch.object(
                portal,
                "_portal_local_now",
                return_value=datetime(2026, 6, 16, 23, 45, tzinfo=portal.PORTAL_LOCAL_TZ),
            ):
                response = portal.listar_exames_clinica_portal(
                    q=None,
                    pet=None,
                    tutor=None,
                    especie=None,
                    tipo_exame=None,
                    status_exame=None,
                    data_inicio=None,
                    data_fim=None,
                    sort_by="data",
                    sort_dir="desc",
                    limit=100,
                    offset=0,
                    db=db,
                    portal_session=clinic_session,
                )

            self.assertIsNotNone(response.operational_summary)
            self.assertEqual(response.operational_summary.realizados_hoje, 3)
            self.assertEqual(response.operational_summary.em_laudo, 1)
            self.assertEqual(response.operational_summary.aguardando_liberacao, 2)
            self.assertEqual(response.operational_summary.liberados_hoje, 1)
            self.assertEqual(response.operational_summary.sla_horas, 48)
            status_keys = {item.status_key for item in response.operational_items}
            self.assertIn("em_laudo", status_keys)
            self.assertIn("aguardando_liberacao", status_keys)
            self.assertIn("liberado_portal", status_keys)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_clinica_operational_pending_items_survive_recent_activity_crowding(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            _, paciente, clinica, _, _, _ = self._seed_portal_data(db, tmpdir)

            laudo_antigo_pendente = Laudo(
                paciente_id=paciente.id,
                veterinario_id=77,
                tipo="ecocardiograma",
                titulo="Eco antigo aguardando liberacao",
                status="Finalizado",
                clinic_id=clinica.id,
                data_exame=datetime(2026, 6, 1, 9, 0),
                criado_por_id=77,
                criado_por_nome="Vet Teste",
            )
            db.add(laudo_antigo_pendente)

            # 8 laudos recentes em outro status, o suficiente pra lotar o
            # top-8 combinado de `operational_items` e comprovar que o
            # pendente antigo some de la mas continua em
            # `operational_pending_items` (achado da secao 4 do spec de
            # portal-clinica-parceira-redesign).
            laudos_recentes = [
                Laudo(
                    paciente_id=paciente.id,
                    veterinario_id=77,
                    tipo="ecocardiograma",
                    titulo=f"Eco recente {indice}",
                    status="Rascunho",
                    clinic_id=clinica.id,
                    data_exame=datetime(2026, 6, 16, 10, indice),
                    criado_por_id=77,
                    criado_por_nome="Vet Teste",
                )
                for indice in range(portal._PORTAL_OPERATIONAL_RECENT_LIMIT)
            ]
            db.add_all(laudos_recentes)
            db.commit()
            db.refresh(laudo_antigo_pendente)

            clinic_session = PortalSessionContext(
                actor_type="clinica",
                actor_id=clinica.id,
                paciente_id=None,
                clinica_id=clinica.id,
                challenge_id="challenge-clinica",
                display_name="Responsavel Clinica",
                channel="email",
                scope=tuple(portal.PORTAL_SCOPE_CLINICA),
                expires_at=datetime.utcnow(),
            )

            with patch.object(
                portal,
                "_portal_local_now",
                return_value=datetime(2026, 6, 16, 23, 45, tzinfo=portal.PORTAL_LOCAL_TZ),
            ):
                response = portal.listar_exames_clinica_portal(
                    q=None,
                    pet=None,
                    tutor=None,
                    especie=None,
                    tipo_exame=None,
                    status_exame=None,
                    data_inicio=None,
                    data_fim=None,
                    sort_by="data",
                    sort_dir="desc",
                    limit=100,
                    offset=0,
                    db=db,
                    portal_session=clinic_session,
                )

            antigo_item_id = f"laudo:{laudo_antigo_pendente.id}"
            operational_item_ids = {item.item_id for item in response.operational_items}
            self.assertNotIn(
                antigo_item_id,
                operational_item_ids,
                "pre-condicao do teste: o pendente antigo precisa ficar de fora do top-8 misturado",
            )

            pending_item_ids = {item.item_id for item in response.operational_pending_items}
            self.assertIn(antigo_item_id, pending_item_ids)
            for item in response.operational_pending_items:
                self.assertEqual(item.status_key, "aguardando_liberacao")
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_admin_mirror_reuses_clinic_portal_scope_and_downloads(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            _, _, clinica, *_ = self._seed_portal_data(db, tmpdir)

            with patch.object(settings, "PORTAL_CLINIC_INVITE_AUTH_ENABLED", True):
                response = portal_clinic_auth.consultar_espelho_portal_clinica_admin(
                    clinica_id=clinica.id,
                    q=None,
                    pet=None,
                    tutor=None,
                    especie=None,
                    tipo_exame=None,
                    status_exame=None,
                    data_inicio=None,
                    data_fim=None,
                    sort_by="data",
                    sort_dir="desc",
                    limit=100,
                    offset=0,
                    db=db,
                    current_user=SimpleNamespace(id=1),
                )

                self.assertEqual(response.clinica_id, clinica.id)
                self.assertEqual(response.clinica_nome, clinica.nome)
                self.assertEqual(response.total, 1)
                self.assertEqual(response.items[0].tipo_exame, "Ecocardiograma")

                download_response = portal_clinic_auth.gerar_download_espelho_portal_clinica_admin(
                    clinica_id=clinica.id,
                    exame_id=response.items[0].id,
                    db=db,
                    current_user=SimpleNamespace(id=1),
                )

            self.assertEqual(download_response.exame_id, response.items[0].id)
            self.assertEqual(len(download_response.items), 1)
            self.assertEqual(download_response.items[0].download_token_header, PORTAL_DOWNLOAD_TOKEN_HEADER)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_clinica_request_creates_email_challenge(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            *_, clinica, _, _, _ = self._seed_portal_data(db, tmpdir)
            with patch.object(settings, "PORTAL_DEBUG_EXPOSE_CODE", True), patch.object(
                portal, "registrar_auditoria", return_value=None
            ), patch.object(
                portal,
                "send_portal_access_code",
                return_value=SimpleNamespace(provider="smtp", channel="email"),
            ) as send_mock:
                response = portal.solicitar_sessao_clinica(
                    PortalClinicaSessionLinkRequest(
                        clinica_id=clinica.id,
                        email=clinica.email,
                        responsavel_nome="Dra. Parceira",
                    ),
                    request=_make_request(),
                    db=db,
                )
            send_mock.assert_called_once()
            delivery_payload = send_mock.call_args.args[0]
            self.assertEqual(delivery_payload.channel, "email")
            self.assertEqual(delivery_payload.destination, clinica.email)

            challenge = db.query(PortalAccessChallenge).filter(
                PortalAccessChallenge.challenge_id == response.challenge_id
            ).first()
            self.assertIsNotNone(challenge)
            self.assertEqual(challenge.actor_type, "clinica")
            self.assertEqual(challenge.clinica_id, clinica.id)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
