import os
import sys
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from pypdf import PdfReader

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "whatsapp-template-test-secret-key-1234567890")

from app.api.v1.endpoints.ordens_servico import (
    _detalhe_cobranca_agrupada,
    _gerar_pdf_recibos_ordens,
    _numeros_comuns_contextos_whatsapp,
    _numeros_whatsapp_os,
    _parametros_cobranca_individual,
)
from app.core.config import settings
from app.services.whatsapp_template_delivery_service import (
    WhatsAppTemplateDeliveryError,
    send_approved_document_template,
    send_approved_utility_template,
)


class WhatsAppTemplateDeliveryTest(unittest.TestCase):
    def test_generic_delivery_uses_authenticated_internal_contract(self):
        response = SimpleNamespace(
            status_code=201,
            json=lambda: {"message_id": "wamid.receipt.contract", "idempotent": False},
        )
        with (
            patch.object(settings, "WHATSAPP_AGENDA_ENABLED", True),
            patch.object(settings, "WHATSAPP_AGENDA_SERVICE_URL", "http://127.0.0.1:3010"),
            patch.object(settings, "WHATSAPP_AGENDA_INTERNAL_TOKEN", "internal-secret"),
            patch("app.services.whatsapp_template_delivery_service.httpx.post", return_value=response) as post,
        ):
            result = send_approved_utility_template(
                template_key="receiptAvailable",
                subject_type="ordem_servico",
                subject_id=51,
                destination="5585988881111",
                parameters=["Animal Care", "OS-51", "Gamora", "R$ 350,00"],
                idempotency_key="receipt-idempotency-51",
            )

        self.assertEqual(result["message_id"], "wamid.receipt.contract")
        kwargs = post.call_args.kwargs
        self.assertEqual(kwargs["headers"]["X-WhatsApp-Internal-Token"], "internal-secret")
        self.assertEqual(kwargs["json"]["template_key"], "receiptAvailable")
        self.assertEqual(kwargs["json"]["subject_type"], "ordem_servico")
        self.assertEqual(kwargs["json"]["parameters"][3], "R$ 350,00")

    def test_generic_delivery_fails_closed_without_message_id(self):
        response = SimpleNamespace(status_code=201, json=lambda: {"idempotent": False})
        with (
            patch.object(settings, "WHATSAPP_AGENDA_ENABLED", True),
            patch.object(settings, "WHATSAPP_AGENDA_SERVICE_URL", "http://127.0.0.1:3010"),
            patch.object(settings, "WHATSAPP_AGENDA_INTERNAL_TOKEN", "internal-secret"),
            patch("app.services.whatsapp_template_delivery_service.httpx.post", return_value=response),
        ):
            with self.assertRaises(WhatsAppTemplateDeliveryError):
                send_approved_utility_template(
                    template_key="pendingPaymentReminder",
                    subject_type="ordem_servico",
                    subject_id=52,
                    destination="5585988881111",
                    parameters=[
                        "Animal Care",
                        "OS-52",
                        "Ecocardiograma",
                        "15/08/2026",
                        "Maria",
                        "Gamora",
                        "R$ 350,00",
                    ],
                    idempotency_key="payment-idempotency-52",
                )

    def test_finance_recipient_is_bound_to_registered_contact(self):
        clinic = SimpleNamespace(
            nome="Animal Care",
            whatsapps=["(85) 98888-1111", "5585877772222"],
            telefone="(85) 98888-1111",
        )
        partner_os = SimpleNamespace(origem_atendimento="clinica_parceira")
        name, numbers = _numeros_whatsapp_os(partner_os, clinica=clinic, tutor=None)
        self.assertEqual(name, "Animal Care")
        self.assertEqual(numbers, ["5585988881111", "5585877772222"])

        tutor = SimpleNamespace(nome="Maria", whatsapp="(85) 99999-3333", telefone=None)
        home_os = SimpleNamespace(origem_atendimento="domiciliar")
        name, numbers = _numeros_whatsapp_os(home_os, clinica=None, tutor=tutor)
        self.assertEqual(name, "Maria")
        self.assertEqual(numbers, ["5585999993333"])

        with self.assertRaises(HTTPException) as missing:
            _numeros_whatsapp_os(home_os, clinica=None, tutor=None)
        self.assertEqual(missing.exception.status_code, 409)

    def test_finance_charge_parameters_include_service_date_tutor_and_pet(self):
        contexto = {
            "os": SimpleNamespace(
                id=52,
                numero_os="OS-52",
                data_atendimento="2026-08-15T09:00:00",
                valor_final=350,
            ),
            "recipient_name": "Animal Care",
            "servico_nome": "Ecocardiograma",
            "tutor_nome": "Maria",
            "paciente_nome": "Gamora",
        }
        parametros = _parametros_cobranca_individual(contexto)
        self.assertEqual(
            parametros,
            [
                "Animal Care",
                "OS-52",
                "Ecocardiograma",
                "15/08/2026",
                "Maria",
                "Gamora",
                "R$ 350,00",
            ],
        )
        detalhe = _detalhe_cobranca_agrupada(contexto)
        self.assertIn("OS OS-52", detalhe)
        self.assertIn("15/08/2026", detalhe)
        self.assertIn("Ecocardiograma", detalhe)
        self.assertIn("Tutor: Maria", detalhe)
        self.assertIn("Pet: Gamora", detalhe)

    def test_grouped_finance_messages_require_same_recipient_and_common_number(self):
        contextos = [
            {
                "recipient_key": "clinica:7",
                "registered_numbers": ["5585988881111", "5585877772222"],
            },
            {
                "recipient_key": "clinica:7",
                "registered_numbers": ["5585988881111"],
            },
        ]
        self.assertEqual(
            _numeros_comuns_contextos_whatsapp(contextos),
            {"5585988881111"},
        )

        with self.assertRaises(HTTPException) as mixed_recipient:
            _numeros_comuns_contextos_whatsapp(
                [
                    contextos[0],
                    {
                        "recipient_key": "clinica:8",
                        "registered_numbers": ["5585988881111"],
                    },
                ]
            )
        self.assertEqual(mixed_recipient.exception.status_code, 409)

        with self.assertRaises(HTTPException) as no_common_number:
            _numeros_comuns_contextos_whatsapp(
                [
                    contextos[0],
                    {
                        "recipient_key": "clinica:7",
                        "registered_numbers": ["5585966663333"],
                    },
                ]
            )
        self.assertEqual(no_common_number.exception.status_code, 409)

    def test_document_delivery_uses_authenticated_multipart_contract(self):
        response = SimpleNamespace(
            status_code=201,
            json=lambda: {
                "message_id": "wamid.receipt.pdf",
                "media_id": "media.receipt.pdf",
                "idempotent": False,
            },
        )
        with (
            patch.object(settings, "WHATSAPP_AGENDA_ENABLED", True),
            patch.object(settings, "WHATSAPP_AGENDA_SERVICE_URL", "http://127.0.0.1:3010"),
            patch.object(settings, "WHATSAPP_AGENDA_INTERNAL_TOKEN", "internal-secret"),
            patch("app.services.whatsapp_template_delivery_service.httpx.post", return_value=response) as post,
        ):
            result = send_approved_document_template(
                template_key="receiptPdf",
                subject_id=52,
                subject_ids=[52],
                destination="5585988881111",
                parameters=[
                    "Animal Care",
                    "OS-52",
                    "Ecocardiograma",
                    "15/08/2026",
                    "Maria",
                    "Gamora",
                    "R$ 350,00",
                ],
                idempotency_key="receipt-pdf-idempotency-52",
                document_bytes=b"%PDF-1.4\nreceipt",
                filename="recibo_os_52.pdf",
            )

        self.assertEqual(result["media_id"], "media.receipt.pdf")
        kwargs = post.call_args.kwargs
        self.assertEqual(kwargs["headers"]["X-WhatsApp-Internal-Token"], "internal-secret")
        self.assertEqual(kwargs["data"]["template_key"], "receiptPdf")
        self.assertEqual(kwargs["data"]["subject_ids"], "[52]")
        self.assertEqual(kwargs["files"]["document"][2], "application/pdf")
        self.assertTrue(kwargs["files"]["document"][1].startswith(b"%PDF"))

    def test_consolidated_receipt_pdf_contains_os_date_service_tutor_and_pet(self):
        recibo = {
            "numero_os": "OS-52",
            "data_atendimento": "2026-08-15T09:00:00",
            "data_recebimento": "2026-08-16T10:00:00",
            "paciente": "Gamora",
            "tutor": "Maria",
            "clinica": "Animal Care",
            "servico": "Ecocardiograma",
            "valor_final": 350,
            "valor_credito_utilizado": 0,
            "pagamentos": [
                {
                    "forma_pagamento_nome": "PIX",
                    "data_recebimento": "2026-08-16T10:00:00",
                    "valor_bruto": 350,
                    "valor_taxa": 0,
                    "valor_liquido": 350,
                }
            ],
            "possui_detalhamento_legacy": False,
            "valor_taxa_total": 0,
            "valor_liquido_exibido": 350,
            "desconto": 0,
        }
        pdf = _gerar_pdf_recibos_ordens(
            recibos=[recibo],
            nome_empresa="Fort Cordis",
            contato_empresa="",
            texto_rodape="Fort Cordis",
            agrupar=True,
            nome_emitente="Financeiro",
            crmv_emitente="",
        )
        texto = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf)).pages)
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertIn("OS-52", texto)
        self.assertIn("15/08/2026", texto)
        self.assertIn("Ecocardiograma", texto)
        self.assertIn("Maria", texto)
        self.assertIn("Gamora", texto)

    def test_document_delivery_rejects_invalid_pdf_before_http(self):
        with (
            patch.object(settings, "WHATSAPP_AGENDA_ENABLED", True),
            patch.object(settings, "WHATSAPP_AGENDA_SERVICE_URL", "http://127.0.0.1:3010"),
            patch.object(settings, "WHATSAPP_AGENDA_INTERNAL_TOKEN", "internal-secret"),
            patch("app.services.whatsapp_template_delivery_service.httpx.post") as post,
        ):
            with self.assertRaises(WhatsAppTemplateDeliveryError):
                send_approved_document_template(
                    template_key="receiptPdf",
                    subject_id=52,
                    subject_ids=[52],
                    destination="5585988881111",
                    parameters=["a"] * 7,
                    idempotency_key="receipt-pdf-idempotency-invalid",
                    document_bytes=b"not-a-pdf",
                    filename="recibo.pdf",
                )
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
