"""Difusao do laudo para os veterinarios vinculados a clinica (CA-006..CA-015)."""
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

from app.api.v1.endpoints import laudos
from app.core.portal_release import PORTAL_RELEASED_STATUS
from app.models.atendimento_clinico import AnexoAtendimento, AtendimentoClinico
from app.models.clinica import Clinica
from app.models.imagem_laudo import ImagemLaudo
from app.models.laudo import Exame, Laudo
from app.models.paciente import Paciente
from app.models.portal_partner import (
    PORTAL_PARTNER_TYPE_VETERINARIO,
    PortalPartnerClinicLink,
    PortalPartnerProfile,
    PortalPartnerReleaseTarget,
)
from app.models.portal_clinic_auth import PortalClinicAccount, PortalClinicInvite
from app.models.portal_partner_auth import PortalPartnerAccount
from app.models.tutor import Tutor

PDF_BYTES = b"%PDF-1.4\nfake\n"
CLINICA_WHATSAPP = "5585999990001"
NOMEADO_WHATSAPP = "5585988880002"
DIFUSAO_WHATSAPP = "5585977770003"

CLINICA_A = 8
CLINICA_B = 9
PARCEIRO_NOMEADO = 4
PARCEIRO_DIFUSAO = 5


def _make_request() -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/laudos/1/portal/liberar-clinica",
        "raw_path": b"/api/v1/laudos/1/portal/liberar-clinica",
        "query_string": b"",
        "headers": [],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "scheme": "http",
        "http_version": "1.1",
    }
    return Request(scope)


class LaudoDifusaoPorVinculoDeClinicaTest(unittest.TestCase):
    def _build_session(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "laudo-difusao-vinculo.db"
        engine = create_engine(f"sqlite:///{db_path}")
        for table in (
            Tutor.__table__,
            Paciente.__table__,
            Clinica.__table__,
            AtendimentoClinico.__table__,
            Laudo.__table__,
            Exame.__table__,
            ImagemLaudo.__table__,
            AnexoAtendimento.__table__,
            PortalPartnerProfile.__table__,
            PortalPartnerClinicLink.__table__,
            PortalPartnerReleaseTarget.__table__,
            PortalPartnerAccount.__table__,
            PortalClinicInvite.__table__,
            PortalClinicAccount.__table__,
        ):
            table.create(engine, checkfirst=True)
        session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
        return tmpdir, session, engine

    @staticmethod
    def _current_user():
        return SimpleNamespace(id=7, nome="Dr. Martiniano", email="vet@example.com")

    def _fake_pdf(self):
        return SimpleNamespace(content=PDF_BYTES, filename="laudo-luna.pdf", cache_key="cache-key")

    def _fake_store(self, tmpdir: tempfile.TemporaryDirectory):
        def _store(atendimento_id: int, filename: str, content: bytes, content_type: str):
            file_path = Path(tmpdir.name) / f"stored-{atendimento_id}-{filename}"
            file_path.write_bytes(content)
            return str(file_path), filename, content_type

        return _store

    def _seed(
        self,
        db,
        *,
        clinic_id: int | None = CLINICA_A,
        nomeado: bool = False,
        difusao_em: int | None = None,
        difusao_ativa: bool = True,
        difusao_partner_ativo: bool = True,
        difusao_whatsapp: str | None = DIFUSAO_WHATSAPP,
        nomeado_tambem_difunde: bool = False,
        status: str = "Finalizado",
    ) -> Laudo:
        tutor = Tutor(nome="Monica", email="monica@example.com", ativo=1)
        db.add(tutor)
        db.flush()
        paciente = Paciente(nome="Luna", especie="Canina", tutor_id=tutor.id, ativo=1)
        db.add(paciente)
        db.add(Clinica(id=CLINICA_A, nome="Animal Care", telefone=CLINICA_WHATSAPP, ativo=True))
        db.add(Clinica(id=CLINICA_B, nome="Bicho Feliz", telefone="5585966660004", ativo=True))
        db.add(
            PortalPartnerProfile(
                id=PARCEIRO_NOMEADO,
                tipo=PORTAL_PARTNER_TYPE_VETERINARIO,
                nome_exibicao="Dra Isadora Bastos",
                email_login="isadora@vetparceiro.com",
                whatsapp=NOMEADO_WHATSAPP,
                ativo=True,
            )
        )
        db.add(
            PortalPartnerProfile(
                id=PARCEIRO_DIFUSAO,
                tipo=PORTAL_PARTNER_TYPE_VETERINARIO,
                nome_exibicao="Dra Carla Soares",
                email_login="carla@vetparceiro.com",
                whatsapp=difusao_whatsapp,
                ativo=difusao_partner_ativo,
            )
        )
        db.flush()

        if difusao_em is not None:
            db.add(
                PortalPartnerClinicLink(
                    partner_id=PARCEIRO_DIFUSAO,
                    clinica_id=difusao_em,
                    receber_todos_laudos=difusao_ativa,
                )
            )
        if nomeado_tambem_difunde:
            db.add(
                PortalPartnerClinicLink(
                    partner_id=PARCEIRO_NOMEADO,
                    clinica_id=CLINICA_A,
                    receber_todos_laudos=True,
                )
            )

        laudo = Laudo(
            paciente_id=paciente.id,
            veterinario_id=7,
            tipo="ecocardiograma",
            titulo="Laudo ecocardiografico - Luna",
            status=status,
            clinic_id=clinic_id,
            veterinario_parceiro_id=PARCEIRO_NOMEADO if nomeado else None,
            data_exame=datetime(2026, 7, 4, 15, 30),
            criado_por_id=7,
            criado_por_nome="Dr. Martiniano",
        )
        db.add(laudo)
        db.commit()
        db.refresh(laudo)
        return laudo

    def _liberar(self, db, laudo, tmpdir):
        with (
            patch.object(laudos, "render_laudo_pdf", return_value=self._fake_pdf()),
            patch.object(laudos, "store_atendimento_attachment_file", side_effect=self._fake_store(tmpdir)),
            patch.object(laudos, "registrar_auditoria", return_value=None) as audit_mock,
            patch("app.services.portal_clinic_notification_service.send_portal_email_message") as clinic_email,
            patch.object(laudos, "notify_partner_report_released") as partner_notify,
        ):
            clinic_email.return_value = SimpleNamespace(provider="smtp", channel="email")
            partner_notify.return_value = SimpleNamespace(
                status="sent",
                destination_masked="ca***@vetparceiro.com",
                provider="smtp",
                reason=None,
            )
            resposta = laudos.liberar_laudo_para_portal_clinica(
                laudo.id,
                request=_make_request(),
                db=db,
                current_user=self._current_user(),
            )
        return resposta, partner_notify, audit_mock

    def _targets(self, db, laudo_id: int) -> set[int]:
        return {
            int(target.partner_id)
            for target in db.query(PortalPartnerReleaseTarget)
            .filter(PortalPartnerReleaseTarget.laudo_id == laudo_id)
            .all()
        }

    # --- liberacao no portal -------------------------------------------------

    def test_difusao_libera_veterinario_sem_precisar_nomear_no_laudo(self) -> None:
        """CA-006."""
        tmpdir, db, engine = self._build_session()
        try:
            laudo = self._seed(db, nomeado=False, difusao_em=CLINICA_A)

            resposta, partner_notify, _ = self._liberar(db, laudo, tmpdir)

            self.assertEqual(self._targets(db, laudo.id), {PARCEIRO_DIFUSAO})
            self.assertEqual(partner_notify.call_count, 1)
            self.assertEqual(partner_notify.call_args.kwargs["partner_id"], PARCEIRO_DIFUSAO)
            self.assertEqual(
                resposta["destinos_liberados_agora"]["veterinarios_por_vinculo"],
                [PARCEIRO_DIFUSAO],
            )
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_nomeado_e_difusao_recebem_os_dois(self) -> None:
        """CA-007."""
        tmpdir, db, engine = self._build_session()
        try:
            laudo = self._seed(db, nomeado=True, difusao_em=CLINICA_A)

            resposta, partner_notify, _ = self._liberar(db, laudo, tmpdir)

            self.assertEqual(self._targets(db, laudo.id), {PARCEIRO_NOMEADO, PARCEIRO_DIFUSAO})
            self.assertEqual(partner_notify.call_count, 2)
            self.assertEqual(
                [call.kwargs["partner_id"] for call in partner_notify.call_args_list],
                [PARCEIRO_NOMEADO, PARCEIRO_DIFUSAO],
            )
            self.assertEqual(
                resposta["destinos_liberados_agora"]["veterinarios_por_vinculo"],
                [PARCEIRO_DIFUSAO],
            )
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_nomeado_que_tambem_difunde_entra_uma_vez_so(self) -> None:
        """CA-008."""
        tmpdir, db, engine = self._build_session()
        try:
            laudo = self._seed(db, nomeado=True, difusao_em=None, nomeado_tambem_difunde=True)

            resposta, partner_notify, _ = self._liberar(db, laudo, tmpdir)

            self.assertEqual(self._targets(db, laudo.id), {PARCEIRO_NOMEADO})
            self.assertEqual(partner_notify.call_count, 1)
            self.assertEqual(partner_notify.call_args.kwargs["partner_id"], PARCEIRO_NOMEADO)
            self.assertEqual(resposta["destinos_liberados_agora"]["veterinarios_por_vinculo"], [])
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_veterinario_inativo_nao_entra_na_difusao(self) -> None:
        """CA-009."""
        tmpdir, db, engine = self._build_session()
        try:
            laudo = self._seed(db, nomeado=False, difusao_em=CLINICA_A, difusao_partner_ativo=False)

            _, partner_notify, _ = self._liberar(db, laudo, tmpdir)

            self.assertEqual(self._targets(db, laudo.id), set())
            self.assertEqual(partner_notify.call_count, 0)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_vinculo_com_interruptor_desligado_nao_difunde(self) -> None:
        """CA-010."""
        tmpdir, db, engine = self._build_session()
        try:
            laudo = self._seed(db, nomeado=False, difusao_em=CLINICA_A, difusao_ativa=False)

            _, partner_notify, _ = self._liberar(db, laudo, tmpdir)

            self.assertEqual(self._targets(db, laudo.id), set())
            self.assertEqual(partner_notify.call_count, 0)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_vinculo_em_outra_clinica_nao_alcanca_o_laudo(self) -> None:
        """CA-010 (contorno): o vinculo e por clinica, nao por veterinario."""
        tmpdir, db, engine = self._build_session()
        try:
            laudo = self._seed(db, nomeado=False, difusao_em=CLINICA_B)

            _, partner_notify, _ = self._liberar(db, laudo, tmpdir)

            self.assertEqual(self._targets(db, laudo.id), set())
            self.assertEqual(partner_notify.call_count, 0)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_laudo_sem_clinica_libera_somente_o_nomeado(self) -> None:
        """CA-011."""
        tmpdir, db, engine = self._build_session()
        try:
            laudo = self._seed(db, clinic_id=None, nomeado=True, difusao_em=CLINICA_A)

            _, partner_notify, _ = self._liberar(db, laudo, tmpdir)

            self.assertEqual(self._targets(db, laudo.id), {PARCEIRO_NOMEADO})
            self.assertEqual(partner_notify.call_count, 1)
            self.assertEqual(partner_notify.call_args.kwargs["partner_id"], PARCEIRO_NOMEADO)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    # --- aviso por WhatsApp --------------------------------------------------

    def _preparar_para_aviso(self, db, laudo, *, liberar_para: list[int]) -> Exame:
        laudo.status = PORTAL_RELEASED_STATUS
        exame = Exame(
            laudo_id=laudo.id,
            paciente_id=laudo.paciente_id,
            tipo_exame="Ecocardiograma",
            status=PORTAL_RELEASED_STATUS,
        )
        db.add(exame)
        db.flush()
        for partner_id in liberar_para:
            db.add(
                PortalPartnerReleaseTarget(
                    partner_id=partner_id,
                    exame_id=exame.id,
                    laudo_id=laudo.id,
                    permitir_download=True,
                    released_at=datetime(2026, 7, 4, 16, 0),
                    created_by_user_id=7,
                    contexto_json="{}",
                )
            )
        db.commit()
        db.refresh(laudo)
        return exame

    @staticmethod
    def _envio(destino_com_falha: str | None = None):
        def _send(**kwargs):
            if destino_com_falha and kwargs["destination"] == destino_com_falha:
                raise laudos.WhatsAppTemplateDeliveryError("Erro simulado da Graph API")
            return {"message_id": f"wamid.{kwargs['destination']}", "idempotent": False}

        return _send

    def _avisar(self, db, laudo, *, idempotency_key: str, destino_com_falha: str | None = None):
        payload = laudos.PortalReportWhatsAppRequest(idempotency_key=idempotency_key)
        with (
            patch.object(
                laudos,
                "send_approved_utility_template",
                side_effect=self._envio(destino_com_falha),
            ) as send_mock,
            patch.object(laudos, "registrar_auditoria", return_value=None) as audit_mock,
        ):
            resposta = laudos.avisar_laudo_liberado_por_whatsapp(
                laudo.id,
                payload,
                request=_make_request(),
                db=db,
                current_user=self._current_user(),
            )
        return resposta, send_mock, audit_mock

    def test_aviso_vai_para_clinica_nomeado_e_difusao(self) -> None:
        """CA-012, CA-015."""
        tmpdir, db, engine = self._build_session()
        try:
            laudo = self._seed(db, nomeado=True, difusao_em=CLINICA_A)
            self._preparar_para_aviso(db, laudo, liberar_para=[PARCEIRO_NOMEADO, PARCEIRO_DIFUSAO])

            resposta, send_mock, _ = self._avisar(db, laudo, idempotency_key="idem-difusao-001")

            self.assertEqual(send_mock.call_count, 3)
            envios = [call.kwargs for call in send_mock.call_args_list]
            self.assertEqual(
                [envio["destination"] for envio in envios],
                [CLINICA_WHATSAPP, NOMEADO_WHATSAPP, DIFUSAO_WHATSAPP],
            )
            self.assertEqual(
                [envio["parameters"][0] for envio in envios],
                ["Animal Care", "Dra Isadora Bastos", "Dra Carla Soares"],
            )
            self.assertEqual(
                [envio["idempotency_key"] for envio in envios],
                ["idem-difusao-001", "idem-difusao-001-vet", f"idem-difusao-001-vet{PARCEIRO_DIFUSAO}"],
            )
            for envio in envios:
                self.assertLessEqual(len(envio["idempotency_key"]), 128)

            db.refresh(laudo)
            self.assertEqual(laudo.whatsapp_parceiro_status, "enviado")
            self.assertIsNone(laudo.whatsapp_parceiro_erro)

            resumos = resposta["veterinarios_parceiros"]
            self.assertEqual(
                [(item["partner_id"], item["origem"], item["status"]) for item in resumos],
                [
                    (PARCEIRO_NOMEADO, "nomeado", "enviado"),
                    (PARCEIRO_DIFUSAO, "vinculo_clinica", "enviado"),
                ],
            )
            # O resumo singular continua sendo o do nomeado (contrato de #151).
            self.assertEqual(resposta["veterinario_parceiro"]["status"], "enviado")
            self.assertEqual(
                resposta["veterinario_parceiro"]["destination_suffix"],
                NOMEADO_WHATSAPP[-4:],
            )
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_difusao_sem_whatsapp_nao_impede_os_demais(self) -> None:
        """CA-013."""
        tmpdir, db, engine = self._build_session()
        try:
            laudo = self._seed(db, nomeado=True, difusao_em=CLINICA_A, difusao_whatsapp=None)
            self._preparar_para_aviso(db, laudo, liberar_para=[PARCEIRO_NOMEADO, PARCEIRO_DIFUSAO])

            resposta, send_mock, _ = self._avisar(db, laudo, idempotency_key="idem-difusao-002")

            self.assertEqual(send_mock.call_count, 2)
            self.assertEqual(
                [call.kwargs["destination"] for call in send_mock.call_args_list],
                [CLINICA_WHATSAPP, NOMEADO_WHATSAPP],
            )
            difusao = next(
                item for item in resposta["veterinarios_parceiros"] if item["partner_id"] == PARCEIRO_DIFUSAO
            )
            self.assertEqual(difusao["status"], "ignorado")
            self.assertEqual(difusao["motivo"], "sem_whatsapp")

            db.refresh(laudo)
            self.assertEqual(laudo.whatsapp_parceiro_status, "enviado")
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_falha_na_difusao_mantem_200_e_resume_como_falhou(self) -> None:
        """CA-014."""
        tmpdir, db, engine = self._build_session()
        try:
            laudo = self._seed(db, nomeado=True, difusao_em=CLINICA_A)
            self._preparar_para_aviso(db, laudo, liberar_para=[PARCEIRO_NOMEADO, PARCEIRO_DIFUSAO])

            resposta, send_mock, _ = self._avisar(
                db,
                laudo,
                idempotency_key="idem-difusao-003",
                destino_com_falha=DIFUSAO_WHATSAPP,
            )

            # O envio ao nomeado aconteceu apesar da falha do outro.
            self.assertEqual(send_mock.call_count, 3)
            resumos = {item["partner_id"]: item for item in resposta["veterinarios_parceiros"]}
            self.assertEqual(resumos[PARCEIRO_NOMEADO]["status"], "enviado")
            self.assertEqual(resumos[PARCEIRO_DIFUSAO]["status"], "falhou")
            self.assertIn("Erro simulado", resumos[PARCEIRO_DIFUSAO]["erro"])

            db.refresh(laudo)
            self.assertEqual(laudo.whatsapp_parceiro_status, "falhou")
            self.assertIn("Erro simulado", laudo.whatsapp_parceiro_erro)
            # O resumo singular do nomeado continua contando o sucesso dele.
            self.assertEqual(resposta["veterinario_parceiro"]["status"], "enviado")
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_difusao_nao_liberada_no_portal_nao_recebe_aviso(self) -> None:
        """NFR-002: o aviso segue o target explicito, nao o vinculo."""
        tmpdir, db, engine = self._build_session()
        try:
            laudo = self._seed(db, nomeado=True, difusao_em=CLINICA_A)
            self._preparar_para_aviso(db, laudo, liberar_para=[PARCEIRO_NOMEADO])

            resposta, send_mock, _ = self._avisar(db, laudo, idempotency_key="idem-difusao-004")

            self.assertEqual(send_mock.call_count, 2)
            difusao = next(
                item for item in resposta["veterinarios_parceiros"] if item["partner_id"] == PARCEIRO_DIFUSAO
            )
            self.assertEqual(difusao["status"], "ignorado")
            self.assertEqual(difusao["motivo"], "nao_liberado")
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    # --- estado do laudo visto pela tela -------------------------------------

    def test_estado_do_laudo_mostra_o_veterinario_que_entrou_por_vinculo(self) -> None:
        """O laudo liberado so por difusao precisa se declarar com destino veterinario.

        Sem isso a Central de laudos anuncia "Avisar clinica" e o backend manda
        WhatsApp tambem para o veterinario — o dialogo nomeia um destinatario e o
        envio vai para dois.
        """
        tmpdir, db, engine = self._build_session()
        try:
            laudo = self._seed(db, nomeado=False, difusao_em=CLINICA_A)
            self._liberar(db, laudo, tmpdir)

            db.refresh(laudo)
            estado = laudos._serialize_portal_release_state(db, laudo=laudo)

            self.assertTrue(estado["portal_veterinario_disponivel"])
            self.assertTrue(estado["portal_veterinario_liberado"])
            self.assertEqual(
                estado["portal_veterinarios_destinos"],
                [
                    {
                        "partner_id": PARCEIRO_DIFUSAO,
                        "nome": "Dra Carla Soares",
                        "origem": "vinculo_clinica",
                        "liberado": True,
                    }
                ],
            )
            self.assertEqual(estado["portal_destinos_pendentes"], [])
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_estado_lista_nomeado_e_difusao_na_ordem_do_envio(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            laudo = self._seed(db, nomeado=True, difusao_em=CLINICA_A)
            self._liberar(db, laudo, tmpdir)

            db.refresh(laudo)
            estado = laudos._serialize_portal_release_state(db, laudo=laudo)

            self.assertEqual(
                [(d["partner_id"], d["origem"], d["liberado"]) for d in estado["portal_veterinarios_destinos"]],
                [
                    (PARCEIRO_NOMEADO, "nomeado", True),
                    (PARCEIRO_DIFUSAO, "vinculo_clinica", True),
                ],
            )
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_vinculo_sem_liberacao_aparece_como_pendente_e_nao_liberado(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            laudo = self._seed(db, nomeado=False, difusao_em=CLINICA_A)
            # Sem liberar: o vinculo existe, o target nao.
            estado = laudos._serialize_portal_release_state(db, laudo=laudo)

            self.assertTrue(estado["portal_veterinario_disponivel"])
            self.assertFalse(estado["portal_veterinario_liberado"])
            self.assertIn("veterinario_parceiro", estado["portal_destinos_pendentes"])
            self.assertEqual(
                [d["liberado"] for d in estado["portal_veterinarios_destinos"]],
                [False],
            )
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_laudo_sem_veterinario_nenhum_continua_sem_destino_veterinario(self) -> None:
        """Contrato antigo: laudo so de clinica nao inventa destino veterinario."""
        tmpdir, db, engine = self._build_session()
        try:
            laudo = self._seed(db, nomeado=False, difusao_em=None)
            self._liberar(db, laudo, tmpdir)

            db.refresh(laudo)
            estado = laudos._serialize_portal_release_state(db, laudo=laudo)

            self.assertFalse(estado["portal_veterinario_disponivel"])
            self.assertFalse(estado["portal_veterinario_liberado"])
            self.assertEqual(estado["portal_veterinarios_destinos"], [])
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
