"""Serviço de consulta de CNPJ via API minima.receita.org (gratuita)."""
import logging
from typing import Optional

import httpx

from app.schemas.fiscal import CNPJConsultaResponse

logger = logging.getLogger(__name__)

# API minima.receita.org - Dados abertos da Receita Federal
CNPJ_API_URL = "https://minhareceita.org/api/cnpj/{cnpj}"


def _clean_cnpj(cnpj: str) -> str:
    """Remove pontuacao do CNPJ."""
    return "".join(c for c in cnpj if c.isdigit())


def consultar_cnpj(cnpj: str) -> CNPJConsultaResponse:
    """
    Consulta dados de uma empresa pelo CNPJ na API minima.receita.org.

    API: https://minhareceita.org/api/cnpj/{cnpj}
    Dados abertos da Receita Federal. Sem autenticação necessária.

    Returns:
        CNPJConsultaResponse com dados da empresa ou campo `error` preenchido.
    """
    cnpj_limpo = _clean_cnpj(cnpj)

    if len(cnpj_limpo) != 14:
        return CNPJConsultaResponse(error="CNPJ deve conter 14 dígitos.")

    try:
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            response = client.get(CNPJ_API_URL.format(cnpj=cnpj_limpo))

        # Erro 400 = CNPJ inválido ou não encontrado
        if response.status_code == 400:
            try:
                data = response.json()
                return CNPJConsultaResponse(error=data.get("message", "CNPJ inválido ou não encontrado."))
            except Exception:
                return CNPJConsultaResponse(error="CNPJ inválido ou não encontrado.")

        if response.status_code != 200:
            return CNPJConsultaResponse(error=f"Erro HTTP {response.status_code} na consulta.")

        data = response.json()

        if not isinstance(data, dict):
            return CNPJConsultaResponse(error="Resposta inválida da API.")

        # Telefone: DDD incluso no campo ddd_telefone_1 (ex: "8532527020")
        telefone_raw = data.get("ddd_telefone_1") or data.get("ddd_telefone_2")
        telefone = None
        if telefone_raw and len(telefone_raw) >= 10:
            telefone = f"({telefone_raw[:2]}) {telefone_raw[2:]}"
        elif telefone_raw:
            telefone = telefone_raw

        # CNAE com descricao
        cnae_code = data.get("cnae_fiscal")
        cnae_desc = data.get("cnae_fiscal_descricao", "")

        return CNPJConsultaResponse(
            razao_social=data.get("razao_social"),
            nome_fantasia=data.get("nome_fantasia"),
            cnpj=data.get("cnpj"),
            logradouro=data.get("logradouro"),
            numero=data.get("numero"),
            complemento=data.get("complemento"),
            bairro=data.get("bairro"),
            municipio=data.get("municipio"),
            uf=data.get("uf"),
            cep=data.get("cep"),
            telefone=telefone,
            email=data.get("email"),  # Receita Federal nao expõe email nos dados públicos
            cnae_principal=str(cnae_code) if cnae_code else None,
            situacao=data.get("descricao_situacao_cadastral"),
        )

    except httpx.TimeoutException:
        logger.warning(f"[CNPJ Consulta] Timeout ao consultar {cnpj_limpo}")
        return CNPJConsultaResponse(error="Timeout na consulta. Tente novamente em instantes.")
    except httpx.HTTPStatusError as exc:
        logger.warning(f"[CNPJ Consulta] HTTP error {exc.response.status_code}: {cnpj_limpo}")
        return CNPJConsultaResponse(error=f"Erro HTTP {exc.response.status_code} na consulta.")
    except Exception as exc:
        logger.exception(f"[CNPJ Consulta] Erro inesperado ao consultar {cnpj_limpo}: {exc}")
        return CNPJConsultaResponse(error="Erro inesperado na consulta do CNPJ.")
