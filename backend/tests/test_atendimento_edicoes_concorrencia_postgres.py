"""Prova do historico encadeado em PostgreSQL local descartavel."""
import json
import os
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "atendimento-history-concurrency-test-secret-key-123456")

from app.api.v1.endpoints import atendimento as api
from app.models.agendamento import Agendamento
from app.models.atendimento_clinico import (
    AtendimentoClinico, DocumentoAtendimento, PrescricaoClinica, PrescricaoItem, PrescricaoItemAjuste,
)
from app.models.auditoria_evento import AuditoriaEvento
from app.models.clinica import Clinica
from app.models.ordem_servico import OrdemServico
from app.models.paciente import Paciente
from app.models.tutor import Tutor
from app.schemas.atendimento import AtendimentoUpdatePayload, PrescricaoSyncPayload
from app.services.atendimento.edit_history_service import listar_historico_edicoes


@pytest.mark.parametrize("alvo", ["consulta", "receita_no_atendimento", "receita_direta"])
def test_edicoes_concorrentes_encadeiam_historico_sem_reabrir_nem_alterar_os(alvo):
    url = os.environ.get("DOCUMENT_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("PostgreSQL local descartavel nao configurado")
    parsed = make_url(url)
    assert parsed.host in {"127.0.0.1", "localhost"} and parsed.database == "document_test"
    schema = "atendimento_edit_test_" + uuid.uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f"CREATE SCHEMA {schema}"))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema} -clock_timeout=10000"})
    sessions = sessionmaker(bind=engine, autoflush=False)
    try:
        for table in (
            Tutor.__table__, Paciente.__table__, Clinica.__table__, Agendamento.__table__,
            AtendimentoClinico.__table__, OrdemServico.__table__, AuditoriaEvento.__table__,
            DocumentoAtendimento.__table__, PrescricaoClinica.__table__, PrescricaoItem.__table__,
            PrescricaoItemAjuste.__table__,
        ):
            table.create(engine)
        with sessions() as db:
            tutor = Tutor(nome="Tutora sintetica", ativo=1)
            clinica = Clinica(nome="Clinica sintetica")
            db.add_all([tutor, clinica]); db.flush()
            paciente = Paciente(nome="Paciente sintetico", especie="Canina", tutor_id=tutor.id, ativo=1)
            db.add(paciente); db.flush()
            agendamento = Agendamento(paciente_id=paciente.id, tutor_id=tutor.id, clinica_id=clinica.id,
                                      inicio=datetime(2026, 10, 10, 9), status="Realizado")
            db.add(agendamento); db.flush()
            atendimento = AtendimentoClinico(paciente_id=paciente.id, tutor_id=tutor.id,
                clinica_id=clinica.id, agendamento_id=agendamento.id, veterinario_id=1, especie="Canina",
                status="Concluido", consulta_concluida=1, observacoes="Versao original")
            ordem = OrdemServico(numero_os="OS-SINTETICA", agendamento_id=agendamento.id,
                paciente_id=paciente.id, clinica_id=clinica.id, servico_id=1, status="Pago",
                valor_servico=Decimal("150.00"), valor_final=Decimal("150.00"))
            db.add_all([atendimento, ordem]); db.flush()
            receita = PrescricaoClinica(atendimento_id=atendimento.id, sequencia=1,
                orientacoes_gerais="Versao original", emitida_em=datetime(2026, 10, 10, 9))
            db.add(receita); db.flush()
            medicamento = PrescricaoItem(prescricao_id=receita.id, medicamento_nome="Item sintetico",
                dose="1 unidade", frequencia="12/12h", via="Oral", ordem=0)
            db.add(medicamento); db.commit()
            atendimento_id, agendamento_id, ordem_id = atendimento.id, agendamento.id, ordem.id
            receita_id, item_id = receita.id, medicamento.id

        barrier = Barrier(2)

        def editar(index):
            with sessions() as db:
                # Ambas as sessoes mantem a versao original no identity map.
                # O lock sozinho nao basta: o endpoint deve reler depois dele.
                original = db.get(AtendimentoClinico, atendimento_id)
                assert original.observacoes == "Versao original"
                receita_antiga = db.get(PrescricaoClinica, receita_id)
                item_antigo = db.get(PrescricaoItem, item_id)
                assert receita_antiga.orientacoes_gerais == "Versao original"
                assert item_antigo.frequencia == "12/12h"
                barrier.wait(timeout=10)
                user = SimpleNamespace(id=index, nome=f"Veterinario sintetico {index}")
                if alvo == "consulta":
                    return api.atualizar_atendimento(atendimento_id,
                        AtendimentoUpdatePayload(observacoes=f"Edicao {index}"), db=db, current_user=user)
                payload_receita = {"orientacoes_gerais": f"Edicao {index}", "itens": [{
                    "id": item_id, "medicamento_nome": "Item sintetico", "dose": "1 unidade",
                    "frequencia": "8/8h" if index == 1 else "24/24h", "via": "Oral", "ordem": 0,
                }]}
                if alvo == "receita_no_atendimento":
                    return api.atualizar_atendimento(atendimento_id,
                        AtendimentoUpdatePayload(prescricao=payload_receita), db=db, current_user=user)
                return api.atualizar_prescricao(atendimento_id, receita_id,
                    PrescricaoSyncPayload(**payload_receita), request=None, db=db, current_user=user)

        # O teste exercita lock, mutacao, auditoria e commit reais. Somente a
        # montagem da resposta, que consulta outros modulos, e isolada.
        with patch.object(api, "_montar_detalhe_atendimento", side_effect=lambda db, item: {"id": item.id}):
            with ThreadPoolExecutor(max_workers=2) as executor:
                resultados = list(executor.map(editar, [1, 2]))
        assert len(resultados) == 2

        with sessions() as db:
            persisted = db.get(AtendimentoClinico, atendimento_id)
            entidade = "atendimento_clinico" if alvo == "consulta" else "prescricao_clinica"
            entidade_id = atendimento_id if alvo == "consulta" else receita_id
            campo = "observacoes" if alvo == "consulta" else "orientacoes_gerais"
            eventos = db.query(AuditoriaEvento).filter_by(entidade=entidade,
                entidade_id=str(entidade_id)).order_by(AuditoriaEvento.id).all()
            assert len(eventos) == 2
            alteracoes = [json.loads(evento.detalhes_json)["alteracoes"][campo] for evento in eventos]
            assert alteracoes[0]["antes"] == "Versao original"
            assert alteracoes[1]["antes"] == alteracoes[0]["depois"]
            valor_final = persisted.observacoes if alvo == "consulta" else db.get(PrescricaoClinica, receita_id).orientacoes_gerais
            assert alteracoes[1]["depois"] == valor_final
            assert {alteracao["depois"] for alteracao in alteracoes} == {"Edicao 1", "Edicao 2"}
            assert {evento.usuario_id for evento in eventos} == {1, 2}
            historico = listar_historico_edicoes(db, atendimento_id)
            assert [item["id"] for item in historico["items"]] == [evento.id for evento in reversed(eventos)]
            if alvo != "consulta":
                itens = [json.loads(evento.detalhes_json)["alteracoes"]["itens"] for evento in eventos]
                assert itens[0]["antes"][0]["frequencia"] == "12/12h"
                assert itens[1]["antes"] == itens[0]["depois"]
                assert itens[1]["depois"][0]["frequencia"] == db.get(PrescricaoItem, item_id).frequencia
            assert persisted.status == "Concluido" and persisted.consulta_concluida == 1
            assert persisted.agendamento_id == agendamento_id
            assert db.get(Agendamento, agendamento_id).status == "Realizado"
            assert db.query(OrdemServico).count() == 1
            ordem = db.get(OrdemServico, ordem_id)
            assert ordem.status == "Pago" and ordem.valor_final == Decimal("150.00")
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()
