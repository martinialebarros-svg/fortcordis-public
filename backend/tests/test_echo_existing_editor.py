"""Real HTTP/SQLite proofs: recovery never edits the issued report; apply is atomic."""
import copy
from datetime import datetime, timedelta
import json
import unittest
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import event, select, text

from tests import test_laudo_editor_drafts as _draft_tests
from app.api.v1.endpoints import laudos
from app.db.database import Base
from app.models.imagem_laudo import ImagemLaudo, ImagemTemporaria
from app.models.laudo import Laudo
from app.models.laudo_editor_draft import LaudoEditorDraftRequest
from app.models.paciente import Paciente
from app.models.papel_permissao import PapelPermissao
from app.models.tutor import Tutor


class ExistingEchoEditorHTTPTest(unittest.TestCase):
    def setUp(self):
        self.harness = _draft_tests.EditorDraftHTTPTest()
        self.harness.setUp()
        self.__dict__.update({key: value for key, value in self.harness.__dict__.items() if not key.startswith('_')})
        self.app.include_router(laudos.router, prefix='/api/v1')
        with self.sessions() as db:
            db.get(Paciente, 901).observacoes = 'Idade: 12a\nNota clínica preservada.'
            db.add_all([PapelPermissao(papel_id=1, modulo=module, visualizar=1, editar=1, excluir=0)
                        for module in ('pacientes', 'tutores')])
            db.add_all([
                ImagemLaudo(id=71, laudo_id=901, nome_arquivo='one.png', conteudo=b'one', tamanho_bytes=3,
                            ordem=0, descricao='original', incluir_no_pdf=True, ativo=1),
                ImagemLaudo(id=72, laudo_id=901, nome_arquivo='two.png', conteudo=b'two', tamanho_bytes=3,
                            ordem=1, descricao='remove explicitly', incluir_no_pdf=True, ativo=1),
            ])
            db.commit()
        self.portal = patch.object(laudos, '_sincronizar_publicacao_laudo_no_portal', return_value=(None, None, None, None))
        self.portal_mock = self.portal.start()

    def tearDown(self):
        self.portal.stop()
        self.harness.tearDown()

    def headers(self, token='editor'):
        return _draft_tests.EditorDraftHTTPTest.headers(token)

    def official(self):
        response = self.client.get('/api/v1/laudos/901', headers=self.headers())
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def saved_draft(self, revision=None):
        source_revision = revision or self.official()['editor_revision']
        snapshot = {'schema_version':1, 'editor':'existing-echo',
                    'source': {'laudo_id':901, 'editor_revision':source_revision},
                    'paciente': {'nome':'Literal de rascunho'},
                    'medidas': {'E':'0', 'A':'', 'E_A':None}, 'sessionId':'echo-edit-temps', 'imagens':[]}
        body = {'expected_revision':0, 'request_id':str(uuid4()), 'context_key':'edit:laudo:901', 'snapshot':snapshot}
        saved = self.client.put(self.url, json=body, headers=self.headers())
        self.assertEqual(saved.status_code, 200, saved.text)
        return saved.json(), body

    def update_body(self, draft=None):
        if draft is None:
            draft, _ = self.saved_draft()
        return {'expected_editor_revision':draft['snapshot']['source']['editor_revision'],
                'request_id':str(uuid4()), 'editor_draft_id':draft['draft_id'],
                'expected_draft_revision':draft['revision'],
                'payload_laudo': {'descricao':'## Medidas Ecocardiograficas\n- E_A: \n- Onda_E: 0\n',
                                  'diagnostico':'Revisão literal autorizada.', 'status':'Finalizado'},
                'imagens': {'persistidas':[{'id':71,'ordem':0,'incluir_no_pdf':False,'descricao':'legenda literal  '}],
                            'removidas_ids':[72], 'temp_config':[]}}

    def apply(self, body, headers=None):
        return self.client.put('/api/v1/laudos/901/editor-update', json=body,
                               headers=self.headers() if headers is None else headers)

    def save_image_descriptors(self, body, descriptors):
        current=self.client.get(self.url,headers=self.headers()).json()
        current['snapshot']['imagens']=descriptors
        response=self.client.put(self.url,headers=self.headers(),json={
            'expected_revision':current['revision'],'request_id':str(uuid4()),
            'context_key':current['context_key'],'snapshot':current['snapshot']})
        self.assertEqual(response.status_code,200,response.text)
        body['expected_draft_revision']=response.json()['revision']

    def database_state(self):
        with self.engine.connect() as connection:
            return {table.name:[tuple(row) for row in connection.execute(select(table))]
                    for table in Base.metadata.sorted_tables}

    def test_revision_tracks_content_not_only_timestamp_and_same_get_payload(self):
        original = self.official()
        self.assertRegex(original['editor_revision'], '^echo-v1:[a-f0-9]{64}$')
        self.assertEqual(original['paciente']['tutor_id'],901)
        self.assertEqual(self.official()['editor_revision'], original['editor_revision'])
        changes = [('laudos', 'descricao', 'Descrição concorrente'), ('pacientes','nome','Nome concorrente'),
                   ('tutores','telefone','000'), ('imagens_laudo','descricao','Legenda concorrente'),
                   ('imagens_laudo','ativo',0)]
        previous = original['editor_revision']
        for table, field, value in changes:
            with self.subTest(table=table, field=field):
                with self.engine.begin() as connection:
                    connection.execute(text(f'UPDATE {table} SET {field}=:value WHERE id=:id'),
                                       {'value':value, 'id':71 if table=='imagens_laudo' else 901})
                current = self.official()
                self.assertNotEqual(current['editor_revision'], previous)
                self.assertEqual(current['updated_at'], original['updated_at'])
                previous = current['editor_revision']
        self.assertEqual(self.official()['descricao'],'Descrição concorrente')

    def test_private_stale_recovery_is_literal_and_source_binding_is_immutable(self):
        saved, body = self.saved_draft()
        with self.sessions() as db:
            db.get(Laudo,901).diagnostico='Outra revisão oficial'
            db.commit()
        clinical = {key:value for key,value in self.database_state().items() if not key.startswith('laudo_editor_draft')}
        body['expected_revision']=1
        body['request_id']=str(uuid4())
        body['snapshot']['medidas']['nova']='  0,00  '
        response=self.client.put(self.url,json=body,headers=self.headers())
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['snapshot'],body['snapshot'])
        recovered=self.client.get(self.url,headers=self.headers()).json()
        self.assertEqual(recovered['snapshot'],body['snapshot'])
        self.assertEqual({key:value for key,value in self.database_state().items() if not key.startswith('laudo_editor_draft')},clinical)
        changed=copy.deepcopy(body)
        changed['request_id']=str(uuid4())
        changed['expected_revision']=2
        changed['snapshot']['source']['editor_revision']=self.official()['editor_revision']
        self.assertEqual(self.client.put(self.url,json=changed,headers=self.headers()).status_code,409)

    def test_workspace_checks_do_not_load_demographics_or_images_on_every_autosave(self):
        _, body=self.saved_draft()
        statements=[]
        def record(_connection,_cursor,statement,_parameters,_context,_executemany):
            statements.append(statement.lower())
        event.listen(self.engine,'before_cursor_execute',record)
        try:
            self.assertEqual(self.client.get(self.url,headers=self.headers()).status_code,200)
            body['expected_revision']=1
            body['request_id']=str(uuid4())
            self.assertEqual(self.client.put(self.url,json=body,headers=self.headers()).status_code,200)
        finally:
            event.remove(self.engine,'before_cursor_execute',record)
        for table in ('pacientes','tutores','imagens_laudo'):
            self.assertFalse(any(f'from {table}' in statement for statement in statements),table)

    def test_atomic_apply_images_demographics_then_portal_and_idempotent_closed_recovery(self):
        body=self.update_body()
        body['paciente']={'nome':'Nome revisado','idade':'13a'}
        body['tutor']={'id':901,'telefone':'123'}
        with self.sessions() as db:
            db.add(ImagemTemporaria(id=80,session_id='echo-edit-temps',nome_arquivo='temp.png',conteudo=b'png',
                                     tamanho_bytes=3,expira_em=datetime.utcnow()+timedelta(hours=1)))
            db.commit()
        body['imagens'].update(temp_session_id='echo-edit-temps',temp_config=[{'id':80,'ordem':1,'incluir_no_pdf':True,'descricao':'nova imagem'}])
        self.save_image_descriptors(body,[{'tempId':80,'uploaded':True}])
        def assert_portal_inputs(db,**kwargs):
            self.assertEqual(db.get(Paciente,901).nome,'Nome revisado')
            self.assertEqual(db.get(Tutor,901).telefone,'123')
            self.assertFalse(db.get(ImagemLaudo,71).incluir_no_pdf)
            self.assertEqual(db.get(ImagemLaudo,72).ativo,0)
            self.assertIsNone(db.get(ImagemTemporaria,80))
            self.assertEqual(db.query(ImagemLaudo).filter(ImagemLaudo.laudo_id==901,ImagemLaudo.ativo==1).count(),2)
            return None,None,None,None
        self.portal_mock.side_effect=assert_portal_inputs
        response=self.apply(body)
        self.assertEqual(response.status_code,200,response.text)
        expected={'id':901,'request_id':body['request_id'],'updated':True}
        self.assertEqual(response.json(),expected)
        committed=self.database_state()
        replay=self.apply(body)
        self.assertEqual(replay.status_code,200,replay.text)
        self.assertEqual(replay.json(),expected)
        self.assertEqual(self.database_state(),committed)
        self.assertEqual(self.portal_mock.call_count,1)
        closed=self.client.get(self.url,headers=self.headers())
        self.assertEqual(closed.status_code,410)
        self.assertEqual(closed.json()['detail'],{'code':'EDITOR_DRAFT_CLOSED','laudo_id':901,'apply_result':expected})
        with self.sessions() as db:
            self.assertEqual(db.get(Paciente,901).observacoes,'Idade: 13a\nNota clínica preservada.')
            self.assertEqual(db.get(ImagemLaudo,71).descricao,'legenda literal  ')
        body['payload_laudo']['diagnostico']='Request ID reused differently'
        self.assertEqual(self.apply(body).status_code,409)
        self.assertEqual(self.database_state(),committed)

    def test_stale_source_and_bad_image_claims_have_no_effects(self):
        for scenario in ('source','images','tutor','report'):
            with self.subTest(scenario=scenario):
                body=self.update_body()
                if scenario=='source':
                    with self.sessions() as db:
                        db.get(Tutor,901).telefone=str(uuid4())
                        db.commit()
                elif scenario=='images': body['imagens']['persistidas'][0]['id']=999
                elif scenario=='tutor': body['tutor']={'id':999,'telefone':'111'}
                else: body['payload_laudo']['paciente_id']=999
                before=self.database_state()
                result=self.apply(body)
                self.assertIn(result.status_code,(409,422),result.text)
                if scenario!='report':
                    self.assertEqual(result.json()['detail']['code'],
                                     {'source':'SOURCE_CHANGED','images':'IMAGES_CHANGED','tutor':'BINDING_CHANGED'}[scenario])
                self.assertEqual(self.database_state(),before)
                self.portal_mock.assert_not_called()
                self.draft_id=str(uuid4());self.url=f'/api/v1/laudos/editor-drafts/{self.draft_id}'

    def test_portal_failure_rolls_back_report_demographics_images_and_workspace(self):
        body=self.update_body()
        body['paciente']={'nome':'Não pode persistir'}
        body['tutor']={'telefone':'não persistir'}
        before=self.database_state()
        self.portal_mock.side_effect=RuntimeError('synthetic rendering failure')
        with self.assertRaisesRegex(RuntimeError,'synthetic rendering failure'):
            self.apply(body)
        self.assertEqual(self.database_state(),before)
        self.assertEqual(self.client.get(self.url,headers=self.headers()).status_code,200)

    def test_demographic_permissions_are_preserved_and_unchanged_headers_do_not_need_extra_rights(self):
        with self.sessions() as db:
            db.query(PapelPermissao).filter(PapelPermissao.modulo.in_(['pacientes','tutores'])).update({'editar':0},synchronize_session=False)
            db.commit()
        body=self.update_body()
        body['paciente']={'nome':'Não autorizado'}
        before=self.database_state()
        self.assertEqual(self.apply(body).status_code,403)
        self.assertEqual(self.database_state(),before)
        body['paciente']={'nome':'TESTE PACIENTE PRESERVADO'}
        body['tutor']={'id':901,'nome':'TESTE TUTOR PRESERVADO'}
        self.assertEqual(self.apply(body).status_code,200)

    def test_owner_change_and_missing_preconditions_do_not_write(self):
        body=self.update_body()
        before=self.database_state()
        wrong=self.headers('other');wrong['X-Editor-Owner-Id']='1'
        self.assertEqual(self.apply(body,wrong).status_code,403)
        missing=copy.deepcopy(body);missing.pop('expected_editor_revision')
        self.assertEqual(self.apply(missing).status_code,422)
        self.assertEqual(self.apply(body,self.headers('reader')).status_code,403)
        self.assertEqual(self.database_state(),before)

    def test_apply_receipt_distinguishes_omitted_demographic_fields_from_explicit_null(self):
        body=self.update_body()
        body['paciente']={}
        self.assertEqual(self.apply(body).status_code,200)
        before=self.database_state()
        different=copy.deepcopy(body)
        different['paciente']['nome']=None
        response=self.apply(different)
        self.assertEqual(response.status_code,409)
        self.assertEqual(response.json()['detail']['code'],'OPERATION_CONFLICT')
        self.assertEqual(self.database_state(),before)

    def test_new_tutor_requires_explicit_unlinked_creation_and_never_reuses_a_homonym(self):
        with self.sessions() as db:
            db.get(Paciente,901).tutor_id=None
            db.add(Tutor(id=902,nome='Homônimo',ativo=1))
            db.commit()
        body=self.update_body()
        body['tutor']={'nome':'Homônimo','telefone':'123'}
        before=self.database_state()
        self.assertEqual(self.apply(body).status_code,422)
        self.assertEqual(self.database_state(),before)
        body['tutor']['criar_novo']=True
        self.assertEqual(self.apply(body).status_code,200)
        with self.sessions() as db:
            patient=db.get(Paciente,901)
            self.assertNotEqual(patient.tutor_id,902)
            self.assertEqual(db.get(Tutor,patient.tutor_id).nome,'Homônimo')
            self.assertEqual(db.query(Tutor).filter(Tutor.nome=='Homônimo').count(),2)

    def test_expired_temp_and_broken_source_binding_are_rejected_without_mutation(self):
        body=self.update_body()
        with self.sessions() as db:
            db.add(ImagemTemporaria(id=80,session_id='echo-edit-temps',nome_arquivo='expired.png',conteudo=b'png',
                                     tamanho_bytes=3,expira_em=datetime.utcnow()-timedelta(hours=1)))
            db.commit()
        body['imagens'].update(temp_session_id='echo-edit-temps',temp_config=[{'id':80,'ordem':2}])
        self.save_image_descriptors(body,[{'tempId':80,'uploaded':True}])
        before=self.database_state()
        expired=self.apply(body)
        self.assertEqual(expired.status_code,409)
        self.assertEqual(expired.json()['detail']['code'],'TEMP_IMAGES_UNAVAILABLE')
        self.assertEqual(self.database_state(),before)

    def test_temp_session_and_ids_are_bound_to_exact_saved_workspace(self):
        body=self.update_body()
        with self.sessions() as db:
            for image_id,session_id in ((80,'echo-edit-temps'),(81,'foreign-session')):
                db.add(ImagemTemporaria(id=image_id,session_id=session_id,nome_arquivo='temp.png',conteudo=b'png',
                                       tamanho_bytes=3,expira_em=datetime.utcnow()+timedelta(hours=1)))
            db.commit()
        self.save_image_descriptors(body,[{'tempId':80,'uploaded':True}])
        body['imagens'].update(temp_session_id='echo-edit-temps',temp_config=[{'id':80,'ordem':2}])
        before=self.database_state()
        for change in ('session','ids'):
            invalid=copy.deepcopy(body)
            if change=='session': invalid['imagens']['temp_session_id']='foreign-session'
            else: invalid['imagens']['temp_config'][0]['id']=81
            response=self.apply(invalid)
            self.assertEqual(response.status_code,409,response.text)
            self.assertEqual(response.json()['detail']['code'],'TEMP_IMAGES_UNAVAILABLE')
            self.assertEqual(self.database_state(),before)
        saved=self.client.get(self.url,headers=self.headers()).json()
        saved['snapshot']['sessionId']='foreign-session'
        changed=self.client.put(self.url,headers=self.headers(),json={
            'expected_revision':saved['revision'],'request_id':str(uuid4()),
            'context_key':saved['context_key'],'snapshot':saved['snapshot']})
        self.assertEqual(changed.status_code,409)
        self.assertEqual(self.database_state(),before)
        with self.sessions() as db:
            db.get(Laudo,901).tipo='pressao_arterial'
            db.commit()
        before=self.database_state()
        self.assertEqual(self.client.get(self.url,headers=self.headers()).status_code,422)
        self.assertEqual(self.client.post(self.url+'/close',headers=self.headers(),
                         json={'expected_revision':1,'request_id':str(uuid4())}).status_code,422)
        self.assertEqual(self.database_state(),before)


if __name__=='__main__':
    unittest.main()
