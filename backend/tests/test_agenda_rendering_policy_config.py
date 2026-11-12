import unittest

from app.core.agenda_route_rules import (
    DEFAULT_AGENDA_ROTA_REGRAS,
    normalizar_agenda_rota_regras,
)


class AgendaRenderingPolicyConfigTest(unittest.TestCase):
    def test_normaliza_rendering_policy_padrao(self) -> None:
        regras = normalizar_agenda_rota_regras(None)
        rendering = regras["rendering_policy"]

        self.assertEqual(rendering["use_custom_window"], DEFAULT_AGENDA_ROTA_REGRAS["rendering_policy"]["use_custom_window"])
        self.assertEqual(rendering["window_start"], DEFAULT_AGENDA_ROTA_REGRAS["rendering_policy"]["window_start"])
        self.assertEqual(rendering["window_end"], DEFAULT_AGENDA_ROTA_REGRAS["rendering_policy"]["window_end"])
        self.assertEqual(rendering["slot_interval_min"], DEFAULT_AGENDA_ROTA_REGRAS["rendering_policy"]["slot_interval_min"])

    def test_window_invalida_retorna_default(self) -> None:
        regras = normalizar_agenda_rota_regras(
            {
                "rendering_policy": {
                    "use_custom_window": True,
                    "window_start": "18:00",
                    "window_end": "08:00",
                    "slot_interval_min": 20,
                }
            }
        )

        rendering = regras["rendering_policy"]
        self.assertTrue(rendering["use_custom_window"])
        self.assertEqual(rendering["window_start"], DEFAULT_AGENDA_ROTA_REGRAS["rendering_policy"]["window_start"])
        self.assertEqual(rendering["window_end"], DEFAULT_AGENDA_ROTA_REGRAS["rendering_policy"]["window_end"])
        self.assertEqual(rendering["slot_interval_min"], 20)

    def test_slot_interval_min_respeita_limites(self) -> None:
        regras_min = normalizar_agenda_rota_regras({"rendering_policy": {"slot_interval_min": 1}})
        regras_max = normalizar_agenda_rota_regras({"rendering_policy": {"slot_interval_min": 999}})

        self.assertEqual(regras_min["rendering_policy"]["slot_interval_min"], 5)
        self.assertEqual(regras_max["rendering_policy"]["slot_interval_min"], 120)


if __name__ == "__main__":
    unittest.main()
