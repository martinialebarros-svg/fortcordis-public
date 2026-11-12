"""Method-specific clinical guidance, separate from catalog intervals."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from app.utils.echo_unit_provenance import ambiguous_echo_length_keys
from app.utils.referencia_eco_defaults import normalizar_especie_referencia


CANINE_AE_AO_METHOD = "2d_eixo_curto_diastole_inicial"
CANINE_AE_AO_SWEDISH_METHOD = "2d_eixo_curto_diastole_inicial_sueco"
CANINE_AE_AO_REFERENCE_TEXT = "<1,60 (2D, eixo curto)"
CANINE_AE_AO_METHOD_NOTE = (
    "AE/Ao: 2D, eixo curto paraesternal direito na base cardíaca, início da diástole "
    "(primeira imagem após o fechamento aórtico). Limiar clínico geral; interpretar "
    "em conjunto com os demais achados."
)
CANINE_AE_AO_SWEDISH_METHOD_NOTE = (
    "AE/Ao: método sueco (Hansson et al., 2002), 2D, eixo curto paraesternal direito "
    "na base cardíaca, início da diástole (primeira imagem após o fechamento "
    "aórtico). Limiar clínico geral; interpretar em conjunto com os demais achados."
)


def canine_ae_ao_clinical_limit_applies(dados_pdf: Mapping[str, Any]) -> bool:
    """Require an explicit acquisition confirmation and a usable canine ratio.

    Rishniw (2023) discusses a clinical threshold, not a weight-specific
    reference/prediction interval. Consequently a catalog row or adult/weight
    assumption must not become a prerequisite or an implied patient finding.
    Existing measurements and their acquisition metadata remain unchanged.
    """
    paciente = dados_pdf.get("paciente")
    medidas = dados_pdf.get("medidas")
    if not isinstance(paciente, Mapping) or not isinstance(medidas, Mapping):
        return False
    if normalizar_especie_referencia(paciente.get("especie")) != "Canina":
        return False
    if medidas.get("AE_Ao_metodo") not in {CANINE_AE_AO_METHOD, CANINE_AE_AO_SWEDISH_METHOD}:
        return False
    value = medidas.get("AE_Ao")
    if isinstance(value, bool):
        return False
    try:
        ratio = float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError):
        return False
    if not math.isfinite(ratio) or ratio <= 0:
        return False
    ambiguous = (dados_pdf["unidades_ambiguas"] if "unidades_ambiguas" in dados_pdf
                 else ambiguous_echo_length_keys(dict(medidas))) or set()
    return not {"AE_Ao", "Aorta", "Atrio_esquerdo"}.intersection(ambiguous)
