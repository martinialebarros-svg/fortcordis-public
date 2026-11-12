import os
import sys
import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "ordens-servico-domiciliar-test-secret-key-1234567890")

from app.api.v1.endpoints import ordens_servico
from app.models.agendamento import Agendamento
from app.models.clinica import Clinica
from app.models.configuracao import Configuracao
from app.models.configuracao import ConfiguracaoUsuario
from app.models.ordem_servico import OrdemServico
from app.models.paciente import Paciente
from app.models.servico import Servico
from app.models.tutor import Tutor


class OrdensServicoDomiciliarTest(unittest.TestCase):
    def _build_session(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "ordens-servico-domiciliar.db"
        engine = create_engine(f"sqlite:///{db_path}")
        for table in (
            Tutor.__table__,
            Paciente.__table__,
            Clinica.__table__,
            Servico.__table__,
            Configuracao.__table__,
            ConfiguracaoUsuario.__table__,
            Agendamento.__table__,
            OrdemServico.__table__,
        ):
            table.create(engine, checkfirst=True)
        session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
        return tmpdir, session, engine

    def test_listar_ordens_rotula_domiciliar_corretamente(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            tutor = Tutor(nome="Joana", telefone="85999990000", ativo=1)
            db.add(tutor)
            db.flush()

            paciente = Paciente(nome="Luna", tutor_id=tutor.id, especie="Canina", ativo=1)
            servico = Servico(nome="Consulta domiciliar", ativo=True)
            db.add_all([paciente, servico])
            db.flush()

            agendamento = Agendamento(
                paciente_id=paciente.id,
                tutor_id=tutor.id,
                clinica_id=None,
                servico_id=servico.id,
                origem_atendimento="domiciliar",
                inicio=datetime(2099, 7, 1, 8, 0, 0),
                fim=datetime(2099, 7, 1, 8, 30, 0),
                status="Realizado",
            )
            db.add(agendamento)
            db.flush()

            os_data = OrdemServico(
                numero_os="OS2099070001",
                agendamento_id=agendamento.id,
                paciente_id=paciente.id,
                clinica_id=None,
                servico_id=servico.id,
                origem_atendimento="domiciliar",
                data_atendimento=agendamento.inicio,
                tipo_horario="comercial",
                valor_servico=Decimal("180.00"),
                desconto=Decimal("0.00"),
                valor_final=Decimal("180.00"),
                status="Pendente",
            )
            db.add(os_data)
            db.commit()

            resposta = ordens_servico.listar_ordens(
                tipo_horario=None,
                db=db,
                current_user=SimpleNamespace(id=1),
            )

            self.assertEqual(resposta["total"], 1)
            self.assertEqual(resposta["items"][0]["origem_atendimento"], "domiciliar")
            self.assertEqual(resposta["items"][0]["clinica"], "Atendimento domiciliar")
            self.assertEqual(resposta["items"][0]["tutor_id"], tutor.id)
            self.assertEqual(resposta["items"][0]["destinatario_tipo"], "tutor")
            self.assertEqual(resposta["items"][0]["destinatario_nome"], "Joana")
            self.assertEqual(resposta["items"][0]["destinatario_telefone"], "85999990000")
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_atualizar_ordem_recalcula_preco_domiciliar_sem_clinica(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            tutor = Tutor(nome="Marcos", telefone="85999990000", ativo=1)
            db.add(tutor)
            db.flush()

            paciente = Paciente(nome="Thor", tutor_id=tutor.id, especie="Canina", ativo=1)
            servico = Servico(
                nome="Eco domiciliar",
                preco_domiciliar_comercial=Decimal("180.00"),
                preco_domiciliar_plantao=Decimal("250.00"),
                ativo=True,
            )
            db.add_all([paciente, servico])
            db.flush()

            agendamento = Agendamento(
                paciente_id=paciente.id,
                tutor_id=tutor.id,
                clinica_id=None,
                servico_id=servico.id,
                origem_atendimento="domiciliar",
                inicio=datetime(2099, 7, 2, 9, 0, 0),
                fim=datetime(2099, 7, 2, 9, 30, 0),
                status="Realizado",
            )
            db.add(agendamento)
            db.flush()

            os_data = OrdemServico(
                numero_os="OS2099070002",
                agendamento_id=agendamento.id,
                paciente_id=paciente.id,
                clinica_id=None,
                servico_id=servico.id,
                origem_atendimento="domiciliar",
                data_atendimento=agendamento.inicio,
                tipo_horario="comercial",
                valor_servico=Decimal("180.00"),
                desconto=Decimal("0.00"),
                valor_final=Decimal("180.00"),
                status="Pendente",
            )
            db.add(os_data)
            db.commit()
            db.refresh(os_data)

            with patch.object(ordens_servico, "registrar_auditoria", return_value=None), patch.object(
                ordens_servico, "send_financeiro_push_notification", return_value={"sent": 0, "failed": 0}
            ):
                resposta = ordens_servico.atualizar_ordem(
                    os_id=os_data.id,
                    dados=ordens_servico.OrdemServicoUpdate(
                        tipo_horario="plantao",
                        desconto=10,
                        recalcular_preco=True,
                    ),
                    request=SimpleNamespace(),
                    db=db,
                    current_user=SimpleNamespace(id=1, nome="Teste"),
                )

            self.assertEqual(resposta["origem_atendimento"], "domiciliar")
            self.assertEqual(resposta["clinica"], "Atendimento domiciliar")
            self.assertEqual(resposta["valor_servico"], 250.0)
            self.assertEqual(resposta["valor_final"], 240.0)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_listar_ordens_filtra_por_origem_domiciliar(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            tutor = Tutor(nome="Rita", telefone="85999990000", whatsapp="85999990000", ativo=1)
            db.add(tutor)
            db.flush()

            paciente = Paciente(nome="Belinha", tutor_id=tutor.id, especie="Canina", ativo=1)
            clinica = Clinica(nome="Clinica A", telefone="8532221111", ativo=True)
            servico = Servico(nome="Consulta", ativo=True)
            db.add_all([paciente, clinica, servico])
            db.flush()

            agendamento_domiciliar = Agendamento(
                paciente_id=paciente.id,
                tutor_id=tutor.id,
                clinica_id=None,
                servico_id=servico.id,
                origem_atendimento="domiciliar",
                inicio=datetime(2099, 7, 5, 8, 0, 0),
                fim=datetime(2099, 7, 5, 8, 30, 0),
                status="Realizado",
            )
            agendamento_clinica = Agendamento(
                paciente_id=paciente.id,
                tutor_id=tutor.id,
                clinica_id=clinica.id,
                servico_id=servico.id,
                origem_atendimento="clinica_parceira",
                inicio=datetime(2099, 7, 5, 9, 0, 0),
                fim=datetime(2099, 7, 5, 9, 30, 0),
                status="Realizado",
            )
            db.add_all([agendamento_domiciliar, agendamento_clinica])
            db.flush()

            db.add_all(
                [
                    OrdemServico(
                        numero_os="OS2099070008",
                        agendamento_id=agendamento_domiciliar.id,
                        paciente_id=paciente.id,
                        clinica_id=None,
                        servico_id=servico.id,
                        origem_atendimento="domiciliar",
                        data_atendimento=agendamento_domiciliar.inicio,
                        tipo_horario="comercial",
                        valor_servico=Decimal("180.00"),
                        desconto=Decimal("0.00"),
                        valor_final=Decimal("180.00"),
                        status="Pendente",
                    ),
                    OrdemServico(
                        numero_os="OS2099070009",
                        agendamento_id=agendamento_clinica.id,
                        paciente_id=paciente.id,
                        clinica_id=clinica.id,
                        servico_id=servico.id,
                        origem_atendimento="clinica_parceira",
                        data_atendimento=agendamento_clinica.inicio,
                        tipo_horario="comercial",
                        valor_servico=Decimal("200.00"),
                        desconto=Decimal("0.00"),
                        valor_final=Decimal("200.00"),
                        status="Pendente",
                    ),
                ]
            )
            db.commit()

            resposta = ordens_servico.listar_ordens(
                origem_atendimento="domiciliar",
                tipo_horario=None,
                db=db,
                current_user=SimpleNamespace(id=1),
            )

            self.assertEqual(resposta["total"], 1)
            self.assertEqual(len(resposta["items"]), 1)
            self.assertEqual(resposta["items"][0]["numero_os"], "OS2099070008")
            self.assertEqual(resposta["items"][0]["origem_atendimento"], "domiciliar")
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_relatorio_pendencias_domiciliar_filtra_e_agrupa_por_tutor(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            tutor = Tutor(
                nome="Aline Souza",
                telefone="85999990000",
                whatsapp="85988887777",
                email="aline@example.com",
                ativo=1,
            )
            db.add(tutor)
            db.flush()

            paciente = Paciente(nome="Nina", tutor_id=tutor.id, especie="Canina", ativo=1)
            clinica = Clinica(nome="Vet Central", telefone="8533334444", email="financeiro@vetcentral.com", ativo=True)
            servico = Servico(nome="Exame", ativo=True)
            db.add_all([paciente, clinica, servico])
            db.flush()

            agendamento_domiciliar = Agendamento(
                paciente_id=paciente.id,
                tutor_id=tutor.id,
                clinica_id=None,
                servico_id=servico.id,
                origem_atendimento="domiciliar",
                inicio=datetime(2099, 7, 3, 10, 0, 0),
                fim=datetime(2099, 7, 3, 10, 30, 0),
                status="Realizado",
            )
            agendamento_clinica = Agendamento(
                paciente_id=paciente.id,
                tutor_id=tutor.id,
                clinica_id=clinica.id,
                servico_id=servico.id,
                origem_atendimento="clinica_parceira",
                inicio=datetime(2099, 7, 4, 10, 0, 0),
                fim=datetime(2099, 7, 4, 10, 30, 0),
                status="Realizado",
            )
            db.add_all([agendamento_domiciliar, agendamento_clinica])
            db.flush()

            db.add_all(
                [
                    OrdemServico(
                        numero_os="OS2099070003",
                        agendamento_id=agendamento_domiciliar.id,
                        paciente_id=paciente.id,
                        clinica_id=None,
                        servico_id=servico.id,
                        origem_atendimento="domiciliar",
                        data_atendimento=agendamento_domiciliar.inicio,
                        tipo_horario="comercial",
                        valor_servico=Decimal("180.00"),
                        desconto=Decimal("0.00"),
                        valor_final=Decimal("180.00"),
                        status="Pendente",
                    ),
                    OrdemServico(
                        numero_os="OS2099070004",
                        agendamento_id=agendamento_clinica.id,
                        paciente_id=paciente.id,
                        clinica_id=clinica.id,
                        servico_id=servico.id,
                        origem_atendimento="clinica_parceira",
                        data_atendimento=agendamento_clinica.inicio,
                        tipo_horario="comercial",
                        valor_servico=Decimal("200.00"),
                        desconto=Decimal("0.00"),
                        valor_final=Decimal("200.00"),
                        status="Pendente",
                    ),
                ]
            )
            db.commit()

            with patch.object(ordens_servico, "_gerar_pdf_cobranca_pendencias", return_value=b"pdf") as pdf_mock:
                resposta = ordens_servico.gerar_relatorio_pendencias_pdf(
                    status="Pendente",
                    tutor_id=tutor.id,
                    tipo_horario=None,
                    db=db,
                    current_user=SimpleNamespace(id=1),
                )

            self.assertEqual(resposta.media_type, "application/pdf")
            self.assertTrue(pdf_mock.called)
            itens_relatorio = pdf_mock.call_args.kwargs["itens"]
            self.assertEqual(len(itens_relatorio), 1)
            self.assertEqual(itens_relatorio[0]["numero_os"], "OS2099070003")
            self.assertEqual(itens_relatorio[0]["destinatario_tipo"], "tutor")
            self.assertEqual(itens_relatorio[0]["destinatario_nome"], "Aline Souza")
            self.assertEqual(itens_relatorio[0]["destinatario_telefone"], "85988887777")
            self.assertEqual(itens_relatorio[0]["destinatario_email"], "aline@example.com")
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
