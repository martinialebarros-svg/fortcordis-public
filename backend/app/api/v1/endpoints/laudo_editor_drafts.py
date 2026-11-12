"""Private recovery workspaces. These routes never save or emit a clinical report."""

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.schemas.laudo_editor_draft import (
    LaudoEditorDraftClose, LaudoEditorDraftClosedResponse,
    LaudoEditorDraftResponse, LaudoEditorDraftSave,
)
from app.schemas.echo_pdf_preview import EchoPdfPreviewRequest
from app.services.laudo_editor_draft_service import close_editor_draft, get_editor_draft, save_editor_draft


router = APIRouter(prefix="/laudos/editor-drafts")


def _require_editor_owner(user: User, expected_owner_id: int) -> None:
    # The cookie remains the authentication authority. This header only stops
    # an old open editor from autosaving under a different browser session.
    if expected_owner_id != user.id:
        raise HTTPException(403, "A sessão mudou. Reabra o editor com o usuário atual antes de continuar.")


@router.get("/{draft_id}", response_model=LaudoEditorDraftResponse)
def get_draft(draft_id: UUID, response: Response,
              expected_owner_id: int = Header(..., alias="X-Editor-Owner-Id", gt=0),
              db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _require_editor_owner(user, expected_owner_id)
    response.headers["Cache-Control"] = "no-store"
    return get_editor_draft(db, user.id, str(draft_id))


@router.put("/{draft_id}", response_model=LaudoEditorDraftResponse)
def save_draft(draft_id: UUID, payload: LaudoEditorDraftSave, response: Response,
               expected_owner_id: int = Header(..., alias="X-Editor-Owner-Id", gt=0),
               db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _require_editor_owner(user, expected_owner_id)
    response.headers["Cache-Control"] = "no-store"
    return save_editor_draft(db, user.id, str(draft_id), payload)


@router.post("/{draft_id}/close", response_model=LaudoEditorDraftClosedResponse)
def close_draft(draft_id: UUID, payload: LaudoEditorDraftClose, response: Response,
                expected_owner_id: int = Header(..., alias="X-Editor-Owner-Id", gt=0),
                db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _require_editor_owner(user, expected_owner_id)
    response.headers["Cache-Control"] = "no-store"
    return close_editor_draft(db, user.id, str(draft_id), payload)


@router.post("/{draft_id}/preview", response_class=Response)
def preview_draft(draft_id: UUID, payload: EchoPdfPreviewRequest,
                  expected_owner_id: int = Header(..., alias="X-Editor-Owner-Id", gt=0),
                  db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.services.echo_pdf_preview import render_echo_editor_preview

    _require_editor_owner(user, expected_owner_id)
    try:
        pdf = render_echo_editor_preview(db, user, str(draft_id), payload)
    except HTTPException:
        raise
    except Exception:
        # Do not echo the submitted clinical content or internal file paths.
        raise HTTPException(500, "Não foi possível gerar a prévia. O rascunho permanece preservado.") from None
    return Response(content=pdf.content, media_type="application/pdf", headers={
        "Content-Disposition": f'inline; filename="{pdf.filename}"',
        "Cache-Control": "private, no-store", "Pragma": "no-cache",
        "X-Content-Type-Options": "nosniff", "X-Echo-Preview-Snapshot": pdf.cache_key,
    })
