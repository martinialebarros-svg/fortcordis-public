import unittest

from pydantic import ValidationError

from app.schemas.ai_echo import EchoStructureRequest


class EchoReferenceMethodSchemaTest(unittest.TestCase):
    def test_accepts_only_explicit_context_methods(self):
        for key, method in (
            ("TAPSE_metodo", "modo_m_apical"),
            ("TAPSE_metodo", "2d"),
            ("AE_Ao_metodo", "2d_eixo_curto_diastole_inicial"),
            ("AE_Ao_metodo", "2d_eixo_curto_diastole_inicial_sueco"),
            ("AE_Ao_metodo", "outro"),
            ("TAPSE_metodo", ""),
        ):
            with self.subTest(key=key, method=method):
                request = EchoStructureRequest.model_validate({
                    "edited_transcript": "Medidas do exame.",
                    "current_measurements": {key: method},
                })
                self.assertEqual(request.current_measurements[key], method)

        for key in ("TAPSE_metodo", "AE_Ao_metodo"):
            with self.subTest(invalid_key=key), self.assertRaises(ValidationError):
                EchoStructureRequest.model_validate({
                    "edited_transcript": "Medidas do exame.",
                    "current_measurements": {key: "inferido_do_valor"},
                })
