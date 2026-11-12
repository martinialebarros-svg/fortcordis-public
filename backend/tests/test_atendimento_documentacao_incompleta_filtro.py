"""Filtro e sinalizacao de documentacao clinica incompleta na listagem.

Cobre o item de acompanhamento apos atendimento-conclusao-confirmavel: agora
que e possivel concluir com pendencias (confirmando explicitamente), a lista
precisa deixar visivel quais prontuarios ja fechados ficaram incompletos,
para o vet voltar e completar depois.
"""
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault(
    "SECRET_KEY", "atendimento-documentacao-incompleta-filtro-test-secret-key-1234"
)

from app.api.v1.endpoints import atendimento
from app.models.atendimento_clinico import AtendimentoClinico, PrescricaoClinica
from app.models.clinica import Clinica
from app.models.laudo import Exame
from app.models.paciente import Paciente
from app.models.tutor import Tutor


class AtendimentoDocumentacaoIncompletaFiltroTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmpdir.name) / "atendimento-documentacao-incompleta.db"
        self.engine = create_engine(f"sqlite:///{db_path}")
        for table in (
            Tutor.__table__,
            Paciente.__table__,
            Clinica.__table__,
            AtendimentoClinico.__table__,
            Exame.__table__,
            PrescricaoClinica.__table__,
        ):
            table.create(self.engine, checkfirst=True)
        self.db = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)()
        self.user = SimpleNamespace(id=1)

        tutor = Tutor(nome="Tutora Teste", ativo=1)
        paciente = Paciente(nome="Paciente Teste", especie="Canina", ativo=1)
        clinica = Clinica(nome="Clinica Teste", ativo=True)
        self.db.add_all([tutor, paciente, clinica])
        self.db.flush()
        paciente.tutor_id = tutor.id
        self.paciente = paciente
        self.tutor = tutor
        self.clinica = clinica
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()
        self.tmpdir.cleanup()

    def _criar_atendimento(self, *, status: str, **campos) -> AtendimentoClinico:
        item = AtendimentoClinico(
            paciente_id=self.paciente.id,
            tutor_id=self.tutor.id,
            clinica_id=self.clinica.id,
            veterinario_id=self.user.id,
            especie=self.paciente.especie,
            data_atendimento=datetime(2026, 8, 2, 9, 0),
            status=status,
            criado_por_id=self.user.id,
            criado_por_nome="Dra. Teste",
            **campos,
        )
        self.db.add(item)
        self.db.commit()
        self.db.refresh(item)
        return item

    def test_filtro_traz_so_concluido_com_pendencia(self) -> None:
        concluido_incompleto = self._criar_atendimento(
            status="Concluido",
            queixa_principal="Tosse cronica.",
            exame_fisico="Ausculta com sopro leve.",
            # sem diagnostico nem plano terapeutico: pendencia do grupo 3
        )
        concluido_completo = self._criar_atendimento(
            status="Concluido",
            queixa_principal="Retorno de rotina.",
            exame_fisico="Estavel.",
            diagnostico_principal="Insuficiencia mitral estagio B2.",
            plano_terapeutico="Manter pimobendana.",
        )
        aberto_incompleto = self._criar_atendimento(status="Em atendimento")

        resultado = atendimento.listar_atendimentos(
            documentacao_incompleta=True,
            skip=0,
            limit=50,
            db=self.db,
            current_user=self.user,
        )

        ids = {item["id"] for item in resultado["items"]}
        self.assertEqual(ids, {concluido_incompleto.id})
        self.assertNotIn(concluido_completo.id, ids)
        self.assertNotIn(aberto_incompleto.id, ids)

    def test_item_traz_lista_de_pendencias_quando_concluido_incompleto(self) -> None:
        item = self._criar_atendimento(
            status="Concluido",
            queixa_principal="Tosse cronica.",
            exame_fisico="Ausculta com sopro leve.",
        )

        resultado = atendimento.listar_atendimentos(
            skip=0, limit=50, db=self.db, current_user=self.user
        )

        encontrado = next(i for i in resultado["items"] if i["id"] == item.id)
        self.assertIn("diagnostico ou plano terapeutico", "; ".join(encontrado["documentacao_pendencias"]))

    def test_item_concluido_completo_nao_tem_pendencias(self) -> None:
        item = self._criar_atendimento(
            status="Concluido",
            queixa_principal="Retorno de rotina.",
            exame_fisico="Estavel.",
            diagnostico_principal="Insuficiencia mitral estagio B2.",
            plano_terapeutico="Manter pimobendana.",
        )

        resultado = atendimento.listar_atendimentos(
            skip=0, limit=50, db=self.db, current_user=self.user
        )

        encontrado = next(i for i in resultado["items"] if i["id"] == item.id)
        self.assertEqual(encontrado["documentacao_pendencias"], [])

    def test_atendimento_aberto_nao_sinaliza_pendencia_mesmo_vazio(self) -> None:
        """CB: um atendimento em andamento tem campos vazios por natureza;
        isso nao e retrabalho, e so mostra pendencia quando ja concluido."""
        item = self._criar_atendimento(status="Triagem")

        resultado = atendimento.listar_atendimentos(
            skip=0, limit=50, db=self.db, current_user=self.user
        )

        encontrado = next(i for i in resultado["items"] if i["id"] == item.id)
        self.assertEqual(encontrado["documentacao_pendencias"], [])

    def test_filtro_combinado_com_status_diferente_de_concluido_fica_vazio(self) -> None:
        self._criar_atendimento(status="Triagem")

        resultado = atendimento.listar_atendimentos(
            status="Triagem",
            documentacao_incompleta=True,
            skip=0,
            limit=50,
            db=self.db,
            current_user=self.user,
        )

        self.assertEqual(resultado["items"], [])


if __name__ == "__main__":
    unittest.main()
