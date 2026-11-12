"""Regression coverage for the acquisition site and precision of XML outflow data."""

from contextlib import redirect_stdout
from io import StringIO
import os
from xml.sax.saxutils import escape

import pytest

from app.utils.xml_parser import parse_xml_eco as parse_xml_eco_v1
from app.utils.xml_parser_v2 import parse_xml_eco as parse_xml_eco_v2
from app.utils.xml_outflow import OUTFLOW_MEASUREMENT_CONFLICT


os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "xml-outflow-test-secret-key-1234567890")


PARSERS = (parse_xml_eco_v1, parse_xml_eco_v2)
OUTFLOW_KEYS = {
    f"{prefix}_{site}"
    for prefix in ("Vmax", "Grad")
    for site in ("VSVE", "aorta", "VSVD", "pulmonar")
}


def _xml(parameters):
    return ("<root>" + "".join(
        f'<parameter NAME="{escape(label)}"><aver>{value}</aver><unit>{unit}</unit></parameter>'
        for label, value, unit in parameters
    ) + "</root>").encode("utf-8")


def _parse(parser, parameters=None, xml=None):
    with redirect_stdout(StringIO()):
        return parser(xml if xml is not None else _xml(parameters))["medidas"]


@pytest.mark.parametrize("parser", PARSERS)
def test_all_four_acquisition_sites_preserve_distinct_imported_values(parser):
    parameters = [
        ("LVOT Vmax P", "1.01", "m/s"), ("LVOT maxPG", "4.11", "mmHg"),
        ("Aortic Vmax", "1.205", "m/s"), ("Aortic maxPG", "5.817", "mmHg"),
        ("RVOT Vmax P", "0.80", "m/s"), ("RVOT maxPG", "2.57", "mmHg"),
        ("Pulmonic Vmax", "0.937", "m/s"), ("Pulmonic maxPG", "3.512", "mmHg"),
    ]
    expected = {
        "Vmax_VSVE": 1.01, "Grad_VSVE": 4.11,
        "Vmax_aorta": 1.205, "Grad_aorta": 5.817,
        "Vmax_VSVD": 0.8, "Grad_VSVD": 2.57,
        "Vmax_pulmonar": 0.937, "Grad_pulmonar": 3.512,
    }
    measures = _parse(parser, parameters)
    assert {key: measures[key] for key in OUTFLOW_KEYS} == expected
    for key, parameter in zip(expected, parameters):
        assert measures[f"{key}_origem"] == "importado"
        assert measures[f"{key}_rotulo_origem"] == parameter[0]


@pytest.mark.parametrize("parser", PARSERS)
@pytest.mark.parametrize("site,velocity_label,gradient_label", [
    ("VSVE", "Vmáx VSVE", "máxPG VSVE"),
    ("aorta", "Vmax aorta", "Gradiente aorta"),
    ("VSVD", "Vmáx VSVD", "maxPG VSVD"),
    ("pulmonar", "Vmax pulmonar", "Gradiente pulmonar"),
])
def test_each_site_imports_in_isolation_without_copying_to_another_site(
    parser, site, velocity_label, gradient_label,
):
    measures = _parse(parser, [(velocity_label, "101.789", "cm/s"), (gradient_label, "4,11", "mmHg")])
    assert measures[f"Vmax_{site}"] == pytest.approx(1.01789)
    assert measures[f"Grad_{site}"] == 4.11
    assert set(measures) & OUTFLOW_KEYS == {f"Vmax_{site}", f"Grad_{site}"}


@pytest.mark.parametrize("parser", PARSERS)
@pytest.mark.parametrize("site,label", [
    ("VSVE", "LVOT Vmax"), ("aorta", "Aortic Vmax"),
    ("VSVD", "RVOT Vmax"), ("pulmonar", "Pulmonary Vmax"),
])
def test_missing_gradient_stays_absent_for_an_identified_later_calculation(parser, site, label):
    measures = _parse(parser, [(label, "1.017891", "m/s")])
    assert measures[f"Vmax_{site}"] == 1.017891
    assert f"Grad_{site}" not in measures
    assert f"Grad_{site}_origem" not in measures
    assert set(measures) & OUTFLOW_KEYS == {f"Vmax_{site}"}


@pytest.mark.parametrize("parser", PARSERS)
def test_gradient_only_does_not_invent_a_velocity_or_symmetric_measurements(parser):
    measures = _parse(parser, [("maxPG VSVD", "2.57", "mmHg")])
    assert measures["Grad_VSVD"] == 2.57
    assert set(measures) & OUTFLOW_KEYS == {"Grad_VSVD"}


@pytest.mark.parametrize("parser", PARSERS)
def test_missing_gradient_unit_does_not_trigger_a_length_conversion(parser):
    measures = _parse(parser, [("Gradiente aorta", "4.11347", "")])
    assert measures["Grad_aorta"] == 4.11347


@pytest.mark.parametrize("parser", PARSERS)
def test_an_explicit_zero_gradient_is_preserved_as_imported(parser):
    measures = _parse(parser, [("RVOT Vmax", "0.8", "m/s"), ("RVOT maxPG", "0", "mmHg")])
    assert measures["Grad_VSVD"] == 0
    assert measures["Grad_VSVD_origem"] == "importado"


@pytest.mark.parametrize("parser", PARSERS)
def test_measpar_name_and_inherited_unit_preserve_explicit_source(parser):
    xml = b'''<root><parameter NAME="Doppler"><unit>cm/s</unit>
      <measpar><name>RVOT Vmax</name><aver>80.1234</aver></measpar>
    </parameter><parameter Name="LVOT maxPG">
      <measpar><aver>4.11347</aver><unit>mmHg</unit></measpar>
    </parameter></root>'''
    measures = _parse(parser, xml=xml)
    assert measures["Vmax_VSVD"] == pytest.approx(0.801234)
    assert measures["Vmax_VSVD_rotulo_origem"] == "RVOT Vmax"
    assert measures["Grad_VSVE"] == 4.11347
    assert measures["Grad_VSVE_rotulo_origem"] == "LVOT maxPG"
    assert "Vmax_pulmonar" not in measures


@pytest.mark.parametrize("parser", PARSERS)
def test_a_differently_labeled_child_is_not_copied_to_the_parent_acquisition_site(parser):
    xml = b'''<root><parameter NAME="RVOT Vmax"><measpar>
      <name>Pulmonic Vmax</name><aver>0.89</aver><unit>m/s</unit>
    </measpar></parameter></root>'''
    measures = _parse(parser, xml=xml)
    assert measures["Vmax_pulmonar"] == 0.89
    assert "Vmax_VSVD" not in measures


@pytest.mark.parametrize("parser", PARSERS)
def test_case_insensitive_nodes_and_unit_attributes(parser):
    xml = b'''<root><Parameter Name="RVOT Vmax"><Value Unit="cm/s">80.17</Value></Parameter>
      <Measpar><Name>RVOT maxPG</Name><Value Unit="mmHg">2.5731</Value></Measpar></root>'''
    measures = _parse(parser, xml=xml)
    assert measures["Vmax_VSVD"] == pytest.approx(0.8017)
    assert measures["Grad_VSVD"] == 2.5731


@pytest.mark.parametrize("parser", PARSERS)
def test_ambiguous_legacy_labels_and_regurgitation_are_not_outflow_measurements(parser):
    measures = _parse(parser, [
        ("Vmax", "1.01", "m/s"), ("maxPG", "4.11", "mmHg"),
        ("Outflow Vmax", "0.80", "m/s"), ("RVOT/Pulmonic Vmax", "0.85", "m/s"),
        ("Aortic Regurg Vmax", "2.8", "m/s"), ("Pulmonic Regurg Vmax", "2.1", "m/s"),
    ])
    assert not (set(measures) & OUTFLOW_KEYS)


@pytest.mark.parametrize("parser", PARSERS)
@pytest.mark.parametrize("value,unit", [("-0.8", "m/s"), ("nan", "m/s"), ("80", "mm/s")])
def test_invalid_or_unsupported_velocity_is_not_imported_as_a_confident_value(parser, value, unit):
    measures = _parse(parser, [("RVOT Vmax", value, unit)])
    assert "Vmax_VSVD" not in measures
    assert "Vmax_pulmonar" not in measures


@pytest.mark.parametrize("parser", PARSERS)
@pytest.mark.parametrize("value,unit", [("-2.57", "mmHg"), ("inf", "mmHg"), ("2.57", "kPa")])
def test_invalid_or_unsupported_gradient_remains_missing(parser, value, unit):
    measures = _parse(parser, [("RVOT Vmax", "0.80", "m/s"), ("RVOT maxPG", value, unit)])
    assert measures["Vmax_VSVD"] == 0.8
    assert "Grad_VSVD" not in measures
    assert "Grad_VSVD_origem" not in measures


@pytest.mark.parametrize("parser", PARSERS)
@pytest.mark.parametrize("reverse", [False, True])
def test_conflicting_explicit_velocity_labels_leave_only_that_field_unresolved(parser, reverse):
    parameters = [("RVOT Vmax", "0.8", "m/s"), ("VSVD Vmax", "1.8", "m/s")]
    if reverse:
        parameters.reverse()
    parameters.extend([("RVOT maxPG", "2.57", "mmHg"), ("RVOT Vmax P", "0.8", "m/s")])
    measures = _parse(parser, parameters)
    assert measures["Vmax_VSVD"] == OUTFLOW_MEASUREMENT_CONFLICT
    assert measures["Vmax_VSVD_origem"] == "importado"
    assert "RVOT Vmax: 0.8 m/s" in measures["Vmax_VSVD_rotulo_origem"]
    assert "VSVD Vmax: 1.8 m/s" in measures["Vmax_VSVD_rotulo_origem"]
    assert "RVOT Vmax P: 0.8 m/s" in measures["Vmax_VSVD_rotulo_origem"]
    assert measures["Grad_VSVD"] == 2.57
    assert "Vmax_pulmonar" not in measures


@pytest.mark.parametrize("parser", PARSERS)
@pytest.mark.parametrize("reverse", [False, True])
def test_equivalent_duplicate_velocities_after_unit_conversion_are_preserved(parser, reverse):
    parameters = [("RVOT Vmax", "80.1234", "cm/s"), ("VSVD Vmax", "0.801234", "m/s")]
    if reverse:
        parameters.reverse()
    measures = _parse(parser, parameters)
    assert measures["Vmax_VSVD"] == pytest.approx(0.801234)
    assert measures["Vmax_VSVD_origem"] == "importado"
    assert measures["Vmax_VSVD_rotulo_origem"] == parameters[0][0]


@pytest.mark.parametrize("parser", PARSERS)
def test_conflicting_gradients_do_not_replace_imported_evidence_with_a_calculation(parser):
    measures = _parse(parser, [
        ("LVOT Vmax", "1.01", "m/s"), ("LVOT maxPG", "4.11", "mmHg"),
        ("maxPG VSVE", "4.08", "mmHg"),
    ])
    assert measures["Vmax_VSVE"] == 1.01
    assert measures["Grad_VSVE"] == OUTFLOW_MEASUREMENT_CONFLICT
    assert measures["Grad_VSVE_origem"] == "importado"
    assert "LVOT maxPG: 4.11 mmHg" in measures["Grad_VSVE_rotulo_origem"]
    assert "maxPG VSVE: 4.08 mmHg" in measures["Grad_VSVE_rotulo_origem"]


@pytest.mark.parametrize("parser", PARSERS)
def test_xml_gradient_conflict_survives_save_reopen_and_blocks_pdf_fallback(parser):
    from app.api.v1.endpoints.laudos import _montar_descricao_ecocardiograma
    from app.utils.ecocardiograma_medidas import extrair_medidas_ecocardiograma_da_descricao
    from app.utils.pdf_laudo import derivar_gradientes_saidas_para_pdf, parametros_saidas_para_pdf

    measures = _parse(parser, [
        ("LVOT Vmax", "1.01", "m/s"), ("LVOT maxPG", "4.11", "mmHg"),
        ("maxPG VSVE", "4.08", "mmHg"),
    ])
    saved = _montar_descricao_ecocardiograma({key: str(value) for key, value in measures.items()}, {})
    reopened = extrair_medidas_ecocardiograma_da_descricao(saved)
    payload = {"medidas": reopened}
    derivar_gradientes_saidas_para_pdf(payload)

    assert reopened["Grad_VSVE"] == OUTFLOW_MEASUREMENT_CONFLICT
    assert reopened["Grad_VSVE_origem"] == "importado"
    assert "4.11 mmHg" in reopened["Grad_VSVE_rotulo_origem"]
    assert "4.08 mmHg" in reopened["Grad_VSVE_rotulo_origem"]
    field = next(item for item in parametros_saidas_para_pdf(reopened) if item["chave"] == "Grad_VSVE")
    assert field["value_unconfirmed"] is True
    assert "calculado" not in field["label"]


@pytest.mark.parametrize("parser", PARSERS)
def test_invalid_or_unlabeled_values_do_not_create_a_conflict_with_explicit_evidence(parser):
    measures = _parse(parser, [
        ("RVOT Vmax", "80", "mm/s"), ("VSVD Vmax", "-1.8", "m/s"),
        ("Vmax", "2.8", "m/s"), ("RVOT Vmax P", "0.8", "m/s"),
    ])
    assert measures["Vmax_VSVD"] == 0.8
    assert measures["Vmax_VSVD_rotulo_origem"] == "RVOT Vmax P"


def test_xml_import_job_uses_the_corrected_real_parser_and_keeps_metadata():
    from app.services.xml_import_jobs import parse_xml_import_content

    with redirect_stdout(StringIO()):
        result = parse_xml_import_content("exame.xml", _xml([
            ("RVOT Vmax P", "0.80", "m/s"), ("RVOT maxPG", "2.57", "mmHg"),
        ]))
    assert result["medidas"]["Vmax_VSVD"] == 0.8
    assert result["medidas"]["Grad_VSVD"] == 2.57
    assert result["medidas"]["Grad_VSVD_origem"] == "importado"
    assert "Vmax_pulmonar" not in result["medidas"]
