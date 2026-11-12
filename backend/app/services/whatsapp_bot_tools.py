"""Tools do chatbot de atendimento do WhatsApp (Fase 4, RF-018).

Modulo PROPRIO, deliberadamente separado de `assistente_ia_tools.py`. As 25
tools do assistente interno rodam com autoridade de staff: a autorizacao
delas mora no endpoint (`require_papel("admin")`), nao nas tools, e o
redator `tool_result_for_model` falha ABERTO (devolve o payload cru para 23
dos 25 nomes). Instanciar aquele contexto aqui reproduziria alcance de admin
sem gate nenhum.

As regras estruturais deste modulo:

- O escopo (`tutor_id` / `clinica_id`) vem do contexto Python resolvido pela
  Fase 3, nunca de argumento do modelo. O LLM nao ve esses parametros no
  schema das tools.
- Cada tool injeta o filtro de escopo no proprio query.
- A allowlist e POR PERSONA e consultada antes do dispatch; nome fora dela
  falha fechado.
- Todo payload de retorno e montado campo a campo (whitelist por
  construcao). Nunca serializa ORM, nunca faz `**vars(obj)`.
"""
from __future__ import annotations

import logging
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Callable, Literal, Optional

from sqlalchemy import String, cast, func, or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.portal_release import (
    PORTAL_RELEASED_EXAM_STATUSES,
    PORTAL_RELEASED_LAUDO_STATUSES,
)
from app.models.atendimento_clinico import AtendimentoClinico
from app.models.clinica import Clinica
from app.models.tutor import Tutor
from app.models.configuracao import Configuracao
from app.models.laudo import Exame, Laudo
from app.models.paciente import Paciente
from app.models.servico import Servico

# Reuso legitimo: helpers PUROS de agenda, que recebem so db/date e nao
# carregam autoridade de staff nem entram em TOOL_DEFINITIONS. Precedente ja
# na branch: whatsapp_bot_handoff_service.py faz o mesmo import.
from app.services.assistente_ia_clinics360 import _whatsapps
from app.services.logistica_service import _haversine_km
from app.services.whatsapp_bot_servico_match import (
    AFINIDADE_EXATA,
    ordenar_candidatos,
    procedimentos_do_pedido,
    procedimentos_do_servico,
)
from app.services.assistente_ia_tools import (
    LOCAL_TZ,
    _agenda_configuration_rules,
    _agenda_day_window,
)

logger = logging.getLogger(__name__)

MAX_SERVICOS_NO_PAYLOAD = 8
MAX_LAUDOS_NO_PAYLOAD = 6
MAX_TRECHOS_CONHECIMENTO = 3
EXCERPT_MAX_CHARS = 500

# Pisos de relevancia, um por ESCALA de sinal. `search_knowledge` mistura dois
# sinais em `score` (0.35 * keyword_normalizado + 0.65 * cosseno), e a
# normalizacao lexical divide pelo maior keyword_score do lote - o melhor hit
# lexical vale SEMPRE exatamente 0.35, independente de ter casado um termo ou
# vinte. Por isso um piso sobre `score` nao mede relevancia absoluta.
#
# Regressao real: a primeira versao deste modulo comparava `score` contra 2.0,
# que e inalcancavel (o teto de `score` e 1.0). O resultado foi
# `buscar_conhecimento_institucional` devolvendo ok=False para toda pergunta e
# todo documento, o que deixava `area_atendimento`, `como_agendar` e
# `como_solicitar_exame` permanentemente em `sem_fonte`. Nenhum teste ligava o
# wrapper ao retorno real de `search_knowledge`, e o bug atravessou tres fases.
# `test_whatsapp_bot_conhecimento.py` agora fecha esse caminho.

# keyword_score e absoluto: 5 por termo casado no titulo, 1 por termo no
# conteudo. 2.0 = ao menos dois casamentos no corpo, ou um no titulo.
CONHECIMENTO_KEYWORD_SCORE_MINIMO = 2.0
# semantic_score e cosseno. O piso interno do buscador semantico e 0.20;
# aqui subimos um pouco porque a resposta vai para cliente.
CONHECIMENTO_SEMANTIC_SCORE_MINIMO = 0.25

# A base de conhecimento e COMPARTILHADA com o assistente interno e nao tem
# coluna de audiencia; o default de categoria em toda a cadeia de criacao e
# "manual", o balde onde ja mora procedimento clinico de staff. Por isso a
# audiencia do bot e explicita por categoria, e "manual" NAO entra: alargar o
# balde default faria manual clinico interno alimentar resposta a cliente.
#
# O casamento e tolerante de proposito (acento, caixa, espaco, hifen,
# underscore e sufixo livre), porque a UI de admin e um campo de texto livre -
# quem digita "Institucional - Tutor" quer o mesmo que "institucional_tutor".
CATEGORIAS_INSTITUCIONAIS = frozenset({
    "institucional",
    "atendimento",
})


def _categoria_e_institucional(categoria: Any) -> bool:
    normalizada = _normalizar(categoria).replace("-", " ").replace("_", " ")
    if not normalizada:
        return False
    primeira = normalizada.split()[0]
    return primeira in CATEGORIAS_INSTITUCIONAIS


# Status de laudo/exame que o cliente pode ver. Nunca escrever
# "Liberado no portal" na mao - `Laudo.status` mistura ciclo clinico e
# publicacao, e "Finalizado" NAO e "pronto".
_RELEASED_EXAM = tuple(PORTAL_RELEASED_EXAM_STATUSES)
_RELEASED_LAUDO = tuple(PORTAL_RELEASED_LAUDO_STATUSES)


class WhatsAppBotToolError(RuntimeError):
    """Erro de uso das tools do bot (escopo incoerente, persona invalida)."""


@dataclass(frozen=True)
class WhatsAppBotToolContext:
    """Escopo imutavel de uma conversa.

    Escopo que pode ser None e escopo que vaza: o `__post_init__` recusa
    contexto incoerente em vez de escolher um lado silenciosamente.
    """

    db: Session
    match_type: Literal["tutor", "clinica", "visitante"]
    tutor_id: Optional[int] = None
    clinica_id: Optional[int] = None

    def __post_init__(self) -> None:
        if self.match_type == "visitante":
            if self.tutor_id is not None or self.clinica_id is not None:
                raise WhatsAppBotToolError("Visitante nao pode carregar dados de cadastro.")
            return
        if self.match_type not in ("tutor", "clinica"):
            raise WhatsAppBotToolError(f"match_type invalido: {self.match_type!r}")
        if self.match_type == "tutor":
            if self.tutor_id is None:
                raise WhatsAppBotToolError("Persona tutor exige tutor_id resolvido.")
            if self.clinica_id is not None:
                raise WhatsAppBotToolError("Persona tutor nao pode carregar clinica_id.")
        else:
            if self.clinica_id is None:
                raise WhatsAppBotToolError("Persona clinica exige clinica_id resolvido.")
            if self.tutor_id is not None:
                raise WhatsAppBotToolError("Persona clinica nao pode carregar tutor_id.")


def _legacy_active(column):
    """Mesmo criterio de `whatsapp_contexto._legacy_active`: NULL e ativo.

    Escolhido de proposito para casar com a resolucao de identidade que
    trouxe a conversa ate aqui (o portal usa `== 1`, mais estrito). Coberto
    por teste.
    """
    return func.lower(func.coalesce(cast(column, String), "1")).in_(["1", "true", "t"])


def _normalizar(value: Any) -> str:
    raw = str(value or "").strip().lower()
    decomposed = unicodedata.normalize("NFKD", raw)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _to_iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _configuracao(db: Session) -> Optional[Configuracao]:
    """Leitura padronizada.

    `Configuracao` nao tem unique constraint e o codebase a le de tres
    formas diferentes; `order_by(id.asc())` casa com
    `_agenda_configuration_rules`, para horario e endereco nao vierem de
    registros distintos. Nunca cria a linha a partir do worker.
    """
    return db.query(Configuracao).order_by(Configuracao.id.asc()).first()


# --------------------------------------------------------------------------
# Tools
# --------------------------------------------------------------------------


def consultar_horario_funcionamento(
    ctx: WhatsAppBotToolContext, *, data: Optional[str] = None
) -> dict[str, Any]:
    """Janela operacional da agenda para uma data.

    `_agenda_day_window` devolve `inicio`/`fim` preenchidos MESMO quando
    `ativo` e False (feriado herda a janela semanal). Por isso o horario so
    entra no payload quando `ativo` e True - senao o bot diria "hoje
    funcionamos de 08:00 as 14:00" num feriado.
    """
    hoje = datetime.now(LOCAL_TZ).date()
    if data:
        try:
            referencia = date.fromisoformat(str(data).strip())
        except ValueError:
            return {"ok": False, "error": "Data invalida. Use o formato AAAA-MM-DD."}
        # O bot nao precisa responder sobre daqui a um ano.
        if not (hoje - timedelta(days=1) <= referencia <= hoje + timedelta(days=30)):
            return {"ok": False, "error": "Data fora da janela consultavel."}
    else:
        referencia = hoje

    exceptions, weekly, holidays = _agenda_configuration_rules(ctx.db)
    janela = _agenda_day_window(
        referencia, exceptions=exceptions, weekly=weekly, holidays=holidays
    )
    aberto = bool(janela.get("ativo"))
    return {
        "ok": True,
        "data": janela.get("data"),
        "aberto": aberto,
        "inicio": janela.get("inicio") if aberto else None,
        "fim": janela.get("fim") if aberto else None,
        "motivo_fechado": None if aberto else (janela.get("motivo") or "fora do expediente"),
        "fonte": janela.get("fonte"),
    }


def consultar_dados_institucionais(ctx: WhatsAppBotToolContext) -> dict[str, Any]:
    """Endereco, telefone e contato publicos, de `Configuracao`.

    Nunca use `DEFAULT_AGENDA_ROTA_REGRAS["base"]`: e o endereco da base
    operacional (residencial), nao endereco institucional publicavel. E
    nunca `horario_comercial_inicio/fim`, que sao legados e contradizem a
    agenda real.

    Falha FECHADO quando nao ha dado publicavel. Ate 2026-08-23 esta funcao
    devolvia `ok=True` sempre que existisse uma linha de `Configuracao`, mesmo
    com todos os campos nulos. Duas consequencias medidas em stage: a
    prontidao pintava `endereco` e `formas_contato` de verde com o cadastro
    vazio, e o turno ficava com fonte valida para a RF-020 sem ter dado algum,
    de modo que endereco inventado passava aprovado.

    `tem_endereco` e `tem_contato` existem porque uma unica tool sustenta
    DUAS intents. Sem eles nao da para a prontidao ser honesta por intent nem
    para o guardrail saber se ha endereco a ancorar.
    """
    config = _configuracao(ctx.db)
    if config is None:
        return {"ok": False, "error": "Dados institucionais nao configurados."}

    def _limpo(valor: Any) -> Optional[str]:
        texto = str(valor or "").strip()
        return texto or None

    endereco = _limpo(config.endereco)
    telefone = _limpo(config.telefone)
    email = _limpo(config.email)
    cidade = _limpo(config.cidade)
    estado = _limpo(config.estado)

    # Cidade/estado NAO valem como endereco: "Fortaleza/CE" nao diz ao cliente
    # onde ele deve chegar. Contato exige telefone ou e-mail de verdade.
    tem_endereco = endereco is not None
    tem_contato = telefone is not None or email is not None

    if not tem_endereco and not tem_contato:
        vazios = [
            nome
            for nome, valor in (
                ("endereco", endereco),
                ("telefone", telefone),
                ("email", email),
            )
            if valor is None
        ]
        return {
            "ok": False,
            "error": (
                "Cadastro institucional sem endereco e sem contato publicavel. "
                "Preencha em Configuracoes > Empresa: " + ", ".join(vazios) + "."
            ),
            "tem_endereco": False,
            "tem_contato": False,
            "campos_vazios": vazios,
        }

    return {
        "ok": True,
        "tem_endereco": tem_endereco,
        "tem_contato": tem_contato,
        "nome_empresa": _limpo(config.nome_empresa),
        "endereco": endereco,
        "telefone": telefone,
        "email": email,
        "cidade": cidade,
        "estado": estado,
        "website": _limpo(config.website),
    }


_REGIAO_COLUNAS = {
    "fortaleza": "preco_fortaleza_comercial",
    "rm": "preco_rm_comercial",
    "domiciliar": "preco_domiciliar_comercial",
}


# `TabelaPreco.id` -> coluna de preco. Espelha `_preco_tabela_padrao` do
# `precos_service`, que e o que a FATURA usa. Duplicar o mapa e deliberado:
# importar `calcular_preco_servico` traria junto o preco negociado da clinica,
# que esta fora da allowlist da RF-019. O que nao pode e divergir -- se o
# financeiro mudar os ids, este mapa tem de mudar junto. Coberto por teste.
_TABELA_PRECO_REGIAO = {1: "fortaleza", 2: "rm", 3: "domiciliar"}


def _regiao_da_clinica(ctx: "WhatsAppBotToolContext") -> tuple[Optional[str], Optional[str]]:
    """Regiao autoritativa da conversa, ou o motivo de nao haver uma.

    Ate 2026-08-25 a regiao vinha de um parametro que o MODELO preenchia, sem
    nenhum dado no prompt para decidir -- e o silencio dele virava "fortaleza".
    Uma clinica de regiao metropolitana recebia preco de Fortaleza, R$ 20 a
    R$ 50 abaixo da tabela dela, com aparencia de resposta correta.

    Tabela fora de {1,2,3} e customizada (`PrecoServico`), ou seja, negociada.
    Devolve `None` de proposito: o bot nao cota preco negociado, nem por
    acidente. Melhor handoff que numero errado.
    """
    if ctx.match_type != "clinica" or ctx.clinica_id is None:
        return None, None
    clinica = ctx.db.query(Clinica).filter(Clinica.id == ctx.clinica_id).first()
    if clinica is None:
        # Escopo sintetico da sonda de prontidao e da simulacao usa
        # `clinica_id=0`, que nunca casa registro. Quebrar a consulta por isso
        # transformaria artefato de diagnostico em falha de produto; a fatura
        # tambem trata ausencia como tabela padrao (`tabela_preco_id or 1`).
        # Sem cadastro nao ha etiqueta: a frase nao afirma uma tabela que nao
        # foi lida.
        if ctx.clinica_id:
            logger.warning(
                "Clinica %s do escopo da conversa nao foi encontrada ao resolver "
                "a tabela de preco; usando tabela padrao.", ctx.clinica_id
            )
        return None, None
    tabela_id = getattr(clinica, "tabela_preco_id", None) or 1
    regiao = _TABELA_PRECO_REGIAO.get(int(tabela_id))
    if regiao is None:
        return None, "tabela_personalizada"
    return regiao, None


def consultar_preco_tabela(
    ctx: WhatsAppBotToolContext,
    *,
    servico_nome: Optional[str] = None,
    regiao: str = "fortaleza",
) -> dict[str, Any]:
    """Preco de TABELA, lido direto das colunas de `Servico`.

    Deliberadamente NAO usa `calcular_preco_servico`: ela prioriza o preco
    negociado da clinica por design, e `usar_preco_clinica=False` nao a
    torna independente de clinica (a tabela ainda e escolhida por
    `clinica.tabela_preco_id`). Com `clinica_id=None` ela levanta
    HTTPException(404), que escaparia do worker como resposta HTTP.

    A assinatura nao tem parametro de clinica em NENHUMA persona: a RF-019
    autoriza "preco de servico em tabela" para as duas, e repasse/negociacao
    esta fora da allowlist. Vazamento de preco negociado fica impossivel por
    construcao, nao por instrucao de prompt.
    """
    regiao_clinica, impedimento = _regiao_da_clinica(ctx)
    if impedimento == "tabela_personalizada":
        # Preco negociado esta fora da allowlist (RF-019). Falha fechado.
        return {
            "ok": False,
            "error": "Esta clinica usa tabela de preco personalizada; valor precisa vir da equipe.",
            "motivo": "tabela_personalizada",
        }

    # Persona clinica: a regiao vem do cadastro, NAO do parametro do modelo -
    # ele nao tem dado no prompt para decidir.
    chave = regiao_clinica or _normalizar(regiao) or "fortaleza"

    if ctx.match_type == "tutor" and chave != "domiciliar":
        # REGRA DE NEGOCIO (2026-08-26, Martiniano): tutor NUNCA recebe a
        # tabela praticada com clinicas parceiras. As tabelas 1 e 2 sao
        # `Clinicas Fortaleza` e `Regiao Metropolitana` -- preco B2B, que a
        # clinica remarca. Passa-lo ao consumidor final subcotaria a clinica
        # parceira contra ela mesma. Atendimento em clinica: o tutor procura a
        # clinica de preferencia dele. So `domiciliar` (tabela 3) e da
        # FortCordis para o tutor.
        #
        # `ok: True` de proposito, apesar de nao haver valor no payload.
        # Devolver `ok: False` deixava a intent sem fonte e o turno virava
        # `blocked` -- e `blocked` nao envia NADA ao cliente. Medido em stage
        # em 26/08: o tutor perguntava preco e recebia silencio. A pergunta
        # "domiciliar ou em clinica?" e uma resposta legitima, entao precisa
        # de fonte valida para sair. Nao ha vazamento: nenhum valor de tabela
        # 1 ou 2 entra no retorno.
        return {
            "ok": True,
            "orientacao": "escolher_tipo_atendimento",
            "itens": [],
            "domiciliar_disponivel": True,
            "servico_perguntado": str(servico_nome or "").strip() or None,
        }
    coluna = _REGIAO_COLUNAS.get(chave)
    if coluna is None:
        return {"ok": False, "error": "Regiao invalida para consulta de preco."}

    ativos = ctx.db.query(Servico).filter(_legacy_active(Servico.ativo)).all()
    pedido = procedimentos_do_pedido(servico_nome)
    exatos = 0

    if pedido:
        # Casamento por conjunto de procedimentos. Substring pura ordenada por
        # nome escondia `Ecocardiograma` (R$ 180) atras de tres combos mais
        # caros quando a pergunta era "quanto custa o eco" -- ver
        # `whatsapp_bot_servico_match`.
        ranqueados = ordenar_candidatos(ativos, pedido=pedido)
        candidatos = [servico for servico, _grau, _comp in ranqueados]
        graus = {id(servico): grau for servico, grau, _comp in ranqueados}
    elif servico_nome:
        # Termo fora do vocabulario (servico novo, nome proprio de exame).
        # Substring continua valendo como rede: melhor devolver algo
        # verificavel do que abrir mao da pergunta.
        alvo = _normalizar(servico_nome)
        candidatos = sorted(
            (s for s in ativos if alvo and alvo in _normalizar(s.nome)),
            key=lambda s: _normalizar(s.nome),
        )
        graus = {}
    else:
        # Pergunta generica de preco: servico simples antes de combinacao,
        # para a resposta comecar pelo piso da tabela e nao pelo alfabeto.
        candidatos = sorted(
            ativos,
            key=lambda s: (len(procedimentos_do_servico(s.nome)) or 99, _normalizar(s.nome)),
        )
        graus = {}

    itens: list[dict[str, Any]] = []
    omitidos: list[str] = []
    exato_sem_preco = False
    for servico in candidatos[:MAX_SERVICOS_NO_PAYLOAD]:
        bruto = getattr(servico, coluna, None)
        try:
            valor = Decimal(str(bruto)) if bruto is not None else Decimal("0")
        except Exception:
            valor = Decimal("0")
        # `to_decimal` do precos_service converte NULL em 0.00 em silencio, e
        # "R$ 0,00" e um resultado alcancavel. Servico sem preco configurado
        # nao entra no payload - sem valor nao ha o que afirmar.
        if valor <= 0:
            # Nesta regiao o servico nao tem preco (ex.: `Consulta + Eletro`
            # sem coluna RM). Some do payload, mas fica registrado: omitir em
            # silencio devolveria lista incompleta com cara de completa.
            omitidos.append(str(servico.nome or ""))
            if graus.get(id(servico)) == AFINIDADE_EXATA:
                exato_sem_preco = True
            continue
        grau = graus.get(id(servico), 0)
        if grau == AFINIDADE_EXATA:
            exatos += 1
        itens.append({
            "servico": servico.nome,
            "valor": f"{valor:.2f}",
            "regiao": chave,
            "tipo_horario": "comercial",
            "fonte": f"tabela:{coluna}",
            "aderencia": grau,
        })

    if exato_sem_preco:
        # O servico PEDIDO nao tem preco nesta regiao. Responder com os
        # vizinhos seria trocar a pergunta por outra sem avisar.
        return {
            "ok": False,
            "error": "Servico pedido nao tem preco cadastrado para esta regiao.",
            "motivo": "sem_preco_na_regiao",
            "regiao": chave,
        }
    if not itens:
        return {"ok": False, "error": "Nenhum servico com preco de tabela configurado para essa consulta."}
    return {
        "ok": True,
        "itens": itens,
        "total": len(itens),
        "pedido": sorted(pedido),
        "exatos": exatos,
        "regiao": chave,
        "regiao_do_cadastro": regiao_clinica is not None,
        "omitidos_sem_preco": omitidos,
    }


def _status_cliente(exame_status: Any, laudo_status: Any) -> str:
    """Colapsa o estado interno em binario para o cliente (RF-019).

    So `Liberado no portal` conta como pronto. "Finalizado" e
    `aguardando_liberacao`, e dizer "pronto" nesse estado seria prometer um
    documento que o cliente nao consegue abrir.
    """
    if str(exame_status or "").strip() in _RELEASED_EXAM:
        return "pronto"
    if str(laudo_status or "").strip() in _RELEASED_LAUDO:
        return "pronto"
    return "ainda_nao"


def consultar_status_laudo(
    ctx: WhatsAppBotToolContext, *, pet_nome: Optional[str] = None
) -> dict[str, Any]:
    """Status binario de laudo/exame no escopo da conversa.

    A liberacao e por EXAME e o filtro do portal e um OR assimetrico
    (`_portal_exam_release_filter`): consultar so `Laudo.status` perde os
    exames de atendimento liberados que nunca tocam a tabela `laudos`, e so
    `Exame.status` perde o caso inverso. Por isso o outerjoin duplo.

    Nenhum campo clinico entra no payload - sem `descricao`, `diagnostico`,
    `observacoes`, `resultado`, `valor_referencia`, `titulo` (texto livre) e
    sem `anexos` (que carrega blob de medidas estruturadas).
    """
    query = (
        ctx.db.query(
            Exame.tipo_exame,
            Exame.status,
            Exame.data_solicitacao,
            Laudo.status.label("laudo_status"),
            Paciente.nome.label("pet_nome"),
        )
        .outerjoin(Laudo, Laudo.id == Exame.laudo_id)
        .join(Paciente, Paciente.id == Exame.paciente_id)
        .filter(_legacy_active(Paciente.ativo))
    )

    if ctx.match_type == "tutor":
        query = query.filter(Paciente.tutor_id == ctx.tutor_id)
    else:
        # `Laudo` nao tem tutor_id e o vinculo com clinica as vezes so existe
        # via AtendimentoClinico - o portal usa exatamente este OR.
        query = query.outerjoin(
            AtendimentoClinico, AtendimentoClinico.id == Exame.atendimento_id
        ).filter(
            or_(
                AtendimentoClinico.clinica_id == ctx.clinica_id,
                Laudo.clinic_id == ctx.clinica_id,
            )
        )

    if pet_nome:
        # Refinamento DENTRO do conjunto ja escopado. `pet_nome` vem do
        # modelo, portanto nunca e criterio de autorizacao - se nao casar
        # nada, o resultado e vazio, nunca o conjunto inteiro.
        alvo = _normalizar(pet_nome)
        rows = [row for row in query.order_by(Exame.id.desc()).all() if alvo in _normalizar(row.pet_nome)]
    else:
        rows = query.order_by(Exame.id.desc()).limit(MAX_LAUDOS_NO_PAYLOAD).all()

    itens: list[dict[str, Any]] = []
    for row in rows[:MAX_LAUDOS_NO_PAYLOAD]:
        itens.append({
            "tipo_exame": row.tipo_exame or "exame",
            "pet_nome": row.pet_nome,
            "status_cliente": _status_cliente(row.status, row.laudo_status),
            "data_solicitacao": _to_iso(row.data_solicitacao),
        })

    if not itens:
        # Sem registro NAO e "ainda nao": negar existencia de exame que pode
        # existir em outro escopo seria afirmar algo sem fonte.
        return {"ok": False, "error": "Nenhum exame encontrado no escopo desta conversa."}
    return {"ok": True, "itens": itens, "total": len(itens)}


def _trecho_relevante(item: dict[str, Any]) -> bool:
    """Relevancia avaliada na escala PROPRIA de cada sinal.

    Aceita o item se ele qualifica por palavra-chave OU por semantica. Um
    item achado so pela semantica tem `keyword_score == 0`, e um achado so
    lexicalmente tem `semantic_score is None` - avaliar os dois pelo mesmo
    numero rejeitaria metade dos acertos legitimos.
    """
    try:
        keyword_score = float(item.get("keyword_score") or 0)
    except (TypeError, ValueError):
        keyword_score = 0.0
    try:
        semantic_score = float(item.get("semantic_score") or 0)
    except (TypeError, ValueError):
        semantic_score = 0.0
    return (
        keyword_score >= CONHECIMENTO_KEYWORD_SCORE_MINIMO
        or semantic_score >= CONHECIMENTO_SEMANTIC_SCORE_MINIMO
    )


def buscar_conhecimento_institucional(
    ctx: WhatsAppBotToolContext, *, consulta: str
) -> dict[str, Any]:
    """Wrapper filtrado sobre `search_knowledge`.

    `search_knowledge` e read-only e sem `current_user`, entao chamar e
    legitimo - o que a RF-018 proibe e `consultar_conhecimento_interno` de
    `assistente_ia_tools`. Mas a base tem escopo ZERO, nao tem coluna de
    audiencia e contem procedimento clinico de staff. Daí os tres filtros:
    categoria institucional, `source` obrigatoria (RF-020 exige fonte citavel
    e a coluna e nullable) e piso de relevancia por escala.

    Todo descarte e CONTADO e devolvido em `descartados`. Sem isso, um admin
    que cadastra o documento com a categoria default (`manual`) ou sem fonte
    ve o bot responder "nao sei" sem nenhuma pista do motivo - foi exatamente
    o que aconteceu na primeira versao deste modulo.
    """
    from app.services.assistente_ia_management import search_knowledge

    texto = str(consulta or "").strip()
    if len(texto) < 3:
        return {
            "ok": False,
            "error": "Consulta muito curta para a base institucional.",
            "motivo": "consulta_curta",
        }

    try:
        resultado = search_knowledge(ctx.db, query=texto, limit=10)
    except Exception:
        logger.exception("Falha ao consultar a base institucional para o bot do WhatsApp.")
        return {
            "ok": False,
            "error": "Base institucional indisponivel.",
            "motivo": "base_indisponivel",
        }

    # Retorno bifurcado: no ramo de falha nao existe a chave `items`.
    if not resultado.get("ok"):
        return {
            "ok": False,
            "error": "Nada encontrado na base institucional.",
            "motivo": "sem_resultado_na_busca",
            "descartados": {},
        }

    descartados = {"categoria": 0, "sem_fonte": 0, "pouco_relevante": 0}
    trechos: list[dict[str, Any]] = []
    for item in resultado.get("items") or []:
        if not isinstance(item, dict):
            continue
        if ctx.match_type == "visitante" and _normalizar(item.get("category")) not in (
            "institucional", "atendimento", "institucional publico", "atendimento publico",
            "institucional_publico", "atendimento_publico",
        ):
            descartados["categoria"] += 1
            continue
        if not _categoria_e_institucional(item.get("category")):
            descartados["categoria"] += 1
            continue
        fonte = str(item.get("source") or "").strip()
        if not fonte:
            descartados["sem_fonte"] += 1
            continue
        if not _trecho_relevante(item):
            descartados["pouco_relevante"] += 1
            continue
        try:
            score = float(item.get("score") or 0)
        except (TypeError, ValueError):
            score = 0.0
        trechos.append({
            "document_id": item.get("document_id"),
            # `chunk_id` so existe no caminho semantico.
            "chunk_id": item.get("chunk_id"),
            "titulo": item.get("title"),
            "fonte": fonte,
            "trecho": str(item.get("excerpt") or "")[:EXCERPT_MAX_CHARS],
            "score": score,
            "retrieval": item.get("retrieval"),
        })
        if len(trechos) >= MAX_TRECHOS_CONHECIMENTO:
            break

    if not trechos:
        if any(descartados.values()):
            logger.info(
                "Base institucional tinha candidatos mas todos foram descartados "
                "(categoria=%s, sem_fonte=%s, pouco_relevante=%s).",
                descartados["categoria"],
                descartados["sem_fonte"],
                descartados["pouco_relevante"],
            )
        return {
            "ok": False,
            "error": "Nada encontrado na base institucional.",
            "motivo": "todos_descartados" if any(descartados.values()) else "sem_candidato",
            "descartados": descartados,
        }
    return {
        "ok": True,
        "trechos": trechos,
        "total": len(trechos),
        "descartados": descartados,
    }


# --------------------------------------------------------------------------
# Allowlist por persona e dispatcher
# --------------------------------------------------------------------------

MAX_CLINICAS_SUGERIDAS = 3


def _distancia_km(lat1: Any, lon1: Any, lat2: Any, lon2: Any) -> Optional[float]:
    """Haversine, reusando a formula ja validada em `logistica_service`.

    Importada em vez de reescrita: duas implementacoes de distancia no mesmo
    repositorio divergiriam em silencio.
    """
    try:
        return _haversine_km(float(lat1), float(lon1), float(lat2), float(lon2))
    except (TypeError, ValueError):
        return None


def _ordenar_por_distancia_do_tutor(
    ctx: "WhatsAppBotToolContext", clinicas: list[Any]
) -> Optional[list[Any]]:
    """Ordena por distancia real, ou `None` se nao der para calcular.

    `None` e diferente de "ordem preservada": o chamador precisa saber que
    NAO houve calculo, para a frase nao afirmar "a mais perto de voce" sem
    ter medido nada.
    """
    tutor = ctx.db.query(Tutor).filter(Tutor.id == ctx.tutor_id).first()
    lat = getattr(tutor, "latitude", None) if tutor is not None else None
    lon = getattr(tutor, "longitude", None) if tutor is not None else None
    if lat is None or lon is None:
        return None
    com_km = []
    for clinica in clinicas:
        km = _distancia_km(lat, lon, getattr(clinica, "latitude", None),
                           getattr(clinica, "longitude", None))
        if km is not None:
            com_km.append((km, clinica))
    if len(com_km) != len(clinicas):
        # Parcial ordenaria umas e deixaria outras no fim por acaso.
        return None
    com_km.sort(key=lambda par: (par[0], _normalizar(par[1].nome)))
    return [clinica for _km, clinica in com_km]


def buscar_clinica_parceira(
    ctx: WhatsAppBotToolContext, *, bairro: Optional[str] = None
) -> dict[str, Any]:
    """Clinicas parceiras perto do tutor, por bairro informado ou por cadastro.

    Existe porque a RF-P17 orienta o tutor a procurar "a clinica de sua
    preferencia" sem dizer QUAL -- resposta correta e inutil. Aqui ela vira
    acionavel.

    Exclusiva da persona tutor, por construcao (`TOOLS_POR_PERSONA`). Uma
    clinica parceira perguntando onde ficam as OUTRAS clinicas parceiras
    receberia o mapa da rede de um concorrente; a allowlist por persona
    impede isso sem depender de instrucao de prompt.

    Duas estrategias, nesta ordem:

    1. **Bairro informado**: casamento por nome normalizado. E o que o cliente
       pediu literalmente, entao ganha de qualquer calculo.
    2. **Sem bairro**: se o tutor tem coordenadas no cadastro, ordena por
       distancia real. Sem elas, devolve `precisa_bairro` -- que NAO e erro:
       e a pergunta que falta, e o turno responde perguntando.

    Nunca cai de uma estrategia para a outra em silencio: bairro sem clinica
    devolve `sem_clinica_no_bairro`, nao a lista da estrategia 2. Sugerir uma
    clinica de outro canto da cidade a quem perguntou por um bairro
    especifico seria trocar a pergunta.
    """
    if ctx.match_type != "tutor":
        return {"ok": False, "error": "Sugestao de clinica parceira e exclusiva de tutor."}

    ativas = [
        c
        for c in ctx.db.query(Clinica).filter(_legacy_active(Clinica.ativo)).all()
        if str(getattr(c, "nome", "") or "").strip()
    ]
    if not ativas:
        return {"ok": False, "error": "Nenhuma clinica parceira ativa cadastrada."}

    alvo = _normalizar(bairro)
    if alvo:
        no_bairro = [c for c in ativas if alvo and alvo == _normalizar(getattr(c, "bairro", None))]
        if not no_bairro:
            # Casamento parcial so DEPOIS do exato: "Centro" nao pode puxar
            # "Centro de Fortaleza" na frente de um "Centro" literal.
            no_bairro = [
                c for c in ativas if alvo and alvo in _normalizar(getattr(c, "bairro", None))
            ]
        if no_bairro:
            # Nome de bairro NAO e unico entre cidades. Em producao (26/08)
            # "Centro" tem 10 clinicas em 5 cidades -- Maranguape, Eusebio,
            # Fortaleza, Aracati e Caucaia. Devolver as primeiras da lista
            # mandaria um tutor de Caucaia para Maranguape, a ~40 km, anunciada
            # como "a mais perto de voce". Havendo coordenadas do tutor, o
            # empate de nome e desfeito por distancia real.
            ordenado = _ordenar_por_distancia_do_tutor(ctx, no_bairro)
            return {
                "ok": True,
                "criterio": "bairro",
                "bairro_consultado": str(bairro or "").strip(),
                "ordenado_por_distancia": ordenado is not None,
                "itens": [
                    _clinica_publicavel(c)
                    for c in (ordenado or no_bairro)[:MAX_CLINICAS_SUGERIDAS]
                ],
            }
        return {
            "ok": True,
            "criterio": "sem_clinica_no_bairro",
            "bairro_consultado": str(bairro or "").strip(),
            "itens": [],
        }

    tutor = ctx.db.query(Tutor).filter(Tutor.id == ctx.tutor_id).first()
    lat = getattr(tutor, "latitude", None) if tutor is not None else None
    lon = getattr(tutor, "longitude", None) if tutor is not None else None
    if lat is None or lon is None:
        return {"ok": True, "criterio": "precisa_bairro", "itens": []}

    com_distancia = []
    for clinica in ativas:
        km = _distancia_km(lat, lon, getattr(clinica, "latitude", None),
                           getattr(clinica, "longitude", None))
        if km is not None:
            com_distancia.append((km, clinica))
    if not com_distancia:
        # Cadastro sem coordenada nenhuma: perguntar o bairro e melhor que
        # devolver uma lista sem criterio.
        return {"ok": True, "criterio": "precisa_bairro", "itens": []}

    com_distancia.sort(key=lambda par: (par[0], _normalizar(par[1].nome)))
    return {
        "ok": True,
        "criterio": "distancia",
        "ordenado_por_distancia": True,
        "itens": [
            {**_clinica_publicavel(c), "distancia_km": f"{km:.1f}"}
            for km, c in com_distancia[:MAX_CLINICAS_SUGERIDAS]
        ],
    }


def _clinica_publicavel(clinica: Any) -> dict[str, Any]:
    """Allowlist de campo, como no resto do bot.

    So o que um tutor precisa para chegar la. `observacoes`, `cnpj`,
    `tabela_preco_id`, `preco_personalizado_*` e afins ficam de fora por
    construcao, nao por instrucao de prompt.
    """
    # WhatsApp antes de telefone: e o canal por onde a clinica de fato se
    # comunica (Martiniano, 27/08). `whatsapps` e coluna JSON com lista, as
    # vezes serializada como string -- `_whatsapps` do clinics360 ja trata as
    # duas formas, e reusar evita uma terceira implementacao divergente.
    lista = _whatsapps(getattr(clinica, "whatsapps", None))
    whatsapp = _so_digitos_contato(lista[0]) if lista else ""
    telefone = _so_digitos_contato(getattr(clinica, "telefone", None))
    return {
        "nome": str(getattr(clinica, "nome", "") or "").strip(),
        "bairro": str(getattr(clinica, "bairro", "") or "").strip() or None,
        # Sem a cidade, "Centro" e ambiguo entre 5 municipios no cadastro real.
        "cidade": str(getattr(clinica, "cidade", "") or "").strip() or None,
        "endereco": str(getattr(clinica, "endereco", "") or "").strip() or None,
        "whatsapp": whatsapp or None,
        "telefone": telefone or None,
    }


def _so_digitos_contato(value: Any) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


_TOOLS_COMUNS: dict[str, Callable[..., dict[str, Any]]] = {
    "consultar_horario_funcionamento": consultar_horario_funcionamento,
    "consultar_dados_institucionais": consultar_dados_institucionais,
    "consultar_preco_tabela": consultar_preco_tabela,
    "consultar_status_laudo": consultar_status_laudo,
    "buscar_conhecimento_institucional": buscar_conhecimento_institucional,
}

# Allowlist e DADO, por persona, consultada antes do dispatch - para a
# classificacao poder ser testada sem chamar o modelo e para uma tool nova
# nao entrar por descuido numa persona.
TOOLS_POR_PERSONA: dict[str, dict[str, Callable[..., dict[str, Any]]]] = {
    "visitante": {
        "consultar_horario_funcionamento": consultar_horario_funcionamento,
        "consultar_dados_institucionais": consultar_dados_institucionais,
        "buscar_conhecimento_institucional": buscar_conhecimento_institucional,
    },
    # `buscar_clinica_parceira` so na persona tutor: dar a uma clinica
    # parceira o endereco das outras seria entregar a rede a um concorrente.
    "tutor": {**_TOOLS_COMUNS, "buscar_clinica_parceira": buscar_clinica_parceira},
    "clinica": dict(_TOOLS_COMUNS),
}

# Schemas expostos ao modelo. Nenhum tem tutor_id/clinica_id: o escopo vem
# do contexto Python. Formato flat da API Responses, com todo campo
# opcional listado em `required` e tipo uniao - `strict: True` exige isso.
TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "buscar_clinica_parceira",
        "description": (
            "Clinicas parceiras perto do tutor. Passe `bairro` quando o cliente disser "
            "onde mora; deixe null para usar o endereco do cadastro dele."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "bairro": {"type": ["string", "null"], "description": "Bairro dito pelo cliente."}
            },
            "required": ["bairro"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "consultar_horario_funcionamento",
        "description": "Horario de funcionamento da FortCordis numa data (default: hoje).",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {"data": {"type": ["string", "null"], "description": "AAAA-MM-DD"}},
            "required": ["data"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "consultar_dados_institucionais",
        "description": "Endereco, telefone, e-mail e cidade publicos da FortCordis.",
        "strict": True,
        "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    },
    {
        "type": "function",
        "name": "consultar_preco_tabela",
        "description": "Preco de tabela de servicos. Nunca preco negociado nem repasse.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "servico_nome": {"type": ["string", "null"]},
                "regiao": {"type": ["string", "null"], "description": "fortaleza | rm | domiciliar"},
            },
            "required": ["servico_nome", "regiao"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "consultar_status_laudo",
        "description": "Se o laudo/exame esta pronto. Devolve apenas pronto ou ainda_nao, sem conteudo do laudo.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {"pet_nome": {"type": ["string", "null"]}},
            "required": ["pet_nome"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "buscar_conhecimento_institucional",
        "description": "Busca informacao institucional (como agendar, area de atendimento, fluxo de exame) na base interna.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {"consulta": {"type": "string"}},
            "required": ["consulta"],
            "additionalProperties": False,
        },
    },
]


def execute_bot_tool(
    ctx: WhatsAppBotToolContext, nome: str, argumentos: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Dispatcher que falha FECHADO.

    Nome fora da allowlist DAQUELA persona nao roda - e nao basta estar na
    uniao das duas. Argumentos sao validados aqui porque com provider fake
    (testes) a garantia do `strict: True` da OpenAI desaparece.
    """
    permitidas = TOOLS_POR_PERSONA.get(ctx.match_type) or {}
    funcao = permitidas.get(str(nome or "").strip())
    if funcao is None:
        return {"ok": False, "error": "Ferramenta nao disponivel para esta conversa."}

    argumentos = argumentos if isinstance(argumentos, dict) else {}
    limpos = {
        chave: valor
        for chave, valor in argumentos.items()
        if chave in {"data", "servico_nome", "regiao", "pet_nome", "consulta"}
        and valor is not None
    }
    try:
        return funcao(ctx, **limpos)
    except TypeError:
        return {"ok": False, "error": "Argumentos invalidos para a ferramenta."}
    except Exception:
        logger.exception("Falha ao executar tool %s do bot de atendimento WhatsApp.", nome)
        return {"ok": False, "error": "Falha ao consultar o dado solicitado."}
