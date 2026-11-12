import os
import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

from app.services.whatsapp_bot_context import build_safe_context


class WhatsAppBotSafeContextTest(unittest.TestCase):
    def test_tutor_nao_recebe_pet_cruzado_por_tutor_id_inconsistente(self) -> None:
        contexto = {
            "resolution": "matched",
            "pets": [
                {"id": 10, "tutor_id": 1, "nome": "Thor", "especie": "Canina"},
                {"id": 20, "tutor_id": 2, "nome": "Pet de outra pessoa", "especie": "Felina"},
            ],
            "agendamentos": [
                {
                    "tutor_id": 1,
                    "pet_id": 10,
                    "pet_nome": "Thor",
                    "servico_nome": "Eco",
                    "status": "Agendado",
                },
                {
                    # Cadastro inconsistente: tutor certo, pet de terceiro.
                    "tutor_id": 1,
                    "pet_id": 20,
                    "pet_nome": "Pet de outra pessoa",
                    "servico_nome": "Eco",
                    "status": "Agendado",
                },
                {
                    # Agendamento legado sem paciente ainda pode pertencer ao tutor.
                    "tutor_id": 1,
                    "pet_id": None,
                    "pet_nome": None,
                    "servico_nome": "Retorno",
                    "status": "Confirmado",
                },
            ],
        }

        seguro = build_safe_context(
            contexto, match_type="tutor", tutor_id=1, clinica_id=None
        )

        self.assertEqual([pet["nome"] for pet in seguro["pets"]], ["Thor"])
        nomes = [item.get("pet_nome") for item in seguro["agendamentos_ativos"]]
        self.assertEqual(nomes, ["Thor", None])
        self.assertNotIn("Pet de outra pessoa", str(seguro))

    def test_clinica_recebe_somente_agendamentos_do_proprio_escopo(self) -> None:
        contexto = {
            "resolution": "matched",
            "clinicas": [
                {"id": 7, "nome": "Clinica Sete"},
                {"id": 8, "nome": "Clinica Oito"},
            ],
            "agendamentos": [
                {"clinica_id": 7, "servico_nome": "Eco", "status": "Reservado"},
                {"clinica_id": 8, "servico_nome": "Holter", "status": "Agendado"},
                {"clinica_id": 7, "servico_nome": "Cancelado", "status": "Cancelado"},
            ],
        }

        seguro = build_safe_context(
            contexto, match_type="clinica", tutor_id=None, clinica_id=7
        )

        self.assertEqual(seguro["clinica_nome"], "Clinica Sete")
        self.assertEqual(
            [item["servico_nome"] for item in seguro["agendamentos_ativos"]], ["Eco"]
        )
        self.assertNotIn("Clinica Oito", str(seguro))
        self.assertNotIn("Holter", str(seguro))


if __name__ == "__main__":
    unittest.main()
