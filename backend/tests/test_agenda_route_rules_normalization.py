"""Regras operacionais permanecem estáveis ao carregar e salvar configurações."""

import json
import unittest

from app.core.agenda_route_rules import (
    DEFAULT_AGENDA_ROTA_REGRAS,
    carregar_agenda_rota_regras,
    normalizar_agenda_rota_regras,
)


class AgendaRouteRulesNormalizationTest(unittest.TestCase):
    @staticmethod
    def _normalizar(pisos):
        return normalizar_agenda_rota_regras({
            "route_policy": {"first_appointment_city_floors": pisos},
        })

    def test_round_trip_preserva_ate_cinquenta_municipios_adicionais(self):
        for quantidade in (46, 47, 50, 51):
            with self.subTest(quantidade=quantidade):
                regras = self._normalizar({
                    f"municipio {indice:02d}": "10:15"
                    for indice in range(quantidade)
                })
                pisos = regras["route_policy"]["first_appointment_city_floors"]
                esperados = {
                    **DEFAULT_AGENDA_ROTA_REGRAS["route_policy"]["first_appointment_city_floors"],
                    **{
                        f"municipio {indice:02d}": "10:15"
                        for indice in range(min(quantidade, 50))
                    },
                }
                self.assertEqual(pisos, esperados)
                self.assertEqual(normalizar_agenda_rota_regras(regras), regras)
                self.assertEqual(carregar_agenda_rota_regras(json.dumps(regras)), regras)

    def test_alias_e_defaults_tardios_atualizam_piso_sem_consumir_limite(self):
        pisos = {
            " São Gonçalo do Amarante ": "09:15",
            **{f"municipio {indice:02d}": "10:15" for indice in range(49)},
            "SAO GONCALO DO AMARANTE": "11:45",
            "CAUCAIA": "08:45",
            " Maracanaú ": "09:30",
            "Eusébio": "09:45",
            "Itaitinga": "10:00",
            "municipio excedente": "12:00",
        }
        regras = self._normalizar(pisos)
        normalizados = regras["route_policy"]["first_appointment_city_floors"]
        self.assertEqual(len(normalizados), 54)
        self.assertEqual(normalizados["sao goncalo do amarante"], "11:45")
        self.assertEqual(normalizados["caucaia"], "08:45")
        self.assertEqual(normalizados["maracanau"], "09:30")
        self.assertEqual(normalizados["eusebio"], "09:45")
        self.assertEqual(normalizados["itaitinga"], "10:00")
        self.assertNotIn("municipio excedente", normalizados)
        self.assertEqual(normalizar_agenda_rota_regras(regras), regras)


    def test_chaves_vazias_ou_invalidas_nao_consumem_limite(self):
        regras = self._normalizar({
            "": "09:00",
            "  ": "09:00",
            "---": "09:00",
            None: "09:00",
            False: "09:00",
            **{f"municipio {indice:02d}": "10:15" for indice in range(50)},
        })
        pisos = regras["route_policy"]["first_appointment_city_floors"]
        self.assertEqual(len(pisos), 54)
        self.assertNotIn("", pisos)
        self.assertEqual(pisos["municipio 49"], "10:15")
        self.assertEqual(normalizar_agenda_rota_regras(regras), regras)

    def test_horarios_invalidos_preservam_fallback_compativel(self):
        regras = self._normalizar({
            "Caucaia": None,
            "Aquiraz": "25:00",
            "Fortaleza": "00:00",
        })
        pisos = regras["route_policy"]["first_appointment_city_floors"]
        self.assertEqual(pisos["caucaia"], "08:30")
        self.assertEqual(pisos["aquiraz"], "08:00")
        self.assertEqual(pisos["fortaleza"], "00:00")
        self.assertEqual(normalizar_agenda_rota_regras(regras), regras)


class AgendaRegionalTransitionNormalizationTest(unittest.TestCase):
    def test_configuracao_legada_mantem_transicao_desativada(self):
        regras = normalizar_agenda_rota_regras({
            "thresholds": {"max_neighbor_travel_min": 30, "safe_margin_min": 5},
            "route_policy": {"end_of_route_window_start": "15:30"},
        })
        politica = regras["route_policy"]
        self.assertFalse(politica["regional_transition_enabled"])
        self.assertEqual(politica["regional_transition_max_travel_min"], 50)
        self.assertEqual(politica["regional_transition_margin_min"], 15)
        self.assertEqual(politica["regional_transition_max_legs_per_day"], 1)
        self.assertEqual(politica["recurrent_clinic_history_days"], 60)
        self.assertEqual(regras["thresholds"]["max_neighbor_travel_min"], 30)
        self.assertEqual(regras["thresholds"]["safe_margin_min"], 5)
        self.assertEqual(politica["end_of_route_window_start"], "15:30")

    def test_strings_e_round_trip_preservam_politica_e_demais_ajustes(self):
        entrada = {
            "thresholds": {"max_neighbor_travel_min": 30, "same_location_transition_min": 0},
            "route_policy": {
                "regional_transition_enabled": "sim",
                "regional_transition_max_travel_min": "45",
                "regional_transition_margin_min": "20",
                "first_appointment_city_floors": {"Aquiraz": "10:00"},
                "reject_clear_inefficiency": False,
            },
        }
        regras = normalizar_agenda_rota_regras(entrada)
        self.assertTrue(regras["route_policy"]["regional_transition_enabled"])
        self.assertEqual(regras["route_policy"]["regional_transition_max_travel_min"], 45)
        self.assertEqual(regras["route_policy"]["regional_transition_margin_min"], 20)
        self.assertEqual(regras["route_policy"]["first_appointment_city_floors"]["aquiraz"], "10:00")
        self.assertFalse(regras["route_policy"]["reject_clear_inefficiency"])
        self.assertEqual(regras["thresholds"]["same_location_transition_min"], 0)
        self.assertEqual(carregar_agenda_rota_regras(json.dumps(regras)), regras)
        self.assertEqual(entrada["route_policy"]["regional_transition_max_travel_min"], "45")

    def test_limites_nao_permitem_ampliar_viagem_cota_ou_reduzir_margem(self):
        for quantidade in (None, 0, -1, "2", 99):
            with self.subTest(quantidade=quantidade):
                regras = normalizar_agenda_rota_regras({"route_policy": {
                    "regional_transition_max_travel_min": 999,
                    "regional_transition_margin_min": 0,
                    "regional_transition_max_legs_per_day": quantidade,
                    "recurrent_clinic_history_days": quantidade,
                }})
                politica = regras["route_policy"]
                self.assertEqual(politica["regional_transition_max_travel_min"], 50)
                self.assertEqual(politica["regional_transition_margin_min"], 15)
                self.assertEqual(politica["regional_transition_max_legs_per_day"], 1)
                self.assertEqual(politica["recurrent_clinic_history_days"], 60)

    def test_valores_nulos_invalidos_e_extremos_tem_fallback_seguro(self):
        for valor in (None, "invalido", [], {}):
            with self.subTest(valor=valor):
                politica = normalizar_agenda_rota_regras({"route_policy": {
                    "regional_transition_enabled": valor,
                    "regional_transition_max_travel_min": valor,
                    "regional_transition_margin_min": valor,
                }})["route_policy"]
                self.assertFalse(politica["regional_transition_enabled"])
                self.assertEqual(politica["regional_transition_max_travel_min"], 50)
                self.assertEqual(politica["regional_transition_margin_min"], 15)
        politica = normalizar_agenda_rota_regras({"route_policy": {
            "regional_transition_enabled": "0",
            "regional_transition_max_travel_min": 0,
            "regional_transition_margin_min": 999,
        }})["route_policy"]
        self.assertFalse(politica["regional_transition_enabled"])
        self.assertEqual(politica["regional_transition_max_travel_min"], 1)
        self.assertEqual(politica["regional_transition_margin_min"], 120)
