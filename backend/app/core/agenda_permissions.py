from typing import Any


PAPEIS_QUE_PODEM_EXCLUIR_AGENDAMENTO = (
    "admin",
    "secretaria",
    "secretária",
    "recepcao",
    "recepção",
)


def usuario_pode_excluir_agendamento(usuario: Any) -> bool:
    """Retorna True quando o usuario pode excluir um agendamento."""
    tem_papel = getattr(usuario, "tem_papel", None)
    if not callable(tem_papel):
        return False

    for papel in PAPEIS_QUE_PODEM_EXCLUIR_AGENDAMENTO:
        try:
            if bool(tem_papel(papel)):
                return True
        except Exception:
            return False
    return False
