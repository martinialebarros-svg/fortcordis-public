from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.agenda_config import carregar_agenda_feriados, obter_feriado
from app.models.configuracao import Configuracao

PRAZO_LAUDO_HORAS_UTEIS = 48

# Tipos de laudo esperados por nome de servico agendado - usado para a fila
# de pendentes cobrir agendamentos sem Atendimento Clinico/Exame (fluxo do
# dropdown "Laudar" na Agenda, que cria o Laudo direto via agendamento_id,
# sem nunca gerar Exame). Confirmado com o usuario em 2026-08-17 a partir do
# catalogo real de servicos em stage - servicos fora desta lista (Consulta,
# Drenagem de Efusao Pericardica, Reavaliacao/Retorno) nunca geram laudo e
# ficam de fora da fila. Combos ("Eco + Eletro", "Eco + PA") esperam 2 tipos.
SERVICO_NOME_TIPOS_LAUDO: dict[str, tuple[str, ...]] = {
    "ecocardiograma": ("ecocardiograma",),
    "eletrocardiograma": ("eletrocardiograma",),
    "pressão arterial": ("pressao_arterial",),
    "eco + eletro": ("ecocardiograma", "eletrocardiograma"),
    "eco + pa": ("ecocardiograma", "pressao_arterial"),
}


def tipos_laudo_esperados(servico_nome: str | None) -> tuple[str, ...]:
    """Tipos de laudo esperados para o nome de servico agendado (ver
    `SERVICO_NOME_TIPOS_LAUDO`). Retorna vazio se o servico nao gera laudo
    ou nao e reconhecido."""
    if not servico_nome:
        return ()
    return SERVICO_NOME_TIPOS_LAUDO.get(servico_nome.strip().lower(), ())


def resolver_servico_nome(db: Session, servico_id, servico_denormalizado: str | None) -> str | None:
    """Nome do servico agendado - `servico_id` (fonte confiavel) com
    fallback para o campo denormalizado `Agendamento.servico` (string
    livre), usado quando `servico_id` e nulo (ocorrencia real conhecida,
    nao so de dados legados/teste)."""
    if servico_id:
        from app.models.servico import Servico

        servico = db.query(Servico).filter(Servico.id == servico_id).first()
        if servico and servico.nome:
            return servico.nome
    return servico_denormalizado


def carregar_feriados(db: Session) -> list[dict[str, str]]:
    config = db.query(Configuracao).first()
    raw = getattr(config, "agenda_feriados", None) if config else None
    return carregar_agenda_feriados(raw)


def _e_dia_util(dia: date, feriados: list[dict[str, str]]) -> bool:
    if dia.weekday() >= 5:  # 5 = sabado, 6 = domingo
        return False
    if obter_feriado(dia, feriados):
        return False
    return True


def horas_uteis_entre(inicio: datetime, fim: datetime, feriados: list[dict[str, str]]) -> float:
    """Horas corridas contidas em dias uteis entre dois timestamps.

    Sabado, domingo e datas em `feriados` contam 0h - sem recorte de
    horario comercial dentro do dia util (conta as 24h corridas do dia).
    """
    inicio_naive = inicio.replace(tzinfo=None) if inicio.tzinfo else inicio
    fim_naive = fim.replace(tzinfo=None) if fim.tzinfo else fim

    if fim_naive <= inicio_naive:
        return 0.0

    total_horas = 0.0
    cursor = inicio_naive
    while cursor.date() < fim_naive.date():
        proximo_dia = datetime.combine(cursor.date() + timedelta(days=1), datetime.min.time())
        if _e_dia_util(cursor.date(), feriados):
            total_horas += (proximo_dia - cursor).total_seconds() / 3600
        cursor = proximo_dia

    if _e_dia_util(cursor.date(), feriados):
        total_horas += (fim_naive - cursor).total_seconds() / 3600

    return total_horas
