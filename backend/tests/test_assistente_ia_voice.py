import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "assistente-ia-voice-test-secret-key-1234567890")

from app.models.clinica import Clinica
from app.services import assistente_ia_voice


class AssistenteIAVoiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self._tmpdir.name) / "assistente-ia-voice.db"
        self._engine = create_engine(f"sqlite:///{db_path}")
        self._session_factory = sessionmaker(bind=self._engine, autocommit=False, autoflush=False)
        Clinica.__table__.create(self._engine, checkfirst=True)
        self.user = SimpleNamespace(id=7, nome="Administrador")

    def tearDown(self) -> None:
        self._engine.dispose()
        self._tmpdir.cleanup()

    def test_transcreve_em_portugues_com_vocabulario_sem_persistir_audio(self) -> None:
        with self._session_factory() as db:
            db.add_all(
                [
                    Clinica(nome="Animal Care", ativo=True),
                    Clinica(nome="Vet World", ativo=True),
                ]
            )
            db.commit()
            create = SimpleNamespace(
                create=lambda **_kwargs: SimpleNamespace(
                    text="Verifique a disponibilidade na Vet World."
                )
            )
            client = SimpleNamespace(audio=SimpleNamespace(transcriptions=create))
            with (
                patch.object(assistente_ia_voice, "ensure_assistant_available"),
                patch.object(assistente_ia_voice, "OpenAI", return_value=client),
                patch.object(assistente_ia_voice, "registrar_auditoria") as audit,
            ):
                result = assistente_ia_voice.transcribe_voice_command(
                    db=db,
                    current_user=self.user,
                    request=SimpleNamespace(headers={}),
                    file_name="comando-voz.webm",
                    content_type="audio/webm;codecs=opus",
                    audio_bytes=b"audio-test",
                )

            self.assertEqual(result["transcript"], "Verifique a disponibilidade na Vet World.")
            self.assertTrue(result["requires_review"])
            self.assertFalse(result["audio_persisted"])
            audit.assert_called_once()
            self.assertFalse(audit.call_args.kwargs["detalhes"]["persistiu_audio"])
            self.assertFalse(audit.call_args.kwargs["detalhes"]["envio_automatico"])

    def test_envia_modelo_idioma_e_vocabulario_ao_provedor(self) -> None:
        with self._session_factory() as db:
            db.add(Clinica(nome="Animal Care", ativo=True))
            db.commit()
            create = Mock(return_value=SimpleNamespace(text="Comando reconhecido."))
            client = SimpleNamespace(audio=SimpleNamespace(transcriptions=SimpleNamespace(create=create)))
            with (
                patch.object(assistente_ia_voice, "ensure_assistant_available"),
                patch.object(assistente_ia_voice, "OpenAI", return_value=client),
                patch.object(assistente_ia_voice, "registrar_auditoria"),
            ):
                assistente_ia_voice.transcribe_voice_command(
                    db=db,
                    current_user=self.user,
                    request=None,
                    file_name="voz.webm",
                    content_type="audio/webm",
                    audio_bytes=b"audio-test",
                )

        payload = create.call_args.kwargs
        self.assertEqual(payload["language"], "pt")
        self.assertEqual(payload["response_format"], "json")
        self.assertEqual(payload["model"], "gpt-4o-transcribe")
        self.assertIn("Animal Care", payload["prompt"])
        self.assertEqual(payload["file"][0], "voz.webm")

    def test_rejeita_formato_e_tamanho_invalidos(self) -> None:
        with self._session_factory() as db:
            with (
                patch.object(assistente_ia_voice, "ensure_assistant_available"),
                self.assertRaises(HTTPException) as unsupported,
            ):
                assistente_ia_voice.transcribe_voice_command(
                    db=db,
                    current_user=self.user,
                    request=None,
                    file_name="voz.txt",
                    content_type="text/plain",
                    audio_bytes=b"audio",
                )
            self.assertEqual(unsupported.exception.status_code, 415)

            with (
                patch.object(assistente_ia_voice, "ensure_assistant_available"),
                patch.object(
                    assistente_ia_voice.settings,
                    "ASSISTENTE_IA_VOICE_MAX_BYTES",
                    3,
                ),
                self.assertRaises(HTTPException) as too_large,
            ):
                assistente_ia_voice.transcribe_voice_command(
                    db=db,
                    current_user=self.user,
                    request=None,
                    file_name="voz.webm",
                    content_type="audio/webm",
                    audio_bytes=b"audio",
                )
            self.assertEqual(too_large.exception.status_code, 413)


if __name__ == "__main__":
    unittest.main()
