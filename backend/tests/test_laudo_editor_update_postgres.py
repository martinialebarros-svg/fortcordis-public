"""Real locking proofs; opt-in only for a disposable local Unix-socket cluster."""
import copy
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "synthetic-editor-pg-local-secret-123456789")

from app.api.v1.endpoints import laudos
from app.db.database import Base
from app.models.imagem_laudo import ImagemLaudo, ImagemTemporaria
from app.models.laudo import Laudo
from app.models.laudo_editor_draft import LaudoEditorDraft, LaudoEditorDraftRequest
from app.models.paciente import Paciente
from app.models.papel import Papel, usuario_papel
from app.models.papel_permissao import PapelPermissao
from app.models.tutor import Tutor
from app.models.user import User
from app.schemas.echo_editor_update import EchoEditorUpdate
from app.schemas.laudo_editor_draft import LaudoEditorDraftSave
from app.services.echo_editor_source import load_echo_editor_source
from app.services.echo_editor_update import apply_echo_editor_update
from app.services.laudo_editor_draft_service import save_editor_draft


@pytest.fixture
def editor_pg():
    value = os.environ.get("LAUDO_EDITOR_TEST_POSTGRES_URL")
    if not value:
        pytest.skip("PostgreSQL descartável local não configurado")
    parsed = make_url(value)
    socket = Path(str(parsed.query.get("host", "")))
    assert parsed.host is None and parsed.database == "echo_editor_test"
    assert socket.is_absolute() and socket.name == "socket"
    assert socket.parent.name.startswith("echo-editor-pg-")
    schema = "echo_editor_" + uuid4().hex
    admin = create_engine(value)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(value, connect_args={"options": f"-csearch_path={schema} -clock_timeout=10000 -cstatement_timeout=20000"})
    tables = [Papel.__table__, User.__table__, usuario_papel, PapelPermissao.__table__,
              Tutor.__table__, Paciente.__table__, Laudo.__table__, ImagemLaudo.__table__,
              ImagemTemporaria.__table__, LaudoEditorDraft.__table__, LaudoEditorDraftRequest.__table__]
    try:
        Base.metadata.create_all(engine, tables=tables)
        sessions = sessionmaker(bind=engine, autoflush=False)
        with sessions() as db:
            db.add(User(id=1, nome="QA", email="editor@example.invalid", ativo=1,
                        papeis=[Papel(id=1, nome="admin")]))
            db.add(Tutor(id=1, nome="QA tutor", ativo=1))
            db.add(Paciente(id=1, nome="QA original", especie="Felina", peso_kg=4.8,
                            tutor_id=1, ativo=1, observacoes="Nota que deve permanecer."))
            db.add(Laudo(id=1, paciente_id=1, veterinario_id=1, tipo="ecocardiograma",
                         titulo="QA", descricao="Original", diagnostico="Original", status="Finalizado"))
            db.flush()
            db.add(ImagemLaudo(laudo_id=1, nome_arquivo="existing.png", tamanho_bytes=3,
                               conteudo=b"qa1", ordem=0, descricao="Original", incluir_no_pdf=True, ativo=1))
            db.add(ImagemTemporaria(session_id="qa-temp", nome_arquivo="new.png", tamanho_bytes=3,
                                    conteudo=b"qa2", expira_em=datetime.utcnow() + timedelta(hours=1)))
            db.commit()
        yield sessions
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def request_for(sessions, revision, label, *, draft_id=None, include_temp=False):
    draft_id = draft_id or str(uuid4())
    snapshot = {"schema_version": 1, "editor": "existing-echo",
                "source": {"laudo_id": 1, "editor_revision": revision},
                "sessionId": "qa-temp", "imagens": [{"tempId": 1, "uploaded": True}] if include_temp else [],
                "conteudo": {"conclusao": label}, "medidas": {"Onda_E": "0", "Onda_A": ""}}
    with sessions() as db:
        saved = save_editor_draft(db, 1, draft_id, LaudoEditorDraftSave(
            expected_revision=0, request_id=uuid4(), context_key="edit:laudo:1", snapshot=snapshot))
    return {"expected_editor_revision": revision, "request_id": str(uuid4()),
            "editor_draft_id": draft_id, "expected_draft_revision": saved["revision"],
            "payload_laudo": {"diagnostico": label, "status": "Finalizado"},
            "paciente": {"nome": label},
            "imagens": {"persistidas": [{"id": 1, "ordem": 0, "descricao": label,
                                          "incluir_no_pdf": False}], "removidas_ids": [],
                         "temp_session_id": "qa-temp" if include_temp else None,
                         "temp_config": [{"id": 1, "ordem": 1, "descricao": label,
                                          "incluir_no_pdf": True}] if include_temp else []}}


def current_revision(sessions):
    with sessions() as db:
        return load_echo_editor_source(db, 1).revision


@pytest.mark.parametrize("same_request", [False, True])
def test_concurrent_source_updates_and_identical_retry(editor_pg, same_request):
    sessions = editor_pg
    version = current_revision(sessions)
    first = request_for(sessions, version, "QA winner A")
    second = copy.deepcopy(first) if same_request else request_for(sessions, version, "QA winner B")
    barrier = Barrier(2)

    def apply(body):
        with sessions() as db:
            # Stale identity maps must be refreshed AFTER obtaining the lock.
            assert load_echo_editor_source(db, 1).revision == version
            barrier.wait(timeout=10)
            try:
                result = apply_echo_editor_update(db, db.get(User, 1), 1, EchoEditorUpdate(**body))
                return 200, result
            except HTTPException as error:
                db.rollback()
                return error.status_code, None

    with patch.object(laudos, "_sincronizar_publicacao_laudo_no_portal", return_value=(None, None, None, None)) as portal:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(apply, [first, second]))
        assert sorted(status for status, _ in results) == ([200, 200] if same_request else [200, 409])
        assert portal.call_count == 1
    with sessions() as db:
        source = load_echo_editor_source(db, 1)
        assert source.laudo.diagnostico in {first["payload_laudo"]["diagnostico"], second["payload_laudo"]["diagnostico"]}
        assert source.paciente.nome == source.laudo.diagnostico == source.imagens[0].descricao
        assert source.paciente.observacoes == "Nota que deve permanecer."
        assert source.laudo.status == "Finalizado" and source.imagens[0].incluir_no_pdf is False
        assert db.query(LaudoEditorDraftRequest).filter_by(operation="apply").count() == 1
        assert db.query(LaudoEditorDraft).filter(LaudoEditorDraft.closed_at.is_not(None)).count() == 1
        assert source.revision != version


@pytest.mark.parametrize("remove_existing", [False, True])
def test_portal_failure_rolls_back_every_effect_and_can_retry(editor_pg, remove_existing):
    sessions = editor_pg
    version = current_revision(sessions)
    body = request_for(sessions, version, "QA changed", include_temp=True)
    if remove_existing:
        body["imagens"]["persistidas"] = []
        body["imagens"]["removidas_ids"] = [1]
    with patch.object(laudos, "_sincronizar_publicacao_laudo_no_portal", side_effect=RuntimeError("QA portal failure")):
        with sessions() as db, pytest.raises(RuntimeError, match="QA portal failure"):
            apply_echo_editor_update(db, db.get(User, 1), 1, EchoEditorUpdate(**body))
    with sessions() as db:
        assert load_echo_editor_source(db, 1).revision == version
        assert db.query(ImagemTemporaria).count() == 1
        assert db.query(ImagemLaudo).count() == 1
        assert db.query(LaudoEditorDraftRequest).filter_by(operation="apply").count() == 0
        draft = db.query(LaudoEditorDraft).one()
        assert draft.closed_at is None and draft.revision == 1
        assert json_snapshot(draft)["conteudo"]["conclusao"] == "QA changed"
    def render_portal(db, *, laudo, **_):
        # What the PDF renderer sees must already contain ALL selected edits.
        assert db.get(Paciente, 1).nome == laudo.diagnostico == "QA changed"
        selected = db.query(ImagemLaudo).filter_by(laudo_id=1, ativo=1).all()
        assert len(selected) == (1 if remove_existing else 2)
        assert all(image.descricao == "QA changed" for image in selected)
        return None, None, None, None

    with patch.object(laudos, "_sincronizar_publicacao_laudo_no_portal", side_effect=render_portal) as portal:
        with sessions() as db:
            confirmed = apply_echo_editor_update(db, db.get(User, 1), 1, EchoEditorUpdate(**body))
        with sessions() as db:
            assert apply_echo_editor_update(db, db.get(User, 1), 1, EchoEditorUpdate(**body)) == confirmed
        assert portal.call_count == 1
    with sessions() as db:
        assert db.query(ImagemTemporaria).count() == 0
        images = db.query(ImagemLaudo).order_by(ImagemLaudo.ordem).all()
        assert len(images) == 2
        assert [image.ativo for image in images] == ([0, 1] if remove_existing else [1, 1])
        assert [image.descricao for image in images] == (["Original", "QA changed"] if remove_existing else ["QA changed", "QA changed"])


def json_snapshot(draft):
    import json
    return json.loads(draft.snapshot_json)
