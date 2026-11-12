"""Pure route policy tests: no database, credentials or network providers."""
import json
from datetime import datetime, timedelta
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.agenda_regional_transition import (
    AvaliacaoTransicaoRegional,
    EstimativaDeslocamentoRegional,
    avaliar_transicao_regional,
)


def appointment(identifier, hour, *, destination=None, status="Agendado"):
    start = datetime.fromisoformat(f"2026-10-23T{hour}:00")
    return {
        "id": identifier, "inicio": start, "fim": start + timedelta(minutes=30),
        "status": status,
        "destino_operacional": {
            "tipo": "clinica_parceira", "entity_id": destination or identifier,
            "localizacao_confiavel": True,
        },
    }


def rules(**policy):
    return {
        "thresholds": {"max_neighbor_travel_min": 30, "safe_margin_min": 5},
        "route_policy": {
            "regional_transition_enabled": True,
            "regional_transition_max_travel_min": 50,
            "regional_transition_margin_min": 15,
            "regional_transition_max_legs_per_day": 1,
            **policy,
        },
    }


def resolver_for(routes, calls=None):
    def resolve(origin, destination):
        pair = (origin["entity_id"], destination["entity_id"])
        if calls is not None:
            calls.append(pair)
        return routes.get(pair, (None, "sem_matriz"))
    return resolve


class AgendaRegionalTransitionTest(unittest.TestCase):
    def evaluate(self, originals, candidate, routes, **kwargs):
        return avaliar_transicao_regional(
            originals, candidate, regras_rota=kwargs.pop("regras_rota", rules()),
            resolver_deslocamento=resolver_for(routes), **kwargs,
        )

    def test_disabled_does_not_call_resolver_or_require_route_data(self):
        def forbidden(*_args):
            self.fail("Disabled policy must not consult routes")
        self.assertIsNone(avaliar_transicao_regional(
            [], {}, regras_rota=rules(regional_transition_enabled=False),
            resolver_deslocamento=forbidden,
        ))

    def test_40_and_50_minutes_with_full_margin_are_allowed(self):
        origin = appointment(1, "09:00")
        for duration in (40, 50):
            with self.subTest(duration=duration):
                candidate = appointment(2, "10:35")
                result = self.evaluate([origin], candidate, {(1, 2): (duration, "google_routes_api_cache")})
                self.assertIsInstance(result, AvaliacaoTransicaoRegional)
                self.assertTrue(result.permitida)
                self.assertTrue(result.usa_transicao_regional)
                self.assertEqual(result.transicoes_longas, 1)
                self.assertEqual(result.trecho_anterior.margem_necessaria_min, 15)
                self.assertEqual(result.trecho_anterior.folga_min, 65)
                self.assertIsNone(result.trecho_proximo)
                self.assertEqual(json.loads(json.dumps(result.as_dict()))["codigo"], "TRANSICAO_REGIONAL_APROVADA")

    def test_51_minutes_is_refused_even_with_abundant_gap(self):
        result = self.evaluate(
            [appointment(1, "09:00")], appointment(2, "12:00"), {(1, 2): (51, "manual")},
        )
        self.assertFalse(result.permitida)
        self.assertEqual(result.codigo, "TRANSICAO_REGIONAL_LIMITE_EXCEDIDO")

    def test_14_margin_is_refused_and_15_is_allowed(self):
        origin = appointment(1, "09:00")
        for time, allowed in (("10:24", False), ("10:25", True)):
            with self.subTest(time=time):
                result = self.evaluate([origin], appointment(2, time), {(1, 2): (40, "manual")})
                self.assertEqual(result.permitida, allowed)
                if not allowed:
                    self.assertEqual(result.codigo, "TRANSICAO_REGIONAL_FOLGA_INSUFICIENTE")

    def test_two_long_legs_around_candidate_are_refused(self):
        result = self.evaluate(
            [appointment(3, "13:00"), appointment(1, "09:00")], appointment(2, "11:00"),
            {(1, 3): (15, "manual"), (1, 2): (40, "manual"), (2, 3): (40, "manual")},
        )
        self.assertFalse(result.permitida)
        self.assertEqual(result.codigo, "TRANSICAO_REGIONAL_COTA_EXCEDIDA")
        self.assertEqual(result.transicoes_longas, 2)
        self.assertEqual(result.trecho_proximo.destino_id, 3)

    def test_update_removes_old_position_and_evaluates_new_directed_route(self):
        originals = [appointment(1, "08:00"), appointment(2, "09:30"), appointment(3, "11:00")]
        candidate = appointment(2, "12:30")
        result = self.evaluate(originals, candidate, {
            (1, 2): (40, "manual"), (2, 3): (10, "manual"),
            (1, 3): (10, "manual"), (3, 2): (40, "manual"),
        }, agendamento_id_excluir=2)
        self.assertTrue(result.permitida)
        self.assertEqual(result.transicoes_longas_anteriores, 1)
        self.assertEqual(result.transicoes_longas, 1)
        self.assertEqual(len(result.trechos), 2)
        self.assertEqual(result.trecho_anterior.origem_id, 3)
        self.assertIsNone(result.trecho_proximo)
        self.assertEqual(originals[1]["inicio"].hour, 9)

    def test_replacing_one_long_leg_by_short_legs_releases_the_quota(self):
        result = self.evaluate(
            [appointment(1, "08:00"), appointment(3, "11:00")], appointment(2, "09:30"),
            {(1, 3): (40, "manual"), (1, 2): (15, "manual"), (2, 3): (15, "manual")},
        )
        self.assertTrue(result.permitida)
        self.assertFalse(result.usa_transicao_regional)
        self.assertEqual(result.transicoes_longas, 0)
        self.assertEqual(result.transicoes_longas_anteriores, 1)

    def test_replacing_existing_long_leg_does_not_consume_second_allowance(self):
        result = self.evaluate(
            [appointment(1, "08:00"), appointment(3, "11:00")], appointment(2, "09:30"),
            {(1, 3): (45, "manual"), (1, 2): (40, "manual"), (2, 3): (10, "manual")},
        )
        self.assertTrue(result.permitida)
        self.assertEqual(result.transicoes_longas, 1)

    def test_cancelled_expired_and_operational_base_do_not_consume_quota(self):
        policy = rules()
        policy["base"] = {"label": "Synthetic base", "lat": 1.0, "lng": 1.0}
        result = self.evaluate(
            [appointment(9, "08:00", status="Cancelado"), appointment(1, "09:00"),
             appointment(8, "11:00", status="Expirado")],
            appointment(2, "10:35"), {(1, 2): (50, "manual")}, regras_rota=policy,
        )
        self.assertTrue(result.permitida)
        self.assertEqual(len(result.trechos), 1)
        self.assertEqual(result.transicoes_longas, 1)

    def test_heuristic_or_unknown_long_source_cannot_grant_exception(self):
        for source in ("heuristica_haversine", "fallback_mesma_cidade", "matriz", "unknown"):
            with self.subTest(source=source):
                result = self.evaluate(
                    [appointment(1, "09:00")], appointment(2, "11:00"), {(1, 2): (40, source)},
                )
                self.assertFalse(result.permitida)
                self.assertEqual(result.codigo, "TRANSICAO_REGIONAL_ROTA_NAO_CONFIAVEL")

    def test_unknown_fixed_leg_prevents_granting_new_exception(self):
        result = self.evaluate(
            [appointment(1, "08:00"), appointment(2, "09:00")], appointment(3, "11:00"),
            {(1, 2): (None, "sem_matriz"), (2, 3): (40, "manual")},
        )
        self.assertFalse(result.permitida)
        self.assertEqual(result.codigo, "TRANSICAO_REGIONAL_ROTA_NAO_CONFIAVEL")

    def test_unknown_duration_alone_does_not_authorize_any_regional_allowance(self):
        for estimate in (None, (None, "sem_matriz"), (0, "sem_matriz"), (0, "manual")):
            with self.subTest(estimate=estimate):
                result = self.evaluate(
                    [appointment(1, "09:00")], appointment(2, "11:00"), {(1, 2): estimate},
                )
                self.assertFalse(result.permitida)
                self.assertFalse(result.usa_transicao_regional)
                self.assertIsNone(result.trecho_anterior.duracao_min)
                self.assertEqual(result.codigo, "TRANSICAO_REGIONAL_ROTA_NAO_CONFIAVEL")

    def test_unknown_fixed_leg_does_not_block_normal_known_insertion(self):
        result = self.evaluate(
            [appointment(1, "08:00"), appointment(2, "09:00")], appointment(3, "11:00"),
            {(1, 2): (None, "sem_matriz"), (2, 3): (20, "manual")},
        )
        self.assertTrue(result.permitida)
        self.assertFalse(result.usa_transicao_regional)

    def test_normal_heuristic_estimate_does_not_gain_regional_authority(self):
        result = self.evaluate(
            [appointment(1, "09:00")], appointment(2, "11:00"),
            {(1, 2): (25, "heuristica_haversine")},
        )
        self.assertTrue(result.permitida)
        self.assertFalse(result.usa_transicao_regional)
        self.assertFalse(result.trecho_anterior.confiavel)

    def test_30_is_normal_and_31_requires_full_regional_margin(self):
        for duration, allowed in ((30, True), (31, False)):
            with self.subTest(duration=duration):
                result = self.evaluate(
                    [appointment(1, "09:00")], appointment(2, "10:05"),
                    {(1, 2): (duration, "manual")},
                )
                self.assertEqual(result.permitida, allowed)
                self.assertEqual(result.usa_transicao_regional, duration > 30)

    def test_typed_real_manual_route_can_attest_confidence_but_not_heuristics(self):
        for source, allowed in (("trajeto_manual_validado", True), ("heuristica_haversine", False)):
            with self.subTest(source=source):
                result = self.evaluate(
                    [appointment(1, "09:00")], appointment(2, "11:00"),
                    {(1, 2): EstimativaDeslocamentoRegional(40, source, confiavel=True)},
                )
                self.assertEqual(result.permitida, allowed)

    def test_shared_cache_resolves_each_directional_pair_only_once(self):
        calls, cache = [], {}
        resolve = resolver_for({(1, 2): (40, "manual"), (2, 1): (20, "manual")}, calls)
        for time in ("10:30", "10:45", "11:00"):
            result = avaliar_transicao_regional(
                [appointment(1, "09:00")], appointment(2, time), regras_rota=rules(),
                resolver_deslocamento=resolve, cache_deslocamentos=cache,
            )
            self.assertTrue(result.permitida)
        reverse = avaliar_transicao_regional(
            [appointment(2, "09:00")], appointment(1, "10:30"), regras_rota=rules(),
            resolver_deslocamento=resolve, cache_deslocamentos=cache,
        )
        self.assertEqual(calls, [(1, 2), (2, 1)])
        self.assertFalse(reverse.usa_transicao_regional)

    def test_unrelated_fixed_exception_is_not_revalidated(self):
        result = self.evaluate(
            [appointment(1, "08:00"), appointment(2, "08:45")], appointment(3, "10:00"),
            {(1, 2): (60, "manual"), (2, 3): (10, "manual")},
        )
        self.assertTrue(result.permitida)
        self.assertEqual(result.transicoes_longas, 1)
        self.assertFalse(result.trechos[0].novo_trecho)

    def test_legacy_two_long_legs_can_remain_but_cannot_increase(self):
        original = [appointment(1, "08:00"), appointment(2, "09:00"), appointment(3, "10:00")]
        for duration, allowed in ((10, True), (40, False)):
            with self.subTest(duration=duration):
                result = self.evaluate(original, appointment(4, "12:00"), {
                    (1, 2): (40, "manual"), (2, 3): (40, "manual"), (3, 4): (duration, "manual"),
                })
                self.assertEqual(result.permitida, allowed)
                self.assertEqual(result.transicoes_longas_anteriores, 2)

    def test_normal_limit_zero_means_disabled_normal_cap_not_long_travel(self):
        config = rules()
        config["thresholds"]["max_neighbor_travel_min"] = 0
        result = self.evaluate(
            [appointment(1, "09:00")], appointment(2, "12:00"),
            {(1, 2): (90, "manual")}, regras_rota=config,
        )
        self.assertTrue(result.permitida)
        self.assertFalse(result.usa_transicao_regional)


if __name__ == "__main__":
    unittest.main()
