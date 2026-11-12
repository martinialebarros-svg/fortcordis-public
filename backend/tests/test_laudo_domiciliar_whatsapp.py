import os
import tempfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException, Request
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("DATABASE_URL", "sqlite:///./test-laudo-domiciliar-whatsapp.db")
os.environ.setdefault("SECRET_KEY", "laudo-domiciliar-whatsapp-test-secret-key-1234567890")

from app.api.v1.endpoints import laudos
from app.models.agendamento import Agendamento
from app.models.clinica import Clinica
from app.models.laudo import Exame, Laudo
from app.models.paciente import Paciente
from app.models.portal_partner import PortalPartnerProfile
from app.models.tutor import Tutor


def _db_with(laudo, agendamento=None, paciente=None, tutor=None):
    db = MagicMock()
    db.query.return_value.filter.return_value.first.side_effect = [laudo, agendamento, paciente, tutor]
    return db


def _send(db):
    return laudos.enviar_laudo_domiciliar_ao_tutor(
        7,
        laudos.PortalReportWhatsAppRequest(idempotency_key="chave-teste-123"),
        Request({"type": "http", "headers": []}),
        db=db,
        current_user=SimpleNamespace(id=4),
    )


def test_recusa_agendamento_nao_domiciliar():
    db = _db_with(
        SimpleNamespace(id=7, status="Finalizado", agendamento_id=3),
        SimpleNamespace(origem_atendimento="clinica_parceira"),
    )
    with pytest.raises(HTTPException) as error:
        _send(db)
    assert error.value.status_code == 409


def test_recusa_tutor_diferente_do_agendamento():
    db = _db_with(
        SimpleNamespace(id=7, status="Finalizado", agendamento_id=3, paciente_id=2),
        SimpleNamespace(origem_atendimento="domiciliar", tutor_id=6),
        SimpleNamespace(tutor_id=5),
    )
    with pytest.raises(HTTPException) as error:
        _send(db)
    assert error.value.status_code == 409


def test_envia_pdf_gerado_ao_numero_cadastrado_do_tutor():
    db = _db_with(
        SimpleNamespace(id=7, status="Finalizado", agendamento_id=3, paciente_id=2, anexos=None),
        SimpleNamespace(origem_atendimento="domiciliar", tutor_id=5),
        SimpleNamespace(tutor_id=5, nome="Pet teste"),
        SimpleNamespace(whatsapp="(85) 99999-1234", nome="Tutor teste"),
    )
    with patch.object(laudos, "render_laudo_pdf", return_value=SimpleNamespace(content=b"%PDF-test", filename="laudo.pdf")), \
         patch.object(laudos, "send_report_pdf_in_customer_window", return_value={"message_id": "wamid.1"}) as send, \
         patch.object(laudos, "registrar_auditoria"):
        assert _send(db)["message_id"] == "wamid.1"
    assert send.call_args.kwargs["destination"] == "5585999991234"
    assert send.call_args.kwargs["document_bytes"] == b"%PDF-test"


def test_servico_recusa_pdf_invalido_antes_da_rede():
    from app.services.whatsapp_template_delivery_service import send_report_pdf_in_customer_window, WhatsAppTemplateDeliveryError
    with patch("app.services.whatsapp_template_delivery_service.settings") as settings:
        settings.WHATSAPP_AGENDA_ENABLED = True
        settings.WHATSAPP_AGENDA_INTERNAL_TOKEN = "test-token"
        settings.WHATSAPP_AGENDA_SERVICE_URL = "http://localhost"
        with pytest.raises(WhatsAppTemplateDeliveryError):
            send_report_pdf_in_customer_window(laudo_id=7, destination="5585999991234",
                idempotency_key="chave-teste-123", document_bytes=b"nao e pdf", filename="laudo.pdf")


def test_servico_distingue_janela_fechada_de_outro_conflito():
    from app.services.whatsapp_template_delivery_service import (
        WhatsAppCustomerWindowClosed, send_report_pdf_in_customer_window,
    )
    with patch("app.services.whatsapp_template_delivery_service.settings") as settings, \
         patch("app.services.whatsapp_template_delivery_service.httpx.post") as post:
        settings.WHATSAPP_AGENDA_ENABLED = True
        settings.WHATSAPP_AGENDA_INTERNAL_TOKEN = "test-token"
        settings.WHATSAPP_AGENDA_SERVICE_URL = "http://localhost"
        post.return_value = SimpleNamespace(status_code=409, json=lambda: {
            "code": "CUSTOMER_WINDOW_CLOSED", "error": "Janela fechada"
        })
        with pytest.raises(WhatsAppCustomerWindowClosed):
            send_report_pdf_in_customer_window(laudo_id=7, destination="5585999991234",
                idempotency_key="chave-teste-123", document_bytes=b"%PDF-test", filename="laudo.pdf")
        post.return_value = SimpleNamespace(status_code=409, json=lambda: {"error": "Envio incerto"})
        with pytest.raises(HTTPException) as error:
            send_report_pdf_in_customer_window(laudo_id=7, destination="5585999991234",
                idempotency_key="chave-teste-123", document_bytes=b"%PDF-test", filename="laudo.pdf")
        assert error.value.status_code == 409


def test_lista_identifica_apenas_laudo_com_agendamento_domiciliar():
    with tempfile.TemporaryDirectory() as directory:
        engine = create_engine(f"sqlite:///{Path(directory) / 'laudos.db'}")
        for table in (Tutor.__table__, Paciente.__table__, Clinica.__table__, Laudo.__table__,
                      Exame.__table__, PortalPartnerProfile.__table__, Agendamento.__table__):
            table.create(engine, checkfirst=True)
        db = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
        try:
            tutor = Tutor(nome="Tutor teste", whatsapp="85999991234", ativo=1)
            db.add(tutor)
            db.flush()
            paciente = Paciente(nome="Paciente teste", especie="Canina", tutor_id=tutor.id, ativo=1)
            db.add(paciente)
            db.flush()
            domiciliar = Agendamento(paciente_id=paciente.id, tutor_id=tutor.id,
                origem_atendimento="domiciliar", inicio=datetime(2026, 9, 20, 10))
            clinica = Agendamento(paciente_id=paciente.id, tutor_id=tutor.id,
                origem_atendimento="clinica_parceira", inicio=datetime(2026, 9, 21, 10))
            db.add_all([domiciliar, clinica])
            db.flush()
            db.add_all([
                Laudo(paciente_id=paciente.id, veterinario_id=4, agendamento_id=domiciliar.id,
                    tipo="ecocardiograma", titulo="Domiciliar", status="Finalizado"),
                Laudo(paciente_id=paciente.id, veterinario_id=4, agendamento_id=clinica.id,
                    tipo="ecocardiograma", titulo="Clinica", status="Finalizado"),
            ])
            db.commit()
            items = laudos.listar_laudos(db=db, current_user=SimpleNamespace(id=4))["items"]
            assert {item["titulo"]: item["atendimento_domiciliar"] for item in items} == {
                "Domiciliar": True, "Clinica": False,
            }
        finally:
            db.close()
            engine.dispose()


def test_envia_pdf_externo_original_sem_renderizar(tmp_path):
    original = tmp_path / "original.pdf"
    original.write_bytes(b"%PDF-original")
    db = _db_with(
        SimpleNamespace(id=7, status="Finalizado", agendamento_id=3, paciente_id=2, anexos="external"),
        SimpleNamespace(origem_atendimento="domiciliar", tutor_id=5),
        SimpleNamespace(tutor_id=5, nome="Pet teste"),
        SimpleNamespace(whatsapp="85999991234", nome="Tutor teste"),
    )
    with patch.object(laudos, "_extrair_pdf_externo_laudo", return_value={"anexo_id": 10}), \
         patch.object(laudos, "_buscar_anexo_pdf_externo_laudo", return_value=SimpleNamespace(caminho_arquivo=str(original))), \
         patch.object(laudos, "render_laudo_pdf") as render, \
         patch.object(laudos, "send_report_pdf_in_customer_window", return_value={"message_id": "wamid.2"}) as send, \
         patch.object(laudos, "registrar_auditoria"):
        assert _send(db)["message_id"] == "wamid.2"
    render.assert_not_called()
    assert send.call_args.kwargs["document_bytes"] == b"%PDF-original"


def test_janela_fechada_usa_modelo_de_documento_para_o_tutor():
    from app.services.whatsapp_template_delivery_service import WhatsAppCustomerWindowClosed

    db = _db_with(
        SimpleNamespace(id=7, status="Finalizado", agendamento_id=3, paciente_id=2, anexos=None),
        SimpleNamespace(origem_atendimento="domiciliar", tutor_id=5),
        SimpleNamespace(tutor_id=5, nome="Pet teste"),
        SimpleNamespace(whatsapp="85999991234", nome="Tutor teste"),
    )
    with patch.object(laudos, "render_laudo_pdf", return_value=SimpleNamespace(content=b"%PDF-test", filename="laudo.pdf")), \
         patch.object(laudos, "send_report_pdf_in_customer_window", side_effect=WhatsAppCustomerWindowClosed("fechada")), \
         patch.object(laudos, "send_approved_document_template", return_value={"message_id": "wamid.template"}) as send, \
         patch.object(laudos, "registrar_auditoria") as audit:
        assert _send(db)["message_id"] == "wamid.template"
    assert send.call_args.kwargs["template_key"] == "homeReportPdf"
    assert send.call_args.kwargs["subject_type"] == "laudo"
    assert send.call_args.kwargs["parameters"] == ["Tutor teste", "Pet teste"]
    assert audit.call_args.kwargs["detalhes"]["delivery_mode"] == "modelo_aprovado"


def test_falha_ou_envio_incerto_na_janela_nao_dispara_modelo():
    db = _db_with(
        SimpleNamespace(id=7, status="Finalizado", agendamento_id=3, paciente_id=2, anexos=None),
        SimpleNamespace(origem_atendimento="domiciliar", tutor_id=5),
        SimpleNamespace(tutor_id=5, nome="Pet teste"),
        SimpleNamespace(whatsapp="85999991234", nome="Tutor teste"),
    )
    with patch.object(laudos, "render_laudo_pdf", return_value=SimpleNamespace(content=b"%PDF-test", filename="laudo.pdf")), \
         patch.object(laudos, "send_report_pdf_in_customer_window", side_effect=HTTPException(status_code=409, detail="Envio incerto")), \
         patch.object(laudos, "send_approved_document_template") as send:
        with pytest.raises(HTTPException) as error:
            _send(db)
    assert error.value.status_code == 409
    send.assert_not_called()
