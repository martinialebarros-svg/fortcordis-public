"""Executar apenas em PostgreSQL descartavel local via DOCUMENT_TEST_POSTGRES_URL."""
import os
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('DATABASE_URL', 'sqlite://')
os.environ.setdefault('SECRET_KEY', 'document-concurrency-test-secret-key-123456')
from app.models.atendimento_clinico import AtendimentoClinico, DocumentoAtendimento
from app.models.auditoria_evento import AuditoriaEvento
from app.schemas.atendimento import DocumentoAtendimentoUpdatePayload
from app.services.atendimento import document_crud_service as service


@pytest.mark.parametrize('operation', ['update', 'archive'])
def test_duas_sessoes_concorrentes_nao_sobrescrevem_nem_apagam(operation):
    url = os.environ.get('DOCUMENT_TEST_POSTGRES_URL')
    if not url:
        pytest.skip('PostgreSQL local descartavel nao configurado')
    parsed = make_url(url)
    assert parsed.host in {'127.0.0.1', 'localhost'} and parsed.database == 'document_test'
    schema = 'document_test_' + uuid.uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA {schema}'))
    engine = create_engine(url, connect_args={'options': f'-csearch_path={schema}'})
    tables = [AtendimentoClinico.__table__, DocumentoAtendimento.__table__, AuditoriaEvento.__table__]
    for table in tables:
        table.create(engine)
    sessions = sessionmaker(bind=engine, autoflush=False)
    user = SimpleNamespace(id=1, nome='Teste concorrencia', email='test@example.invalid')
    try:
        with sessions() as db:
            parent = AtendimentoClinico(paciente_id=1, veterinario_id=1, especie='Canina', status='Em atendimento')
            db.add(parent); db.flush()
            document = DocumentoAtendimento(atendimento_id=parent.id, titulo='Documento sintetico', corpo='Original', status='rascunho', updated_at=service.agora_documento())
            db.add(document); db.commit()
            aid, did = parent.id, document.id
            version = service.versao_documento(document)
        barrier = Barrier(2)
        def modify(index):
            with sessions() as db:
                # Precarrega o identity map em ambas as sessoes antes do lock.
                parent = db.get(AtendimentoClinico, aid)
                loaded_document = db.get(DocumentoAtendimento, did)
                assert service.versao_documento(loaded_document) == version
                barrier.wait(timeout=10)
                try:
                    if operation == 'archive' and index == 2:
                        result = service.excluir_documento_atendimento(db, aid, did, current_user=user, versao=version)
                    else:
                        result = service.atualizar_documento_atendimento(db, parent, aid, did,
                            DocumentoAtendimentoUpdatePayload(versao=version, corpo=f'Edicao {index}'), current_user=user)
                    return 200, result
                except HTTPException as error:
                    db.rollback()
                    return error.status_code, None
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(modify, [1, 2]))
        assert sorted(status for status, _ in results) == [200, 409]
        winner = next(result for status, result in results if status == 200)
        with sessions() as db:
            persisted = db.get(DocumentoAtendimento, did)
            assert persisted.atendimento_id == aid
            assert persisted.corpo == winner['corpo']
            assert persisted.status == winner['status']
            assert db.query(AuditoriaEvento).count() == 1
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA {schema} CASCADE'))
        admin.dispose()
