import asyncio
import io
import json
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from starlette.datastructures import Headers, UploadFile

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "atendimento-upload-endpoint-test-secret-key-1234567890")

from app.api.v1.endpoints import atendimento
from app.core.portal_release import PORTAL_RELEASED_STATUS
from app.services.atendimento_upload_service import AttachmentTooLargeError, AttachmentTypeError


class _FakeQuery:
    def __init__(self, result):
        self._result = result

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return self._result


class _FakeDB:
    def __init__(self, *, atendimento_exists: bool = True, existing_anexo_sequence=None):
        self._atendimento = SimpleNamespace(id=1) if atendimento_exists else None
        self._exame = None
        self._anexo_query_results = list(existing_anexo_sequence or [])
        self._last_anexo_result = self._anexo_query_results[-1] if self._anexo_query_results else None
        self.added = []
        self.commit_count = 0
        self.rollback_count = 0

    def query(self, model):
        model_name = getattr(model, "__name__", "")
        if model_name == "AtendimentoClinico":
            return _FakeQuery(self._atendimento)
        if model_name == "Exame":
            return _FakeQuery(self._exame)
        if model_name == "AnexoAtendimento":
            if self._anexo_query_results:
                result = self._anexo_query_results.pop(0)
                self._last_anexo_result = result
                return _FakeQuery(result)
            return _FakeQuery(self._last_anexo_result)
        return _FakeQuery(None)

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        if self.added and getattr(self.added[-1], "id", None) is None:
            self.added[-1].id = 123

    def commit(self):
        self.commit_count += 1

    def refresh(self, obj):
        return None

    def rollback(self):
        self.rollback_count += 1


def _make_upload_file(filename: str, content_type: str, content: bytes) -> UploadFile:
    headers = Headers({"content-type": content_type})
    return UploadFile(
        io.BytesIO(content),
        filename=filename,
        headers=headers,
        size=len(content),
    )


class AtendimentoUploadEndpointTest(unittest.TestCase):
    def setUp(self) -> None:
        self.user = SimpleNamespace(id=99, nome="Teste Upload")

    def test_upload_anexo_returns_201_payload_when_storage_succeeds(self) -> None:
        db = _FakeDB()
        arquivo = _make_upload_file("resultado.pdf", "application/pdf", b"conteudo-ok")

        with patch.object(
            atendimento,
            "store_atendimento_attachment_file",
            return_value=("C:/tmp/anexo.pdf", "resultado.pdf", "application/pdf"),
        ) as store_mock:
            payload = asyncio.run(
                atendimento.upload_anexo(
                    atendimento_id=1,
                    arquivo=arquivo,
                    tipo="documento",
                    descricao="Arquivo de resultado",
                    exame_id=None,
                    evolucao_id=None,
                    db=db,
                    current_user=self.user,
                )
            )

        self.assertEqual(store_mock.call_count, 1)
        self.assertEqual(db.commit_count, 1)
        self.assertEqual(len(db.added), 1)
        self.assertEqual(payload["nome_original"], "resultado.pdf")
        self.assertEqual(payload["mime_type"], "application/pdf")
        self.assertFalse(payload["deduplicado"])

    def test_upload_anexo_returns_200_existing_attachment_when_hash_matches(self) -> None:
        existing_anexo = SimpleNamespace(
            id=7,
            atendimento_id=1,
            exame_id=None,
            evolucao_id=None,
            tipo="documento",
            descricao="ja existente",
            url="/api/v1/atendimentos/anexos/7/arquivo",
            nome_original="resultado.pdf",
            tamanho=12,
            mime_type="application/pdf",
            arquivo_hash="hash-duplicado",
            caminho_arquivo="C:/tmp/existente.pdf",
            origem="upload",
            created_at=None,
        )
        db = _FakeDB(existing_anexo_sequence=[existing_anexo])
        arquivo = _make_upload_file("resultado.pdf", "application/pdf", b"conteudo-ok")

        with patch.object(atendimento, "calculate_attachment_sha256", return_value="hash-duplicado"), patch.object(
            atendimento,
            "store_atendimento_attachment_file",
        ) as store_mock:
            response = asyncio.run(
                atendimento.upload_anexo(
                    atendimento_id=1,
                    arquivo=arquivo,
                    tipo="documento",
                    descricao="Arquivo duplicado",
                    exame_id=None,
                    evolucao_id=None,
                    db=db,
                    current_user=self.user,
                )
            )

        self.assertEqual(response.status_code, 200)
        body = json.loads(response.body.decode("utf-8"))
        self.assertEqual(body["id"], 7)
        self.assertTrue(body["deduplicado"])
        self.assertEqual(store_mock.call_count, 0)
        self.assertEqual(db.commit_count, 0)

    def test_upload_anexo_handles_integrity_error_as_dedupe_response(self) -> None:
        existing_anexo = SimpleNamespace(
            id=11,
            atendimento_id=1,
            exame_id=None,
            evolucao_id=None,
            tipo="documento",
            descricao="concorrente",
            url="/api/v1/atendimentos/anexos/11/arquivo",
            nome_original="resultado.pdf",
            tamanho=12,
            mime_type="application/pdf",
            arquivo_hash="hash-duplicado",
            dedupe_key="exame:none|sha256:hash-duplicado",
            caminho_arquivo="C:/tmp/existente.pdf",
            origem="upload",
            created_at=None,
        )
        db = _FakeDB(existing_anexo_sequence=[None, existing_anexo])
        arquivo = _make_upload_file("resultado.pdf", "application/pdf", b"conteudo-ok")

        with patch.object(atendimento, "calculate_attachment_sha256", return_value="hash-duplicado"), patch.object(
            atendimento,
            "store_atendimento_attachment_file",
            return_value=("C:/tmp/novo.pdf", "resultado.pdf", "application/pdf"),
        ) as store_mock, patch.object(
            atendimento, "remove_atendimento_attachment_file"
        ) as remove_mock, patch.object(
            db,
            "flush",
            side_effect=IntegrityError("INSERT", {"id": 1}, Exception("duplicate key")),
        ):
            response = asyncio.run(
                atendimento.upload_anexo(
                    atendimento_id=1,
                    arquivo=arquivo,
                    tipo="documento",
                    descricao="Arquivo concorrente",
                    exame_id=None,
                    evolucao_id=None,
                    db=db,
                    current_user=self.user,
                )
            )

        self.assertEqual(response.status_code, 200)
        body = json.loads(response.body.decode("utf-8"))
        self.assertTrue(body["deduplicado"])
        self.assertEqual(body["id"], 11)
        self.assertEqual(store_mock.call_count, 1)
        remove_mock.assert_called_once_with("C:/tmp/novo.pdf")
        self.assertEqual(db.rollback_count, 1)
        self.assertEqual(db.commit_count, 0)

    def test_upload_anexo_maps_type_error_to_400(self) -> None:
        db = _FakeDB()
        arquivo = _make_upload_file("resultado.exe", "application/octet-stream", b"fake")

        with patch.object(
            atendimento,
            "store_atendimento_attachment_file",
            side_effect=AttachmentTypeError("Tipo de arquivo nao permitido."),
        ):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(
                    atendimento.upload_anexo(
                        atendimento_id=1,
                        arquivo=arquivo,
                        tipo="documento",
                        descricao="Arquivo invalido",
                        exame_id=None,
                        evolucao_id=None,
                        db=db,
                        current_user=self.user,
                    )
                )

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("Tipo de arquivo", str(ctx.exception.detail))
        self.assertEqual(db.commit_count, 0)

    def test_upload_anexo_maps_size_error_to_413(self) -> None:
        db = _FakeDB()
        arquivo = _make_upload_file("resultado.pdf", "application/pdf", b"x" * 16)

        with patch.object(
            atendimento,
            "store_atendimento_attachment_file",
            side_effect=AttachmentTooLargeError("Arquivo excede o limite de 25MB"),
        ):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(
                    atendimento.upload_anexo(
                        atendimento_id=1,
                        arquivo=arquivo,
                        tipo="documento",
                        descricao="Arquivo grande",
                        exame_id=None,
                        evolucao_id=None,
                        db=db,
                        current_user=self.user,
                    )
                )

        self.assertEqual(ctx.exception.status_code, 413)
        self.assertIn("25MB", str(ctx.exception.detail))
        self.assertEqual(db.commit_count, 0)

    def test_upload_anexo_rejects_empty_file_before_storage(self) -> None:
        db = _FakeDB()
        arquivo = _make_upload_file("vazio.pdf", "application/pdf", b"")

        with patch.object(atendimento, "store_atendimento_attachment_file") as store_mock:
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(
                    atendimento.upload_anexo(
                        atendimento_id=1,
                        arquivo=arquivo,
                        tipo="documento",
                        descricao="",
                        exame_id=None,
                        evolucao_id=None,
                        db=db,
                        current_user=self.user,
                    )
                )

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("Arquivo vazio", str(ctx.exception.detail))
        self.assertEqual(store_mock.call_count, 0)

    def _upload_para_exame(self, exame) -> None:
        db = _FakeDB()
        db._exame = exame
        arquivo = _make_upload_file("segundo-resultado.pdf", "application/pdf", b"conteudo-novo")

        with patch.object(
            atendimento,
            "store_atendimento_attachment_file",
            return_value=("C:/tmp/segundo.pdf", "segundo-resultado.pdf", "application/pdf"),
        ):
            asyncio.run(
                atendimento.upload_anexo(
                    atendimento_id=1,
                    arquivo=arquivo,
                    tipo="documento",
                    descricao="Segundo arquivo do exame",
                    exame_id=exame.id,
                    evolucao_id=None,
                    db=db,
                    current_user=self.user,
                )
            )

    def test_upload_anexo_preserves_portal_released_exam_status(self) -> None:
        """Anexar um segundo arquivo nao pode retirar o exame do portal."""
        exame = SimpleNamespace(
            id=5,
            atendimento_id=1,
            status=PORTAL_RELEASED_STATUS,
            data_resultado="2026-07-31T10:00:00",
        )

        self._upload_para_exame(exame)

        self.assertEqual(exame.status, PORTAL_RELEASED_STATUS)

    def test_upload_anexo_still_promotes_pending_exam_to_in_progress(self) -> None:
        exame = SimpleNamespace(id=6, atendimento_id=1, status="Solicitado", data_resultado=None)

        self._upload_para_exame(exame)

        self.assertEqual(exame.status, "Em andamento")

    def test_upload_anexo_does_not_downgrade_concluded_exam(self) -> None:
        exame = SimpleNamespace(
            id=7,
            atendimento_id=1,
            status="Concluido",
            data_resultado="2026-07-31T10:00:00",
        )

        self._upload_para_exame(exame)

        self.assertEqual(exame.status, "Concluido")


if __name__ == "__main__":
    unittest.main()
