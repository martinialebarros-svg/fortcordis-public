"""Conversao administrativa atomica; usa as validacoes da agenda existente."""
import json
from datetime import datetime, timezone
from fastapi import HTTPException
from app.models.whatsapp_bot import WhatsAppBotSolicitacao as Pedido, WhatsAppBotResposta
from app.models.agendamento import Agendamento
from app.models.clinica import Clinica
from app.models.paciente import Paciente
from app.models.tutor import Tutor
from app.models.servico import Servico
from app.services.whatsapp_bot_agendamento import normalizar
from app.services.whatsapp_bot_fila import ABERTOS


def autorizado(user):
    if not any(user.tem_papel(p) for p in ('admin','recepcao','veterinario','cardiologista')):
        raise HTTPException(403, 'Sem permissão para agendar pedidos do WhatsApp.')


def obter(db, pedido_id, user, lock=False):
    autorizado(user)
    q=db.query(Pedido).filter_by(id=pedido_id)
    row=(q.with_for_update() if lock else q).first()
    if not row:
        raise HTTPException(404, 'Pedido não encontrado.')
    if row.responsavel_id != user.id:
        raise HTTPException(403, 'Assuma o pedido na central WhatsApp antes de agendar.')
    return row


def coleta_do_pedido(db, row):
    response=db.get(WhatsAppBotResposta,row.resposta_id)
    if (not response or response.clinica_id != row.clinica_id or response.wa_identity != row.wa_identity
            or str(response.conversation_id) != str(row.conversation_id)):
        return {}
    try:
        state=json.loads(response.tools_usadas or '{}').get('solicitacao_agendamento',{}) if response else {}
    except (ValueError,TypeError):
        state={}
    return state if isinstance(state,dict) and state.get('clinica_id') == row.clinica_id else {}


def dados_coletados(db, row):
    dados = coleta_do_pedido(db, row).get('dados', {})
    return dados if isinstance(dados, dict) else {}


def preferencia_do_pedido(coleta, historico):
    from app.services.whatsapp_bot_opcoes_agenda import interpretar_preferencia
    dados = coleta.get('dados', {})
    literal = dados.get('preferencia') if isinstance(dados, dict) else None
    if not literal:
        return None
    try:
        events = json.loads(historico or '[]')
        # Um complemento livre pode ter revogado a preferência original.
        if any(e.get('acao') == 'complemento_cliente' and not e.get('horario_preferido') for e in events):
            return None
        return interpretar_preferencia(literal, coleta.get('preferencia_recebida_em'))
    except (ValueError, TypeError, AttributeError):
        return None


def divergencias(db, row, pet, tutor):
    dados = dados_coletados(db, row)
    return {k: {"informado": dados[k], "selecionado": nome}
            for k, nome in (("paciente", pet.nome), ("tutor", tutor.nome))
            if dados.get(k) and normalizar(dados[k]) != normalizar(nome)}


def preparar(db, pedido_id, user):
    row=obter(db,pedido_id,user)
    if row.agendamento_id or row.status not in ABERTOS:
        raise HTTPException(409, 'Pedido já concluído. Consulte o registro na fila.')
    clinic=db.get(Clinica,row.clinica_id)
    if not clinic or not clinic.ativo:
        raise HTTPException(409, 'Clínica indisponível; revise o cadastro antes de agendar.')
    coleta=coleta_do_pedido(db, row)
    dados=coleta.get('dados', {})
    if not isinstance(dados, dict):
        dados={}
    preferencia=preferencia_do_pedido(coleta, row.historico)
    # Nomes nunca viram cadastro automaticamente. O par paciente/tutor precisa
    # ser unico, ativo e constar do contexto da clinica atualmente resolvida.
    from app.services.whatsapp_bot_generation import _resolver_contexto, _escopo_da_persona
    ctx=_resolver_contexto(db,row.wa_identity)
    _,_,clinic_id=_escopo_da_persona(ctx) if ctx.get('resolution')=='matched' else (None,None,None)
    pet=None;tutor=None
    if clinic_id==row.clinica_id and dados.get('paciente') and dados.get('tutor'):
        ids=[p['id'] for p in ctx.get('pets',[]) if p.get('id')]
        pairs=db.query(Paciente,Tutor).join(Tutor,Tutor.id==Paciente.tutor_id).filter(Paciente.id.in_(ids),Paciente.ativo==1,Tutor.ativo==1).all() if ids else []
        matches=[(p,t) for p,t in pairs if normalizar(p.nome)==normalizar(dados['paciente']) and normalizar(t.nome)==normalizar(dados['tutor'])]
        if len(matches)==1:
            pet,tutor=matches[0]
    services=[s for s in db.query(Servico).filter(Servico.ativo.is_(True)).all() if dados.get('exame') and normalizar(s.nome)==normalizar(dados['exame'])]
    service=services[0] if len(services)==1 else None
    return {'pedido_id':row.id,'versao':row.versao,'clinica_id':row.clinica_id,'resumo':row.resumo,
        'dados_coletados': {**{k: dados.get(k) for k in ('paciente', 'tutor')},
            'preferencia_horario': dados.get('preferencia'), 'preferencia_agenda': preferencia},
        'paciente':{'id':pet.id,'nome':pet.nome,'tutor_id':tutor.id,'tutor':tutor.nome} if pet else None,
        'tutor':{'id':tutor.id,'nome':tutor.nome} if tutor else None,
        'servico_id':service.id if service else None,
        'avisos':([] if pet else ['Selecione paciente e tutor: não houve identificação única e segura.']) + ([] if service else ['Selecione o exame no catálogo.'])
            + (['Revise a preferência de horário com a clínica antes de buscar opções.'] if dados.get('preferencia') and preferencia is None else [])}


def iniciar(db, request, user):
    """Depois do lock global da agenda, antes de qualquer escrita/validacao de slot."""
    if request.pedido_whatsapp_id is None:
        if request.pedido_whatsapp_versao is not None:
            raise HTTPException(422, 'Informe o pedido junto da versão.')
        return None,None
    if request.pedido_whatsapp_versao is None:
        raise HTTPException(422, 'Informe a versão do pedido.')
    row=obter(db,request.pedido_whatsapp_id,user,lock=True)
    if row.agendamento_id:
        previous=db.get(Agendamento,row.agendamento_id)
        from app.api.v1.endpoints.agenda import _coerce_datetime
        same=previous and all(getattr(previous,k)==getattr(request,k) for k in ('paciente_id','tutor_id','clinica_id','servico_id')) and _coerce_datetime(previous.inicio)==_coerce_datetime(request.inicio)
        if not same or previous.status not in ('Agendado','Confirmado'):
            raise HTTPException(409, 'Este pedido já tem agendamento. Consulte a agenda para alterações.')
        return row,previous
    if row.status not in ABERTOS or row.versao!=request.pedido_whatsapp_versao:
        raise HTTPException(409, 'Pedido alterado ou concluído. Reabra pela fila antes de agendar.')
    if request.clinica_id!=row.clinica_id or request.origem_atendimento!='clinica_parceira':
        raise HTTPException(422, 'O agendamento deve manter a clínica do pedido.')
    if request.status!='Agendado' or not all((request.paciente_id,request.tutor_id,request.servico_id)):
        raise HTTPException(422, 'Selecione paciente, tutor e exame para criar um agendamento confirmado pela equipe.')
    pet=db.get(Paciente,request.paciente_id);tutor=db.get(Tutor,request.tutor_id)
    clinic=db.get(Clinica,request.clinica_id);service=db.get(Servico,request.servico_id)
    if not pet or pet.ativo!=1 or not tutor or tutor.ativo!=1 or pet.tutor_id!=tutor.id or not clinic or not clinic.ativo or not service or not service.ativo:
        raise HTTPException(422, 'Cadastro inativo ou paciente/tutor incompatíveis. Revise os dados.')
    differences = divergencias(db, row, pet, tutor)
    if differences and not request.pedido_whatsapp_divergencia_confirmada:
        raise HTTPException(422, 'Pet ou tutor diferente do pedido do WhatsApp. Confira a divergência e confirme os cadastros selecionados antes de salvar.')
    return row,None


def vincular(db, pedido, agendamento, user):
    if not pedido:return
    db.flush() # id real, mesma transacao; uma falha reverte ambos
    now=datetime.now(timezone.utc)
    events=json.loads(pedido.historico)
    events.append({'acao':'agendamento_criado','em':now.isoformat(),'usuario_id':user.id,'usuario_nome':user.nome,
        'status':'agendado','agendamento_id':agendamento.id,'observacao':f'Vinculado ao agendamento #{agendamento.id}.'})
    differences = divergencias(db, pedido, db.get(Paciente, agendamento.paciente_id), db.get(Tutor, agendamento.tutor_id))
    if differences:
        events[-1]['divergencias_confirmadas'] = differences
    pedido.agendamento_id=agendamento.id;pedido.status='agendado';pedido.concluida_em=now
    pedido.updated_at=now;pedido.versao+=1;pedido.historico=json.dumps(events,ensure_ascii=False)
