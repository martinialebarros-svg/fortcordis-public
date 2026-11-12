"""Read explicitly labeled outflow measurements without changing acquisition sites."""

import math
import re
import unicodedata
from typing import Any


OUTFLOW_MEASUREMENT_CONFLICT = "Conflito de medidas no exame de origem"


_OUTFLOW_LABELS = (
    (
        "VSVE",
        ("LVOT Vmax P", "LVOT Vmax", "Vmáx VSVE", "Vmax VSVE", "VSVE Vmax", "VSVE Vmáx",
         "Left ventricular outflow tract Vmax", "Vmax via de saída do ventrículo esquerdo"),
        ("LVOT maxPG", "LVOT max PG", "máxPG VSVE", "VSVE maxPG", "Gradiente VSVE",
         "Grad VSVE", "VSVE Grad", "LVOT peak gradient", "LVOT PGmax"),
    ),
    (
        "aorta",
        ("Aortic Vmax", "Aortic Vmax P", "Aorta Vmax", "Vmax aorta", "Vmax aórtico",
         "Vmax aórtica", "AV Vmax", "AV Vmax P", "Ao Vmax", "Vmax Ao"),
        ("Aortic maxPG", "Aortic max PG", "Aorta maxPG", "maxPG aorta", "Gradiente aorta",
         "Gradiente aórtico", "Gradiente aórtica", "Grad aorta", "AV maxPG", "Ao maxPG",
         "Aortic peak gradient"),
    ),
    (
        "VSVD",
        ("RVOT Vmax P", "RVOT Vmax", "Vmáx VSVD", "Vmax VSVD", "VSVD Vmax", "VSVD Vmáx",
         "Right ventricular outflow tract Vmax", "Vmax via de saída do ventrículo direito"),
        ("RVOT maxPG", "RVOT max PG", "máxPG VSVD", "VSVD maxPG", "Gradiente VSVD",
         "Grad VSVD", "VSVD Grad", "RVOT peak gradient", "RVOT PGmax"),
    ),
    (
        "pulmonar",
        ("Pulmonic Vmax", "Pulmonic Vmax P", "Pulmonary Vmax", "Pulmonar Vmax",
         "Vmax pulmonar", "PV Vmax", "PV Vmax P"),
        ("Pulmonic maxPG", "Pulmonic max PG", "Pulmonary maxPG", "Pulmonar maxPG",
         "maxPG pulmonar", "Gradiente pulmonar", "Grad pulmonar", "PV maxPG",
         "Pulmonary peak gradient"),
    ),
)


def _normalize_label(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").strip().lower())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", text)


def _attribute(item, name: str) -> str:
    return next((str(value) for key, value in item.attrs.items() if key.lower() == name), "")


def _child(item, names):
    return item.find(lambda tag: str(tag.name).lower() in names, recursive=False)


def _label(item) -> str:
    name_node = _child(item, {"name"})
    return (_attribute(item, "name") or (name_node.get_text() if name_node else "")).strip()


def _read_measurement(item, velocity: bool):
    """Read only the matching container, never another named child measurement."""
    value_container = item
    value_node = _child(value_container, {"aver", "val", "value"})
    if value_node is None and str(item.name).lower() == "parameter":
        children = item.find_all(lambda tag: str(tag.name).lower() == "measpar", recursive=False)
        if len(children) != 1:
            return None
        child_label = _label(children[0])
        if child_label and _normalize_label(child_label) != _normalize_label(_label(item)):
            return None
        value_container = children[0]
        value_node = _child(value_container, {"aver", "val", "value"})
    if value_node is None:
        return None

    # Preserve the imported precision. Reject negative/non-finite measurements.
    match = re.match(r"^\s*([+-]?\d+(?:[.,]\d+)?(?:[eE][+-]?\d+)?)", value_node.get_text())
    if not match:
        return None
    value = float(match.group(1).replace(",", "."))
    if not math.isfinite(value) or value < 0:
        return None

    unit_node = _child(value_container, {"unit"})
    if unit_node is None and value_container is not item:
        unit_node = _child(item, {"unit"})
    if unit_node is None and str(item.name).lower() == "measpar" and item.parent:
        unit_node = _child(item.parent, {"unit"})
    unit = ((unit_node.get_text() if unit_node else "") or _attribute(value_node, "unit")
            or _attribute(value_container, "unit") or _attribute(item, "unit"))
    # A unit included with the numeric value is explicit evidence too.
    if not unit:
        unit = value_node.get_text()[match.end():].strip()
    unit = unit.strip().lower().replace(" ", "")
    if velocity:
        if unit == "cm/s":
            return value / 100
        return value if unit in {"", "m/s"} else None
    return value if unit in {"", "mmhg"} else None


def extract_outflow_measurements(soup) -> dict[str, Any]:
    """Return only imported fields with an explicit, exact anatomical label.

    A missing gradient stays absent here. A conflict remains explicitly filled
    for confirmation, preventing presentation layers from treating it as an
    absent gradient and replacing the conflicting evidence with a calculation.
    """
    fields = {}
    for site, velocity_names, gradient_names in _OUTFLOW_LABELS:
        for prefix, names, velocity in (("Vmax", velocity_names, True), ("Grad", gradient_names, False)):
            for name in names:
                fields[_normalize_label(name)] = (f"{prefix}_{site}", velocity)

    measurements = {}
    conflicts = set()
    source_details = {}
    for item in soup.find_all(lambda tag: str(tag.name).lower() in {"parameter", "measpar"}):
        original_label = _label(item)
        field = fields.get(_normalize_label(original_label))
        if field is None:
            continue
        key, velocity = field
        value = _read_measurement(item, velocity)
        if value is None:
            continue
        detail = f"{original_label}: {value} {'m/s' if velocity else 'mmHg'}"
        source_details.setdefault(key, [])
        if detail not in source_details[key]:
            source_details[key].append(detail)
        if key in conflicts:
            measurements[f"{key}_rotulo_origem"] = " | ".join(source_details[key])
            continue
        if key in measurements:
            # Unit conversion can introduce binary floating-point noise. Any
            # meaningful disagreement leaves this field explicitly unresolved, regardless
            # of the order of the explicit labels in the source XML.
            if not math.isclose(measurements[key], value, rel_tol=1e-12, abs_tol=0):
                conflicts.add(key)
                measurements[key] = OUTFLOW_MEASUREMENT_CONFLICT
                measurements[f"{key}_rotulo_origem"] = " | ".join(source_details[key])
            continue
        measurements[key] = value
        measurements[f"{key}_origem"] = "importado"
        measurements[f"{key}_rotulo_origem"] = original_label
    return measurements
