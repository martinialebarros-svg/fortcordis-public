import os
import sys
import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "agenda-resumo-financeiro-test-secret-key-1234567890")

from app.api.v1.endpoints import agenda
from app.models.agendamento import Agendamento
from app.models.clinica import Clinica
from app.models.ordem_servico import OrdemServico
from app.models.paciente import Paciente
from app.models.servico import Servico
from app.models.tabela_preco import PrecoServico, PrecoServicoClinica
from app.models.tutor import Tutor
from app.services.precos_service import calcular_precos_servicos_em_lote


class AgendaResumoFinanceiroTest(unittest.TestCase):
    def _build_session(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "agenda-resumo-financeiro.db"
        engine = create_engine(f"sqlite:///{db_path}")
        for table in (
            Tutor.__table__,
            Paciente.__table__,
            Clinica.__table__,
            Servico.__table__,
            PrecoServico.__table__,
            PrecoServicoClinica.__table__,
            Agendamento.__table__,
            OrdemServico.__table__,
        ):
            table.create(engine, checkfirst=True)
        session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
        return tmpdir, session, engine

    def _seed_base(self, db):
        tutor = Tutor(nome="Maria Oliveira", telefone="85999990001", ativo=1)
        db.add(tutor)
        db.flush()

        paciente = Paciente(tutor_id=tutor.id, nome="Luna", especie="Canina", ativo=1)
        clinica = Clinica(nome="Pet Center", ativo=True)
        servico = Servico(
            nome="Ecocardiograma",
            ativo=True,
            preco_fortaleza_comercial=Decimal("80.00"),
            preco=Decimal("60.00"),
        )
        db.add_all([paciente, clinica, servico])
        db.flush()

        return tutor, paciente, clinica, servico

    def _create_agendamento(
        self,
        db,
        *,
        data: str,
        hora: str,
        status: str,
        paciente_id: int,
        clinica_id: int | None,
        servico_id: int,
        origem_atendimento: str = "clinica_parceira",
    ):
        inicio = datetime.fromisoformat(f"{data}T{hora}:00")
        agendamento = Agendamento(
            paciente_id=paciente_id,
            clinica_id=clinica_id,
            servico_id=servico_id,
            inicio=inicio,
            fim=inicio,
            data=data,
            hora=hora,
            status=status,
            origem_atendimento=origem_atendimento,
        )
        db.add(agendamento)
        db.flush()
        return agendamento

    def _create_os(self, db, *, numero: str, agendamento: Agendamento, valor_final: Decimal, status: str = "Pago"):
        db.add(
            OrdemServico(
                numero_os=numero,
                agendamento_id=agendamento.id,
                paciente_id=agendamento.paciente_id,
                clinica_id=agendamento.clinica_id,
                servico_id=agendamento.servico_id,
                origem_atendimento=agendamento.origem_atendimento,
                data_atendimento=agendamento.inicio,
                tipo_horario="comercial",
                valor_servico=valor_final,
                desconto=Decimal("0.00"),
                valor_final=valor_final,
                status=status,
            )
        )

    def test_resumo_financeiro_respeita_periodo_e_filtros(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            _tutor, paciente, clinica, servico = self._seed_base(db)

            ag_realizado = self._create_agendamento(
                db,
                data="2026-05-17",
                hora="09:00",
                status="Realizado",
                paciente_id=paciente.id,
                clinica_id=clinica.id,
                servico_id=servico.id,
            )
            ag_agendado = self._create_agendamento(
                db,
                data="2026-05-18",
                hora="10:30",
                status="Agendado",
                paciente_id=paciente.id,
                clinica_id=clinica.id,
                servico_id=servico.id,
            )
            self._create_os(db, numero="OS-1", agendamento=ag_realizado, valor_final=Decimal("120.50"))
            self._create_os(db, numero="OS-2", agendamento=ag_agendado, valor_final=Decimal("90.00"))
            db.commit()

            resultado = agenda.resumo_financeiro_agenda(
                data_inicio="2026-05-17",
                data_fim="2026-05-18",
                clinica_id=clinica.id,
                servico_id=servico.id,
                tutor_nome="Maria",
                db=db,
                current_user=SimpleNamespace(tem_papel=lambda role: role == "admin"),
            )

            self.assertEqual(resultado["data_inicio"], "2026-05-17")
            self.assertEqual(resultado["data_fim"], "2026-05-18")
            self.assertEqual(resultado["qtd_realizados"], 1)
            self.assertEqual(resultado["qtd_agendados"], 1)
            self.assertAlmostEqual(resultado["valor_realizado"], 120.50, places=2)
            self.assertAlmostEqual(resultado["valor_agendado"], 90.00, places=2)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_resumo_financeiro_filtra_por_origem_atendimento(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            tutor, paciente, clinica, servico = self._seed_base(db)

            ag_clinica = self._create_agendamento(
                db,
                data="2026-05-19",
                hora="09:00",
                status="Realizado",
                paciente_id=paciente.id,
                clinica_id=clinica.id,
                servico_id=servico.id,
                origem_atendimento="clinica_parceira",
            )
            ag_domiciliar = self._create_agendamento(
                db,
                data="2026-05-19",
                hora="11:00",
                status="Realizado",
                paciente_id=paciente.id,
                clinica_id=None,
                servico_id=servico.id,
                origem_atendimento="domiciliar",
            )
            self._create_os(db, numero="OS-CLINICA", agendamento=ag_clinica, valor_final=Decimal("150.00"))
            self._create_os(db, numero="OS-DOMICILIAR", agendamento=ag_domiciliar, valor_final=Decimal("210.00"))
            db.commit()

            resultado = agenda.resumo_financeiro_agenda(
                data_inicio="2026-05-19",
                data_fim="2026-05-19",
                origem_atendimento="domiciliar",
                tutor_nome=tutor.nome,
                db=db,
                current_user=SimpleNamespace(tem_papel=lambda role: role == "admin"),
            )

            self.assertEqual(resultado["qtd_realizados"], 1)
            self.assertEqual(resultado["qtd_agendados"], 0)
            self.assertAlmostEqual(resultado["valor_realizado"], 210.0, places=2)
            self.assertAlmostEqual(resultado["valor_agendado"], 0.0, places=2)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_precos_em_lote_preservam_negociado_e_domiciliar(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            _tutor, _paciente, clinica, servico = self._seed_base(db)
            servico.preco_domiciliar_comercial = Decimal("72.00")
            db.add(
                PrecoServicoClinica(
                    clinica_id=clinica.id,
                    servico_id=servico.id,
                    preco_comercial=Decimal("110.00"),
                    ativo=1,
                )
            )
            db.commit()

            precos = calcular_precos_servicos_em_lote(
                db,
                [
                    (clinica.id, servico.id, "clinica_parceira"),
                    (None, servico.id, "domiciliar"),
                ],
            )

            self.assertEqual(precos[(clinica.id, servico.id, "clinica_parceira")], Decimal("110.00"))
            self.assertEqual(precos[(None, servico.id, "domiciliar")], Decimal("72.00"))
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_resumo_financeiro_calcula_previsoes_em_consultas_limitadas(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            _tutor, paciente, clinica, servico = self._seed_base(db)
            db.add(
                PrecoServicoClinica(
                    clinica_id=clinica.id,
                    servico_id=servico.id,
                    preco_comercial=Decimal("105.00"),
                    ativo=1,
                )
            )
            for indice in range(12):
                self._create_agendamento(
                    db,
                    data="2026-05-20",
                    hora=f"{8 + (indice % 10):02d}:{(indice % 2) * 30:02d}",
                    status="Agendado",
                    paciente_id=paciente.id,
                    clinica_id=clinica.id,
                    servico_id=servico.id,
                )
            db.commit()

            selects: list[str] = []

            def registrar_select(_conn, _cursor, statement, _parameters, _context, _executemany):
                if statement.lstrip().upper().startswith("SELECT"):
                    selects.append(statement)

            event.listen(engine, "before_cursor_execute", registrar_select)
            try:
                resultado = agenda.resumo_financeiro_agenda(
                    data="2026-05-20",
                    db=db,
                    current_user=SimpleNamespace(tem_papel=lambda role: role == "admin"),
                )
            finally:
                event.remove(engine, "before_cursor_execute", registrar_select)

            self.assertEqual(resultado["qtd_agendados"], 12)
            self.assertAlmostEqual(resultado["valor_agendado"], 1260.0, places=2)
            self.assertLessEqual(len(selects), 5)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
