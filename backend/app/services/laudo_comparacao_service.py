"""Read-only, same-patient comparison of explicitly dated echocardiograms."""

from __future__ import annotations

import re
from datetime import date, datetime

from sqlalchemy import func
from sqlalchemy.orm import Session, load_only

from app.core.portal_release import PORTAL_RELEASED_STATUS
from app.models.laudo import Laudo
from app.models.paciente import Paciente
from app.schemas.laudo_comparacao import (
    LaudoComparacaoAnteriorResponse,
    LaudoComparacaoOpcao,
    LaudoComparacaoSnapshot,
)
from app.utils.ecocardiograma_medidas import extrair_medidas_ecocardiograma_da_descricao
from app.utils.echo_unit_provenance import CONFIRMED_UNIT_PREFIX, ECHO_LENGTH_KEYS
from app.utils.paciente_helpers import OPERATIONAL_TIME_ZONE, data_civil_referencia


# Preserve the complete registered length context for the existing ambiguity
# guard. Only the 12 LV dimensions and AE/Ao are rows in this initial UI.
_SNAPSHOT_KEYS = ECHO_LENGTH_KEYS | {
    "AE_Ao", "VE_tecnica_relatorio", "VE_vista_2D", "AE_Ao_metodo",
} | {f"{CONFIRMED_UNIT_PREFIX}{key}" for key in ECHO_LENGTH_KEYS}
_MEASUREMENTS_SECTION = re.compile(
    r"^[ \t]*##[ \t]*Medidas[ \t]+Ecocardiogr(?:a|á)ficas[ \t]*(?:\r?\n|\Z)"
    r"(.*?)(?=^[ \t]*##|\Z)",
    re.IGNORECASE | re.DOTALL | re.MULTILINE,
)
_MEASUREMENT_LINE = re.compile(
    r"^[ \t]*-[ \t]*([A-Za-z0-9_]+):[ \t]*(.*?)[ \t]*$",
    re.MULTILINE,
)


class LaudoComparacaoNaoEncontrada(Exception):
    """The current report or a requested eligible previous report is absent."""


class LaudoComparacaoPacienteAusente(Exception):
    """An explicit patient identity is required; names are never a fallback."""


def _exam_day(laudo: Laudo) -> date | None:
    # Never substitute report creation, update or finalization for acquisition.
    return data_civil_referencia(laudo.data_exame, data_calendario=True)


def _snapshot(laudo: Laudo) -> LaudoComparacaoSnapshot:
    section = _MEASUREMENTS_SECTION.search(laudo.descricao or "")
    # Isolate the first real section before calling the shared parser. In an
    # empty legacy section, its whitespace matching otherwise reaches the next
    # heading and could mistake narrative or a second study for measurements.
    measurements = extrair_medidas_ecocardiograma_da_descricao(
        f"## Medidas Ecocardiograficas\n{section.group(1)}" if section else None,
    )
    explicit = {}
    if section:
        for match in _MEASUREMENT_LINE.finditer(section.group(1)):
            key, raw_value = match.group(1), match.group(2).strip()
            if key not in _SNAPSHOT_KEYS:
                continue
            # A legacy description may repeat a canonical field. Only its last
            # registered occurrence is authoritative, including clears or an
            # unknown unit/method. Parsing that single line retains the shared
            # normalization of valid values without reviving an older value.
            parsed_line = extrair_medidas_ecocardiograma_da_descricao(
                f"## Medidas Ecocardiograficas\n- {key}: {raw_value}\n",
            )
            explicit[key] = parsed_line.get(key, raw_value)
    measurements.update(explicit)
    # The shared parser infers a sole populated LV technique for the editor.
    # This read projection requires an explicitly registered technique instead.
    if "VE_tecnica_relatorio" not in explicit:
        measurements.pop("VE_tecnica_relatorio", None)
    day = _exam_day(laudo)
    return LaudoComparacaoSnapshot(
        id=laudo.id,
        paciente_id=laudo.paciente_id,
        status=laudo.status or "",
        data_exame=day.isoformat() if day else None,
        medidas={key: value for key, value in measurements.items() if key in _SNAPSHOT_KEYS},
    )


def comparar_laudo_anterior(
    db: Session,
    laudo_id: int,
    *,
    anterior_id: int | None = None,
) -> LaudoComparacaoAnteriorResponse:
    """Select a completed prior echo by acquisition day, never by patient name.

    Values remain as recorded, with explicit unit/method metadata. There is no
    current-patient weight fallback, clinical derivation, persistence or PDF job.
    """
    with db.no_autoflush:
        current = db.query(Laudo).filter(Laudo.id == laudo_id).first()
        if current is None:
            raise LaudoComparacaoNaoEncontrada()
        if not current.paciente_id or not db.query(Paciente.id).filter(
            Paciente.id == current.paciente_id,
        ).first():
            raise LaudoComparacaoPacienteAusente()

        response = LaudoComparacaoAnteriorResponse(
            estado="sem_anterior",
            paciente_id=current.paciente_id,
            atual=_snapshot(current),
        )
        is_echo = str(current.tipo or "").strip().lower() == "ecocardiograma"
        current_day = _exam_day(current)
        today = datetime.now(OPERATIONAL_TIME_ZONE).date()
        if not is_echo or current_day is None or current_day > today:
            if anterior_id is not None:
                raise LaudoComparacaoNaoEncontrada()
            response.estado = "tipo_nao_suportado" if not is_echo else "data_atual_ausente"
            # A different modality must not expose coincidentally named fields.
            if not is_echo:
                response.atual.medidas = {}
            return response

        candidates = (
            db.query(Laudo)
            .options(load_only(Laudo.id, Laudo.data_exame, Laudo.paciente_id, Laudo.status))
            .filter(
                Laudo.paciente_id == current.paciente_id,
                Laudo.id != current.id,
                func.lower(func.trim(Laudo.tipo)) == "ecocardiograma",
                # Portal release changes the stored status of a completed
                # report; it must remain eligible without admitting drafts or
                # archived reports. Keep the original status in the snapshot.
                Laudo.status.in_(("Finalizado", PORTAL_RELEASED_STATUS)),
                Laudo.data_exame.isnot(None),
            )
            .all()
        )
        eligible = [
            (candidate, day)
            for candidate in candidates
            if (day := _exam_day(candidate)) is not None and day < current_day and day <= today
        ]
        # ID only stabilizes the selector's presentation. It never resolves two
        # exams on the same civil day automatically.
        eligible.sort(key=lambda item: (item[1], item[0].id), reverse=True)
        response.opcoes = [
            LaudoComparacaoOpcao(id=candidate.id, data_exame=day.isoformat())
            for candidate, day in eligible
        ]

        if anterior_id is not None:
            selected = next((candidate for candidate, _ in eligible if candidate.id == anterior_id), None)
            if selected is None:
                # Same generic result for absent, foreign-patient or ineligible IDs.
                raise LaudoComparacaoNaoEncontrada()
        elif not eligible:
            return response
        elif len(eligible) > 1 and eligible[0][1] == eligible[1][1]:
            response.estado = "data_anterior_ambigua"
            return response
        else:
            selected = eligible[0][0]

        response.estado = "disponivel"
        response.anterior = _snapshot(selected)
        return response
