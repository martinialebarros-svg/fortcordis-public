"""Address automation helpers (ViaCEP + Google Geocoding)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.services.google_maps_cost_control import authorize_google_call


class GeocodingError(Exception):
    pass


def normalizar_cep(cep: Optional[str]) -> str:
    digits = "".join(ch for ch in str(cep or "") if ch.isdigit())
    return digits[:8]


def _http_get_json(url: str, timeout: float = 8.0) -> dict:
    req = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "FortCordis/1.0",
        },
    )
    with urlopen(req, timeout=timeout) as resp:
        payload = resp.read().decode("utf-8", errors="replace")
    return json.loads(payload or "{}")


def buscar_cep_viacep(cep: str) -> dict:
    cep_norm = normalizar_cep(cep)
    if len(cep_norm) != 8:
        raise GeocodingError("CEP invalido. Informe 8 digitos.")

    url = f"https://viacep.com.br/ws/{cep_norm}/json/"
    try:
        data = _http_get_json(url)
    except Exception as exc:
        raise GeocodingError(f"Falha ao consultar ViaCEP: {exc}") from exc

    if data.get("erro"):
        raise GeocodingError("CEP nao encontrado no ViaCEP.")

    return {
        "cep": normalizar_cep(data.get("cep")),
        "logradouro": str(data.get("logradouro") or "").strip(),
        "complemento": str(data.get("complemento") or "").strip(),
        "bairro": str(data.get("bairro") or "").strip(),
        "cidade": str(data.get("localidade") or "").strip(),
        "estado": str(data.get("uf") or "").strip().upper(),
        "ibge": str(data.get("ibge") or "").strip(),
    }


def montar_endereco_completo(
    *,
    endereco: Optional[str],
    numero: Optional[str],
    complemento: Optional[str],
    bairro: Optional[str],
    cidade: Optional[str],
    estado: Optional[str],
    cep: Optional[str],
) -> str:
    partes = [
        str(endereco or "").strip(),
        str(numero or "").strip(),
        str(complemento or "").strip(),
        str(bairro or "").strip(),
        str(cidade or "").strip(),
        str(estado or "").strip().upper(),
        str(cep or "").strip(),
        "Brasil",
    ]
    return ", ".join([p for p in partes if p])


@dataclass
class GeocodeResult:
    latitude: float
    longitude: float
    endereco_normalizado: str
    place_id: str
    bairro: str
    cidade: str
    estado: str
    cep: str


def _extract_component(components: list[dict], accepted_types: set[str]) -> tuple[str, str]:
    for comp in components:
        types = set(str(item) for item in (comp.get("types") or []))
        if types.intersection(accepted_types):
            long_name = str(comp.get("long_name") or "").strip()
            short_name = str(comp.get("short_name") or "").strip()
            return long_name, short_name
    return "", ""


def geocodificar_endereco_google(endereco_completo: str, api_key: str) -> GeocodeResult:
    if not api_key:
        raise GeocodingError("GOOGLE_MAPS_API_KEY nao configurada no backend.")
    if not str(endereco_completo or "").strip():
        raise GeocodingError("Endereco vazio para geocoding.")

    params = urlencode(
        {
            "address": endereco_completo,
            "key": api_key,
            "language": "pt-BR",
            "region": "br",
        }
    )
    url = f"https://maps.googleapis.com/maps/api/geocode/json?{params}"

    authorize_google_call("geocoding")
    try:
        data = _http_get_json(url)
    except Exception:
        # Provider exception strings may contain the URL, key and full address.
        raise GeocodingError("Falha ao consultar Google Geocoding. Inicie uma nova consulta para tentar novamente.") from None

    status = str(data.get("status") or "").strip().upper()
    if status != "OK":
        safe_statuses = {"ZERO_RESULTS", "OVER_DAILY_LIMIT", "OVER_QUERY_LIMIT", "REQUEST_DENIED", "INVALID_REQUEST", "UNKNOWN_ERROR"}
        detail = status if status in safe_statuses else "erro_desconhecido"
        raise GeocodingError(f"Google Geocoding retornou erro ({detail}).")

    results = data.get("results") or []
    if not isinstance(results, list) or not results:
        raise GeocodingError("Google Geocoding nao retornou resultados.")

    result = results[0] or {}
    geometry = result.get("geometry") or {}
    location = geometry.get("location") or {}
    lat = location.get("lat")
    lng = location.get("lng")
    if lat is None or lng is None:
        raise GeocodingError("Resultado do geocoding sem latitude/longitude.")

    components = result.get("address_components") or []
    bairro, _ = _extract_component(
        components,
        {"neighborhood", "sublocality", "sublocality_level_1"},
    )
    cidade, _ = _extract_component(
        components,
        {"locality", "administrative_area_level_2"},
    )
    _estado_long, estado_short = _extract_component(
        components,
        {"administrative_area_level_1"},
    )
    cep_long, _cep_short = _extract_component(components, {"postal_code"})

    return GeocodeResult(
        latitude=float(lat),
        longitude=float(lng),
        endereco_normalizado=str(result.get("formatted_address") or "").strip(),
        place_id=str(result.get("place_id") or "").strip(),
        bairro=bairro,
        cidade=cidade,
        estado=estado_short.upper(),
        cep=normalizar_cep(cep_long),
    )

