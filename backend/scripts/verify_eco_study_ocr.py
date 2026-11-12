#!/usr/bin/env python3
from __future__ import annotations

import io
import json
from pathlib import Path
import sys

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.eco_study_extraction_service import parse_eco_study_import_content

EXPECTED_MEASUREMENTS = {
    "DIVEd": 32.4,
    "DIVES": 21,
    "SIVd": 7.1,
    "PLVEd": 6.9,
    "FE_Teicholz": 62,
    "DeltaD_FS": 35,
    "AE_Ao": 1.62,
    "IT_Vmax": 3.25,
}


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "DejaVuSans.ttf",
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def build_synthetic_study_image() -> bytes:
    heading_font = _load_font(34)
    measure_font = _load_font(25)
    image = Image.new("RGB", (1500, 950), "#071018")
    draw = ImageDraw.Draw(image)
    draw.ellipse((100, 120, 850, 820), outline="#69737a", width=4)
    draw.text((930, 75), "MEASUREMENTS", font=heading_font, fill="white")
    lines = (
        "LVIDd 3.24 cm",
        "LVIDs 2.10 cm",
        "IVSd 0.71 cm",
        "LVPWd 0.69 cm",
        "EF Teich 62 %",
        "FS 35 %",
        "LA/Ao 1.62",
        "TR Vmax 3.25 m/s",
    )
    for index, line in enumerate(lines):
        draw.text((930, 145 + index * 74), line, font=measure_font, fill="#f4f4f4")

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def build_scanned_pdf(image_content: bytes) -> bytes:
    buffer = io.BytesIO()
    document = canvas.Canvas(buffer, pagesize=(1500, 950))
    document.drawImage(
        ImageReader(io.BytesIO(image_content)),
        0,
        0,
        width=1500,
        height=950,
    )
    document.showPage()
    document.save()
    return buffer.getvalue()


def _validate(label: str, payload: dict) -> None:
    measurements = payload.get("medidas") or {}
    if measurements != EXPECTED_MEASUREMENTS:
        raise RuntimeError(
            f"{label}: medidas divergentes. "
            f"esperado={EXPECTED_MEASUREMENTS!r} obtido={measurements!r}"
        )
    print(
        json.dumps(
            {
                "source": label,
                "measurements": measurements,
                "meta": payload.get("meta_importacao_estudo"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


def main() -> int:
    image_content = build_synthetic_study_image()
    image_payload = parse_eco_study_import_content("synthetic-ultrasound.png", image_content)
    _validate("image", image_payload)

    pdf_content = build_scanned_pdf(image_content)
    pdf_payload = parse_eco_study_import_content("synthetic-scanned.pdf", pdf_content)
    _validate("scanned_pdf", pdf_payload)
    print("eco-study OCR smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
