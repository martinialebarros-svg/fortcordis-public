import os
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "agenda-formalizacao-test-secret-key-1234567890")

from app.models.agenda_formalizacao import AgendaFormalizacaoInvite
from app.models.agendamento import Agendamento
from app.models.clinica import Clinica
from app.models.paciente import Paciente
from app.models.tutor import Tutor
from app.core.config import settings
from app.services.agenda_formalizacao_service import (
    INVITE_KIND,
    build_formalizacao_url,
    criar_ou_reutilizar_convite,
    obter_contexto_publico,
    obter_convite_valido,
    processar_submissao,
)
from app.services.portal_clinic_auth_service import generate_opaque_token, hash_secret


class AgendaFormalizacaoServiceTest(unittest.TestCase):
    def _build_session(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "agenda-formalizacao.db"
        engine = create_engine(f"sqlite:///{db_path}")
        for table in (
            Clinica.__table__,
            Tutor.__table__,
            Paciente.__table__,
            Agendamento.__table__,
            AgendaFormalizacaoInvite.__table__,
        ):
            table.create(engine, checkfirst=True)
        session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
        return tmpdir, session, engine

    def _seed_reserva(self, db, *, reserva_expira_em=None, status="Reservado"):
        clinica = Clinica(
            nome="Clinica Teste",
            telefone="(85) 98888-1111",
            whatsapps=["5585988881111"],
            ativo=True,
        )
        db.add(clinica)
        db.flush()
        now = datetime.now(timezone.utc)
        agendamento = Agendamento(
            clinica_id=clinica.id,
            servico="Ecocardiograma",
            inicio=now + timedelta(days=1),
            fim=now + timedelta(days=1, minutes=30),
            status=status,
            reserva_expira_em=reserva_expira_em,
        )
        db.add(agendamento)
        db.commit()
        db.refresh(agendamento)
        return clinica, agendamento

    def test_criar_convite_usa_prazo_da_reserva_quando_disponivel(self):
        tmpdir, db, engine = self._build_session()
        try:
            prazo = datetime.now(timezone.utc) + timedelta(hours=5)
            _clinica, agendamento = self._seed_reserva(db, reserva_expira_em=prazo)
            invite, raw_token = criar_ou_reutilizar_convite(db, agendamento)

            self.assertTrue(raw_token)
            self.assertEqual(invite.status, "pending")
            self.assertAlmostEqual(
                invite.expires_at.replace(tzinfo=timezone.utc).timestamp(),
                prazo.timestamp(),
                delta=1,
            )

            resolved = obter_convite_valido(db, raw_token)
            self.assertEqual(resolved.id, invite.id)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_criar_convite_sem_prazo_usa_default_configurado(self):
        tmpdir, db, engine = self._build_session()
        try:
            _clinica, agendamento = self._seed_reserva(db, reserva_expira_em=None)
            with patch.object(settings, "AGENDA_FORMALIZACAO_INVITE_DEFAULT_HOURS", 48):
                invite, _raw_token = criar_ou_reutilizar_convite(db, agendamento)

            expected = datetime.now(timezone.utc) + timedelta(hours=48)
            self.assertAlmostEqual(
                invite.expires_at.replace(tzinfo=timezone.utc).timestamp(),
                expected.timestamp(),
                delta=5,
            )
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_novo_convite_revoga_pendente_anterior(self):
        tmpdir, db, engine = self._build_session()
        try:
            _clinica, agendamento = self._seed_reserva(db)
            _invite1, raw_token1 = criar_ou_reutilizar_convite(db, agendamento)
            _invite2, raw_token2 = criar_ou_reutilizar_convite(db, agendamento)

            with self.assertRaises(HTTPException) as ctx:
                obter_convite_valido(db, raw_token1)
            self.assertEqual(ctx.exception.status_code, 410)

            resolved2 = obter_convite_valido(db, raw_token2)
            self.assertEqual(resolved2.status, "pending")
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_obter_convite_valido_rejeita_token_desconhecido(self):
        tmpdir, db, engine = self._build_session()
        try:
            with self.assertRaises(HTTPException) as ctx:
                obter_convite_valido(db, "token-que-nao-existe")
            self.assertEqual(ctx.exception.status_code, 404)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_obter_convite_valido_expira_convite_vencido(self):
        tmpdir, db, engine = self._build_session()
        try:
            _clinica, agendamento = self._seed_reserva(db)
            raw_token = generate_opaque_token()
            invite = AgendaFormalizacaoInvite(
                agendamento_id=agendamento.id,
                token_hash=hash_secret(INVITE_KIND, raw_token),
                status="pending",
                expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
            )
            db.add(invite)
            db.commit()

            with self.assertRaises(HTTPException) as ctx:
                obter_convite_valido(db, raw_token)
            self.assertEqual(ctx.exception.status_code, 410)

            db.refresh(invite)
            self.assertEqual(invite.status, "expired")
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_obter_contexto_publico_retorna_dados_da_reserva(self):
        tmpdir, db, engine = self._build_session()
        try:
            _clinica, agendamento = self._seed_reserva(db)
            invite, _raw_token = criar_ou_reutilizar_convite(db, agendamento)
            contexto = obter_contexto_publico(db, invite)
            self.assertEqual(contexto["clinica_nome"], "Clinica Teste")
            self.assertEqual(contexto["servico"], "Ecocardiograma")
            self.assertTrue(contexto["data"])
            self.assertTrue(contexto["hora"])
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_build_formalizacao_url_exige_configuracao(self):
        with patch.object(settings, "PUBLIC_APP_BASE_URL", ""):
            with self.assertRaises(HTTPException) as ctx:
                build_formalizacao_url("abc")
            self.assertEqual(ctx.exception.status_code, 503)

        with patch.object(settings, "PUBLIC_APP_BASE_URL", "https://app.fortcordis.com"):
            url = build_formalizacao_url("abc123")
            self.assertEqual(url, "https://app.fortcordis.com/agenda/formalizar/abc123")

    def test_processar_submissao_cria_tutor_e_paciente_e_formaliza_agendamento(self):
        tmpdir, db, engine = self._build_session()
        try:
            _clinica, agendamento = self._seed_reserva(db)
            invite, _raw_token = criar_ou_reutilizar_convite(db, agendamento)

            with patch(
                "app.services.agenda_formalizacao_service.send_agenda_utility_template"
            ) as mocked_send:
                resultado = processar_submissao(
                    db,
                    invite=invite,
                    nome_paciente="Rex",
                    nome_tutor="João Silva",
                    telefone_tutor="(85) 98888-7777",
                )

            self.assertEqual(resultado.status, "Agendado")
            self.assertEqual(resultado.paciente, "Rex")
            self.assertEqual(resultado.tutor, "João Silva")

            tutor = db.query(Tutor).filter(Tutor.id == resultado.tutor_id).one()
            self.assertEqual(tutor.whatsapp, "5585988887777")
            paciente = db.query(Paciente).filter(Paciente.id == resultado.paciente_id).one()
            self.assertEqual(paciente.nome, "Rex")
            self.assertEqual(paciente.tutor_id, tutor.id)

            db.refresh(invite)
            self.assertEqual(invite.status, "used")
            mocked_send.assert_called_once()
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_processar_submissao_nao_reutiliza_tutor_existente_por_nome(self):
        tmpdir, db, engine = self._build_session()
        try:
            tutor_existente = Tutor(nome="Joao Silva", nome_key="joao silva", ativo=1)
            db.add(tutor_existente)
            db.flush()
            _clinica, agendamento = self._seed_reserva(db)
            invite, _raw_token = criar_ou_reutilizar_convite(db, agendamento)

            with patch("app.services.agenda_formalizacao_service.send_agenda_utility_template"):
                resultado = processar_submissao(
                    db,
                    invite=invite,
                    nome_paciente="Rex",
                    nome_tutor="João Silva",
                    telefone_tutor="85988887777",
                )

            self.assertNotEqual(resultado.tutor_id, tutor_existente.id)
            self.assertEqual(db.query(Tutor).count(), 2)
            db.refresh(tutor_existente)
            self.assertIsNone(tutor_existente.telefone)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_processar_submissao_falha_de_notificacao_nao_bloqueia_salvamento(self):
        tmpdir, db, engine = self._build_session()
        try:
            _clinica, agendamento = self._seed_reserva(db)
            invite, _raw_token = criar_ou_reutilizar_convite(db, agendamento)

            with patch(
                "app.services.agenda_formalizacao_service.send_agenda_utility_template",
                side_effect=RuntimeError("provider indisponivel"),
            ):
                resultado = processar_submissao(
                    db,
                    invite=invite,
                    nome_paciente="Rex",
                    nome_tutor="João Silva",
                    telefone_tutor="85988887777",
                )

            self.assertEqual(resultado.status, "Agendado")
            db.refresh(invite)
            self.assertEqual(invite.status, "used")
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_processar_submissao_valida_campos_obrigatorios(self):
        tmpdir, db, engine = self._build_session()
        try:
            _clinica, agendamento = self._seed_reserva(db)
            invite, _raw_token = criar_ou_reutilizar_convite(db, agendamento)

            with self.assertRaises(HTTPException) as ctx:
                processar_submissao(
                    db,
                    invite=invite,
                    nome_paciente="Rex",
                    nome_tutor="",
                    telefone_tutor="",
                )
            self.assertEqual(ctx.exception.status_code, 422)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_somente_primeiro_nome_e_pet_sem_telefone_e_sem_especie_presumida(self):
        tmpdir, db, engine = self._build_session()
        try:
            _clinica, agendamento = self._seed_reserva(db)
            invite, _raw_token = criar_ou_reutilizar_convite(db, agendamento)
            with patch("app.services.agenda_formalizacao_service.send_agenda_utility_template"):
                resultado = processar_submissao(db, invite=invite, nome_paciente="Pingo", nome_tutor="Cristiane", telefone_tutor="")
            tutor = db.get(Tutor, resultado.tutor_id)
            pet = db.get(Paciente, resultado.paciente_id)
            self.assertEqual(resultado.status, "Agendado")
            self.assertTrue(tutor.identificacao_pendente)
            self.assertFalse(tutor.telefone)
            self.assertIsNone(pet.especie)
            with self.assertRaises(HTTPException) as ctx:
                processar_submissao(db, invite=invite, nome_paciente="Pingo", nome_tutor="Cristiane", telefone_tutor="")
            self.assertEqual(ctx.exception.status_code, 410)
            self.assertEqual(db.query(Tutor).count(), 1)
            self.assertEqual(db.query(Paciente).count(), 1)
        finally:
            db.close(); engine.dispose(); tmpdir.cleanup()

    def test_processar_submissao_rejeita_convite_ja_usado(self):
        tmpdir, db, engine = self._build_session()
        try:
            _clinica, agendamento = self._seed_reserva(db)
            invite, raw_token = criar_ou_reutilizar_convite(db, agendamento)

            with patch("app.services.agenda_formalizacao_service.send_agenda_utility_template"):
                processar_submissao(
                    db,
                    invite=invite,
                    nome_paciente="Rex",
                    nome_tutor="João Silva",
                    telefone_tutor="85988887777",
                )

            with self.assertRaises(HTTPException) as ctx:
                obter_convite_valido(db, raw_token)
            self.assertEqual(ctx.exception.status_code, 410)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_submissoes_concorrentes_do_mesmo_convite_criam_apenas_um_tutor_e_pet(self):
        tmpdir, db, engine = self._build_session()
        try:
            _clinica, agendamento = self._seed_reserva(db)
            invite, raw_token = criar_ou_reutilizar_convite(db, agendamento)
            agendamento_id, invite_id = agendamento.id, invite.id
            db.close()
            session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
            convites_carregados = Barrier(2)

            def submeter():
                with session_factory() as session:
                    # Ambas as requisicoes validaram o token antes que qualquer
                    # uma delas consumisse o convite. O objeto da segunda fica
                    # desatualizado enquanto a primeira salva os dados.
                    convite_carregado = obter_convite_valido(session, raw_token)
                    self.assertEqual(convite_carregado.status, "pending")
                    convites_carregados.wait(timeout=10)
                    try:
                        resultado = processar_submissao(
                            session,
                            invite=convite_carregado,
                            nome_paciente="Pingo Concorrencia",
                            nome_tutor="Cristiane Teste",
                            telefone_tutor="",
                        )
                        return 200, resultado.tutor_id, resultado.paciente_id
                    except HTTPException as exc:
                        session.rollback()
                        return exc.status_code, None, None

            with patch(
                "app.services.agenda_formalizacao_service.send_agenda_utility_template"
            ) as mocked_send:
                with ThreadPoolExecutor(max_workers=2) as executor:
                    futures = [executor.submit(submeter) for _ in range(2)]
                    resultados = [future.result(timeout=20) for future in futures]

            self.assertEqual(sorted(status for status, _, _ in resultados), [200, 410])
            mocked_send.assert_called_once()
            with session_factory() as verification:
                tutor = verification.query(Tutor).one()
                pet = verification.query(Paciente).one()
                reserva = verification.get(Agendamento, agendamento_id)
                convite = verification.get(AgendaFormalizacaoInvite, invite_id)
                self.assertEqual(reserva.status, "Agendado")
                self.assertEqual((reserva.tutor_id, reserva.paciente_id), (tutor.id, pet.id))
                self.assertEqual(pet.tutor_id, tutor.id)
                self.assertTrue(tutor.identificacao_pendente)
                self.assertFalse(tutor.telefone)
                self.assertIsNone(pet.especie)
                self.assertEqual(convite.status, "used")
                self.assertIsNotNone(convite.used_at)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_schema_formalizacao_aceita_telefone_omitido(self):
        from app.api.v1.endpoints.whatsapp_agenda import AgendaFormalizacaoSubmitRequest

        payload = AgendaFormalizacaoSubmitRequest(nome_paciente="Pingo", nome_tutor="Cristiane")
        self.assertEqual(payload.telefone_tutor, "")


if __name__ == "__main__":
    unittest.main()
