"""Identity checks shared by clinical validation and explicit veterinary review."""
from __future__ import annotations

from copy import deepcopy
import unicodedata


DECISAO_RACA_PENDENTE = "mesmo_paciente_raca_pendente"
DECISAO_NOME_IDADE = "mesmo_paciente_nome_idade"
AVISO_RACA_PENDENTE = (
    "Raça pendente de revisão veterinária. A identidade dos documentos selecionados "
    "foi confirmada pelo veterinário; o cadastro e os originais não foram alterados. "
    "Não presuma uma raça para orientar a conduta."
)


def normal(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    return " ".join("".join(c for c in text if not unicodedata.combining(c)).casefold().split())


def species(value: str | None) -> str:
    text = normal(value)
    return {"canina": "canina", "canino": "canina", "cao": "canina", "cachorro": "canina",
            "felina": "felina", "felino": "felina", "gato": "felina"}.get(text, text)


def impedimento_revisao_identidade(fonte: dict, context: dict) -> str | None:
    patient = context.get("paciente", {})
    if not normal(patient.get("nome")) or not normal(fonte.get("paciente_nome")):
        return "Confirme a identificação do paciente no documento; o nome está ausente."
    expected_species, extracted = species(patient.get("especie")), species(fonte.get("especie"))
    if not expected_species or not extracted:
        return "A espécie precisa estar identificada no cadastro e no documento."
    if expected_species != extracted:
        return "A espécie no documento difere do paciente. Confira o original e o cadastro."
    return None


def impedimento_revisao_raca(fonte: dict, context: dict) -> str | None:
    """Never classify an opaque AI warning as breed-only; the vet must attest it."""
    expected_name, name = normal(context.get("paciente", {}).get("nome")), normal(fonte.get("paciente_nome"))
    if expected_name and name and expected_name != name:
        return "O nome no documento difere do paciente. Esta opção é somente para raça."
    return impedimento_revisao_identidade(fonte, context)


def _decisao_registrada(revisao: dict | None, decisao: str) -> bool:
    return bool(isinstance(revisao, dict) and revisao.get("decisao") == decisao
                and type(revisao.get("usuario_id")) is int and revisao["usuario_id"] > 0
                and isinstance(revisao.get("registrado_em"), str) and revisao["registrado_em"].strip())


def revisao_identidade_aplicavel(fonte: dict, context: dict, revisao: dict | None) -> bool:
    return _decisao_registrada(revisao, DECISAO_NOME_IDADE) and impedimento_revisao_identidade(fonte, context) is None


def revisao_raca_aplicavel(fonte: dict, context: dict, revisao: dict | None) -> bool:
    """Only consume a server-bound review, never a model-generated assertion."""
    return _decisao_registrada(revisao, DECISAO_RACA_PENDENTE) and impedimento_revisao_raca(fonte, context) is None


AVISO_IDENTIDADE_ACHADO = "Identidade não confirmada: este achado não pode ser incorporado ao paciente."
PENDENCIA_IDENTIDADE_LEGADA = "Corrija ou remova os arquivos com identificação divergente ou não confirmada e refaça a análise."
ERROS_IDENTIDADE_LEGADOS = {
    "Há identificações pendentes. Confira os documentos antes de continuar a análise.",
    "Há exames aguardando conferência no contexto atualizado.",
    "O contexto da revisão mudou. Confira novamente a identificação.",
    "A revisão mudou durante a análise. Confira novamente a identificação.",
}


def normalizar_vinculo_anexos(resultado: dict) -> dict:
    """Project historical readings under the attachment association policy.

    The document's demographics remain source evidence. Only messages created by
    the former identity gate are removed, and no clinical value is reconstructed.
    """
    result = deepcopy(resultado)
    result["bloqueado_integracao"] = False
    for finding in result.get("achados_exames", []):
        finding["alertas"] = list(dict.fromkeys(
            notice for notice in finding.get("alertas", []) if notice != AVISO_IDENTIDADE_ACHADO
        ))
    for field in ("pendencias", "avisos"):
        result[field] = list(dict.fromkeys(
            notice for notice in result.get(field, [])
            if notice not in {AVISO_IDENTIDADE_ACHADO, PENDENCIA_IDENTIDADE_LEGADA}
        ))
    return result
