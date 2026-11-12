import os
import sys
import tempfile
import unittest
import unittest.mock
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "laudos-fila-pendentes-test-secret-key-1234567890")

from app.api.v1.endpoints import agenda, laudos
from app.models.agendamento import Agendamento
from app.models.atendimento_clinico import AtendimentoClinico
from app.models.clinica import Clinica
from app.models.configuracao import Configuracao
from app.models.laudo import Exame, Laudo
from app.models.paciente import Paciente
from app.models.servico import Servico
from app.models.tutor import Tutor


class LaudosFilaPendentesTest(unittest.TestCase):
    def _build_session(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "laudos-fila-pendentes.db"
        engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
        for table in (
            Paciente.__table__,
            Tutor.__table__,
            Clinica.__table__,
            Servico.__table__,
            Agendamento.__table__,
            AtendimentoClinico.__table__,
            Exame.__table__,
            Laudo.__table__,
            Configuracao.__table__,
        ):
            table.create(engine, checkfirst=True)
        session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        return tmpdir, session_factory(), engine

    def _user(self):
        return SimpleNamespace(id=1, nome="Dr Teste", tem_papel=lambda papel: False)

    def _seed_atendimento(self, db, *, agendamento_status: str, data_atendimento: datetime, clinica_id=None):
        """Fluxo A (raro): Atendimento Clinico completo, gera Exame."""
        tutor = Tutor(nome="Tutor Sintetico 7")
        db.add(tutor)
        db.flush()
        paciente = Paciente(nome="Paciente Teste", tutor_id=tutor.id)
        db.add(paciente)
        db.flush()
        agendamento = Agendamento(inicio=data_atendimento, status=agendamento_status)
        db.add(agendamento)
        db.flush()
        atendimento = AtendimentoClinico(
            paciente_id=paciente.id,
            tutor_id=tutor.id,
            clinica_id=clinica_id,
            agendamento_id=agendamento.id,
            veterinario_id=1,
            data_atendimento=data_atendimento,
            status="Concluido",
        )
        db.add(atendimento)
        db.commit()
        return paciente, tutor, agendamento, atendimento

    def _seed_agendamento_sem_atendimento(
        self, db, *, servico_nome: str, inicio: datetime, status: str = "Realizado", servico_id_denormalizado_apenas=False
    ):
        """Fluxo B (comum): so Agendamento, sem Atendimento Clinico - o Laudo
        (se existir) e criado direto via `Laudo.agendamento_id` (fluxo do
        dropdown "Laudar" da Agenda)."""
        servico = Servico(nome=servico_nome, duracao_minutos=30, ativo=True)
        db.add(servico)
        db.flush()
        agendamento = Agendamento(
            inicio=inicio,
            status=status,
            servico_id=None if servico_id_denormalizado_apenas else servico.id,
            servico=servico_nome,
        )
        db.add(agendamento)
        db.commit()
        return agendamento

    # --- Fluxo A: exame vinculado a Atendimento Clinico completo ---

    def test_exame_realizado_sem_laudo_aparece_na_fila(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            _, _, _, atendimento = self._seed_atendimento(
                db, agendamento_status="Realizado", data_atendimento=datetime(2026, 8, 10, 10, 0)
            )
            exame = Exame(atendimento_id=atendimento.id, paciente_id=atendimento.paciente_id, tipo_exame="Ecocardiograma")
            db.add(exame)
            db.commit()

            resultado = laudos.listar_laudos_pendentes(db=db, current_user=self._user())

            self.assertEqual(resultado["total"], 1)
            self.assertEqual(resultado["items"][0]["exame_id"], exame.id)
            self.assertFalse(resultado["items"][0]["tem_rascunho"])
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_exame_com_laudo_rascunho_aparece_na_fila(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            _, _, _, atendimento = self._seed_atendimento(
                db, agendamento_status="Realizado", data_atendimento=datetime(2026, 8, 10, 10, 0)
            )
            laudo = Laudo(paciente_id=atendimento.paciente_id, veterinario_id=1, tipo="ecocardiograma", titulo="L", status="Rascunho")
            db.add(laudo)
            db.commit()
            exame = Exame(
                atendimento_id=atendimento.id,
                paciente_id=atendimento.paciente_id,
                tipo_exame="Ecocardiograma",
                laudo_id=laudo.id,
            )
            db.add(exame)
            db.commit()

            resultado = laudos.listar_laudos_pendentes(db=db, current_user=self._user())

            self.assertEqual(resultado["total"], 1)
            self.assertTrue(resultado["items"][0]["tem_rascunho"])
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_exame_de_agendamento_nao_realizado_nao_aparece(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            _, _, _, atendimento = self._seed_atendimento(
                db, agendamento_status="Confirmado", data_atendimento=datetime(2026, 8, 10, 10, 0)
            )
            exame = Exame(atendimento_id=atendimento.id, paciente_id=atendimento.paciente_id, tipo_exame="Ecocardiograma")
            db.add(exame)
            db.commit()

            resultado = laudos.listar_laudos_pendentes(db=db, current_user=self._user())

            self.assertEqual(resultado["total"], 0)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_exame_com_laudo_finalizado_nao_aparece(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            _, _, _, atendimento = self._seed_atendimento(
                db, agendamento_status="Realizado", data_atendimento=datetime(2026, 8, 10, 10, 0)
            )
            laudo = Laudo(paciente_id=atendimento.paciente_id, veterinario_id=1, tipo="ecocardiograma", titulo="L", status="Finalizado")
            db.add(laudo)
            db.commit()
            exame = Exame(
                atendimento_id=atendimento.id,
                paciente_id=atendimento.paciente_id,
                tipo_exame="Ecocardiograma",
                laudo_id=laudo.id,
            )
            db.add(exame)
            db.commit()

            resultado = laudos.listar_laudos_pendentes(db=db, current_user=self._user())

            self.assertEqual(resultado["total"], 0)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_exame_sem_atendimento_nao_aparece(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            paciente = Paciente(nome="Paciente Solto")
            db.add(paciente)
            db.commit()
            exame = Exame(paciente_id=paciente.id, tipo_exame="Eletrocardiograma")
            db.add(exame)
            db.commit()

            resultado = laudos.listar_laudos_pendentes(db=db, current_user=self._user())

            self.assertEqual(resultado["total"], 0)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_exame_atrasado_recebe_selo_atrasado(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            # Realizado ha bem mais de 48h uteis (dias corridos, sem feriado).
            data_antiga = datetime.utcnow() - timedelta(days=10)
            _, _, _, atendimento = self._seed_atendimento(
                db, agendamento_status="Realizado", data_atendimento=data_antiga
            )
            exame = Exame(atendimento_id=atendimento.id, paciente_id=atendimento.paciente_id, tipo_exame="Ecocardiograma")
            db.add(exame)
            db.commit()

            resultado = laudos.listar_laudos_pendentes(db=db, current_user=self._user())

            self.assertTrue(resultado["items"][0]["atrasado"])
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_urgente_no_agendamento_aparece_primeiro_mesmo_sendo_mais_recente(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            _, _, agendamento_antigo, atendimento_antigo = self._seed_atendimento(
                db, agendamento_status="Realizado", data_atendimento=datetime(2026, 8, 1, 10, 0)
            )
            exame_antigo = Exame(
                atendimento_id=atendimento_antigo.id,
                paciente_id=atendimento_antigo.paciente_id,
                tipo_exame="Ecocardiograma",
            )
            db.add(exame_antigo)

            _, _, agendamento_recente, atendimento_recente = self._seed_atendimento(
                db, agendamento_status="Realizado", data_atendimento=datetime(2026, 8, 15, 10, 0)
            )
            agendamento_recente.urgente_laudo = True
            exame_urgente = Exame(
                atendimento_id=atendimento_recente.id,
                paciente_id=atendimento_recente.paciente_id,
                tipo_exame="Ecocardiograma",
            )
            db.add(exame_urgente)
            db.commit()

            resultado = laudos.listar_laudos_pendentes(db=db, current_user=self._user())

            self.assertEqual(resultado["total"], 2)
            self.assertEqual(resultado["items"][0]["exame_id"], exame_urgente.id)
            self.assertTrue(resultado["items"][0]["urgente"])
            self.assertEqual(resultado["items"][0]["agendamento_id"], agendamento_recente.id)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_toggle_urgente_via_atualizar_agendamento(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            agendamento = Agendamento(inicio=datetime(2026, 8, 10, 10, 0), status="Realizado")
            db.add(agendamento)
            db.commit()

            with patch.object(agenda, "registrar_auditoria", return_value=None), patch.object(
                agenda, "_notificar_agenda_update", return_value=None
            ):
                agenda.atualizar_agendamento(
                    agendamento_id=agendamento.id,
                    agendamento=agenda.AgendamentoUpdate(urgente_laudo=True),
                    request=SimpleNamespace(),
                    db=db,
                    current_user=self._user(),
                )

            db.refresh(agendamento)
            self.assertTrue(agendamento.urgente_laudo)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    # --- Fluxo B: agendamento "Realizado" sem Atendimento Clinico ---

    def test_agendamento_sem_atendimento_com_servico_exame_aparece_na_fila(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            agendamento = self._seed_agendamento_sem_atendimento(
                db, servico_nome="Ecocardiograma", inicio=datetime(2026, 8, 10, 10, 0)
            )

            resultado = laudos.listar_laudos_pendentes(db=db, current_user=self._user())

            self.assertEqual(resultado["total"], 1)
            item = resultado["items"][0]
            self.assertIsNone(item["exame_id"])
            self.assertEqual(item["agendamento_id"], agendamento.id)
            self.assertEqual(item["tipo_exame"], "ecocardiograma")
            self.assertFalse(item["tem_rascunho"])
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_agendamento_servico_nao_exame_nao_aparece(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            for nome in ("Consulta", "Drenagem de Efusão Pericárdica", "Reavaliação/Retorno"):
                self._seed_agendamento_sem_atendimento(db, servico_nome=nome, inicio=datetime(2026, 8, 10, 10, 0))

            resultado = laudos.listar_laudos_pendentes(db=db, current_user=self._user())

            self.assertEqual(resultado["total"], 0)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_agendamento_combo_gera_dois_itens_pendentes(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            self._seed_agendamento_sem_atendimento(
                db, servico_nome="Eco + Eletro", inicio=datetime(2026, 8, 10, 10, 0)
            )

            resultado = laudos.listar_laudos_pendentes(db=db, current_user=self._user())

            self.assertEqual(resultado["total"], 2)
            tipos = sorted(item["tipo_exame"] for item in resultado["items"])
            self.assertEqual(tipos, ["ecocardiograma", "eletrocardiograma"])
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_agendamento_combo_com_um_tipo_finalizado_gera_um_item(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            agendamento = self._seed_agendamento_sem_atendimento(
                db, servico_nome="Eco + PA", inicio=datetime(2026, 8, 10, 10, 0)
            )
            laudo_eco = Laudo(
                paciente_id=1,
                veterinario_id=1,
                agendamento_id=agendamento.id,
                tipo="ecocardiograma",
                titulo="L",
                status="Finalizado",
            )
            db.add(laudo_eco)
            db.commit()

            resultado = laudos.listar_laudos_pendentes(db=db, current_user=self._user())

            self.assertEqual(resultado["total"], 1)
            self.assertEqual(resultado["items"][0]["tipo_exame"], "pressao_arterial")
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_agendamento_com_laudo_rascunho_aparece_marcado(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            agendamento = self._seed_agendamento_sem_atendimento(
                db, servico_nome="Eletrocardiograma", inicio=datetime(2026, 8, 10, 10, 0)
            )
            laudo = Laudo(
                paciente_id=1,
                veterinario_id=1,
                agendamento_id=agendamento.id,
                tipo="eletrocardiograma",
                titulo="L",
                status="Rascunho",
            )
            db.add(laudo)
            db.commit()

            resultado = laudos.listar_laudos_pendentes(db=db, current_user=self._user())

            self.assertEqual(resultado["total"], 1)
            self.assertTrue(resultado["items"][0]["tem_rascunho"])
            self.assertEqual(resultado["items"][0]["laudo_id"], laudo.id)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_agendamento_com_laudo_finalizado_nao_aparece(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            agendamento = self._seed_agendamento_sem_atendimento(
                db, servico_nome="Pressão Arterial", inicio=datetime(2026, 8, 10, 10, 0)
            )
            laudo = Laudo(
                paciente_id=1,
                veterinario_id=1,
                agendamento_id=agendamento.id,
                tipo="pressao_arterial",
                titulo="L",
                status="Finalizado",
            )
            db.add(laudo)
            db.commit()

            resultado = laudos.listar_laudos_pendentes(db=db, current_user=self._user())

            self.assertEqual(resultado["total"], 0)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_agendamento_usa_o_laudo_mais_recente_do_mesmo_tipo(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            agendamento = self._seed_agendamento_sem_atendimento(
                db, servico_nome="Ecocardiograma", inicio=datetime(2026, 8, 10, 10, 0)
            )
            db.add_all(
                [
                    Laudo(
                        paciente_id=1,
                        veterinario_id=1,
                        agendamento_id=agendamento.id,
                        tipo="ecocardiograma",
                        titulo="Rascunho antigo",
                        status="Rascunho",
                        created_at=datetime(2026, 8, 10, 11, 0),
                    ),
                    Laudo(
                        paciente_id=1,
                        veterinario_id=1,
                        agendamento_id=agendamento.id,
                        tipo="ecocardiograma",
                        titulo="Finalizado recente",
                        status="Finalizado",
                        created_at=datetime(2026, 8, 10, 12, 0),
                    ),
                ]
            )
            db.commit()

            resultado = laudos.listar_laudos_pendentes(db=db, current_user=self._user())

            self.assertEqual(resultado["total"], 0)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_agendamento_servico_id_nulo_usa_nome_denormalizado(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            self._seed_agendamento_sem_atendimento(
                db,
                servico_nome="Ecocardiograma",
                inicio=datetime(2026, 8, 10, 10, 0),
                servico_id_denormalizado_apenas=True,
            )

            resultado = laudos.listar_laudos_pendentes(db=db, current_user=self._user())

            self.assertEqual(resultado["total"], 1)
            self.assertEqual(resultado["items"][0]["tipo_exame"], "ecocardiograma")
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_agendamento_atrasado_usa_horario_agendado_como_referencia(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            inicio_antigo = datetime.utcnow() - timedelta(days=10)
            self._seed_agendamento_sem_atendimento(db, servico_nome="Ecocardiograma", inicio=inicio_antigo)

            resultado = laudos.listar_laudos_pendentes(db=db, current_user=self._user())

            self.assertTrue(resultado["items"][0]["atrasado"])
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_agendamento_nao_realizado_com_servico_exame_nao_aparece(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            self._seed_agendamento_sem_atendimento(
                db, servico_nome="Ecocardiograma", inicio=datetime(2026, 8, 10, 10, 0), status="Confirmado"
            )

            resultado = laudos.listar_laudos_pendentes(db=db, current_user=self._user())

            self.assertEqual(resultado["total"], 0)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_paginacao_da_fila_acontece_no_banco_antes_da_hidratacao(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            servico = Servico(nome="Ecocardiograma", duracao_minutos=30, ativo=True)
            db.add(servico)
            db.flush()
            inicio_base = datetime(2026, 8, 1, 8, 0)
            for indice in range(125):
                db.add(
                    Agendamento(
                        inicio=inicio_base + timedelta(minutes=indice),
                        status="Realizado",
                        servico_id=servico.id,
                        servico="Ecocardiograma",
                    )
                )
            db.commit()

            statements: list[str] = []

            def registrar_sql(conn, cursor, statement, parameters, context, executemany):
                statements.append(statement)

            event.listen(engine, "before_cursor_execute", registrar_sql)
            try:
                primeira_pagina = laudos.listar_laudos_pendentes(
                    skip=0,
                    limit=100,
                    db=db,
                    current_user=self._user(),
                )
                segunda_pagina = laudos.listar_laudos_pendentes(
                    skip=100,
                    limit=25,
                    db=db,
                    current_user=self._user(),
                )
            finally:
                event.remove(engine, "before_cursor_execute", registrar_sql)

            self.assertEqual(primeira_pagina["total"], 125)
            self.assertEqual(len(primeira_pagina["items"]), 100)
            self.assertEqual(len(segunda_pagina["items"]), 25)
            self.assertFalse(
                {item["agendamento_id"] for item in primeira_pagina["items"]}
                & {item["agendamento_id"] for item in segunda_pagina["items"]}
            )

            consultas_fila = [
                statement.upper()
                for statement in statements
                if "FILA_LAUDOS_PENDENTES" in statement.upper()
            ]
            self.assertTrue(any("UNION ALL" in statement for statement in consultas_fila))
            self.assertTrue(
                any("LIMIT" in statement and "OFFSET" in statement for statement in consultas_fila)
            )
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    # --- Indicador de agilidade ---

    def test_agilidade_calcula_percentual_e_tendencia(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            agora = datetime.utcnow()

            # Janela atual (ultimos 90 dias): 1 no prazo, 1 atrasado -> 50%.
            agendamento_1 = Agendamento(inicio=agora - timedelta(days=10), status="Realizado")
            db.add(agendamento_1)
            db.flush()
            laudo_1 = Laudo(
                paciente_id=1,
                veterinario_id=1,
                agendamento_id=agendamento_1.id,
                tipo="ecocardiograma",
                titulo="L1",
                status="Finalizado",
                finalizado_em=agora - timedelta(days=10) + timedelta(hours=10),
            )
            db.add(laudo_1)

            agendamento_2 = Agendamento(inicio=agora - timedelta(days=20), status="Realizado")
            db.add(agendamento_2)
            db.flush()
            laudo_2 = Laudo(
                paciente_id=1,
                veterinario_id=1,
                agendamento_id=agendamento_2.id,
                tipo="ecocardiograma",
                titulo="L2",
                status="Finalizado",
                finalizado_em=agora - timedelta(days=5),  # 15 dias corridos depois = bem atrasado
            )
            db.add(laudo_2)
            db.commit()

            resultado = laudos.obter_agilidade_laudos(db=db, current_user=self._user())

            self.assertEqual(resultado["janela_atual"]["total_finalizados"], 2)
            self.assertEqual(resultado["janela_atual"]["no_prazo"], 1)
            self.assertEqual(resultado["janela_atual"]["percentual_no_prazo"], 50.0)
            # Sem dados na janela anterior (91-180 dias atras) -> tendencia None.
            self.assertIsNone(resultado["tendencia"])
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_agilidade_conta_laudo_sem_exame_vinculado(self) -> None:
        """Cobre o fluxo comum (dropdown "Laudar"): Laudo.agendamento_id
        preenchido sem nenhum Exame/AtendimentoClinico - a versao anterior
        do indicador so contava laudos com Exame vinculado e subcontava
        esse caso (a maioria)."""
        tmpdir, db, engine = self._build_session()
        try:
            agora = datetime.utcnow()
            agendamento = Agendamento(inicio=agora - timedelta(days=3), status="Realizado")
            db.add(agendamento)
            db.flush()
            laudo = Laudo(
                paciente_id=1,
                veterinario_id=1,
                agendamento_id=agendamento.id,
                tipo="ecocardiograma",
                titulo="L",
                status="Finalizado",
                finalizado_em=agora - timedelta(days=3) + timedelta(hours=5),
            )
            db.add(laudo)
            db.commit()

            resultado = laudos.obter_agilidade_laudos(db=db, current_user=self._user())

            self.assertEqual(resultado["janela_atual"]["total_finalizados"], 1)
            self.assertEqual(resultado["janela_atual"]["no_prazo"], 1)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
