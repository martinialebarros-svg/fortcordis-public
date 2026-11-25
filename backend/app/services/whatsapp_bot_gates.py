from __future__ import annotations

import json
import re
import logging
import unicodedata
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from app.core.config import settings
from app.db.database import SessionLocal
from app.models.configuracao import Configuracao
from app.models.whatsapp_bot import WhatsAppBotClinicaEstado, WhatsAppBotConversaEstado

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
PEDIDO_HUMANO_TERMOS_PATH = DATA_DIR / "whatsapp_bot_pedido_humano_termos.json"
EMERGENCIA_TERMOS_PATH = DATA_DIR / "whatsapp_bot_emergencia_termos.json"
CORTESIA_TERMOS_PATH = DATA_DIR / "whatsapp_bot_cortesia_termos.json"

MODOS_VALIDOS = {"off", "suggest", "auto"}
PARTICIPACOES_VALIDAS = {"todos", "piloto"}


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


# --- RF-008: os dois interruptores -----------------------------------------


def is_whatsapp_bot_enabled() -> bool:
    """`WHATSAPP_BOT_ENABLED` (env) E `configuracoes.whatsapp_bot_atendimento_habilitado`

    (banco) precisam estar ligados. Falha na leitura fecha para desabilitado -
    nunca deve destravar acao automatica por acidente.
    """
    if not settings.WHATSAPP_BOT_ENABLED:
        return False
    db = SessionLocal()
    try:
        config = db.query(Configuracao).first()
        return bool(config and config.whatsapp_bot_atendimento_habilitado)
    except Exception:
        logger.exception("Falha ao consultar configuracao do bot de atendimento do WhatsApp.")
        return False
    finally:
        db.close()


# --- RF-009: modo por conversa ----------------------------------------------


def resolve_conversation_state(db, wa_identity: str) -> Optional[WhatsAppBotConversaEstado]:
    return (
        db.query(WhatsAppBotConversaEstado)
        .filter(WhatsAppBotConversaEstado.wa_identity == wa_identity)
        .first()
    )


def _institutional_default_mode(db) -> str:
    config = db.query(Configuracao).first()
    modo = str(getattr(config, "whatsapp_bot_modo", None) or "suggest").strip().lower()
    return modo if modo in MODOS_VALIDOS else "suggest"


def resolve_participacao(db) -> str:
    """RF-P02: `todos` preserva o comportamento atual; `piloto` inverte o default.

    Falha para `todos` quando a leitura nao produz valor conhecido - o valor
    seguro aqui e o que NAO muda comportamento; `piloto` e uma decisao
    deliberada, nunca um acidente de leitura.
    """
    config = db.query(Configuracao).first()
    valor = str(getattr(config, "whatsapp_bot_participacao", None) or "todos").strip().lower()
    return valor if valor in PARTICIPACOES_VALIDAS else "todos"


def _modo_da_clinica(db, clinica_id: Optional[int]) -> Optional[str]:
    if not clinica_id:
        return None
    linha = (
        db.query(WhatsAppBotClinicaEstado)
        .filter(WhatsAppBotClinicaEstado.clinica_id == clinica_id)
        .first()
    )
    if linha is None:
        return None
    modo = str(linha.modo or "").strip().lower()
    return modo if modo in MODOS_VALIDOS else None


def resolve_modo_efetivo(
    db,
    *,
    wa_identity: str,
    match_type: Optional[str],
    clinica_id: Optional[int],
    modo_atual: str,
    estado: Optional[WhatsAppBotConversaEstado] = None,
) -> tuple[str, Optional[str]]:
    """RF-P03: precedencia conversa > clinica > institucional.

    Devolve `(modo, motivo_de_bloqueio)`. O motivo so vem preenchido quando a
    conversa e barrada pela participacao, e distingue POR QUE:
    `clinica_desabilitada` e "foi tirado", `fora_do_piloto` e "ainda nao
    entrou".

    `modo_atual` e o que o chamador ja resolveu (conversa, com fallback
    institucional). Esta funcao **nunca** o recalcula: so o substitui quando a
    clinica tem modo proprio. Recalcular seria duplicar a leitura e abrir a
    porta para as duas discordarem.

    A conversa vence a clinica de proposito: e o controle do atendente na
    conversa aberta, e precisa desligar o bot na hora mesmo numa clinica
    habilitada (CA-P05).

    Nao pode ser dobrado dentro de `resolve_conversation_mode`: aquele roda nos
    portoes de `_process_job`, ANTES de a identidade existir.
    """
    if estado is None:
        estado = resolve_conversation_state(db, wa_identity)
    if estado is not None and str(estado.modo or "").strip().lower() in MODOS_VALIDOS:
        return modo_atual, None

    if match_type == "clinica":
        modo_clinica = _modo_da_clinica(db, clinica_id)
        if modo_clinica == "off":
            return "off", "clinica_desabilitada"
        if modo_clinica is not None:
            return modo_clinica, None

    # CA-P02/CA-P06: em piloto, ausencia de habilitacao explicita e `off` -
    # inclusive para tutor, que nao tem agrupamento equivalente.
    if resolve_participacao(db) == "piloto":
        return "off", "fora_do_piloto"

    return modo_atual, None


def resolve_conversation_mode(
    db, wa_identity: str, *, estado: Optional[WhatsAppBotConversaEstado] = None
) -> str:
    """RF-009: sem linha em `whatsapp_bot_conversa_estado`, a conversa herda

    `configuracoes.whatsapp_bot_modo` (default `suggest`).
    """
    if estado is None:
        estado = resolve_conversation_state(db, wa_identity)
    if estado is not None and str(estado.modo or "").strip().lower() in MODOS_VALIDOS:
        return str(estado.modo).strip().lower()
    return _institutional_default_mode(db)


# --- RF-010: pausa por mensagem humana ou claim -----------------------------


def _pause_hours() -> int:
    parsed = _safe_int(settings.WHATSAPP_BOT_HANDOFF_PAUSE_HOURS, 12)
    return parsed if parsed > 0 else 12


def _assisted_send_pause_hours() -> int:
    """Zero mantem o copiloto ativo; pausa positiva preserva configuracao legada.

    Aprovar uma resposta nao significa assumir a conversa. A pausa explicita
    e o handoff continuam usando a duracao propria.
    """
    parsed = _safe_int(settings.WHATSAPP_BOT_ASSISTED_SEND_PAUSE_HOURS, 0)
    return max(0, parsed)


def is_locally_paused(
    estado: Optional[WhatsAppBotConversaEstado], *, now: Optional[datetime] = None
) -> bool:
    if estado is None or estado.pausado_ate is None:
        return False
    now = now or _utc_now()
    pausado_ate = _as_aware_utc(estado.pausado_ate)
    return pausado_ate is not None and pausado_ate > now


def pause_conversation(
    db,
    wa_identity: str,
    *,
    atualizado_por_id: Optional[int] = None,
    now: Optional[datetime] = None,
    horas: Optional[int] = None,
) -> WhatsAppBotConversaEstado:
    """RF-010: mensagem humana (from_me=true) ou claim de atendente pausa o

    bot por `WHATSAPP_BOT_HANDOFF_PAUSE_HOURS`. Mensagem enviada pelo proprio
    bot não pausa por este detector. O envio assistido de um rascunho aprovado
    pausa explicitamente a conversa no endpoint de revisão, com o atendente
    responsável registrado.

    `horas` permite ao chamador impor uma duracao propria. Existe para o envio
    assistido, cuja semantica ("um atendente respondeu esta mensagem") e mais
    fraca que a de handoff ("a equipe assumiu"). Default `None` preserva o
    comportamento dos demais chamadores sem que eles precisem mudar.
    """
    now = now or _utc_now()
    estado = resolve_conversation_state(db, wa_identity)
    if estado is None:
        # modo=None EXPLICITO: a linha existe para a escrituracao abaixo,
        # nao para virar override. Omitir o kwarg deixaria o DEFAULT do
        # servidor reintroduzir "suggest" e furar o portao do piloto.
        estado = WhatsAppBotConversaEstado(wa_identity=wa_identity, modo=None)
        db.add(estado)
    estado.pausado_ate = now + timedelta(
        hours=horas if horas is not None and horas > 0 else _pause_hours()
    )
    estado.atualizado_por_id = atualizado_por_id
    estado.updated_at = now
    return estado


def set_handoff_motivo(
    db, wa_identity: str, motivo: str, *, atualizado_por_id: Optional[int] = None, now: Optional[datetime] = None
) -> WhatsAppBotConversaEstado:
    now = now or _utc_now()
    estado = resolve_conversation_state(db, wa_identity)
    if estado is None:
        # modo=None EXPLICITO: a linha existe para a escrituracao abaixo,
        # nao para virar override. Omitir o kwarg deixaria o DEFAULT do
        # servidor reintroduzir "suggest" e furar o portao do piloto.
        estado = WhatsAppBotConversaEstado(wa_identity=wa_identity, modo=None)
        db.add(estado)
    estado.handoff_motivo = motivo
    estado.atualizado_por_id = atualizado_por_id
    estado.updated_at = now
    return estado


# --- RF-012: janela de atendimento de 24h -----------------------------------

CUSTOMER_SERVICE_WINDOW_HOURS = 24


def is_customer_service_window_open(
    last_inbound_at: Optional[datetime], *, now: Optional[datetime] = None
) -> bool:
    """Replica `describeCustomerServiceWindow` (Node,

    `whatsapp-stage-backend/src/services/customerServiceWindow.ts`): a janela
    fica aberta por 24h a partir da ultima mensagem inbound.
    """
    inbound_at = _as_aware_utc(last_inbound_at)
    if inbound_at is None:
        return False
    now = now or _utc_now()
    expires_at = inbound_at + timedelta(hours=CUSTOMER_SERVICE_WINDOW_HOURS)
    return now < expires_at


# --- RF-013: tipo de mensagem ------------------------------------------------


def is_supported_message_type(message_type: Optional[str]) -> bool:
    return str(message_type or "text").strip().lower() == "text"


# --- RF-011/RF-023: vocabulario de pedido de humano e emergencia -----------


def _normalize_texto(value: Any) -> str:
    raw = str(value or "").strip().lower()
    normalized = unicodedata.normalize("NFKD", raw)
    without_accents = "".join(char for char in normalized if not unicodedata.combining(char))
    alphanumeric = "".join(char if char.isalnum() else " " for char in without_accents)
    return " ".join(alphanumeric.split())


@lru_cache(maxsize=None)
def _load_termos(path: Path) -> tuple[str, ...]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return tuple()
    termos = payload.get("termos") if isinstance(payload, dict) else None
    if not isinstance(termos, list):
        return tuple()
    return tuple(_normalize_texto(termo) for termo in termos if str(termo or "").strip())


def carregar_termos_pedido_humano() -> tuple[str, ...]:
    return _load_termos(PEDIDO_HUMANO_TERMOS_PATH)


def carregar_termos_emergencia() -> tuple[str, ...]:
    return _load_termos(EMERGENCIA_TERMOS_PATH)


def detecta_pedido_humano(texto: str) -> bool:
    normalized = _normalize_texto(texto)
    if not normalized:
        return False
    return any(termo in normalized for termo in carregar_termos_pedido_humano() if termo)


def detecta_emergencia(texto: str) -> bool:
    normalized = _normalize_texto(texto)
    if not normalized:
        return False
    return any(termo in normalized for termo in carregar_termos_emergencia() if termo)


def _colapsa_repeticao(texto: str) -> str:
    """"bom diaa" -> "bom dia", "obrigadaa" -> "obrigada", "kkkk" -> "k".

    Aplicado dos DOIS lados - mensagem e vocabulario -, entao colapsar letra
    dobrada legitima ("abraco" nao tem, mas "arretado" tem) nao cria
    divergencia: os dois lados viram a mesma coisa. Isso troca dezenas de
    variantes de alongamento por uma regra.
    """
    return re.sub(r"(.)\1+", r"\1", texto)


@lru_cache(maxsize=None)
def carregar_termos_cortesia() -> tuple[str, ...]:
    """Termos de cortesia, do mais longo para o mais curto.

    A ordem importa: o casamento e guloso e consome o trecho encontrado, entao
    "muito obrigada" precisa ser tentado antes de "obrigada".
    """
    try:
        payload = json.loads(CORTESIA_TERMOS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.exception("Falha ao carregar termos de cortesia: %s", CORTESIA_TERMOS_PATH)
        return ()
    termos: list[str] = []
    for chave, valores in (payload or {}).items():
        if chave.startswith("_") or not isinstance(valores, list):
            continue
        for valor in valores:
            normalizado = _colapsa_repeticao(_normalize_texto(valor))
            if normalizado:
                termos.append(normalizado)
    return tuple(sorted(set(termos), key=len, reverse=True))


def detecta_cortesia(texto: str) -> bool:
    """RF-P11: mensagem que nao pede resposta - so saudacao, agradecimento,

    confirmacao ou despedida.

    Ao contrario de `detecta_emergencia` e `detecta_pedido_humano`, que casam
    por SUBSTRING, aqui a mensagem INTEIRA precisa ser cortesia. Substring
    engoliria "obrigada, voces fazem eco?".

    Erra para o lado seguro nas duas direcoes. Falso positivo apenas deixa de
    oferecer rascunho, e a mensagem continua visivel na central para uma
    pessoa; falso negativo devolve ao comportamento anterior, que e gerar e ser
    barrado por `sem_fonte`.
    """
    bruto = str(texto or "").strip()
    if not bruto:
        return False

    # REGRA 1 - interrogacao desqualifica, sempre.
    #
    # Um ataque adversarial produziu 79 falsos positivos e quase todos passavam
    # por aqui: "ok?", "ta ai?", "ja viu?", "so isso?", "e o senhor?". A
    # normalizacao apaga pontuacao, entao "ok" e "ok?" chegavam identicos ao
    # casamento - mensagens opostas, indistinguiveis. Pior: a pergunta pode ser
    # feita INTEIRA com palavras de cortesia, entao o teste de "sobrou algo?"
    # nao a detecta. Custa alguns falsos negativos ("tudo bem?") e isso e barato.
    if "?" in bruto:
        return False

    restante = _colapsa_repeticao(_normalize_texto(bruto))

    # REGRA 2 - sem uma letra sequer, nao arrisca.
    #
    # Emoji e pontuacao sozinhos sao ambiguos: "👍" encerra, "🆘" e socorro,
    # "..." e impaciencia. Nao da para distinguir por vocabulario, e numa
    # cardiologia veterinaria o custo dos dois erros e assimetrico. Vai para o
    # caminho normal, que tem detector de emergencia antes.
    if not restante:
        return False

    for termo in carregar_termos_cortesia():
        if not termo:
            continue
        while f" {termo} " in f" {restante} ":
            restante = " ".join(f" {restante} ".replace(f" {termo} ", " ", 1).split())
            if not restante:
                return True
    return not restante
