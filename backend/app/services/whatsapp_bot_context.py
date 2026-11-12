"""Recorte seguro do contexto por persona (Fase 4, RF-016/017, CA-013/023).

Por que este modulo existe: `resolve_whatsapp_context` devolve listas PLANAS
(`clinicas`, `tutores`, `pets`) que nao carregam marca de origem, e no caso
`ambiguous` as listas `clinicas`/`tutores` vem POPULADAS com os nomes dos
candidatos. Despejar esse dict no prompt faria um numero reatribuido vazar o
nome do cliente anterior. O corte tem que ser no codigo, antes de montar o
prompt - instrucao de prompt nao e mecanismo de autorizacao.

Regras aplicadas aqui:
- `resolution != "matched"` -> nenhum dado de registro entra (RF-016).
- persona tutor: so os proprios pets, filtrados defensivamente por
  `pet["tutor_id"]`; nunca as listas `tutores`/`clinicas` inteiras.
- persona clinica: so linhas com `clinica_id` igual ao escopo; nunca varre
  `tutores`.
- ordens de servico NUNCA entram: `numero_os`, `valor_final` e `status`
  ('Pendente' = cobranca em aberto) sao proibidos nas duas personas
  (RF-019/CA-024), mesmo estando disponiveis no payload.
- agendamento com status nao ativo nao entra: `_relevant_appointments` nao
  filtra status, e confirmar consulta cancelada e promessa de prazo falsa.
"""
from __future__ import annotations

from typing import Any, Optional

# Status de agendamento que ainda valem como compromisso. 'Cancelado',
# 'Faltou' e 'Expirado' ficam de fora de proposito.
STATUS_AGENDAMENTO_ATIVO = frozenset({"agendado", "reservado", "confirmado"})

MAX_PETS = 6
MAX_AGENDAMENTOS = 3


def _ativo(status: Any) -> bool:
    return str(status or "").strip().lower() in STATUS_AGENDAMENTO_ATIVO


def build_safe_context(
    contexto: dict[str, Any],
    *,
    match_type: Optional[str],
    tutor_id: Optional[int],
    clinica_id: Optional[int],
) -> dict[str, Any]:
    """Contexto minimo e por persona que pode ir para o prompt."""
    resolution = str(contexto.get("resolution") or "not_found")

    # RF-016: em `ambiguous`/`not_found` o bot nao menciona NENHUM dado de
    # registro - nem nome de pet, nem agendamento, nem clinica.
    if resolution != "matched" or match_type not in ("tutor", "clinica"):
        return {"resolucao": resolution, "persona": None, "tem_dados_do_cliente": False}

    if match_type == "tutor":
        return _contexto_tutor(contexto, tutor_id=tutor_id)
    return _contexto_clinica(contexto, clinica_id=clinica_id)


def _contexto_tutor(contexto: dict[str, Any], *, tutor_id: Optional[int]) -> dict[str, Any]:
    pets_brutos = contexto.get("pets") or []
    # Filtro defensivo: o payload monta agendamentos com
    # or_(tutor_id == X, paciente_id in pets_de_X), entao um agendamento com
    # tutor_id correto e paciente_id de OUTRO tutor (erro de digitacao na
    # agenda) traz o pet do outro tutor para dentro da lista.
    pets = [
        {"nome": p.get("nome"), "especie": p.get("especie")}
        for p in pets_brutos
        if isinstance(p, dict) and tutor_id is not None and p.get("tutor_id") == tutor_id
    ][:MAX_PETS]

    pet_ids = {
        p.get("id")
        for p in pets_brutos
        if isinstance(p, dict) and p.get("tutor_id") == tutor_id
    }
    agendamentos = [
        {
            "inicio": a.get("inicio"),
            "status": a.get("status"),
            "pet_nome": a.get("pet_nome"),
            "servico_nome": a.get("servico_nome"),
        }
        for a in (contexto.get("agendamentos") or [])
        if isinstance(a, dict)
        and _ativo(a.get("status"))
        and (
            a.get("pet_id") in pet_ids
            or (a.get("pet_id") is None and a.get("tutor_id") == tutor_id)
        )
    ][:MAX_AGENDAMENTOS]

    return {
        "resolucao": "matched",
        "persona": "tutor",
        "tem_dados_do_cliente": True,
        "pets": pets,
        "agendamentos_ativos": agendamentos,
    }


def _contexto_clinica(contexto: dict[str, Any], *, clinica_id: Optional[int]) -> dict[str, Any]:
    clinicas = [
        c for c in (contexto.get("clinicas") or [])
        if isinstance(c, dict) and c.get("id") == clinica_id
    ]
    agendamentos = [
        {
            "inicio": a.get("inicio"),
            "status": a.get("status"),
            "servico_nome": a.get("servico_nome"),
        }
        for a in (contexto.get("agendamentos") or [])
        if isinstance(a, dict) and _ativo(a.get("status")) and a.get("clinica_id") == clinica_id
    ][:MAX_AGENDAMENTOS]

    return {
        "resolucao": "matched",
        "persona": "clinica",
        "tem_dados_do_cliente": True,
        # So a propria clinica, resolvida por id - nunca a lista inteira.
        "clinica_nome": clinicas[0].get("nome") if clinicas else None,
        # Nome de tutor e de pet de terceiros NAO entram numa conversa de
        # clinica: e dado pessoal que ela nao pediu, e o payload nao marca de
        # qual clinica cada pet/tutor veio.
        "agendamentos_ativos": agendamentos,
    }
