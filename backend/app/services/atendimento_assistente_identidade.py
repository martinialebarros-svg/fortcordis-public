"""Identity checks shared by clinical validation and explicit veterinary review."""
from __future__ import annotations

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
