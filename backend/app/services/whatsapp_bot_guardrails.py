"""Guardrails de saida do chatbot de atendimento (Fase 4, RF-019/020/022/025).

Diferenca deliberada em relacao a `ai_echo_validation.py`: la o "bloqueio" e
codificado como warning numa lista e quem impede a aplicacao e o humano na
tela de revisao. No modo `auto` do bot nao existe esse humano, entao aqui o
veredito e EXPLICITO (`GuardrailVeredito.aprovado`) e o motivo e um `Literal`
fechado, para virar metrica na Fase 6.

Tambem nao portamos duas praticas do ai-echo:
- supressao de alerta por casamento de substring
  (`_filter_contextual_provider_warnings`), que inverte o risco;
- reescrita silenciosa do texto do modelo. Aqui, detectou -> RASCUNHO com
  motivo, nunca um texto "limpo" enviado ao cliente.
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.whatsapp_bot import WhatsAppBotResposta

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
BLOQUEIO_CLINICO_PATH = DATA_DIR / "whatsapp_bot_bloqueio_clinico_termos.json"

MotivoBloqueio = Literal[
    "diagnostico",
    "dose_medicacao",
    "prognostico",
    "avaliacao_sintoma",
    "prazo_nao_confirmado",
    "valor_fora_tabela",
    "intent_fora_allowlist",
    "sem_fonte",
    "teto_diario",
    "teto_caracteres",
    "contato_fora_da_fonte",
    "endereco_sem_fonte",
    "vazamento_conteudo_laudo",
]

# Intents que o bot ATENDE, por persona. Nao confundir com elegibilidade a
# `auto`: aqui esta tudo que ele sabe responder e que a prontidao precisa
# sondar, mesmo o que exige revisao humana. Separar as duas listas evita o
# efeito colateral de tirar uma intent do `auto` e, sem querer, apaga-la do
# painel de prontidao - o admin perderia a visibilidade da fonte.
INTENTS_ATENDIDAS_POR_PERSONA: dict[str, frozenset[str]] = {
    "visitante": frozenset({
        "horario_funcionamento", "endereco", "area_atendimento",
        "formas_contato", "como_agendar", "como_solicitar_exame",
    }),
    "tutor": frozenset({
        "horario_funcionamento",
        "endereco",
        "clinica_proxima",
        "area_atendimento",
        "formas_contato",
        "preco_servico",
        "status_laudo",
        "como_agendar",
    }),
    "clinica": frozenset({
        "horario_funcionamento",
        "endereco",
        "area_atendimento",
        "formas_contato",
        "preco_servico",
        "status_laudo",
        "como_solicitar_exame",
    }),
}

# Intents que NAO podem sair sozinhas, mesmo com a conversa em `auto`.
#
# `preco_servico` (2026-08-24): a tabela viva das secretarias tem uma faixa de
# PLANTAO - seg a sex apos 18h, sabado apos 16h, domingos e feriados - com
# precos distintos, e o modelo de dados so tem colunas `*_comercial`.
# `consultar_preco_tabela` crava `"tipo_horario": "comercial"`, entao fora do
# expediente ela devolve o valor errado. E o guardrail ancora valor no retorno
# LITERAL da tool: o numero errado passaria como conferido. Como o bot roda
# 24/7 justamente para atender fora do expediente, o erro cairia exatamente na
# faixa em que o plantao vale. Volta ao `auto` quando plantao estiver modelado.
INTENTS_BLOQUEADAS_NO_AUTO: frozenset[str] = frozenset({"preco_servico"})

# RF-019: intents elegiveis ao modo `auto`, POR PERSONA. Fora daqui a
# resposta sempre vira rascunho, mesmo com a conversa em `auto` e mesmo com
# o dado disponivel no contexto.
INTENTS_AUTO_POR_PERSONA: dict[str, frozenset[str]] = {
    persona: intents - INTENTS_BLOQUEADAS_NO_AUTO
    for persona, intents in INTENTS_ATENDIDAS_POR_PERSONA.items()
}

# Intents que exigem fonte factual (tool ou trecho de conhecimento). As
# demais - como `formas_contato` - tambem exigem, porque telefone/endereco
# vem de `Configuracao` via tool.
_INTENTS_SEM_FONTE_PERMITIDA: frozenset[str] = frozenset()


@dataclass(frozen=True)
class GuardrailVeredito:
    """Separa seguranca editorial de elegibilidade ao modo automatico."""

    aprovado: bool
    auto_elegivel: bool = True
    motivo: Optional[MotivoBloqueio] = None
    detalhe: Optional[str] = None


@dataclass
class TurnoDeGeracao:
    """O que de fato aconteceu no turno, para o guardrail comparar.

    `valores_permitidos` e `horarios_permitidos` sao preenchidos a partir do
    retorno LITERAL das tools - e o que sustenta a regra de "prazo/valor nao
    confirmado por tool" (RF-022) sem depender de o modelo declarar suas
    fontes honestamente.
    """

    persona: str
    tools_ok: list[str] = field(default_factory=list)
    valores_permitidos: set[str] = field(default_factory=set)
    horarios_permitidos: set[str] = field(default_factory=set)
    datas_permitidas: set[str] = field(default_factory=set)
    textos_clinicos_proibidos: list[str] = field(default_factory=list)
    telefones_permitidos: set[str] = field(default_factory=set)
    ceps_permitidos: set[str] = field(default_factory=set)
    tem_endereco_na_fonte: bool = False

    @property
    def tem_fonte(self) -> bool:
        return bool(self.tools_ok)


_FONTE_EXIGIDA_POR_INTENT: dict[str, frozenset[str]] = {
    "horario_funcionamento": frozenset({"consultar_horario_funcionamento"}),
    "endereco": frozenset({"consultar_dados_institucionais"}),
    "formas_contato": frozenset({"consultar_dados_institucionais"}),
    "preco_servico": frozenset({"consultar_preco_tabela"}),
    "status_laudo": frozenset({"consultar_status_laudo"}),
    "area_atendimento": frozenset({"buscar_conhecimento_institucional"}),
    "como_agendar": frozenset({"buscar_conhecimento_institucional"}),
    "como_solicitar_exame": frozenset({"buscar_conhecimento_institucional"}),
    "clinica_proxima": frozenset({"buscar_clinica_parceira"}),
}


def _normalizar(value: Any) -> str:
    raw = str(value or "").strip().lower()
    decomposed = unicodedata.normalize("NFKD", raw)
    sem_acento = "".join(c for c in decomposed if not unicodedata.combining(c))
    alfanumerico = "".join(c if c.isalnum() else " " for c in sem_acento)
    return " ".join(alfanumerico.split())


@lru_cache(maxsize=1)
def _carregar_grupos_bloqueio() -> tuple[tuple[str, tuple[str, ...]], ...]:
    try:
        payload = json.loads(BLOQUEIO_CLINICO_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # Degradar em silencio aqui seria desligar o guardrail clinico. Loga.
        logger.exception("Falha ao carregar a lista de bloqueio clinico do bot do WhatsApp.")
        return tuple()
    grupos = payload.get("grupos") if isinstance(payload, dict) else None
    if not isinstance(grupos, dict):
        logger.error("Lista de bloqueio clinico do bot em formato inesperado.")
        return tuple()
    return tuple(
        (str(nome), tuple(_normalizar(t) for t in termos if str(t or "").strip()))
        for nome, termos in grupos.items()
        if isinstance(termos, list)
    )


def _max_reply_chars() -> int:
    try:
        parsed = int(settings.WHATSAPP_BOT_MAX_REPLY_CHARS)
    except Exception:
        parsed = 900
    return parsed if parsed > 0 else 900


def _max_replies_per_day() -> int:
    try:
        parsed = int(settings.WHATSAPP_BOT_MAX_REPLIES_PER_CONVERSATION_DAY)
    except Exception:
        parsed = 20
    return parsed if parsed > 0 else 20


def contar_respostas_do_dia(db: Session, wa_identity: str, *, now: Optional[datetime] = None) -> int:
    """Respostas efetivamente ENVIADAS hoje nesta conversa (RF-025).

    Conta so `decisao == "sent"`: rascunho nao consome teto, senao uma
    conversa cheia de rascunhos deixaria de gerar sugestao para a equipe.
    """
    now = now or datetime.now(timezone.utc)
    inicio_do_dia = datetime.combine(now.date(), datetime.min.time(), tzinfo=timezone.utc)
    return (
        db.query(WhatsAppBotResposta)
        .filter(
            WhatsAppBotResposta.wa_identity == wa_identity,
            WhatsAppBotResposta.decisao == "sent",
            WhatsAppBotResposta.created_at >= inicio_do_dia,
        )
        .count()
    )


_RE_VALOR = re.compile(r"(?:r\$\s*)?(\d{1,3}(?:\.\d{3})*(?:,\d{2})|\d+(?:[.,]\d{2}))")
_RE_HORARIO = re.compile(r"\b([01]?\d|2[0-3])\s*[:h]\s*([0-5]\d)\b")
_RE_DATA = re.compile(r"\b(\d{1,2})\s*/\s*(\d{1,2})(?:\s*/\s*(\d{2,4}))?\b")
_RE_CEP = re.compile(r"\b\d{5}-\d{3}\b")
_RE_TELEFONE = re.compile(
    r"(?:\+?55[\s.-]?)?(?:\(?\d{2}\)?[\s.-]?)?\d{4,5}[\s.-]?\d{4}\b"
)

# Palavras que so aparecem quando a resposta esta dando um endereco. Servem
# para detectar endereco afirmado SEM fonte; nao tentam conferir prosa contra
# o cadastro, o que texto livre nao suporta de forma confiavel.
_TERMOS_DE_LOGRADOURO: frozenset[str] = frozenset({
    "rua", "avenida", "av", "travessa", "alameda", "rodovia", "estrada",
})


def _valores_no_texto(texto: str) -> set[str]:
    encontrados: set[str] = set()
    for bruto in _RE_VALOR.findall(texto.lower()):
        normalizado = bruto.replace(".", "").replace(",", ".")
        try:
            encontrados.add(f"{float(normalizado):.2f}")
        except ValueError:
            continue
    return encontrados


def _horarios_no_texto(texto: str) -> set[str]:
    return {f"{int(h):02d}:{m}" for h, m in _RE_HORARIO.findall(texto.lower())}


def _so_digitos(valor: Any) -> str:
    return "".join(c for c in str(valor or "") if c.isdigit())


def _ceps_no_texto(texto: str) -> set[str]:
    return {_so_digitos(bruto) for bruto in _RE_CEP.findall(texto or "")}


def _telefones_no_texto(texto: str) -> set[str]:
    """Sequencias com cara de telefone, ja sem os CEPs.

    CEP tem os mesmos 8 digitos de um fixo, entao ele sai do texto antes -
    senao todo endereco com CEP seria acusado de telefone inventado.
    """
    sem_cep = _RE_CEP.sub(" ", texto or "")
    return {
        digitos
        for digitos in (_so_digitos(b) for b in _RE_TELEFONE.findall(sem_cep))
        if len(digitos) >= 8
    }


def _telefone_ancorado(candidato: str, permitidos: set[str]) -> bool:
    """Compara pela cauda, para o DDI/DDD nao criar falso bloqueio.

    O cadastro guarda `(85) 3333-4444` e a resposta pode dizer
    `+55 85 3333-4444`. Sao o mesmo numero; comparar string exata acusaria
    invencao onde nao ha.
    """
    return any(
        p.endswith(candidato) or candidato.endswith(p)
        for p in permitidos
        if len(p) >= 8
    )


def avaliar_resposta(
    *,
    texto: str,
    intent: str,
    modo: str,
    turno: TurnoDeGeracao,
) -> GuardrailVeredito:
    """Veredito unico sobre uma resposta candidata.

    Ordem deliberada: primeiro os bloqueios de conteudo clinico (o requisito
    mais importante da entrega), depois fonte, depois ancoragem de
    valor/horario, depois allowlist de intent, por ultimo tetos. Assim o
    motivo gravado e sempre o mais grave, nao o primeiro que casou por acaso.
    """
    texto_normalizado = _normalizar(texto)

    # RF-022: conteudo clinico. Roda TAMBEM quando a resposta esta ancorada
    # em trecho da base - "veio da base" nao e passe livre, porque a base
    # contem procedimento clinico de staff.
    for grupo, termos in _carregar_grupos_bloqueio():
        for termo in termos:
            if termo and termo in texto_normalizado:
                return GuardrailVeredito(
                    aprovado=False,
                    motivo=grupo,  # type: ignore[arg-type]
                    detalhe=f"termo bloqueado: {termo}",
                )

    # Vazamento de conteudo de laudo: o turno sabe quais textos clinicos
    # foram carregados; se algum aparecer (mesmo parafraseado por copia
    # literal de trecho), bloqueia.
    for proibido in turno.textos_clinicos_proibidos:
        trecho = _normalizar(proibido)
        if len(trecho) >= 12 and trecho in texto_normalizado:
            return GuardrailVeredito(
                aprovado=False,
                motivo="vazamento_conteudo_laudo",
                detalhe="texto do laudo/exame presente na resposta",
            )

    # RF-020: a fonte precisa sustentar A INTENT, nao apenas ter sido chamada
    # em algum momento do turno. Uma consulta de horario nao autoriza afirmar
    # preco ou status de laudo.
    fontes_exigidas = _FONTE_EXIGIDA_POR_INTENT.get(intent)
    if fontes_exigidas:
        fonte_presente = bool(fontes_exigidas.intersection(turno.tools_ok))
    else:
        fonte_presente = turno.tem_fonte
    if not fonte_presente and intent not in _INTENTS_SEM_FONTE_PERMITIDA:
        return GuardrailVeredito(
            aprovado=False,
            motivo="sem_fonte",
            detalhe=f"fonte exigida ausente para intent {intent}",
        )

    # RF-022: valor que nao veio de tabela de preco.
    valores_texto = _valores_no_texto(texto)
    nao_ancorados = valores_texto - turno.valores_permitidos
    if nao_ancorados:
        return GuardrailVeredito(
            aprovado=False,
            motivo="valor_fora_tabela",
            detalhe=f"valores sem fonte: {sorted(nao_ancorados)}",
        )

    # RF-022: prazo/horario nao confirmado por tool.
    horarios_texto = _horarios_no_texto(texto)
    horarios_nao_ancorados = horarios_texto - turno.horarios_permitidos
    if horarios_nao_ancorados:
        return GuardrailVeredito(
            aprovado=False,
            motivo="prazo_nao_confirmado",
            detalhe=f"horarios sem fonte: {sorted(horarios_nao_ancorados)}",
        )

    # RF-022: telefone/CEP que nao vieram do cadastro institucional. Mesma
    # regra ja aplicada a valor e horario: o conjunto permitido vem do retorno
    # LITERAL da tool, nao do que o modelo diz ter usado.
    contatos_texto = _telefones_no_texto(texto) | _ceps_no_texto(texto)
    permitidos_contato = turno.telefones_permitidos | turno.ceps_permitidos
    nao_ancorados_contato = {
        candidato
        for candidato in contatos_texto
        if not _telefone_ancorado(candidato, permitidos_contato)
    }
    if nao_ancorados_contato:
        return GuardrailVeredito(
            aprovado=False,
            motivo="contato_fora_da_fonte",
            detalhe=f"telefone/CEP sem fonte: {sorted(nao_ancorados_contato)}",
        )

    # RF-020/RF-022: endereco afirmado sem endereco no cadastro. Nao tentamos
    # conferir a prosa contra o cadastro - texto livre nao suporta comparacao
    # confiavel -, mas afirmar logradouro quando a fonte nao tem NENHUM
    # endereco e invencao pura, e era o caminho que stage deixava passar.
    if not turno.tem_endereco_na_fonte:
        tokens = set(texto_normalizado.split())
        if tokens & _TERMOS_DE_LOGRADOURO:
            return GuardrailVeredito(
                aprovado=False,
                motivo="endereco_sem_fonte",
                detalhe="resposta cita logradouro e o cadastro institucional nao tem endereco",
            )

    # RF-019: intent fora da allowlist continua segura para revisao humana,
    # mas nunca e elegivel ao modo automatico.
    permitidas = INTENTS_AUTO_POR_PERSONA.get(turno.persona, frozenset())
    if intent not in permitidas:
        return GuardrailVeredito(
            aprovado=True,
            auto_elegivel=False,
            motivo="intent_fora_allowlist",
            detalhe=f"intent {intent} nao e auto na persona {turno.persona}",
        )

    # RF-025: teto de caracteres.
    if len(texto or "") > _max_reply_chars():
        return GuardrailVeredito(
            aprovado=False,
            motivo="teto_caracteres",
            detalhe=f"{len(texto)} > {_max_reply_chars()}",
        )

    return GuardrailVeredito(aprovado=True)


def turno_a_partir_dos_resultados(
    persona: str, resultados: list[tuple[str, dict[str, Any]]]
) -> TurnoDeGeracao:
    """Constroi o `TurnoDeGeracao` a partir do retorno LITERAL das tools.

    E aqui que "valor/horario com fonte" ganha significado: o conjunto
    permitido vem do payload que a tool devolveu, nao do que o modelo diz
    ter usado.
    """
    turno = TurnoDeGeracao(persona=persona)
    for nome, resultado in resultados:
        if not isinstance(resultado, dict) or not resultado.get("ok"):
            continue
        turno.tools_ok.append(nome)

        if nome == "consultar_preco_tabela":
            for item in resultado.get("itens") or []:
                valor = str(item.get("valor") or "").strip()
                if valor:
                    try:
                        turno.valores_permitidos.add(f"{float(valor):.2f}")
                    except ValueError:
                        continue

        if nome == "consultar_horario_funcionamento":
            for chave in ("inicio", "fim"):
                valor = resultado.get(chave)
                if valor:
                    turno.horarios_permitidos.add(str(valor))
            if resultado.get("data"):
                turno.datas_permitidas.add(str(resultado["data"]))

        if nome == "buscar_clinica_parceira":
            # O endereco e o telefone da clinica sugerida sao dado de
            # cadastro, como os institucionais. Sem alimentar o turno aqui, a
            # RF-022 barraria a propria resposta que a tool autorizou -- e o
            # bot ficaria mudo justamente na intent nova.
            for item in resultado.get("itens") or []:
                if item.get("endereco"):
                    turno.tem_endereco_na_fonte = True
                for bruto in (item.get("whatsapp"), item.get("telefone")):
                    numero = _so_digitos(bruto)
                    if len(numero) >= 8:
                        turno.telefones_permitidos.add(numero)
                for cep in _RE_CEP.findall(str(item.get("endereco") or "")):
                    turno.ceps_permitidos.add(_so_digitos(cep))

        if nome == "consultar_dados_institucionais":
            turno.tem_endereco_na_fonte = bool(resultado.get("tem_endereco"))
            telefone = _so_digitos(resultado.get("telefone"))
            if len(telefone) >= 8:
                turno.telefones_permitidos.add(telefone)
            for cep in _RE_CEP.findall(str(resultado.get("endereco") or "")):
                turno.ceps_permitidos.add(_so_digitos(cep))

    return turno
