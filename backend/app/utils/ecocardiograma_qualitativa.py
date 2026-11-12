"""Leitura conservadora dos blocos qualitativos já salvos no laudo eco."""
from __future__ import annotations

import re
import unicodedata


CAMPOS_QUALITATIVOS = ("valvas", "camaras", "funcao", "pericardio", "vasos", "ad_vd")
_MARCADOR_CAMPO = re.compile(
    r"^\s*-\s*(valvas|camaras|funcao|pericardio|vasos|ad_vd)\s*:\s*(.*)$",
    re.IGNORECASE,
)


def _cabecalho_qualitativo(linha: str) -> bool:
    if not linha.lstrip().startswith("##"):
        return False
    normalizada = unicodedata.normalize("NFKD", linha)
    normalizada = normalizada.encode("ascii", "ignore").decode("ascii").lower()
    return "qualitativa" in normalizada and "avalia" in normalizada


def extrair_qualitativa_ecocardiograma_da_descricao(descricao: str | None) -> dict[str, str]:
    """Preserva itens e quebras de linha até o próximo campo conhecido ou seção."""
    if not descricao:
        return {}

    resultados: dict[str, str] = {}
    campo_atual: str | None = None
    linhas_campo: list[str] = []
    dentro_da_secao = False

    def guardar() -> None:
        if campo_atual:
            texto = "\n".join(linhas_campo).strip()
            if texto:
                resultados[campo_atual] = texto

    for linha in descricao.splitlines():
        if linha.lstrip().startswith("##"):
            if dentro_da_secao:
                break
            dentro_da_secao = _cabecalho_qualitativo(linha)
            continue
        if not dentro_da_secao:
            continue
        marcador = _MARCADOR_CAMPO.match(linha)
        if marcador:
            guardar()
            campo_atual = marcador.group(1).lower()
            linhas_campo = [marcador.group(2)] if marcador.group(2) else []
        elif campo_atual:
            linhas_campo.append(linha)

    guardar()
    return resultados
