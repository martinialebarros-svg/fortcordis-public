"""A cleared canonical measurement must survive saving and never revive an alias."""
import os
import re
import sys
import unittest
from copy import deepcopy
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "echo-alias-roundtrip-synthetic-secret-1234567890")

from pypdf import PdfReader
from app.api.v1.endpoints.laudos import _montar_descricao_ecocardiograma
from app.utils.ecocardiograma_medidas import extrair_medidas_ecocardiograma_da_descricao
from app.utils.echo_diastolic import diastolic_references
from app.utils.pdf_laudo import (
    filtrar_parametros_preenchidos, gerar_pdf_laudo_eco, normalizar_medidas_para_pdf,
)

ALIASES = {
    "MV_E": "Onda_E", "MV_A": "Onda_A", "MV_E_A": "E_A", "MV_DT": "TD",
    "IVRT": "TRIV", "MV_E_TRIV": "E_TRIV", "TDI_e": "e_doppler",
    "TDI_a": "a_doppler", "EEp": "E_E_linha",
}
CANONICAL_KEYS = (*ALIASES.values(), "doppler_tecidual_relacao")
INVALID_VALUES = ("", None, "0", 0, False, "NaN", float("nan"), "inf", float("inf"), "a conferir", "-1")
PROTOCOLS = {
    "Canina": {"Diastolica_metodo": "canino_2a6_anos_nao_sedado_pw_apical_fim_fluxo",
               "Diastolica_ondas": "separadas", "TDI_metodo": "canino_pw_anel_septal_choi", "TDI_ondas": "separadas"},
    "Felina": {"Diastolica_metodo": "felino_adulto_nao_sedado_pw_apical_fim_fluxo",
               "Diastolica_ondas": "separadas", "TDI_metodo": "felino_pw_anel_lateral", "TDI_ondas": "separadas"},
}


def edit_description(measurements):
    """The edit form's physical description format, including explicit clears."""
    return "## Medidas Ecocardiograficas\n" + "\n".join(
        f"- {key}: {'' if value is None else value}" for key, value in measurements.items()
    ) + "\n\n## Avaliacao Qualitativa\n"


def pdf_text(measurements, species):
    payload = {"paciente": {"nome": "TESTE ALIAS ROUNDTRIP", "especie": species,
                             "data_exame": "2026-10-26", "idade": "4 anos"},
               "medidas": measurements, "conclusao": "Teste sintetico, sem finalidade clinica.",
               "qualitativa": {}, "clinica": "Clinica sintetica"}
    before = deepcopy(payload)
    text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(gerar_pdf_laudo_eco(payload))).pages)
    # deepcopy preserves NaN only by value in a new object, so compare its representation.
    assert repr(payload) == repr(before)
    return re.sub(r"\s+", " ", text)


class EchoDiastolicAliasRoundtripTest(unittest.TestCase):
    def test_create_writer_retains_only_explicit_canonical_falsy_values_and_history(self):
        for key in CANONICAL_KEYS:
            for value in ("", None, 0, False):
                with self.subTest(key=key, value=value):
                    raw = {"MV_E": "1.80", key: value, "DIVEd": "", "VDF": 0, "VSF": None}
                    before = deepcopy(raw)
                    saved = _montar_descricao_ecocardiograma(raw, {})
                    expected = "" if value is None else str(value)
                    self.assertIn(f"- {key}: {expected}\n", saved)
                    self.assertIn("- MV_E: 1.80", saved)
                    for other in ("DIVEd", "VDF", "VSF"):
                        self.assertNotIn(f"- {other}:", saved)
                    self.assertEqual(raw, before)

    def test_parser_keeps_a_blank_on_its_own_physical_line_and_the_next_measurement(self):
        for separator in ("\n", "\r\n"):
            for canonical_first in (True, False):
                with self.subTest(separator=repr(separator), canonical_first=canonical_first):
                    pair = ["- Onda_E: ", "- MV_E: 1.80"]
                    if not canonical_first:
                        pair.reverse()
                    saved = separator.join(["## Medidas Ecocardiograficas", *pair, "- TRIV: 85", "", "## Avaliacao Qualitativa"])
                    restored = extrair_medidas_ecocardiograma_da_descricao(saved)
                    self.assertEqual(restored, {"Onda_E": "", "MV_E": "1.80", "TRIV": "85"})

    def test_create_and_edit_roundtrip_preserve_explicit_canonical_precedence(self):
        for species, protocol in PROTOCOLS.items():
            for alias, canonical in ALIASES.items():
                for value in INVALID_VALUES:
                    for canonical_first in (True, False):
                        with self.subTest(species=species, key=canonical, value=repr(value), canonical_first=canonical_first):
                            pair = [(canonical, value), (alias, "1.80")]
                            raw = {**dict(pair if canonical_first else reversed(pair)), **protocol}
                            before = repr(raw)
                            for writer in (_montar_descricao_ecocardiograma, lambda data, _: edit_description(data)):
                                saved = writer(raw, {})
                                restored = extrair_medidas_ecocardiograma_da_descricao(saved)
                                self.assertIn(canonical, restored)
                                self.assertEqual(restored[canonical], "" if value is None else str(value))
                                self.assertEqual(restored[alias], "1.80")
                                normalized = normalizar_medidas_para_pdf(restored)
                                self.assertEqual(normalized[canonical], restored[canonical])
                                self.assertNotIn(canonical, diastolic_references(restored, species))
                                self.assertEqual(filtrar_parametros_preenchidos([{"chave": canonical}], normalized), [])
                            self.assertEqual(repr(raw), before)

    def test_pdf_filter_requires_finite_positive_diastolic_values_except_fusion(self):
        for key in CANONICAL_KEYS:
            for value in (*INVALID_VALUES, float("-inf"), "-inf"):
                with self.subTest(key=key, value=repr(value)):
                    self.assertEqual(filtrar_parametros_preenchidos([{"chave": key, "value_recorded": True}], {key: value}), [])
                    masked = {"chave": key, "value_unmeasurable": True}
                    self.assertEqual(filtrar_parametros_preenchidos([masked], {key: value}), [masked])
            for value in ("0.47", "0,47", 0.47, "85"):
                parameter = {"chave": key}
                self.assertEqual(filtrar_parametros_preenchidos([parameter], {key: value}), [parameter])
        # Outflow confirmation and historical non-diastolic behavior are unchanged.
        recorded = {"chave": "Grad_VSVE", "value_recorded": True}
        self.assertEqual(filtrar_parametros_preenchidos([recorded], {"Grad_VSVE": "a confirmar"}), [recorded])

    def test_actual_pdf_roundtrip_omits_stale_alias_and_nonfinite_canonical_values(self):
        for species, protocol in PROTOCOLS.items():
            for alias, canonical in (("MV_E", "Onda_E"), ("TDI_e", "e_doppler"), ("IVRT", "TRIV")):
                for value in ("", None, "0", "NaN", "inf", "a conferir", "-1"):
                    with self.subTest(species=species, key=canonical, value=value):
                        saved = _montar_descricao_ecocardiograma({alias: "1.80", canonical: value, **protocol}, {})
                        restored = extrair_medidas_ecocardiograma_da_descricao(saved)
                        text = pdf_text(restored, species)
                        control = pdf_text({canonical: restored.get(canonical), **protocol}, species)
                        self.assertEqual(text, control)
                        self.assertNotIn("1.80", text)
                        self.assertNotRegex(text, r"\b(?:nan|inf)\b")

    def test_fusion_masks_override_cleared_and_invalid_values_after_roundtrip(self):
        for species, protocol in PROTOCOLS.items():
            for domain in ("Diastolica_ondas", "TDI_ondas"):
                raw = {"MV_E": "1.80", "Onda_E": "NaN", "TDI_e": "1.80", "e_doppler": "",
                       "TRIV": "85", **protocol, domain: "fundidas"}
                restored = extrair_medidas_ecocardiograma_da_descricao(_montar_descricao_ecocardiograma(raw, {}))
                text = pdf_text(restored, species)
                self.assertIn("Não mensurável", text)
                self.assertIn("85.00 ms", text)
                self.assertNotIn("1.80", text)
                self.assertNotRegex(text, r"\b(?:nan|inf)\b")


if __name__ == "__main__":
    unittest.main()
