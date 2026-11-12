"""Consentimento administrativo limitado aos slots efetivamente revisados."""
import hashlib
import json
from datetime import datetime, timezone

from fastapi import HTTPException


def assinatura(valor) -> str:
    return hashlib.sha256(json.dumps(valor, sort_keys=True).encode()).hexdigest()


def ler_concessao(agendamento) -> dict:
    try:
        valor = json.loads(getattr(agendamento, "excecao_sobreposicao", None) or "null")
    except (TypeError, ValueError):
        return {}
    return valor if isinstance(valor, dict) else {}


def validar_pedido(payload, usuario) -> dict:
    confirmar = bool(getattr(payload, "confirmar_sobreposicao", False))
    motivo = str(getattr(payload, "motivo_excecao_sobreposicao", "") or "").strip()
    if confirmar:
        if not usuario.tem_papel("admin"):
            raise HTTPException(403, "Somente administradores podem autorizar sobreposicao de horarios.")
        if not motivo:
            raise HTTPException(422, "Informe o motivo da sobreposicao autorizada.")
    return {
        "detalhar_sobreposicao": True,
        "confirmar_sobreposicao": confirmar,
        "escopo_sobreposicao_confirmado": getattr(payload, "escopo_sobreposicao_confirmado", None),
        "motivo_excecao_sobreposicao": motivo,
        "usuario_sobreposicao": usuario,
    }


def validar_conflitos(agendamento, escopo, conflitos, *, confirmar_sobreposicao=False,
                      escopo_sobreposicao_confirmado=None, motivo_excecao_sobreposicao="",
                      usuario_sobreposicao=None):
    concessao = ler_concessao(agendamento)
    if concessao.get("escopo") != escopo:
        agendamento.excecao_sobreposicao = None
        concessao = {}
    if not conflitos:
        return
    revisados = sorted(item["assinatura"] for item in conflitos)
    token = assinatura({"escopo": escopo, "conflitos": revisados})
    if confirmar_sobreposicao:
        if usuario_sobreposicao is None or not usuario_sobreposicao.tem_papel("admin"):
            raise HTTPException(403, "Somente administradores podem autorizar sobreposicao de horarios.")
        if not str(motivo_excecao_sobreposicao or "").strip():
            raise HTTPException(422, "Informe o motivo da sobreposicao autorizada.")
        if escopo_sobreposicao_confirmado == token:
            agendamento.excecao_sobreposicao = json.dumps({
                "escopo": escopo, "conflitos": revisados, "confirmacao": token,
                "concedida_por_id": usuario_sobreposicao.id,
                "concedida_por_nome": usuario_sobreposicao.nome,
                "concedida_em": datetime.now(timezone.utc).isoformat(),
                "motivo": motivo_excecao_sobreposicao.strip(),
                "intervalos_conflitantes": [
                    {k: item[k] for k in ("id", "inicio", "fim")} for item in conflitos
                ],
            }, ensure_ascii=False)
            return
    elif all(
        item["autorizado_pelo_existente"] or item["assinatura"] in concessao.get("conflitos", [])
        for item in conflitos
    ):
        return
    resumo = "; ".join(
        f"{datetime.fromisoformat(item['inicio']).strftime('%d/%m/%Y %H:%M')} "
        f"às {datetime.fromisoformat(item['fim']).strftime('%H:%M')} "
        f"({item.get('paciente') or 'paciente não informado'}, agendamento #{item['id']})"
        for item in conflitos
    )
    raise HTTPException(409, {
        "codigo": "CONFLITO_SOBREPOSICAO_AGENDA",
        "mensagem": f"Horario indisponivel: ja existe atendimento neste slot: {resumo}. "
                    "Um administrador pode revisar e autorizar esta sobreposicao.",
        "confirmavel": True, "escopo": token,
        "conflitos": [
            {k: item[k] for k in ("id", "paciente", "inicio", "fim")} for item in conflitos
        ],
    })
