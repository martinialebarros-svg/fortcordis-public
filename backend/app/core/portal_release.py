PORTAL_RELEASED_STATUS = "Liberado no portal"

PORTAL_RELEASED_EXAM_STATUSES = (PORTAL_RELEASED_STATUS,)
PORTAL_RELEASED_LAUDO_STATUSES = (PORTAL_RELEASED_STATUS,)


def is_portal_released_status(status: str | None, *, kind: str = "exam") -> bool:
    value = str(status or "").strip()
    if kind == "laudo":
        return value in PORTAL_RELEASED_LAUDO_STATUSES
    return value in PORTAL_RELEASED_EXAM_STATUSES
