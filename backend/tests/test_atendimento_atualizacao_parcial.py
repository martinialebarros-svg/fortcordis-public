"""Regressoes de preservacao de dados nos blocos parciais do prontuario."""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "atendimento-partial-test-secret-key-20261115")

from app.api.v1.endpoints import atendimento
from app.models.atendimento_clinico import AtendimentoClinico
from app.models.auditoria_evento import AuditoriaEvento
from app.models.clinica import Clinica
from app.models.paciente import Paciente
from app.models.tutor import Tutor
from app.schemas.atendimento import AtendimentoUpdatePayload


class AtendimentoAtualizacaoParcialTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{Path(self.tmpdir.name) / 'parcial.db'}")
        for model in (Tutor, Paciente, Clinica, AtendimentoClinico, AuditoriaEvento):
            model.__table__.create(self.engine)
        self.db = sessionmaker(bind=self.engine, autoflush=False)()
        self.user = SimpleNamespace(id=17, nome="Veterinaria sintetica")
        tutor = Tutor(nome="Tutor sintetico", ativo=1)
        clinica = Clinica(nome="Clinica sintetica")
        self.db.add_all([tutor, clinica])
        self.db.flush()
        paciente = Paciente(nome="Paciente sintetico", especie="Canina", tutor_id=tutor.id, ativo=1)
        self.db.add(paciente)
        self.db.flush()
        self.registro = AtendimentoClinico(
            paciente_id=paciente.id, tutor_id=tutor.id, clinica_id=clinica.id,
            veterinario_id=self.user.id, especie="Canina", status="Em atendimento",
            data_atendimento=datetime(2026, 11, 15, 9),
            peso=8.0, temperatura=38.5, frequencia_cardiaca=90,
            pressao_arterial="120", mucosas="Rosadas",
            queixa_principal="Retorno sintetico", exame_fisico="Exame sintetico",
            diagnostico_principal="Diagnostico sintetico A",
            diagnostico_secundario="Diagnostico sintetico B",
            diagnostico_diferencial="Hipotese sintetica", prognostico="Favoravel",
        )
        self.db.add(self.registro)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        self.tmpdir.cleanup()

    def atualizar(self, **payload):
        # Lock, mutacao, auditoria e commit sao reais; a resposta de outros
        # modulos e isolada para manter o teste em um banco temporario minimo.
        with patch.object(atendimento, "_montar_detalhe_atendimento", return_value={}):
            atendimento.atualizar_atendimento(
                self.registro.id, AtendimentoUpdatePayload(**payload),
                db=self.db, current_user=self.user,
            )
        self.db.refresh(self.registro)

    def alteracoes_auditadas(self):
        evento = self.db.query(AuditoriaEvento).one()
        return json.loads(evento.detalhes_json)["alteracoes"]

    def test_peso_isolado_preserva_outros_sinais_vitais_e_audita_apenas_o_peso(self):
        self.atualizar(triagem={"peso": 9.0})
        self.assertEqual(self.registro.peso, 9.0)
        self.assertEqual(self.registro.temperatura, 38.5)
        self.assertEqual(self.registro.frequencia_cardiaca, 90)
        self.assertEqual(self.registro.pressao_arterial, "120")
        self.assertEqual(self.registro.mucosas, "Rosadas")
        self.assertEqual(set(self.alteracoes_auditadas()), {"peso"})

    def test_prognostico_isolado_preserva_diagnosticos_e_audita_apenas_prognostico(self):
        self.atualizar(diagnostico={"prognostico": "Reservado"})
        self.assertEqual(self.registro.prognostico, "Reservado")
        self.assertEqual(self.registro.diagnostico_principal, "Diagnostico sintetico A")
        self.assertEqual(self.registro.diagnostico_secundario, "Diagnostico sintetico B")
        self.assertEqual(self.registro.diagnostico_diferencial, "Hipotese sintetica")
        self.assertEqual(set(self.alteracoes_auditadas()), {"prognostico"})

    def test_blocos_vazios_nao_apagam_conteudo_nem_geram_edicao_clinica(self):
        antes = atendimento._snapshot_conteudo_clinico(self.registro)
        self.atualizar(triagem={}, diagnostico={})
        self.assertEqual(atendimento._snapshot_conteudo_clinico(self.registro), antes)
        self.assertEqual(self.db.query(AuditoriaEvento).count(), 0)

    def test_limpeza_explicita_na_triagem_preserva_os_campos_omitidos(self):
        self.atualizar(triagem={"peso": None, "pressao_arterial": ""})
        self.assertIsNone(self.registro.peso)
        self.assertEqual(self.registro.pressao_arterial, "")
        self.assertEqual(self.registro.temperatura, 38.5)
        self.assertEqual(self.registro.frequencia_cardiaca, 90)
        self.assertEqual(set(self.alteracoes_auditadas()), {"peso", "pressao_arterial"})

    def test_limpeza_explicita_do_diagnostico_preserva_os_campos_omitidos(self):
        self.atualizar(diagnostico={"diagnostico_principal": None, "prognostico": ""})
        self.assertEqual(self.registro.diagnostico_principal, "")
        self.assertIsNone(self.registro.prognostico)
        self.assertEqual(self.registro.diagnostico_secundario, "Diagnostico sintetico B")
        self.assertEqual(self.registro.diagnostico_diferencial, "Hipotese sintetica")
        self.assertEqual(set(self.alteracoes_auditadas()), {"diagnostico_principal", "prognostico"})

    def test_diagnostico_legado_em_texto_atualiza_somente_o_principal(self):
        self.atualizar(diagnostico=" Novo diagnostico sintetico ")
        self.assertEqual(self.registro.diagnostico_principal, "Novo diagnostico sintetico")
        self.assertEqual(self.registro.diagnostico_secundario, "Diagnostico sintetico B")
        self.assertEqual(self.registro.diagnostico_diferencial, "Hipotese sintetica")
        self.assertEqual(self.registro.prognostico, "Favoravel")
        self.assertEqual(set(self.alteracoes_auditadas()), {"diagnostico_principal"})

    def test_diagnosticos_nulos_omitidos_permanecem_nulos(self):
        self.registro.diagnostico_principal = None
        self.registro.diagnostico_diferencial = None
        self.db.commit()
        self.atualizar(diagnostico={"prognostico": "Reservado"})
        self.assertIsNone(self.registro.diagnostico_principal)
        self.assertIsNone(self.registro.diagnostico_diferencial)

    def test_conclusao_com_prognostico_parcial_considera_diagnostico_salvo(self):
        self.atualizar(status="Concluido", diagnostico={"prognostico": "Reservado"})
        self.assertEqual(self.registro.status, "Concluido")
        self.assertEqual(self.registro.consulta_concluida, 1)
        self.assertEqual(self.registro.diagnostico_principal, "Diagnostico sintetico A")

    def test_conclusao_com_diagnosticos_explicitamente_apagados_exige_confirmacao(self):
        with self.assertRaises(HTTPException) as erro:
            self.atualizar(status="Concluido", diagnostico={
                "diagnostico_principal": None, "diagnostico_secundario": "",
                "diagnostico_diferencial": None,
            })
        self.assertEqual(erro.exception.status_code, 409)
        self.assertEqual(erro.exception.detail["codigo"], "CONFIRMACAO_CONCLUSAO_PENDENCIAS")
        self.db.refresh(self.registro)
        self.assertEqual(self.registro.status, "Em atendimento")
        self.assertEqual(self.registro.diagnostico_principal, "Diagnostico sintetico A")
        self.assertEqual(self.db.query(AuditoriaEvento).count(), 0)


if __name__ == "__main__":
    unittest.main()
