"""Regression for distinct feline atrial, LVOT and aortic XML measurements."""

from contextlib import redirect_stdout
from io import StringIO

from app.utils.xml_parser import parse_xml_eco as parse_xml_eco_v1
from app.utils.xml_parser_v2 import parse_xml_eco as parse_xml_eco_v2


XML_WITH_DISTINCT_SOURCES = b"""<root>
  <parameter NAME="LADmax"><aver>1.8</aver><unit>cm</unit></parameter>
  <parameter NAME="LADmin"><aver>1.35</aver><unit>cm</unit></parameter>
  <parameter NAME="LAA Vmax"><aver>0.18</aver><unit>m/s</unit></parameter>
  <parameter NAME="LA FS"><aver>25</aver><unit>%</unit></parameter>
  <parameter NAME="LVOT Vmax"><aver>2.5</aver><unit>m/s</unit></parameter>
  <parameter NAME="Aortic Vmax"><aver>0.69</aver><unit>m/s</unit></parameter>
  <parameter NAME="LVOT maxPG"><aver>25</aver><unit>mmHg</unit></parameter>
</root>"""


def test_xml_parsers_keep_feline_markers_separate():
    for parser in (parse_xml_eco_v1, parse_xml_eco_v2):
        with redirect_stdout(StringIO()):
            medidas = parser(XML_WITH_DISTINCT_SOURCES)["medidas"]
        assert medidas["AE_diametro_max"] == 18
        assert medidas["AE_diametro_min"] == 13.5
        assert medidas["Fluxo_auricular"] == 0.18
        assert medidas["Fracao_encurtamento_AE"] == 25
        assert medidas["Vmax_VSVE"] == 2.5
        assert medidas["Vmax_aorta"] == 0.69
        assert medidas["Grad_VSVE"] == 25
        assert "Aorta" not in medidas
        assert "Atrio_esquerdo" not in medidas


def test_xml_explicit_millimeters_are_not_converted_twice():
    xml = XML_WITH_DISTINCT_SOURCES.replace(b"1.8</aver><unit>cm", b"1.8</aver><unit>mm")
    for parser in (parse_xml_eco_v1, parse_xml_eco_v2):
        with redirect_stdout(StringIO()):
            medidas = parser(xml)["medidas"]
        assert medidas["AE_diametro_max"] == 1.8


def test_xml_converts_explicit_centimeters_per_second_for_laa_flow():
    xml = XML_WITH_DISTINCT_SOURCES.replace(
        b"0.18</aver><unit>m/s", b"18</aver><unit>cm/s"
    )
    for parser in (parse_xml_eco_v1, parse_xml_eco_v2):
        with redirect_stdout(StringIO()):
            medidas = parser(xml)["medidas"]
        assert medidas["Fluxo_auricular"] == 0.18
