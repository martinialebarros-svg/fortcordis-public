import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "atendimento-timeline-limitada-test-secret-key-1234567890")

from app.api.v1.endpoints import atendimento
from app.models.atendimento_clinico import AnexoAtendimento, AtendimentoClinico, EvolucaoClinica
from app.models.laudo import Exame, Laudo
from app.models.paciente import Paciente


class AtendimentoTimelineLimitadaTest(unittest.TestCase):
    """Achado #23 da auditoria: _montar_timeline_paciente fazia uma segunda
    query INDEPENDENTE e sem limite em AtendimentoClinico (ignorando a lista
    ja buscada e limitada pelo endpoint de historico), e Exame/Laudo eram
    buscados sem limite algum - um paciente cronico com anos de
    acompanhamento fazia o endpoint escanear TODO o historico a cada
    chamada."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmpdir.name) / "atendimento-timeline-limitada.db"
        self.engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
        for table in (
            AtendimentoClinico.__table__,
            EvolucaoClinica.__table__,
            AnexoAtendimento.__table__,
            Exame.__table__,
            Laudo.__table__,
            Paciente.__table__,
        ):
            table.create(self.engine, checkfirst=True)
        self.db = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)()

        self.paciente = Paciente(nome="Rex", especie="Canina", ativo=1)
        self.db.add(self.paciente)
        self.db.flush()

        base = datetime(2020, 1, 1, 9, 0)
        self.atendimentos = []
        for i in range(30):
            item = AtendimentoClinico(
                paciente_id=self.paciente.id,
                veterinario_id=1,
                especie="Canina",
                data_atendimento=base + timedelta(days=i * 30),
                status="Concluido",
            )
            self.db.add(item)
            self.atendimentos.append(item)
        self.db.flush()

        for i, atendimento_item in enumerate(self.atendimentos):
            self.db.add(
                Exame(
                    atendimento_id=atendimento_item.id,
                    paciente_id=self.paciente.id,
                    tipo_exame=f"Exame {i}",
                    status="Concluido",
                    data_solicitacao=atendimento_item.data_atendimento,
                )
            )
            self.db.add(
                Laudo(
                    paciente_id=self.paciente.id,
                    veterinario_id=1,
                    tipo="ecocardiograma",
                    titulo=f"Laudo {i}",
                    status="Finalizado",
                    data_laudo=atendimento_item.data_atendimento,
                )
            )
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()
        self.tmpdir.cleanup()

    def _capturar_sql(self):
        statements = []

        def _capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            statements.append(statement.lower())

        event.listen(self.engine, "before_cursor_execute", _capture)
        return statements, lambda: event.remove(self.engine, "before_cursor_execute", _capture)

    def test_reaproveita_lista_de_atendimentos_ja_buscada_sem_reconsultar(self) -> None:
        atendimentos_ja_buscados = (
            self.db.query(AtendimentoClinico)
            .filter(AtendimentoClinico.paciente_id == self.paciente.id)
            .order_by(AtendimentoClinico.data_atendimento.desc())
            .limit(12)
            .all()
        )

        statements, parar_captura = self._capturar_sql()
        try:
            resultado = atendimento._montar_timeline_paciente(
                self.db,
                self.paciente.id,
                limite=12,
                atendimentos_paciente=atendimentos_ja_buscados,
            )
        finally:
            parar_captura()

        selects_atendimentos_clinicos = [
            sql for sql in statements if "select" in sql and "atendimentos_clinicos" in sql
        ]
        self.assertEqual(
            len(selects_atendimentos_clinicos),
            0,
            msg="nao deveria reconsultar atendimentos_clinicos quando a lista ja foi passada",
        )
        self.assertGreater(len(resultado), 0)

    def test_exames_e_laudos_sao_limitados_mesmo_com_centenas_no_historico(self) -> None:
        statements, parar_captura = self._capturar_sql()
        try:
            resultado = atendimento._montar_timeline_paciente(self.db, self.paciente.id, limite=5)
        finally:
            parar_captura()

        # Conta quantos EVENTOS de exame_solicitado/laudo aparecem na timeline
        # resultante - com 30 exames e 30 laudos no banco mas limite=5, o
        # numero de eventos dessas categorias tem que ficar proximo do limite,
        # nao dos 30 totais.
        eventos = [evento for ano in resultado for evento in ano["eventos"]]
        eventos_exame = [e for e in eventos if e["tipo"] == "exame_solicitado"]
        eventos_laudo = [e for e in eventos if e["tipo"] == "laudo"]

        self.assertLessEqual(len(eventos_exame), 5)
        self.assertLessEqual(len(eventos_laudo), 5)
        self.assertGreater(len(eventos_exame), 0)
        self.assertGreater(len(eventos_laudo), 0)

    def test_sem_atendimentos_paciente_faz_a_propria_query_limitada(self) -> None:
        """Caminho do endpoint /timeline isolado, que nao tem uma lista
        pre-buscada para reaproveitar - deve continuar funcionando, so que
        com limite proprio em vez de ilimitado."""
        resultado = atendimento._montar_timeline_paciente(self.db, self.paciente.id, limite=3)
        eventos = [evento for ano in resultado for evento in ano["eventos"]]
        eventos_atendimento = [e for e in eventos if e["tipo"] == "atendimento"]
        self.assertLessEqual(len(eventos_atendimento), 3)

    def test_anos_e_eventos_em_ordem_decrescente(self) -> None:
        """Achado #48 da auditoria: a timeline vinha em ordem cronologica
        crescente (mais antigo primeiro), tanto para os anos quanto para os
        eventos dentro de cada ano - o evento mais recente ficava no fim,
        exigindo rolagem. Agora deve vir do mais recente para o mais antigo
        em ambos os niveis."""
        resultado = atendimento._montar_timeline_paciente(self.db, self.paciente.id, limite=30)

        anos = [grupo["ano"] for grupo in resultado]
        self.assertEqual(anos, sorted(anos, reverse=True), msg="anos deveriam vir do mais recente para o mais antigo")

        for grupo in resultado:
            datas = [evento["data"] for evento in grupo["eventos"] if evento.get("data")]
            self.assertEqual(
                datas,
                sorted(datas, reverse=True),
                msg=f"eventos do ano {grupo['ano']} deveriam vir do mais recente para o mais antigo",
            )


if __name__ == "__main__":
    unittest.main()
