"""Method-specific canine diastolic evidence without inventing normal limits.

Only the published PW E RI95% has individual bounds. Other cohorts provide
means/SD, never mean +/- 2 SD, diagnostic cutoffs, or an automatic grade.
An explicit exam-level protocol confirms the acquisition/population domain.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from app.utils.echo_diastolic_aliases import normalize_echo_diastolic_aliases
from app.utils.referencia_eco_defaults import normalizar_especie_referencia

CANINE_DIASTOLIC_KEYS = (
    "Onda_E", "Onda_A", "E_A", "TD", "TRIV", "E_TRIV", "e_doppler",
    "a_doppler", "doppler_tecidual_relacao", "E_E_linha",
)
PW_METHOD = "canino_nao_sedado_pw_apical"
PEREIRA_METHOD = "canino_2a6_anos_nao_sedado_pw_apical_fim_fluxo"
PW_METHODS = {PW_METHOD, PEREIRA_METHOD}
CHOI_METHOD = "canino_pw_anel_septal_choi"
WESS_SEPTAL_METHOD = "canino_pw_basal_septal_wess"
WESS_LATERAL_METHOD = "canino_pw_basal_lateral_wess"
CHOMPOOSAN = {
    "source": "Chompoosan et al. (2022)", "doi": "10.1111/jsap.13472",
    "bibliography": "Chompoosan et al. (2022). Epidemiology of heart disease in English Bull Terriers and echocardiographic characteristics of mitral valve abnormalities. Tabela 3: controles saudáveis de múltiplas raças. DOI: 10.1111/jsap.13472.",
}
PEREIRA = {
    "source": "Pereira et al. (2009)", "doi": "10.1590/S0100-736X2009000400003",
    "bibliography": "Pereira et al. (2009). Doppler transmitral e TRIV em 40 cães saudáveis não sedados: estatísticas descritivas. DOI: 10.1590/S0100-736X2009000400003.",
}
CHOI = {
    "source": "Choi et al. (2013)", "doi": "10.4142/jvs.2013.14.1.85",
    "bibliography": "Choi et al. (2013). Doppler tecidual pulsado do anel mitral septal em 45 cães saudáveis: estatísticas descritivas. DOI: 10.4142/jvs.2013.14.1.85.",
}
WESS = {
    "source": "Wess et al. (2010)", "doi": "10.1111/j.1939-1676.2009.0460.x",
    "bibliography": "Wess et al. (2010). Doppler tecidual pulsado dos segmentos basais septal e lateral em 71 cães saudáveis: estatísticas descritivas. DOI: 10.1111/j.1939-1676.2009.0460.x.",
}
FUSION = {
    "source": "Schober et al. (2010)", "doi": "10.1111/j.1939-1676.2010.0592.x",
    "bibliography": "Schober et al. (2010). Detection of congestive heart failure in dogs by Doppler echocardiography. Medidas dependentes de ondas individualizadas; sem adoção de limiar diagnóstico genérico. DOI: 10.1111/j.1939-1676.2010.0592.x.",
}


def _positive(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    try:
        value = float(str(value).strip().replace(",", "."))
    except (ValueError, TypeError):
        return False
    return math.isfinite(value) and value > 0


def _unconfirmed(note: str) -> dict[str, Any]:
    return {"text": "", "kind": "unconfirmed", "source": "", "doi": "",
            "statistic": "", "bibliography": "", "note": note}


def _description(text: str, source: Mapping[str, str], note: str) -> dict[str, Any]:
    return {**source, "text": text, "kind": "descriptive", "statistic": "mean_sd", "note": note}


def _fusion(text: str, note: str) -> dict[str, Any]:
    return {**FUSION, "text": text, "kind": "uninterpretable", "statistic": "", "note": note}


def canine_diastolic_references(measurements: Mapping[str, Any], species: Any) -> dict[str, dict[str, Any]]:
    """Return only explicitly confirmed evidence, independent of a weight catalog.

    Method enums confirm the technique and study population; no method is
    inferred from numeric values. Fusion affects presentation, never history.
    """
    if normalizar_especie_referencia(species) != "Canina":
        return {}
    measurements = normalize_echo_diastolic_aliases(measurements)
    references = {
        key: _unconfirmed("Confirme a técnica, a população aplicável e a separação das ondas para consultar os dados publicados")
        for key in CANINE_DIASTOLIC_KEYS if _positive(measurements.get(key))
    }
    method = measurements.get("Diastolica_metodo")
    separated = measurements.get("Diastolica_ondas") == "separadas"
    if method in PW_METHODS and separated and "Onda_E" in references:
        references["Onda_E"] = {
            **CHOMPOOSAN, "text": "IR95%: 0,51-1,10 m/s", "kind": "reference_interval",
            "statistic": "reference_interval_95", "min": 0.51, "max": 1.10,
            "note": "120 cães saudáveis de 19 raças, não sedados, sem medicação cardioativa; Doppler pulsado apical de 4 câmaras, nas pontas mitrais; ondas separadas; FC observada 55-171 bpm",
        }
    if method == PEREIRA_METHOD:
        cohort = "40 cães saudáveis não sedados, 2-6 anos, 4,2-37,4 kg; Doppler pulsado apical nas pontas mitrais; média ± DP, sem intervalo individual"
        if separated:
            for key, text in {
                "Onda_A": "Média ± DP: 0,487 ± 0,062 m/s",
                "E_A": "Média ± DP: 1,533 ± 0,198",
                "TD": "Média ± DP: 88,7 ± 9,2 ms",
            }.items():
                if key in references:
                    references[key] = _description(text, PEREIRA, cohort + "; ondas separadas")
        if "TRIV" in references:
            references["TRIV"] = _description("Média ± DP: 80 ± 9 ms", PEREIRA,
                cohort + "; TRIV: fim do fluxo aórtico até início do fluxo mitral, vista apical de 5 câmaras")
    if "E_TRIV" in references:
        references["E_TRIV"]["note"] = "Sem intervalo individual adotado; cortes de estudos com cardiopatas dependem da doença e não representam faixa de normalidade"

    tdi_method = measurements.get("TDI_metodo")
    tdi_separated = measurements.get("TDI_ondas") == "separadas"
    if tdi_separated and tdi_method == CHOI_METHOD:
        cohort = "45 cães saudáveis não sedados, 1-9,6 anos, 1,3-14 kg; Doppler tecidual pulsado do anel mitral septal; ondas separadas; dados descritivos"
        for key, text in {
            "e_doppler": "Média ± DP: 0,0658 ± 0,0181 m/s",
            "a_doppler": "Média ± DP: 0,0510 ± 0,0200 m/s",
            "doppler_tecidual_relacao": "Média ± DP: 1,40 ± 0,40",
            "E_E_linha": "Média ± DP: 10,94 ± 3,27",
        }.items():
            if key in references and (key != "E_E_linha" or (separated and method in PW_METHODS)):
                references[key] = _description(text, CHOI, cohort)
    elif tdi_separated and tdi_method in {WESS_SEPTAL_METHOD, WESS_LATERAL_METHOD}:
        septal = tdi_method == WESS_SEPTAL_METHOD
        site = "septal" if septal else "lateral"
        cohort = f"71 cães saudáveis não sedados, 1-14 anos, 3-55 kg; Doppler tecidual pulsado no segmento basal {site}, volume de amostra 5 mm, apical de 4 câmaras; ondas separadas; dados descritivos"
        for key, text in {
            "e_doppler": "Média ± DP: 0,0741 ± 0,0146 m/s" if septal else "Média ± DP: 0,1041 ± 0,0294 m/s",
            "a_doppler": "Média ± DP: 0,0716 ± 0,0208 m/s" if septal else "Média ± DP: 0,0906 ± 0,0247 m/s",
        }.items():
            if key in references:
                references[key] = _description(text, WESS, cohort)
    if measurements.get("Diastolica_ondas") == "fundidas":
        for key in ("Onda_E", "Onda_A", "E_A", "TD", "E_E_linha", "E_TRIV"):
            references[key] = _fusion("Fusão E/A: sem comparação", "Componente transmitral E não individualizado; interpretar o conjunto do exame")
    if measurements.get("TDI_ondas") == "fundidas":
        for key in ("e_doppler", "a_doppler", "doppler_tecidual_relacao", "E_E_linha"):
            references[key] = _fusion("Fusão e'/a': sem comparação", "Picos teciduais não individualizados; não substituir o pico fundido por e' ou a'")
    return references


def canine_diastolic_notes(measurements: Mapping[str, Any], species: Any) -> list[str]:
    references = canine_diastolic_references(measurements, species)
    if not references:
        return []
    notes: list[str] = []
    if references.get("Onda_E", {}).get("kind") == "reference_interval":
        notes.append("Onda E: IR95% de Chompoosan et al. (2022), controles saudáveis de 120 cães de 19 raças, não sedados e sem medicação cardioativa; Doppler pulsado apical de 4 câmaras, amostra nas pontas mitrais, ondas separadas e FC no domínio observado de 55-171 bpm.")
    if any(ref["kind"] == "descriptive" for ref in references.values()):
        notes.append("Diastólica: dados de consulta expressos como média ± DP, conforme técnica e população dos estudos; não constituem limites individuais de normalidade. Interpretar com idade, frequência cardíaca e demais achados.")
    for source, note in (
        (PEREIRA, "Pereira et al. (2009): 40 cães saudáveis não sedados, 2-6 anos e 4,2-37,4 kg. No estudo, o fluxo transmitral foi medido por Doppler pulsado apical de 4 câmaras, nas pontas mitrais, com ondas separadas; o TRIV foi obtido do fim do fluxo aórtico ao início mitral em vista apical de 5 câmaras."),
        (CHOI, "TDI septal: Choi et al. (2013), 45 cães saudáveis não sedados, 1-9,6 anos e 1,3-14 kg; Doppler tecidual pulsado do anel mitral septal. Não intercambiar com anel lateral ou segmento basal."),
        (WESS, "TDI basal: Wess et al. (2010), 71 cães saudáveis não sedados, 1-14 anos e 3-55 kg; Doppler tecidual pulsado nos segmentos basais, amostra de 5 mm. Não intercambiar com Doppler tecidual colorido ou medida anular genérica."),
    ):
        if any(ref.get("doi") == source["doi"] for ref in references.values()):
            notes.append(note)
    if measurements.get("Diastolica_ondas") == "fundidas":
        notes.append("Ondas E/A transmitrais fundidas: picos e índices dependentes de E/A não são interpretados como ondas separadas. Doppler tecidual avaliado independentemente.")
    if measurements.get("TDI_ondas") == "fundidas":
        notes.append("Ondas e'/a' teciduais fundidas: picos e índices dependentes de e'/a' não são interpretados como ondas separadas.")
    return notes
