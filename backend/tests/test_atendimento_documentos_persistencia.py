"""HTTP, sessoes independentes e banco descartavel; nenhum dado de producao."""
import os
import sys
from pathlib import Path
from types import SimpleNamespace
import json

os.environ.setdefault('DATABASE_URL', 'sqlite://')
os.environ.setdefault('SECRET_KEY', 'controlled-document-persistence-secret-12345678')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.api.v1.endpoints import atendimento as api
from app.db.database import Base, get_db
from app.models.atendimento_clinico import AtendimentoClinico, DocumentoAtendimento
from app.models.auditoria_evento import AuditoriaEvento
from app.models.paciente import Paciente
from app.models.tutor import Tutor
from app.services.atendimento import document_crud_service as service


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    engine = create_engine(f'sqlite:///{tmp_path / "test.db"}', connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False)
    user = SimpleNamespace(id=1, nome='Veterinario de teste', email='test@example.invalid')
    with sessions() as db:
        tutor = Tutor(nome='Tutora sintetica', ativo=1)
        db.add(tutor); db.flush()
        patient = Paciente(nome='Paciente sintetica', especie='Canina', tutor_id=tutor.id, ativo=1)
        db.add(patient); db.flush()
        db.add(AtendimentoClinico(id=69, paciente_id=patient.id, tutor_id=tutor.id,
                                 veterinario_id=1, status='Em atendimento', especie='Canina'))
        db.commit()
    def get_test_db():
        with sessions() as db:
            yield db
    app = FastAPI()
    app.include_router(api.router, prefix='/atendimentos')
    app.dependency_overrides[get_db] = get_test_db
    app.dependency_overrides[api.get_current_user] = lambda: user
    monkeypatch.setattr(api, '_autenticar_usuario_pdf', lambda request, db: user)
    monkeypatch.setattr(api, '_obter_branding_pdf_documento', lambda db, user: {
        'nome_veterinario': user.nome, 'crmv': 'TESTE', 'logomarca_bytes': None,
        'assinatura_bytes': None, 'texto_rodape': 'DOCUMENTO SINTETICO - SEM VALIDADE CLINICA',
    })
    with TestClient(app) as client:
        yield client, sessions, tmp_path
    engine.dispose()


def create(client):
    r = client.post('/atendimentos/69/documentos', json={
        'titulo': 'Parecer sintetico para teste',
        'corpo': 'DOCUMENTO DE TESTE. Sem validade clinica.\n\nTexto preservado entre sessoes e apos salvar atendimento.',
    })
    assert r.status_code == 201, r.text
    return r.json()


def test_salvar_atendimento_nao_apaga_documento_e_pdf_baixado_aberto(scenario):
    client, sessions, tmp_path = scenario
    doc = create(client)
    # Estado antigo que ainda nao continha documentos; o PUT nao sincroniza essa colecao.
    r = client.put('/atendimentos/69', json={'observacoes': 'Save posterior', 'documentos': []})
    assert r.status_code == 200, r.text
    assert [d['id'] for d in r.json()['documentos']] == [doc['id']]
    assert client.get('/atendimentos/69/documentos').json()['documentos'][0]['corpo'] == doc['corpo']
    r = client.get(f"/atendimentos/69/documentos/{doc['id']}/pdf", params={'versao': doc['versao']})
    assert r.status_code == 200, r.text
    assert r.headers['content-type'] == 'application/pdf'
    assert 'attachment' in r.headers['content-disposition']
    assert r.content.startswith(b'%PDF-')
    pdf = tmp_path / 'documento-baixado.pdf'
    pdf.write_bytes(r.content)
    from pypdf import PdfReader
    reader = PdfReader(str(pdf))
    text = '\n'.join(page.extract_text() for page in reader.pages)
    assert 'Paciente sintetica' in text
    assert 'Tutora sintetica' in text
    assert 'Texto preservado entre sessoes' in text
    # Conexao nova comprova persistencia; PDF emitido tem fuso explicito.
    with sessions() as db:
        persisted = db.get(DocumentoAtendimento, doc['id'])
        assert persisted.status == 'emitido'
        assert persisted.corpo == doc['corpo']
        events = db.query(AuditoriaEvento).filter_by(entidade='documento_atendimento').all()
        assert [e.acao for e in events] == ['DOCUMENTO_ATENDIMENTO_CRIADO', 'DOCUMENTO_ATENDIMENTO_PDF_GERADO']
        assert json.loads(events[-1].detalhes_json)['pdf_bytes'] == len(r.content)
    fresh = client.get('/atendimentos/69/documentos').json()['documentos'][0]
    assert fresh['emitido_at'].endswith('+00:00')
    output = os.environ.get('DOCUMENT_PDF_TEST_OUTPUT')
    if output:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_bytes(r.content)


def test_edicao_antiga_rejeitada_e_arquivo_restauravel(scenario):
    client, sessions, _ = scenario
    original = create(client)
    path = f"/atendimentos/69/documentos/{original['id']}"
    revised = client.put(path, json={'versao': original['versao'], 'corpo': 'Revisao nova preservada.'})
    assert revised.status_code == 200
    assert client.put(path, json={'versao': original['versao'], 'corpo': 'Texto antigo'}).status_code == 409
    assert client.delete(path, params={'versao': original['versao']}).status_code == 409
    assert client.get(path + '/pdf', params={'versao': original['versao']}).status_code == 409
    assert client.delete(path).status_code == 428
    assert client.put(path, json={'corpo': 'Cliente antigo'}).status_code == 428
    archived = client.delete(path, params={'versao': revised.json()['versao']})
    assert archived.status_code == 200
    assert archived.json()['status'] == 'arquivado'
    assert client.get('/atendimentos/69/documentos').json()['documentos'][0]['id'] == original['id']
    assert client.put(path, json={'versao': revised.json()['versao'], 'corpo': 'Aba antiga'}).status_code == 409
    assert client.get(path + '/pdf', params={'versao': archived.json()['versao']}).status_code == 409
    # O DELETE do pai nao pode contornar a retencao.
    assert client.delete('/atendimentos/69', params={'confirmar_exclusao': True}).status_code == 409
    restored = client.post(path + '/restaurar', json={'versao': archived.json()['versao']})
    assert restored.status_code == 200
    assert restored.json()['corpo'] == 'Revisao nova preservada.'
    with sessions() as db:
        assert db.get(DocumentoAtendimento, original['id']).atendimento_id == 69
        actions = [e.acao for e in db.query(AuditoriaEvento).all()]
        assert 'DOCUMENTO_ATENDIMENTO_ARQUIVADO' in actions
        assert 'DOCUMENTO_ATENDIMENTO_RESTAURADO' in actions


def test_arquivar_emitido_preserva_emissao_e_restauracao(scenario):
    client, _, _ = scenario
    doc = create(client)
    path = f"/atendimentos/69/documentos/{doc['id']}"
    assert client.get(path + '/pdf', params={'versao': doc['versao']}).status_code == 200
    issued = client.get('/atendimentos/69/documentos').json()['documentos'][0]
    archived = client.delete(path, params={'versao': issued['versao']}).json()
    restored = client.post(path + '/restaurar', json={'versao': archived['versao']}).json()
    assert restored['status'] == 'emitido'
    assert restored['emitido_at'] == issued['emitido_at']
    assert restored['corpo'] == doc['corpo']


def test_auditoria_falha_reverte_criacao(scenario):
    client, sessions, _ = scenario
    engine = sessions.kw['bind']
    def fail_audit(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith('INSERT INTO auditoria_eventos'):
            raise RuntimeError('falha controlada de auditoria')
    event.listen(engine, 'before_cursor_execute', fail_audit)
    try:
        with pytest.raises(RuntimeError, match='falha controlada'):
            create(client)
    finally:
        event.remove(engine, 'before_cursor_execute', fail_audit)
    with sessions() as db:
        assert db.query(DocumentoAtendimento).count() == 0


def test_rota_com_atendimento_errado_nao_altera_documento(scenario):
    client, _, _ = scenario
    doc = create(client)
    assert client.delete(f"/atendimentos/999/documentos/{doc['id']}", params={'versao': doc['versao']}).status_code == 404
    assert client.get('/atendimentos/69/documentos').json()['documentos'][0]['corpo'] == doc['corpo']
