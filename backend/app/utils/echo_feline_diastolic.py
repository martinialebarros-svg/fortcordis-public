"""Feline diastolic consultation data, never statistical normal intervals.

The means and standard deviations come from primary study tables. Do not
turn them into limits, color a value as normal/abnormal, or infer an acquisition
or a diastolic grade from numbers. Kept in parity with the frontend helper.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from app.utils.echo_diastolic_aliases import normalize_echo_diastolic_aliases
from app.utils.referencia_eco_defaults import normalizar_especie_referencia

FELINE_DIASTOLIC_KEYS = (
    "Onda_E", "Onda_A", "E_A", "TD", "TRIV", "E_TRIV", "e_doppler",
    "a_doppler", "doppler_tecidual_relacao", "E_E_linha",
)
PW_METHODS = {
    "felino_adulto_nao_sedado_pw_apical_clique_aortico",
    "felino_adulto_nao_sedado_pw_apical_fim_fluxo",
}
TRIV_CLICK_METHODS = {"felino_adulto_nao_sedado_pw_clique_aortico", "felino_adulto_nao_sedado_pw_apical_clique_aortico"}
TRIV_END_METHODS = {"felino_adulto_nao_sedado_pw_fim_fluxo", "felino_adulto_nao_sedado_pw_apical_fim_fluxo"}
DISATIAN = {
    "source": "Disatian et al. (2008)", "doi": "10.1111/j.1939-1676.2008.0066.x",
    "bibliography": "Disatian et al. (2008). Association of Age and Heart Rate with Pulsed-Wave Doppler Measurements in Healthy, Nonsedated Cats. DOI: 10.1111/j.1939-1676.2008.0066.x.",
}
SOARES = {
    "source": "Soares et al. (2005)", "doi": "10.1590/S0103-84782005000600020",
    "bibliography": "Soares et al. (2005). Indices ecodopplercardiográficos de função diastólica de gatos saudáveis não sedados. DOI: 10.1590/S0103-84782005000600020.",
}
WARD = {
    "source": "Ward et al. (2012)", "doi": "10.1177/1098612X12447729",
    "bibliography": "Ward et al. (2012). Effects of sedation on echocardiographic variables of left atrial and left ventricular function in healthy cats. DOI: 10.1177/1098612X12447729.",
}
KIATSILAPANAN = {
    "source": "Kiatsilapanan & Surachetpong (2020)", "doi": "10.1186/s12917-020-02557-3",
    "bibliography": "Kiatsilapanan & Surachetpong (2020). Assessment of left atrial function in feline hypertrophic cardiomyopathy by using two-dimensional speckle tracking echocardiography. DOI: 10.1186/s12917-020-02557-3.",
}
FUSION = {
    "source": "Fuentes et al. (2020)", "doi": "10.1111/jvim.15745",
    "bibliography": "Fuentes et al. (2020). ACVIM consensus statement on cardiomyopathies in cats. DOI: 10.1111/jvim.15745.",
}


def _positive(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    try:
        number = float(str(value).strip().replace(",", "."))
    except (ValueError, TypeError):
        return False
    return math.isfinite(number) and number > 0


def _description(text: str, source: Mapping[str, str], note: str) -> dict[str, str]:
    return {**source, "text": text, "kind": "descriptive", "statistic": "mean_sd", "note": note}


def _uninterpretable(text: str, note: str) -> dict[str, str]:
    return {**FUSION, "text": text, "kind": "uninterpretable", "statistic": "", "note": note}


def feline_diastolic_references(
    measurements: Mapping[str, Any], species: Any,
) -> dict[str, dict[str, str]]:
    """Return neutral descriptions or explicit confirmed-fusion guards.

    Weight/catalog availability is irrelevant to these descriptive summaries.
    The protocol confirms adult, nonsedated acquisition; no method is inferred
    from a value, the LV imaging technique, or a generic equipment label.
    Confirmed fusion retains its limitation even after numeric fields are
    cleared. This describes presentation eligibility without changing history.
    """
    if normalizar_especie_referencia(species) != "Felina":
        return {}
    measurements = normalize_echo_diastolic_aliases(measurements)
    present = [key for key in FELINE_DIASTOLIC_KEYS if _positive(measurements.get(key))]
    references = {
        key: {"text": "", "kind": "unconfirmed", "source": "", "doi": "",
              "statistic": "", "bibliography": "",
              "note": "Confirme a aquisição e a separação das ondas para consultar dados publicados"}
        for key in present
    }
    method = measurements.get("Diastolica_metodo")
    separated = measurements.get("Diastolica_ondas") == "separadas"
    pw_data = {
        "Onda_E": ("Média ± DP: 0,70 ± 0,14 m/s", DISATIAN, "Gatos saudáveis não sedados; Doppler pulsado transmitral na vista apical esquerda de 4 câmaras, nas pontas dos folhetos mitrais; ondas separadas; n=66"),
        "Onda_A": ("Média ± DP: 0,65 ± 0,14 m/s", DISATIAN, "Gatos saudáveis não sedados; Doppler pulsado transmitral na vista apical esquerda de 4 câmaras, nas pontas dos folhetos mitrais; ondas separadas; n=66"),
        "E_A": ("Média ± DP: 1,12 ± 0,22", DISATIAN, "Gatos saudáveis não sedados; Doppler pulsado transmitral na vista apical esquerda de 4 câmaras, nas pontas dos folhetos mitrais; ondas separadas; n=66"),
        "TD": ("Média ± DP: 72,29 ± 9,56 ms", SOARES, "Gatos adultos saudáveis não sedados; Doppler pulsado transmitral na vista apical esquerda de 4 câmaras; ondas separadas; n=24"),
    }
    if method not in PW_METHODS:
        for key in ("Onda_E", "Onda_A", "E_A", "TD", "E_E_linha"):
            if key in references:
                references[key]["note"] = "Confirme Doppler pulsado transmitral na vista apical esquerda de 4 câmaras, amostra nas pontas dos folhetos mitrais, paciente adulto não sedado e ondas separadas"
    if method in PW_METHODS and separated:
        for key, (text, source, note) in pw_data.items():
            if key in references:
                references[key] = _description(text, source, note)
    if "TRIV" in references:
        if method in TRIV_CLICK_METHODS:
            references["TRIV"] = _description("Média ± DP: 46,2 ± 7,6 ms", DISATIAN,
                "Doppler pulsado em vista apical esquerda de 5 câmaras: início do clique de fechamento aórtico até início do fluxo mitral; n=87")
        elif method in TRIV_END_METHODS:
            references["TRIV"] = _description("Média ± DP: 68,75 ± 19,14 ms", SOARES,
                "Doppler pulsado em vista apical esquerda de 5 câmaras: fim do fluxo aórtico até início do fluxo mitral; n=40")
    if "E_TRIV" in references:
        references["E_TRIV"]["note"] = "Sem intervalo individual adotado; não aplicar limiares caninos a felinos"

    tdi_method = measurements.get("TDI_metodo")
    tdi_separated = measurements.get("TDI_ondas") == "separadas"
    tdi_data = {
        "felino_pw_anel_lateral": {
            "e_doppler": "Média ± DP: 0,11 ± 0,03 m/s",
            "a_doppler": "Média ± DP: 0,08 ± 0,03 m/s",
            "doppler_tecidual_relacao": "Média ± DP: 1,33 ± 0,31",
            "E_E_linha": "Média ± DP: 7,8 ± 2,92",
        },
        "felino_pw_anel_septal": {
            "e_doppler": "Média ± DP: 0,075 ± 0,026 m/s",
            "a_doppler": "Média ± DP: 0,061 ± 0,017 m/s",
            "E_E_linha": "Média ± DP: 8,7 ± 1,7",
        },
    }
    if tdi_method == "felino_pw_anel_septal" and "doppler_tecidual_relacao" in references:
        references["doppler_tecidual_relacao"]["note"] = "Comparador septal e'/a' de Ward et al. (2012) não adotado: resumo publicado com inconsistência aparente entre as médias dos picos e da relação; sem substituir pela razão das médias"
    if tdi_separated and tdi_method in tdi_data:
        site = "lateral" if tdi_method == "felino_pw_anel_lateral" else "septal"
        for key, text in tdi_data[tdi_method].items():
            if key in references and (key != "E_E_linha" or (separated and method in PW_METHODS)):
                references[key] = _description(text, KIATSILAPANAN if site == "lateral" else WARD,
                    "Doppler tecidual pulsado; anel mitral lateral; grupo controle de 20 gatos não sedados; ondas fundidas excluídas"
                    if site == "lateral" else "Anel mitral septal; antes da sedação; 7 gatos jovens (1-3 anos); dados descritivos")

    if measurements.get("Diastolica_ondas") == "fundidas":
        for key in ("Onda_E", "Onda_A", "E_A", "TD", "E_E_linha", "E_TRIV"):
            references[key] = _uninterpretable("Fusão E/A: sem comparação", "Componente transmitral E não individualizado; interpretar o conjunto do exame")
    if measurements.get("TDI_ondas") == "fundidas":
        for key in ("e_doppler", "a_doppler", "doppler_tecidual_relacao", "E_E_linha"):
            references[key] = _uninterpretable("Fusão e'/a': sem comparação", "Picos teciduais não individualizados; não substituir o pico fundido por e' ou a'")
    return references


def feline_diastolic_notes(measurements: Mapping[str, Any], species: Any) -> list[str]:
    references = feline_diastolic_references(measurements, species)
    if not references:
        return []
    notes: list[str] = []
    if any(ref["kind"] == "descriptive" for ref in references.values()):
        notes.append("Diastólica: dados de consulta expressos como média ± DP, conforme técnica e população dos estudos; interpretar com frequência cardíaca e demais achados.")
    if any(references.get(key, {}).get("kind") == "unconfirmed" for key in ("Onda_E", "Onda_A", "E_A", "TD", "E_E_linha")):
        notes.append("Fluxo transmitral: confirme Doppler pulsado na vista apical esquerda de 4 câmaras, com amostra nas pontas dos folhetos mitrais e ondas separadas, para consultar os dados publicados.")
    if any(references.get(key, {}).get("kind") == "descriptive" for key in ("Onda_E", "Onda_A", "E_A", "TD")):
        notes.append("Fluxo transmitral: Doppler pulsado na vista apical esquerda de 4 câmaras, nas pontas dos folhetos mitrais, com ondas separadas. Disatian et al. (2008) incluíram gatos não sedados de 3 meses a 19 anos; Soares et al. (2005), gatos adultos não sedados.")
    if references.get("TRIV", {}).get("kind") == "descriptive":
        timing = ("início do clique de fechamento aórtico" if measurements.get("Diastolica_metodo") in TRIV_CLICK_METHODS else "fim do fluxo aórtico")
        label = "TRIV" if measurements.get("Diastolica_metodo") in PW_METHODS else "Referência de TRIV"
        notes.append(f"{label}: Doppler pulsado em vista apical esquerda de 5 câmaras com registro simultâneo de entrada e saída do VE; do {timing} até o início do fluxo mitral.")
    if measurements.get("Diastolica_ondas") == "fundidas":
        notes.append("Ondas E/A transmitrais fundidas: picos e índices dependentes de E/A não são interpretados como ondas separadas. Doppler tecidual avaliado independentemente.")
    if measurements.get("TDI_ondas") == "fundidas":
        notes.append("Ondas e'/a' teciduais fundidas: picos e índices dependentes de e'/a' não são interpretados como ondas separadas.")
    if any(ref.get("doi") == WARD["doi"] for ref in references.values()):
        notes.append("TDI anular: Ward et al. (2012), valores basais antes da sedação em 7 gatos jovens (1-3 anos); média ± DP por sítio.")
    if any(ref.get("doi") == KIATSILAPANAN["doi"] for ref in references.values()):
        notes.append("TDI lateral: Kiatsilapanan & Surachetpong (2020), dados descritivos do grupo controle de 20 gatos não sedados, com exclusão das ondas fundidas.")
    return notes
