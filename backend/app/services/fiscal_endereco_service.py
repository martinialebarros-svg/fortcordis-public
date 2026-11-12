"""Seleção contábil de endereço, sem escrita ou chamada a provedores de mapas."""
from pydantic import ValidationError

from app.schemas.clinica_fiscal import EnderecoFiscal

CAMPOS_ENDERECO = ("endereco", "numero", "complemento", "bairro", "cidade", "estado", "cep")


def resolver_endereco(tomador, tipo: str, documento: str):
    fiscal = getattr(tomador, "endereco_fiscal", None) if tipo == "PJ" else None
    if fiscal is None:
        return ({field: str(getattr(tomador, field, None) or "").strip() for field in CAMPOS_ENDERECO},
                {"cliente_endereco_origem": "cadastro_operacional", "cliente_endereco_fonte": "", "cliente_endereco_conferido_em": ""}, [])
    # Endereço fiscal é um conjunto completo. Cadastro incompleto/desvinculado
    # fica pendente, sem misturar silenciosamente campos operacionais.
    try:
        if not isinstance(fiscal, dict):
            raise ValueError
        payload = EnderecoFiscal.model_validate({k: v for k, v in fiscal.items() if k not in {"conferido_em", "conferido_por"}})
        if payload.cnpj != documento:
            raise ValueError
    except (ValueError, ValidationError):
        return ({field: "" for field in CAMPOS_ENDERECO},
                {"cliente_endereco_origem": "fiscal_pendente", "cliente_endereco_fonte": "", "cliente_endereco_conferido_em": ""},
                ["Endereço fiscal incompleto ou vinculado a outro CNPJ. Confira o cadastro fiscal da clínica."])
    return ({field: getattr(payload, field) for field in CAMPOS_ENDERECO},
            {"cliente_endereco_origem": "cadastro_cnpj", "cliente_endereco_fonte": payload.fonte_url,
             "cliente_endereco_conferido_em": str(fiscal.get("conferido_em") or "")}, [])
