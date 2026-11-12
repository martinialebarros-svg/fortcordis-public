"""Identity checks shared by clinical validation and explicit veterinary review."""
from __future__ import annotations

import unicodedata


DECISAO_RACA_PENDENTE = "mesmo_paciente_raca_pendente"
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


def impedimento_revisao_raca(fonte: dict, context: dict) -> str | None:
    """Never classify an opaque AI warning as breed-only; the vet must attest it."""
    patient = context.get("paciente", {})
    expected_name, name = normal(patient.get("nome")), normal(fonte.get("paciente_nome"))
    if not expected_name or not name:
        return "Confirme a identificação do paciente no documento; o nome está ausente."
    if expected_name != name:
        return "O nome no documento difere do paciente. Esta opção é somente para raça."
    expected_species, extracted = species(patient.get("especie")), species(fonte.get("especie"))
    if not expected_species or not extracted:
        return "A espécie precisa estar identificada no cadastro e no documento."
    if expected_species != extracted:
        return "A espécie no documento difere do paciente. Esta opção é somente para raça."
    return None


def revisao_raca_aplicavel(fonte: dict, context: dict, revisao: dict | None) -> bool:
    """Only consume a server-bound review, never a model-generated assertion."""
    return bool(isinstance(revisao, dict)
                and revisao.get("decisao") == DECISAO_RACA_PENDENTE
                and type(revisao.get("usuario_id")) is int and revisao["usuario_id"] > 0
                and isinstance(revisao.get("registrado_em"), str) and revisao["registrado_em"].strip()
                and impedimento_revisao_raca(fonte, context) is None)
