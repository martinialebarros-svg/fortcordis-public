"""Sessoes HTTP independentes comprovam edicao apos alta e historico atomico."""
import json
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event

from tests.test_atendimento_documentos_persistencia import scenario
from app.api.v1.endpoints import atendimento as api
from app.models.agendamento import Agendamento
from app.models.atendimento_clinico import AtendimentoClinico, DocumentoAtendimento, PrescricaoClinica, PrescricaoItem
from app.models.auditoria_evento import AuditoriaEvento
from app.models.clinica import Clinica
from app.models.ordem_servico import OrdemServico


@pytest.fixture
def concluido(scenario):
    client, sessions, tmp_path = scenario
    with sessions() as db:
        item = db.get(AtendimentoClinico, 69)
        item.status = 'Concluido'
        item.consulta_concluida = 1
        item.observacoes = 'Texto original'
        item.data_atendimento = datetime(2026, 9, 11, 13)
        clinica = Clinica(nome="Clinica sintetica")
        db.add(clinica); db.flush()
        item.clinica_id = clinica.id
        agenda = Agendamento(clinica_id=clinica.id, inicio=item.data_atendimento, paciente_id=item.paciente_id,
                             tutor_id=item.tutor_id, status='Realizado')
        db.add(agenda); db.flush()
        item.agendamento_id = agenda.id
        db.add(OrdemServico(numero_os='TESTE-69', agendamento_id=agenda.id, paciente_id=item.paciente_id,
                            servico_id=1, valor_final=150, status='Pago'))
        receita = PrescricaoClinica(atendimento_id=69, sequencia=1,
                                   orientacoes_gerais='Orientacao original', emitida_em=datetime(2026, 9, 11, 14))
        db.add(receita); db.flush()
        db.add(PrescricaoItem(prescricao_id=receita.id, medicamento_nome='Medicamento sintetico',
                             dose='1 unidade', frequencia='12/12h', ordem=0))
        db.add(DocumentoAtendimento(atendimento_id=69, titulo='Documento sintetico', corpo='Corpo original',
                                   status='emitido', emitido_at=datetime(2026, 9, 11, 17)))
        db.commit()
    return client, sessions, tmp_path


def historico(client, **params):
    resposta = client.get('/atendimentos/69/historico-edicoes', params=params)
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


def test_editar_concluido_preserva_encerramento_agenda_os_e_historico_recarregado(concluido):
    client, sessions, _ = concluido
    response = client.put('/atendimentos/69', json={'observacoes': 'Correcao atual', 'consulta_concluida': 0})
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'Concluido'
    with sessions() as db:
        item = db.get(AtendimentoClinico, 69)
        assert item.observacoes == 'Correcao atual'
        assert item.consulta_concluida == 1
        assert item.data_atendimento == datetime(2026, 9, 11, 13)
        assert db.get(Agendamento, item.agendamento_id).status == 'Realizado'
        os = db.query(OrdemServico).one()
        assert os.status == 'Pago' and float(os.valor_final) == 150
    history = historico(client)
    assert history['total'] == 1
    change = history['items'][0]
    assert change['usuario_nome'] == 'Veterinario de teste'
    assert change['usuario_id'] == 1
    assert change['created_at'].endswith('+00:00')
    assert change['alteracoes'] == {'observacoes': {'antes': 'Texto original', 'depois': 'Correcao atual'}}
    assert 'ip_origem' not in change and 'usuario_email' not in change
    # Autosave identico nao duplica historico.
    assert client.put('/atendimentos/69', json={'observacoes': 'Correcao atual'}).status_code == 200
    assert historico(client)['total'] == 1


@pytest.mark.parametrize('payload', [{'status': 'Triagem'}, {'paciente_id': 999}, {'agendamento_id': None}])
def test_edicao_nao_reabre_nem_transfere_identidade(concluido, payload):
    client, sessions, _ = concluido
    assert client.put('/atendimentos/69', json=payload).status_code in (404, 409)
    with sessions() as db:
        item = db.get(AtendimentoClinico, 69)
        assert item.status == 'Concluido' and item.paciente_id != 999 and item.agendamento_id
        assert db.query(OrdemServico).count() == 1
    assert historico(client)['total'] == 0


def test_receita_emitida_editavel_sem_confirmacao_e_historico_duravel(concluido):
    client, sessions, _ = concluido
    receita = client.get('/atendimentos/69').json()['prescricao']
    item = receita['itens'][0]
    item['frequencia'] = '8/8h'
    item['unidade_dose_calculo'] = None
    payload = {'orientacoes_gerais': 'Orientacao corrigida', 'itens': [item]}
    path = f"/atendimentos/69/prescricoes/{receita['id']}"
    response = client.put(path, json=payload)
    assert response.status_code == 200, response.text
    assert response.json()['prescricao']['emitida_em'] == receita['emitida_em']
    change = historico(client)['items'][0]
    assert change['acao'] == 'EDITAR_RECEITA_EMITIDA'
    assert change['alteracoes']['itens']['antes'][0]['frequencia'] == '12/12h'
    assert change['alteracoes']['itens']['depois'][0]['frequencia'] == '8/8h'
    assert client.put(path, json=payload).status_code == 200
    assert historico(client)['total'] == 1


def test_documento_emitido_editavel_filtrado_e_pdf_regenerado(concluido):
    client, sessions, _ = concluido
    doc = client.get('/atendimentos/69/documentos').json()['documentos'][0]
    path = f"/atendimentos/69/documentos/{doc['id']}"
    response = client.put(path, json={'versao': doc['versao'], 'corpo': 'Texto revisado depois da alta.'})
    assert response.status_code == 200, response.text
    revised = response.json()
    assert revised['status'] == 'emitido' and revised['emitido_at'] == doc['emitido_at']
    assert client.put(path, json={'versao': doc['versao'], 'corpo': 'Aba antiga'}).status_code == 409
    history = historico(client, documento_id=doc['id'])
    assert history['total'] == 1
    assert history['items'][0]['alteracoes']['corpo'] == {'antes': 'Corpo original', 'depois': 'Texto revisado depois da alta.'}
    pdf = client.get(path + '/pdf', params={'versao': revised['versao']})
    assert pdf.status_code == 200 and pdf.content.startswith(b'%PDF-')
    from io import BytesIO
    from pypdf import PdfReader
    assert 'Texto revisado depois da alta.' in '\n'.join(p.extract_text() for p in PdfReader(BytesIO(pdf.content)).pages)


@pytest.mark.parametrize('alvo', ['atendimento', 'documento', 'receita'])
def test_falha_auditoria_reverte_alteracao_inteira(concluido, alvo):
    client, sessions, _ = concluido
    before = client.get('/atendimentos/69').json()
    doc = before['documentos'][0]
    receita = before['prescricao']
    for item in receita['itens']:
        item['unidade_dose_calculo'] = None
    path, payload = {
        'atendimento': ('/atendimentos/69', {'observacoes': 'Nao pode persistir',
                        'prescricao': {'orientacoes_gerais': 'Tambem reverter', 'itens': receita['itens']}}),
        'documento': (f"/atendimentos/69/documentos/{doc['id']}", {'versao': doc['versao'], 'corpo': 'Nao pode persistir'}),
        'receita': (f"/atendimentos/69/prescricoes/{receita['id']}", {'orientacoes_gerais': 'Nao pode persistir', 'itens': receita['itens']}),
    }[alvo]
    engine = sessions.kw['bind']
    def fail(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith('INSERT INTO auditoria_eventos'):
            raise RuntimeError('falha controlada de auditoria')
    event.listen(engine, 'before_cursor_execute', fail)
    try:
        with pytest.raises(RuntimeError, match='falha controlada'):
            client.put(path, json=payload)
    finally:
        event.remove(engine, 'before_cursor_execute', fail)
    with sessions() as db:
        assert db.get(AtendimentoClinico, 69).observacoes == 'Texto original'
        assert db.get(DocumentoAtendimento, doc['id']).corpo == 'Corpo original'
        assert db.get(PrescricaoClinica, receita['id']).orientacoes_gerais == 'Orientacao original'
        assert db.query(AuditoriaEvento).count() == 0


def test_historico_nao_expoe_outro_atendimento_paginacao_e_filtro(concluido):
    client, sessions, _ = concluido
    for value in ['Primeira', 'Segunda']:
        assert client.put('/atendimentos/69', json={'observacoes': value}).status_code == 200
    with sessions() as db:
        db.add(AtendimentoClinico(id=70, paciente_id=999, veterinario_id=1, status='Concluido'))
        db.add(DocumentoAtendimento(id=900, atendimento_id=70, titulo='Alheio', corpo='Privado'))
        db.add(AuditoriaEvento(modulo='atendimento', entidade='documento_atendimento', entidade_id='900',
                              acao='DOCUMENTO_ATENDIMENTO_ATUALIZADO', detalhes_json=json.dumps({'alteracoes': {'corpo': {'antes': 'Privado', 'depois': 'Sigiloso'}}})))
        db.commit()
    first = historico(client, limit=1)
    second = historico(client, limit=1, skip=1)
    assert first['total'] == second['total'] == 2
    assert len(first['items']) == len(second['items']) == 1
    assert first['items'][0]['id'] > second['items'][0]['id']
    assert client.get('/atendimentos/69/historico-edicoes', params={'documento_id': 900}).status_code == 404
    assert client.get('/atendimentos/999/historico-edicoes').status_code == 404
    assert client.get('/atendimentos/69/historico-edicoes', params={'limit': 101}).status_code == 422


def test_historico_exige_autenticacao():
    app = FastAPI()
    app.include_router(api.router, prefix='/api/v1/atendimentos')
    with TestClient(app) as client:
        response = client.get('/api/v1/atendimentos/69/historico-edicoes')
        assert response.status_code == 401


def test_historico_respeita_matriz_de_leitura_do_atendimento(concluido, monkeypatch):
    from types import SimpleNamespace
    from app.core import security
    from app.db.database import get_db
    _, sessions, _ = concluido
    user = SimpleNamespace(id=1, ativo=1, tem_papel=lambda role: False)
    monkeypatch.setattr(security, '_decode_token_and_load_user', lambda db, token: user)
    def denied(db, usuario, modulo, acao):
        assert modulo == 'atendimento_clinico' and acao == 'visualizar'
        return False
    monkeypatch.setattr(security, '_user_has_matrix_permission', denied)
    def test_db():
        with sessions() as db:
            yield db
    app = FastAPI()
    app.include_router(api.router, prefix='/api/v1/atendimentos')
    app.dependency_overrides[get_db] = test_db
    with TestClient(app) as client:
        assert client.get('/api/v1/atendimentos/69/historico-edicoes', headers={'Authorization': 'Bearer test'}).status_code == 403


def test_mesma_data_em_fuso_explicito_nao_inventa_edicao(concluido):
    client, _, _ = concluido
    response = client.put('/atendimentos/69', json={'data_atendimento': '2026-09-11T13:00:00-03:00'})
    assert response.status_code == 200, response.text
    assert historico(client)['total'] == 0
