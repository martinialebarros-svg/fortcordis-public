import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "agenda-janela-operacional-test-secret-key-1234567890")

from app.api.v1.endpoints import agenda
from app.models.agendamento import Agendamento
from app.models.clinica import Clinica
from app.models.configuracao import Configuracao
from app.models.servico import Servico
from app.models.tutor import Tutor
from app.models.google_maps_cost_control import COST_TABLES
from app.services import google_maps_cost_control as cost_guard


def _agenda_semanal_aberta() -> dict[str, dict[str, object]]:
    return {
        str(dia): {"ativo": True, "inicio": "08:00", "fim": "18:00"}
        for dia in range(1, 8)
    }


class AgendaSugestaoJanelaOperacionalTest(unittest.TestCase):
    def setUp(self):
        # Testes de vizinhanca/grade usam rota residencial deterministica.
        # Assim a primeira saida continua exigida sem depender da rede.
        patcher = patch.object(
            agenda, "estimar_deslocamento",
            return_value=(2.0, 5, "google_distance_matrix_traffic"),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _build_session(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "agenda-sugestao-janela-operacional.db"
        engine = create_engine(f"sqlite:///{db_path}")
        for table in (
            Configuracao.__table__,
            Clinica.__table__,
            Servico.__table__,
            Tutor.__table__,
            Agendamento.__table__,
            *COST_TABLES,
        ):
            table.create(engine, checkfirst=True)
        # Shared route-rule fixtures use deterministic providers. Policy reads
        # still need an isolated, unconfigured ledger on an independent connection.
        policy = patch.object(cost_guard.database, "engine", engine)
        policy.start()
        self.addCleanup(policy.stop)
        session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
        return tmpdir, session, engine

    def _seed_config(self, db, *, excecoes: list[dict], regras_rota: dict | None = None):
        # A primeira saida precisa de uma base georreferenciada tambem nos
        # cenarios legados que exercitam sugestoes sem atendimento anterior.
        regras_com_base = {
            "base": {
                "label": "Base sintetica de teste",
                "address": "Endereco sintetico, Fortaleza - CE",
                "zip_code": "60000-000",
                "lat": -3.7319,
                "lng": -38.5267,
            },
            **(regras_rota or {}),
        }
        config = Configuracao(
            agenda_semanal=json.dumps(_agenda_semanal_aberta()),
            agenda_feriados=json.dumps([]),
            agenda_excecoes=json.dumps(excecoes),
            agenda_rota_regras=json.dumps(regras_com_base),
        )
        db.add(config)
        db.commit()

    def _seed_clinicas(
        self,
        db,
        *,
        clinica_base_coords: tuple[float | None, float | None] = (-3.7319, -38.5267),
        clinica_ancora_coords: tuple[float | None, float | None] = (-3.7342, -38.5434),
        clinica_base_cidade: str = "Fortaleza",
        clinica_base_estado: str = "CE",
        clinica_ancora_cidade: str = "Fortaleza",
        clinica_ancora_estado: str = "CE",
    ) -> tuple[Clinica, Clinica]:
        clinica_base = Clinica(
            nome="Pet Xodo",
            ativo=True,
            latitude=clinica_base_coords[0],
            longitude=clinica_base_coords[1],
            cidade=clinica_base_cidade,
            estado=clinica_base_estado,
        )
        clinica_ancora = Clinica(
            nome="Pet Sanus Caucaia",
            ativo=True,
            latitude=clinica_ancora_coords[0],
            longitude=clinica_ancora_coords[1],
            cidade=clinica_ancora_cidade,
            estado=clinica_ancora_estado,
        )
        db.add_all([clinica_base, clinica_ancora])
        db.commit()
        db.refresh(clinica_base)
        db.refresh(clinica_ancora)
        return clinica_base, clinica_ancora

    def _criar_agendamento(
        self,
        db,
        *,
        clinica_id: int | None,
        data: str,
        hora: str,
        status: str = "Agendado",
        duracao_minutos: int = 30,
        tutor_id: int | None = None,
        origem_atendimento: str = "clinica_parceira",
        clinica_nome: str = "Clinica teste",
    ) -> Agendamento:
        inicio = datetime.fromisoformat(f"{data}T{hora}:00")
        agendamento = Agendamento(
            clinica_id=clinica_id,
            tutor_id=tutor_id,
            origem_atendimento=origem_atendimento,
            inicio=inicio,
            fim=inicio + timedelta(minutes=duracao_minutos),
            data=data,
            hora=hora,
            status=status,
            clinica=clinica_nome,
        )
        db.add(agendamento)
        db.commit()
        db.refresh(agendamento)
        return agendamento

    def _seed_servico(self, db, *, nome: str, duracao_minutos: int) -> Servico:
        servico = Servico(
            nome=nome,
            duracao_minutos=duracao_minutos,
            ativo=True,
        )
        db.add(servico)
        db.commit()
        db.refresh(servico)
        return servico

    def _seed_tutor(
        self,
        db,
        *,
        nome: str = "Tutor domiciliar",
        latitude: float = -3.7305,
        longitude: float = -38.5216,
    ) -> Tutor:
        tutor = Tutor(
            nome=nome,
            telefone="85999990000",
            endereco="Rua das Flores",
            numero="123",
            bairro="Centro",
            cidade="Fortaleza",
            estado="CE",
            cep="60000000",
            latitude=latitude,
            longitude=longitude,
            ativo=1,
        )
        db.add(tutor)
        db.commit()
        db.refresh(tutor)
        return tutor

    def test_ancora_d2_nao_considera_dia_fechado(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            self._seed_config(
                db,
                excecoes=[
                    {"data": "2099-05-21", "ativo": False, "inicio": "08:00", "fim": "18:00", "motivo": "Fechado"},
                ],
            )
            clinica_base, clinica_ancora = self._seed_clinicas(db)
            self._criar_agendamento(db, clinica_id=clinica_ancora.id, data="2099-05-21", hora="10:00")

            with patch.object(agenda, "_obter_duracao_deslocamento_cacheado", return_value=(10, "mock")) as mocked:
                possui_ancora = agenda._existe_ancora_proxima_no_dia(
                    db,
                    clinica_id=clinica_base.id,
                    data_iso="2099-05-21",
                    limite_minutos=20,
                    perfil_deslocamento="comercial",
                )

            self.assertFalse(possui_ancora)
            mocked.assert_not_called()
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_sugestao_proximidade_ignora_agendamento_fora_janela(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            self._seed_config(
                db,
                excecoes=[
                    # Janela especial curta para o dia 21: qualquer ancora fora deste intervalo deve ser ignorada.
                    {"data": "2099-05-21", "ativo": True, "inicio": "08:00", "fim": "12:00", "motivo": "Janela reduzida"},
                ],
            )
            clinica_base, clinica_ancora = self._seed_clinicas(db)
            self._criar_agendamento(db, clinica_id=clinica_ancora.id, data="2099-05-21", hora="15:00")
            self._criar_agendamento(db, clinica_id=clinica_ancora.id, data="2099-05-22", hora="09:30")

            payload = agenda.SugestaoProximidadePayload(
                clinica_id=clinica_base.id,
                data="2099-05-21",
                data_contato="2099-05-19",
                perfil_deslocamento="comercial",
                limite_minutos=25,
                janela_dias_proximidade=3,
                incluir_mesma_clinica=False,
            )

            with patch.object(agenda, "_obter_duracao_deslocamento_cacheado", return_value=(12, "mock")):
                resposta = agenda.sugerir_agendamento_proximo(
                    payload=payload,
                    db=db,
                    current_user=SimpleNamespace(id=1),
                )

            self.assertTrue(resposta["ok"])
            self.assertTrue(resposta["sugerir"])
            self.assertEqual(resposta["item"]["data"], "2099-05-22")
            self.assertEqual(int(resposta.get("itens_ignorados_janela", 0)), 1)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_sugestoes_horario_ignoram_slots_passados_no_dia_atual(self) -> None:
        class DateTimeFixa(datetime):
            @classmethod
            def now(cls, tz=None):
                if tz is not None:
                    return cls(2099, 5, 19, 14, 20, 0, tzinfo=tz)
                return cls(2099, 5, 19, 14, 20, 0)

        tmpdir, db, engine = self._build_session()
        try:
            self._seed_config(db, excecoes=[])
            clinica_base, _ = self._seed_clinicas(db)

            payload = agenda.SugestaoHorarioPayload(
                data="2099-05-19",
                clinica_id=clinica_base.id,
                duracao_minutos=30,
                intervalo_minutos=30,
                limite=8,
                perfil_deslocamento="comercial",
            )

            with patch.object(agenda, "datetime", DateTimeFixa):
                resposta = agenda.sugerir_horarios_agenda(
                    payload=payload,
                    db=db,
                    current_user=SimpleNamespace(id=1),
                )

            self.assertTrue(resposta["ok"])
            self.assertGreater(len(resposta["items"]), 0)
            primeiro_inicio = str(resposta["items"][0]["inicio"])
            self.assertGreaterEqual(primeiro_inicio, "2099-05-19 14:30")
            for item in resposta["items"]:
                inicio = datetime.strptime(item["inicio"], "%Y-%m-%d %H:%M")
                self.assertGreaterEqual(inicio, datetime(2099, 5, 19, 14, 30))
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_sugestoes_horario_usam_duracao_do_servico_mesmo_com_payload_maior(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            self._seed_config(db, excecoes=[])
            clinica_base, _clinica_ancora = self._seed_clinicas(db)
            servico = self._seed_servico(db, nome="Eletrocardiograma", duracao_minutos=20)

            payload = agenda.SugestaoHorarioPayload(
                data="2099-05-25",
                clinica_id=clinica_base.id,
                servico_id=servico.id,
                duracao_minutos=60,
                intervalo_minutos=30,
                limite=4,
                perfil_deslocamento="comercial",
            )

            resposta = agenda.sugerir_horarios_agenda(
                payload=payload,
                db=db,
                current_user=SimpleNamespace(id=1),
            )

            self.assertTrue(resposta["ok"])
            self.assertGreater(len(resposta["items"]), 0)
            self.assertEqual(int(resposta.get("duracao_minutos", 0)), 20)

            primeiro = resposta["items"][0]
            inicio = datetime.strptime(str(primeiro["inicio"]), "%Y-%m-%d %H:%M")
            fim = datetime.strptime(str(primeiro["fim"]), "%Y-%m-%d %H:%M")
            self.assertEqual(int((fim - inicio).total_seconds() // 60), 20)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_sugestoes_horario_nao_ofertam_slot_ocupado_mesmo_com_drift_em_inicio(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            self._seed_config(db, excecoes=[])
            clinica_base, _ = self._seed_clinicas(db)

            # Simula legado/drift: coluna "data" no dia correto, mas "inicio" gravado em outro dia.
            agendamento = Agendamento(
                clinica_id=clinica_base.id,
                inicio=datetime.fromisoformat("2099-05-27T00:30:00"),
                fim=datetime.fromisoformat("2099-05-27T00:50:00"),
                data="2099-05-26",
                hora="14:30",
                status="Agendado",
                clinica=clinica_base.nome,
            )
            db.add(agendamento)
            db.commit()

            payload = agenda.SugestaoHorarioPayload(
                data="2099-05-26",
                clinica_id=clinica_base.id,
                duracao_minutos=20,
                intervalo_minutos=10,
                limite=50,
                perfil_deslocamento="comercial",
            )

            resposta = agenda.sugerir_horarios_agenda(
                payload=payload,
                db=db,
                current_user=SimpleNamespace(id=1),
            )

            self.assertTrue(resposta["ok"])
            inicios = {str(item.get("inicio") or "") for item in resposta.get("items", [])}
            self.assertNotIn("2099-05-26 14:30", inicios)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_sugestoes_horario_nao_ignoram_ocupacao_quando_data_legada_esta_em_formato_invalido(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            self._seed_config(db, excecoes=[])
            clinica_base, _ = self._seed_clinicas(db)

            # Simula legado: coluna "data" preenchida fora do padrao ISO.
            # A deteccao de conflito deve continuar bloqueando o slot ocupado.
            agendamento = Agendamento(
                clinica_id=clinica_base.id,
                inicio=datetime.fromisoformat("2099-05-26T14:30:00"),
                fim=datetime.fromisoformat("2099-05-26T14:50:00"),
                data="26/05/2099",
                hora="14:30",
                status="Agendado",
                clinica=clinica_base.nome,
            )
            db.add(agendamento)
            db.commit()

            payload = agenda.SugestaoHorarioPayload(
                data="2099-05-26",
                clinica_id=clinica_base.id,
                duracao_minutos=20,
                intervalo_minutos=10,
                limite=50,
                perfil_deslocamento="comercial",
            )

            resposta = agenda.sugerir_horarios_agenda(
                payload=payload,
                db=db,
                current_user=SimpleNamespace(id=1),
            )

            self.assertTrue(resposta["ok"])
            inicios = {str(item.get("inicio") or "") for item in resposta.get("items", [])}
            self.assertNotIn("2099-05-26 14:30", inicios)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_sugestoes_horario_validam_proximo_fora_da_janela_para_evitar_conflito_operacional(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            self._seed_config(
                db,
                excecoes=[
                    {"data": "2099-05-26", "ativo": True, "inicio": "08:00", "fim": "13:30", "motivo": "Janela curta"},
                ],
            )
            clinica_base, clinica_proxima = self._seed_clinicas(db)

            # Agendamento real fora da janela ativa do dia; ainda assim deve entrar no calculo
            # de deslocamento do "proximo" para nao ofertar slot inviavel antes dele.
            self._criar_agendamento(
                db,
                clinica_id=clinica_proxima.id,
                data="2099-05-26",
                hora="14:00",
                status="Agendado",
            )

            payload = agenda.SugestaoHorarioPayload(
                data="2099-05-26",
                clinica_id=clinica_base.id,
                duracao_minutos=20,
                intervalo_minutos=30,
                limite=50,
                perfil_deslocamento="comercial",
            )

            def _mock_deslocamento(
                db,
                *,
                origem_clinica_id,
                destino_clinica_id,
                perfil,
                permitir_estimativa_fallback=True,
                cache=None,
                commit_cache=True,
            ):
                self.assertTrue(commit_cache, "Consultas de leitura preservam cache persistente")
                if (
                    int(origem_clinica_id or 0) == int(clinica_base.id)
                    and int(destino_clinica_id or 0) == int(clinica_proxima.id)
                ):
                    return (45, "mock_next")
                return (0, "mock")

            with patch.object(agenda, "_obter_duracao_deslocamento_cacheado", side_effect=_mock_deslocamento):
                resposta = agenda.sugerir_horarios_agenda(
                    payload=payload,
                    db=db,
                    current_user=SimpleNamespace(id=1),
                )

            self.assertTrue(resposta["ok"])
            inicios = {str(item.get("inicio") or "") for item in resposta.get("items", [])}
            self.assertNotIn("2099-05-26 13:00", inicios)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_sugestoes_horario_exigem_margem_segura_entre_vizinhos(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            self._seed_config(db, excecoes=[])
            clinica_destino, clinica_anterior = self._seed_clinicas(db)
            inicio_anterior = datetime.fromisoformat("2099-05-25T08:30:00")
            db.add(
                Agendamento(
                    clinica_id=clinica_anterior.id,
                    inicio=inicio_anterior,
                    fim=inicio_anterior + timedelta(minutes=20),
                    data="2099-05-25",
                    hora="08:30",
                    status="Agendado",
                    clinica=clinica_anterior.nome,
                )
            )
            db.commit()

            payload = agenda.SugestaoHorarioPayload(
                data="2099-05-25",
                clinica_id=clinica_destino.id,
                duracao_minutos=30,
                intervalo_minutos=30,
                limite=50,
                perfil_deslocamento="comercial",
            )

            def _mock_deslocamento(
                db,
                *,
                origem_clinica_id,
                destino_clinica_id,
                perfil,
                permitir_estimativa_fallback=True,
                cache=None,
                commit_cache=True,
            ):
                self.assertTrue(commit_cache, "Consultas de leitura preservam cache persistente")
                ids = {int(origem_clinica_id or 0), int(destino_clinica_id or 0)}
                if ids == {int(clinica_destino.id), int(clinica_anterior.id)}:
                    return (39, "mock")
                return (0, "mesma_clinica")

            with patch.object(agenda, "_obter_duracao_deslocamento_cacheado", side_effect=_mock_deslocamento):
                resposta = agenda.sugerir_horarios_agenda(
                    payload=payload,
                    db=db,
                    current_user=SimpleNamespace(id=1),
                )

            self.assertTrue(resposta["ok"])
            inicios = {str(item.get("inicio") or "") for item in resposta.get("items", [])}
            self.assertNotIn("2099-05-25 09:30", inicios)
            self.assertIn("2099-05-25 10:00", inicios)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_validacao_agendamento_exige_margem_segura_de_deslocamento(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            self._seed_config(db, excecoes=[])
            clinica_destino, clinica_anterior = self._seed_clinicas(
                db,
                clinica_base_coords=(-3.7278, -38.4772),
                clinica_ancora_coords=(-3.7756, -38.6055),
            )
            inicio_anterior = datetime.fromisoformat("2099-05-25T08:30:00")
            db.add(
                Agendamento(
                    clinica_id=clinica_anterior.id,
                    inicio=inicio_anterior,
                    fim=inicio_anterior + timedelta(minutes=20),
                    data="2099-05-25",
                    hora="08:30",
                    status="Agendado",
                    clinica=clinica_anterior.nome,
                )
            )
            db.commit()

            inicio_novo = datetime.fromisoformat("2099-05-25T09:30:00")
            novo = Agendamento(
                clinica_id=clinica_destino.id,
                inicio=inicio_novo,
                fim=inicio_novo + timedelta(minutes=30),
                data="2099-05-25",
                hora="09:30",
                status="Agendado",
                clinica=clinica_destino.nome,
            )

            with patch.object(agenda, "_obter_duracao_deslocamento_cacheado", return_value=(39, "mock")):
                with self.assertRaises(HTTPException) as ctx:
                    agenda._validar_deslocamento_agendamento(db, novo)

            self.assertEqual(ctx.exception.status_code, 409)
            detail = ctx.exception.detail
            self.assertEqual(detail.get("codigo"), "CONFLITO_DESLOCAMENTO")
            self.assertEqual(int(detail.get("duracao_min")), 39)
            self.assertEqual(int(detail.get("folga_min")), 40)
            self.assertEqual(int(detail.get("margem_segura_min")), 5)
            self.assertEqual(int(detail.get("folga_necessaria_min")), 44)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_sugestoes_horario_priorizam_limite_exato_com_transicao(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            self._seed_config(db, excecoes=[])
            clinica_base, _ = self._seed_clinicas(db)
            self._criar_agendamento(
                db,
                clinica_id=clinica_base.id,
                data="2099-05-25",
                hora="09:00",
                status="Agendado",
                duracao_minutos=20,
            )

            payload = agenda.SugestaoHorarioPayload(
                data="2099-05-25",
                clinica_id=clinica_base.id,
                duracao_minutos=20,
                intervalo_minutos=30,
                limite=50,
                perfil_deslocamento="comercial",
            )

            with patch.object(agenda, "_obter_duracao_deslocamento_cacheado", return_value=(0, "mesma_clinica")):
                resposta = agenda.sugerir_horarios_agenda(
                    payload=payload,
                    db=db,
                    current_user=SimpleNamespace(id=1),
                )

            self.assertTrue(resposta["ok"])
            self.assertGreater(len(resposta["items"]), 0)
            primeiro = resposta["items"][0]
            self.assertEqual(str(primeiro.get("inicio") or ""), "2099-05-25 08:35")
            self.assertEqual(int(primeiro.get("preferencia_ancora_ordem", 99)), 0)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_sugestoes_horario_marcam_apenas_slots_adjacentes_da_ancora(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            self._seed_config(db, excecoes=[])
            clinica_base, _ = self._seed_clinicas(db)
            self._criar_agendamento(
                db,
                clinica_id=clinica_base.id,
                data="2099-05-25",
                hora="10:00",
                status="Agendado",
                duracao_minutos=20,
            )

            payload = agenda.SugestaoHorarioPayload(
                data="2099-05-25",
                clinica_id=clinica_base.id,
                duracao_minutos=20,
                intervalo_minutos=30,
                limite=50,
                perfil_deslocamento="comercial",
            )

            with patch.object(agenda, "_obter_duracao_deslocamento_cacheado", return_value=(0, "mesma_clinica")):
                resposta = agenda.sugerir_horarios_agenda(
                    payload=payload,
                    db=db,
                    current_user=SimpleNamespace(id=1),
                )

            self.assertTrue(resposta["ok"])
            self.assertTrue(bool(resposta.get("tem_ancora_mesma_clinica_no_dia")))
            itens = resposta["items"]
            self.assertGreaterEqual(len(itens), 3)
            itens_adjacentes = {
                str(item.get("inicio") or ""): str(item.get("adjacencia_tipo") or "")
                for item in itens
                if bool(item.get("adjacente_ancora"))
            }
            self.assertEqual(itens_adjacentes.get("2099-05-25 09:35"), "antes_ancora")
            self.assertEqual(itens_adjacentes.get("2099-05-25 10:25"), "apos_ancora")
            self.assertFalse(bool(next(item for item in itens if item["inicio"] == "2099-05-25 11:00")["adjacente_ancora"]))
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_validacao_agendamento_bloqueia_trecho_vizinho_acima_do_limite_mesmo_com_folga(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            self._seed_config(
                db,
                excecoes=[],
                regras_rota={
                    "thresholds": {
                        "max_neighbor_travel_min": 45,
                        "safe_margin_min": 5,
                    }
                },
            )
            clinica_destino, clinica_anterior = self._seed_clinicas(
                db,
                clinica_base_coords=(-3.7278, -38.4772),
                clinica_ancora_coords=(-3.7756, -38.6055),
            )
            inicio_anterior = datetime.fromisoformat("2099-05-25T08:30:00")
            db.add(
                Agendamento(
                    clinica_id=clinica_anterior.id,
                    inicio=inicio_anterior,
                    fim=inicio_anterior + timedelta(minutes=20),
                    data="2099-05-25",
                    hora="08:30",
                    status="Agendado",
                    clinica=clinica_anterior.nome,
                )
            )
            db.commit()

            inicio_novo = datetime.fromisoformat("2099-05-25T10:30:00")
            novo = Agendamento(
                clinica_id=clinica_destino.id,
                inicio=inicio_novo,
                fim=inicio_novo + timedelta(minutes=30),
                data="2099-05-25",
                hora="10:30",
                status="Agendado",
                clinica=clinica_destino.nome,
            )

            with patch.object(agenda, "_obter_duracao_deslocamento_cacheado", return_value=(62, "mock")):
                with self.assertRaises(HTTPException) as ctx:
                    agenda._validar_deslocamento_agendamento(db, novo)

            self.assertEqual(ctx.exception.status_code, 409)
            detail = ctx.exception.detail
            self.assertEqual(detail.get("codigo"), "CONFLITO_DESLOCAMENTO")
            self.assertEqual(int(detail.get("duracao_min")), 62)
            self.assertEqual(int(detail.get("limite_trecho_vizinho_min")), 45)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_sugestoes_horario_bloqueiam_trecho_vizinho_acima_do_limite(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            self._seed_config(
                db,
                excecoes=[],
                regras_rota={
                    "thresholds": {
                        "max_neighbor_travel_min": 45,
                        "safe_margin_min": 5,
                    }
                },
            )
            clinica_destino, clinica_ancora = self._seed_clinicas(
                db,
                clinica_base_coords=(-3.7278, -38.4772),
                clinica_ancora_coords=(-3.7756, -38.6055),
            )
            self._criar_agendamento(
                db,
                clinica_id=clinica_ancora.id,
                data="2099-05-25",
                hora="09:00",
                status="Agendado",
                duracao_minutos=20,
            )

            payload = agenda.SugestaoHorarioPayload(
                data="2099-05-25",
                clinica_id=clinica_destino.id,
                duracao_minutos=20,
                intervalo_minutos=30,
                limite=8,
                perfil_deslocamento="comercial",
            )

            with patch.object(agenda, "_obter_duracao_deslocamento_cacheado", return_value=(62, "mock")):
                resposta = agenda.sugerir_horarios_agenda(
                    payload=payload,
                    db=db,
                    current_user=SimpleNamespace(id=1),
                )

            self.assertTrue(resposta["ok"])
            self.assertEqual(resposta["items"], [])
            regras_aplicadas = resposta.get("regras_aplicadas") or {}
            self.assertEqual(int(regras_aplicadas.get("max_neighbor_travel_min") or 0), 45)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_sugestao_permite_encaixe_adjacente_a_ancora_registrada(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            self._seed_config(
                db,
                excecoes=[],
                regras_rota={
                    "thresholds": {
                        "max_neighbor_travel_min": 30,
                        "nearby_anchor_max_travel_min": 20,
                        "safe_margin_min": 5,
                    }
                },
            )
            clinica_destino, _ = self._seed_clinicas(db, clinica_base_coords=(-3.8904, -38.4392))
            clinica_anterior = Clinica(
                nome="PATAS E ASAS",
                ativo=True,
                latitude=-3.733,
                longitude=-38.524,
                cidade="Fortaleza",
                estado="CE",
            )
            db.add(clinica_anterior)
            db.commit()
            db.refresh(clinica_anterior)
            tutor = self._seed_tutor(db, latitude=-3.8973, longitude=-38.4417)
            self._criar_agendamento(
                db,
                clinica_id=clinica_anterior.id,
                data="2099-05-25",
                hora="09:00",
                status="Agendado",
                duracao_minutos=25,
                clinica_nome=clinica_anterior.nome,
            )
            agendamento_domiciliar = self._criar_agendamento(
                db,
                clinica_id=None,
                tutor_id=tutor.id,
                origem_atendimento="domiciliar",
                data="2099-05-25",
                hora="14:00",
                status="Confirmado",
                duracao_minutos=30,
                clinica_nome="Atendimento domiciliar",
            )

            def _mock_deslocamento(db, *, origem, destino, perfil, **kwargs):
                origem_chave = (str((origem or {}).get("tipo") or ""), int((origem or {}).get("entity_id") or 0))
                destino_chave = (str((destino or {}).get("tipo") or ""), int((destino or {}).get("entity_id") or 0))
                if origem_chave == ("clinica_parceira", clinica_anterior.id) and destino_chave == (
                    "clinica_parceira",
                    clinica_destino.id,
                ):
                    return (38, "mock_prev")
                if origem_chave == ("clinica_parceira", clinica_destino.id) and destino_chave == (
                    "clinica_parceira",
                    clinica_anterior.id,
                ):
                    return (36, "mock_next_far")
                if origem_chave == ("clinica_parceira", clinica_destino.id) and destino_chave == (
                    "domiciliar",
                    tutor.id,
                ):
                    return (5, "mock_next")
                if origem_chave == ("domiciliar", tutor.id) and destino_chave == (
                    "clinica_parceira",
                    clinica_destino.id,
                ):
                    return (5, "mock_prev_anchor")
                if origem_chave == ("clinica_parceira", clinica_anterior.id) and destino_chave == (
                    "domiciliar",
                    tutor.id,
                ):
                    return (36, "mock_direct")
                return (0, "mock")

            payload = agenda.SugestaoHorarioPayload(
                data="2099-05-25",
                clinica_id=clinica_destino.id,
                duracao_minutos=25,
                intervalo_minutos=30,
                limite=50,
                perfil_deslocamento="comercial",
            )

            with patch.object(agenda, "_obter_duracao_deslocamento_operacional", side_effect=_mock_deslocamento):
                resposta = agenda.sugerir_horarios_agenda(
                    payload=payload,
                    db=db,
                    current_user=SimpleNamespace(id=1),
                )

            self.assertTrue(resposta["ok"])
            self.assertGreater(len(resposta["items"]), 0)
            primeiro = resposta["items"][0]
            self.assertEqual(str(primeiro.get("inicio") or ""), "2099-05-25 13:30")
            self.assertEqual(int(primeiro.get("tempo_deslocamento_total_min") or 0), 5)
            self.assertEqual(int((primeiro.get("proximo") or {}).get("agendamento_id") or 0), agendamento_domiciliar.id)
            self.assertTrue(bool((primeiro.get("anterior") or {}).get("trecho_desconsiderado_ancora_adjacente")))
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_validacao_permite_encaixe_adjacente_a_ancora_registrada(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            self._seed_config(
                db,
                excecoes=[],
                regras_rota={
                    "thresholds": {
                        "max_neighbor_travel_min": 30,
                        "nearby_anchor_max_travel_min": 20,
                        "safe_margin_min": 5,
                    }
                },
            )
            clinica_destino, _ = self._seed_clinicas(db, clinica_base_coords=(-3.8904, -38.4392))
            clinica_anterior = Clinica(
                nome="PATAS E ASAS",
                ativo=True,
                latitude=-3.733,
                longitude=-38.524,
                cidade="Fortaleza",
                estado="CE",
            )
            db.add(clinica_anterior)
            db.commit()
            db.refresh(clinica_anterior)
            tutor = self._seed_tutor(db, latitude=-3.8973, longitude=-38.4417)
            self._criar_agendamento(
                db,
                clinica_id=clinica_anterior.id,
                data="2099-05-25",
                hora="09:00",
                status="Agendado",
                duracao_minutos=25,
                clinica_nome=clinica_anterior.nome,
            )
            self._criar_agendamento(
                db,
                clinica_id=None,
                tutor_id=tutor.id,
                origem_atendimento="domiciliar",
                data="2099-05-25",
                hora="14:00",
                status="Confirmado",
                duracao_minutos=30,
                clinica_nome="Atendimento domiciliar",
            )
            inicio_novo = datetime.fromisoformat("2099-05-25T13:30:00")
            novo = Agendamento(
                clinica_id=clinica_destino.id,
                inicio=inicio_novo,
                fim=inicio_novo + timedelta(minutes=25),
                data="2099-05-25",
                hora="13:30",
                status="Agendado",
                clinica=clinica_destino.nome,
            )

            def _mock_deslocamento(db, *, origem, destino, perfil, **kwargs):
                origem_chave = (str((origem or {}).get("tipo") or ""), int((origem or {}).get("entity_id") or 0))
                destino_chave = (str((destino or {}).get("tipo") or ""), int((destino or {}).get("entity_id") or 0))
                if origem_chave == ("clinica_parceira", clinica_anterior.id) and destino_chave == (
                    "clinica_parceira",
                    clinica_destino.id,
                ):
                    return (38, "mock_prev")
                if origem_chave == ("clinica_parceira", clinica_destino.id) and destino_chave == (
                    "clinica_parceira",
                    clinica_anterior.id,
                ):
                    return (36, "mock_next_far")
                if origem_chave == ("clinica_parceira", clinica_destino.id) and destino_chave == (
                    "domiciliar",
                    tutor.id,
                ):
                    return (5, "mock_next")
                if origem_chave == ("domiciliar", tutor.id) and destino_chave == (
                    "clinica_parceira",
                    clinica_destino.id,
                ):
                    return (5, "mock_prev_anchor")
                if origem_chave == ("clinica_parceira", clinica_anterior.id) and destino_chave == (
                    "domiciliar",
                    tutor.id,
                ):
                    return (36, "mock_direct")
                return (0, "mock")

            with patch.object(agenda, "_obter_duracao_deslocamento_operacional", side_effect=_mock_deslocamento):
                agenda._validar_deslocamento_agendamento(db, novo)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_proximidade_usa_trecho_aderente_em_encaixe_adjacente(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            self._seed_config(
                db,
                excecoes=[],
                regras_rota={
                    "thresholds": {
                        "max_neighbor_travel_min": 30,
                        "nearby_anchor_max_travel_min": 20,
                        "safe_margin_min": 5,
                    }
                },
            )
            clinica_destino, _ = self._seed_clinicas(db, clinica_base_coords=(-3.8904, -38.4392))
            clinica_anterior = Clinica(
                nome="PATAS E ASAS",
                ativo=True,
                latitude=-3.733,
                longitude=-38.524,
                cidade="Fortaleza",
                estado="CE",
            )
            db.add(clinica_anterior)
            db.commit()
            db.refresh(clinica_anterior)
            tutor = self._seed_tutor(db, latitude=-3.8973, longitude=-38.4417)
            agendamento_domiciliar = self._criar_agendamento(
                db,
                clinica_id=None,
                tutor_id=tutor.id,
                origem_atendimento="domiciliar",
                data="2099-05-25",
                hora="14:00",
                status="Confirmado",
                duracao_minutos=30,
                clinica_nome="Atendimento domiciliar",
            )
            self._criar_agendamento(
                db,
                clinica_id=clinica_anterior.id,
                data="2099-05-25",
                hora="09:00",
                status="Agendado",
                duracao_minutos=25,
                clinica_nome=clinica_anterior.nome,
            )

            def _mock_deslocamento(db, *, origem, destino, perfil, **kwargs):
                origem_chave = (str((origem or {}).get("tipo") or ""), int((origem or {}).get("entity_id") or 0))
                destino_chave = (str((destino or {}).get("tipo") or ""), int((destino or {}).get("entity_id") or 0))
                if origem_chave == ("clinica_parceira", clinica_anterior.id) and destino_chave == (
                    "clinica_parceira",
                    clinica_destino.id,
                ):
                    return (38, "mock_prev")
                if origem_chave == ("clinica_parceira", clinica_destino.id) and destino_chave == (
                    "clinica_parceira",
                    clinica_anterior.id,
                ):
                    return (36, "mock_next_far")
                if origem_chave == ("clinica_parceira", clinica_destino.id) and destino_chave == (
                    "domiciliar",
                    tutor.id,
                ):
                    return (5, "mock_next")
                if origem_chave == ("domiciliar", tutor.id) and destino_chave == (
                    "clinica_parceira",
                    clinica_destino.id,
                ):
                    return (5, "mock_prev_anchor")
                if origem_chave == ("clinica_parceira", clinica_anterior.id) and destino_chave == (
                    "domiciliar",
                    tutor.id,
                ):
                    return (36, "mock_direct")
                return (0, "mock")

            payload = agenda.SugestaoProximidadePayload(
                data="2099-05-25",
                data_contato="2099-05-25",
                clinica_id=clinica_destino.id,
                duracao_minutos=25,
                intervalo_minutos=30,
                limite_sugestoes_operacionais=50,
                perfil_deslocamento="comercial",
                limite_minutos=20,
                janela_dias_proximidade=0,
            )

            with patch.object(agenda, "_obter_duracao_deslocamento_operacional", side_effect=_mock_deslocamento):
                resposta = agenda.sugerir_agendamento_proximo(
                    payload=payload,
                    db=db,
                    current_user=SimpleNamespace(id=1),
                )

            self.assertTrue(resposta["ok"])
            self.assertTrue(resposta["sugerir"])
            item = resposta["item"]
            self.assertEqual(int(item.get("agendamento_id") or 0), agendamento_domiciliar.id)
            self.assertEqual(item.get("inicio"), "13:30")
            self.assertEqual(int(item.get("duracao_deslocamento_min") or 0), 5)
            self.assertTrue(bool(item.get("trecho_anterior_desconsiderado_ancora_adjacente")))
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_sugestoes_horario_bloqueiam_data_passada(self) -> None:
        class DateTimeFixa(datetime):
            @classmethod
            def now(cls, tz=None):
                if tz is not None:
                    return cls(2099, 5, 19, 14, 20, 0, tzinfo=tz)
                return cls(2099, 5, 19, 14, 20, 0)

        tmpdir, db, engine = self._build_session()
        try:
            self._seed_config(db, excecoes=[])
            clinica_base, _ = self._seed_clinicas(db)

            payload = agenda.SugestaoHorarioPayload(
                data="2099-05-18",
                clinica_id=clinica_base.id,
                duracao_minutos=30,
                intervalo_minutos=30,
                limite=8,
                perfil_deslocamento="comercial",
            )

            with patch.object(agenda, "datetime", DateTimeFixa):
                resposta = agenda.sugerir_horarios_agenda(
                    payload=payload,
                    db=db,
                    current_user=SimpleNamespace(id=1),
                )

            self.assertTrue(resposta["ok"])
            self.assertEqual(resposta["total_encontrados"], 0)
            self.assertEqual(resposta["items"], [])
            self.assertIn("datas passadas", str(resposta.get("motivo", "")))
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_sugestao_proximidade_bloqueia_data_passada(self) -> None:
        class DateTimeFixa(datetime):
            @classmethod
            def now(cls, tz=None):
                if tz is not None:
                    return cls(2099, 5, 19, 9, 0, 0, tzinfo=tz)
                return cls(2099, 5, 19, 9, 0, 0)

        tmpdir, db, engine = self._build_session()
        try:
            self._seed_config(db, excecoes=[])
            clinica_base, _ = self._seed_clinicas(db)

            payload = agenda.SugestaoProximidadePayload(
                clinica_id=clinica_base.id,
                data="2099-05-18",
                data_contato="2099-05-17",
                perfil_deslocamento="comercial",
                limite_minutos=25,
                janela_dias_proximidade=3,
                incluir_mesma_clinica=False,
            )

            with patch.object(agenda, "datetime", DateTimeFixa):
                resposta = agenda.sugerir_agendamento_proximo(
                    payload=payload,
                    db=db,
                    current_user=SimpleNamespace(id=1),
                )

            self.assertTrue(resposta["ok"])
            self.assertFalse(resposta["sugerir"])
            self.assertIsNone(resposta["item"])
            self.assertIn("datas passadas", str(resposta.get("mensagem", "")))
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_sugestao_proximidade_distante_sem_ancora_d2_prioriza_dias_politica(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            self._seed_config(
                db,
                excecoes=[],
                regras_rota={
                    "base": {
                        "label": "Casa",
                        "address": "Endereco sintetico, Fortaleza - CE",
                        "zip_code": "60000-000",
                        "lat": -3.7319,
                        "lng": -38.5267,
                    },
                    "thresholds": {
                        "nearby_anchor_max_travel_min": 20,
                        "distant_clinic_min_travel_from_base_min": 35,
                        "low_frequency_max_bookings_30d": 3,
                        "max_insertion_detour_min": 25,
                        "safe_margin_min": 5,
                    },
                    "offer_policy": {
                        "default_first_offer_days_ahead": [2],
                        "distant_low_frequency_first_offer_days_ahead": [3, 4],
                        "allow_d2_if_anchor_exists": True,
                        "emergency_first_offer_days_ahead": [1, 2],
                    },
                    "route_policy": {
                        "end_of_route_window_start": "16:00",
                        "prefer_near_base_at_end_of_route": True,
                        "bonus_near_base_score": 15,
                        "penalty_far_base_score": 10,
                        "reject_clear_inefficiency": True,
                    },
                    "fallback_policy": {
                        "suggest_alternative_slots_when_blocked": True,
                        "max_alternative_suggestions": 3,
                        "allow_extra_slot_start_or_end_route_for_emergency": True,
                    },
                    "clinic_overrides": [],
                },
            )
            clinica_base, clinica_ancora = self._seed_clinicas(
                db,
                clinica_base_coords=(-3.9320, -38.4700),
                clinica_ancora_coords=(-3.7320, -38.5270),
            )
            self._criar_agendamento(db, clinica_id=clinica_ancora.id, data="2099-05-21", hora="09:00")

            payload = agenda.SugestaoProximidadePayload(
                clinica_id=clinica_base.id,
                data="2099-05-21",
                data_contato="2099-05-19",
                perfil_deslocamento="comercial",
                limite_minutos=25,
                janela_dias_proximidade=3,
                incluir_mesma_clinica=False,
            )

            with patch.object(agenda, "_obter_duracao_deslocamento_cacheado", return_value=(42, "mock")):
                resposta = agenda.sugerir_agendamento_proximo(
                    payload=payload,
                    db=db,
                    current_user=SimpleNamespace(id=1),
                )

            self.assertTrue(resposta["ok"])
            self.assertFalse(resposta["sugerir"])
            self.assertIsNone(resposta.get("item"))
            politica = resposta.get("politica_oferta") or {}
            self.assertTrue(politica.get("distante_base"))
            self.assertTrue(politica.get("baixa_frequencia"))
            self.assertFalse(politica.get("ancora_d2"))
            self.assertEqual(
                politica.get("datas_preferenciais"),
                ["2099-05-22", "2099-05-23"],
            )
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_sugestao_proximidade_sem_base_geo_aplica_regra_conservadora(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            self._seed_config(
                db,
                excecoes=[],
                regras_rota={
                    "base": {
                        "label": "Casa",
                        "address": "Endereco sintetico, Fortaleza - CE",
                        "zip_code": "60000-000",
                        "lat": None,
                        "lng": None,
                    },
                    "thresholds": {
                        "nearby_anchor_max_travel_min": 20,
                        "distant_clinic_min_travel_from_base_min": 35,
                        "low_frequency_max_bookings_30d": 3,
                        "max_insertion_detour_min": 25,
                        "safe_margin_min": 5,
                    },
                    "offer_policy": {
                        "default_first_offer_days_ahead": [2],
                        "distant_low_frequency_first_offer_days_ahead": [3, 4],
                        "allow_d2_if_anchor_exists": True,
                        "emergency_first_offer_days_ahead": [1, 2],
                    },
                    "route_policy": {
                        "end_of_route_window_start": "16:00",
                        "prefer_near_base_at_end_of_route": True,
                        "bonus_near_base_score": 15,
                        "penalty_far_base_score": 10,
                        "reject_clear_inefficiency": True,
                    },
                    "fallback_policy": {
                        "suggest_alternative_slots_when_blocked": True,
                        "max_alternative_suggestions": 3,
                        "allow_extra_slot_start_or_end_route_for_emergency": True,
                    },
                    "clinic_overrides": [],
                },
            )
            clinica_base, clinica_ancora = self._seed_clinicas(
                db,
                clinica_base_cidade="Fortaleza",
                clinica_ancora_cidade="Caucaia",
            )
            self._criar_agendamento(db, clinica_id=clinica_ancora.id, data="2099-05-21", hora="09:00")

            payload = agenda.SugestaoProximidadePayload(
                clinica_id=clinica_base.id,
                data="2099-05-21",
                data_contato="2099-05-19",
                perfil_deslocamento="comercial",
                limite_minutos=25,
                janela_dias_proximidade=3,
                incluir_mesma_clinica=False,
            )

            with patch.object(agenda, "_obter_duracao_deslocamento_cacheado", return_value=(42, "mock")):
                resposta = agenda.sugerir_agendamento_proximo(
                    payload=payload,
                    db=db,
                    current_user=SimpleNamespace(id=1),
                )

            self.assertTrue(resposta["ok"])
            self.assertFalse(resposta["sugerir"])
            politica = resposta.get("politica_oferta") or {}
            self.assertTrue(politica.get("distante_base"))
            self.assertFalse(politica.get("ancora_d2"))
            self.assertEqual(
                politica.get("datas_preferenciais"),
                ["2099-05-22", "2099-05-23"],
            )
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_politica_oferta_prioriza_d0_quando_ha_ancora_em_d0_sem_ancora_d2_d3(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            self._seed_config(
                db,
                excecoes=[],
                regras_rota={
                    "base": {
                        "label": "Casa",
                        "address": "Endereco sintetico, Fortaleza - CE",
                        "zip_code": "60000-000",
                        "lat": -3.7319,
                        "lng": -38.5267,
                    },
                    "thresholds": {
                        "nearby_anchor_max_travel_min": 20,
                        "distant_clinic_min_travel_from_base_min": 35,
                        "low_frequency_max_bookings_30d": 3,
                        "max_insertion_detour_min": 25,
                        "safe_margin_min": 5,
                    },
                    "offer_policy": {
                        "default_first_offer_days_ahead": [2],
                        "distant_low_frequency_first_offer_days_ahead": [3, 4],
                        "allow_d2_if_anchor_exists": True,
                        "emergency_first_offer_days_ahead": [1, 2],
                    },
                    "route_policy": {
                        "end_of_route_window_start": "16:00",
                        "prefer_near_base_at_end_of_route": True,
                        "bonus_near_base_score": 15,
                        "penalty_far_base_score": 10,
                        "reject_clear_inefficiency": True,
                    },
                    "fallback_policy": {
                        "suggest_alternative_slots_when_blocked": True,
                        "max_alternative_suggestions": 3,
                        "allow_extra_slot_start_or_end_route_for_emergency": True,
                    },
                    "clinic_overrides": [],
                },
            )
            clinica_base, clinica_ancora = self._seed_clinicas(
                db,
                clinica_base_coords=(-3.7320, -38.5270),
                clinica_ancora_coords=(-3.7325, -38.5275),
            )
            self._criar_agendamento(db, clinica_id=clinica_ancora.id, data="2099-05-19", hora="09:00")

            regras_rota = agenda._obter_regras_rota_agenda(db)
            with patch.object(agenda, "_obter_duracao_deslocamento_cacheado", return_value=(12, "mock")):
                politica = agenda._classificar_politica_oferta(
                    db,
                    clinica_id=clinica_base.id,
                    data_contato_iso="2099-05-19",
                    perfil_deslocamento="comercial",
                    regras_rota=regras_rota,
                )

            self.assertTrue(politica.get("base_proxima"))
            self.assertTrue(politica.get("ancora_d0"))
            self.assertFalse(politica.get("ancora_d2"))
            self.assertFalse(politica.get("ancora_d3"))
            self.assertTrue(politica.get("prioridade_d0_aplicada"))
            self.assertEqual(politica.get("dias_preferenciais"), [0])
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_politica_oferta_prioriza_d0_quando_d0_vazio_sem_ancora_d2_d3(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            self._seed_config(
                db,
                excecoes=[],
                regras_rota={
                    "base": {
                        "label": "Casa",
                        "address": "Endereco sintetico, Fortaleza - CE",
                        "zip_code": "60000-000",
                        "lat": -3.7319,
                        "lng": -38.5267,
                    },
                    "thresholds": {
                        "nearby_anchor_max_travel_min": 20,
                        "distant_clinic_min_travel_from_base_min": 35,
                        "low_frequency_max_bookings_30d": 3,
                        "max_insertion_detour_min": 25,
                        "safe_margin_min": 5,
                    },
                    "offer_policy": {
                        "default_first_offer_days_ahead": [2],
                        "distant_low_frequency_first_offer_days_ahead": [3, 4],
                        "allow_d2_if_anchor_exists": True,
                        "emergency_first_offer_days_ahead": [1, 2],
                    },
                    "route_policy": {
                        "end_of_route_window_start": "16:00",
                        "prefer_near_base_at_end_of_route": True,
                        "bonus_near_base_score": 15,
                        "penalty_far_base_score": 10,
                        "reject_clear_inefficiency": True,
                    },
                    "fallback_policy": {
                        "suggest_alternative_slots_when_blocked": True,
                        "max_alternative_suggestions": 3,
                        "allow_extra_slot_start_or_end_route_for_emergency": True,
                    },
                    "clinic_overrides": [],
                },
            )
            clinica_base, _ = self._seed_clinicas(
                db,
                clinica_base_coords=(-3.7320, -38.5270),
                clinica_ancora_coords=(-3.8200, -38.6500),
            )

            regras_rota = agenda._obter_regras_rota_agenda(db)
            politica = agenda._classificar_politica_oferta(
                db,
                clinica_id=clinica_base.id,
                data_contato_iso="2099-05-19",
                perfil_deslocamento="comercial",
                regras_rota=regras_rota,
            )

            self.assertTrue(politica.get("base_proxima"))
            self.assertTrue(politica.get("sem_agendamentos_d0"))
            self.assertFalse(politica.get("ancora_d2"))
            self.assertFalse(politica.get("ancora_d3"))
            self.assertTrue(politica.get("prioridade_d0_aplicada"))
            self.assertEqual(politica.get("dias_preferenciais"), [0])
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_politica_oferta_nao_prioriza_d0_quando_existe_ancora_d2_ou_d3(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            self._seed_config(
                db,
                excecoes=[],
                regras_rota={
                    "base": {
                        "label": "Casa",
                        "address": "Endereco sintetico, Fortaleza - CE",
                        "zip_code": "60000-000",
                        "lat": -3.7319,
                        "lng": -38.5267,
                    },
                    "thresholds": {
                        "nearby_anchor_max_travel_min": 20,
                        "distant_clinic_min_travel_from_base_min": 35,
                        "low_frequency_max_bookings_30d": 3,
                        "max_insertion_detour_min": 25,
                        "safe_margin_min": 5,
                    },
                    "offer_policy": {
                        "default_first_offer_days_ahead": [2],
                        "distant_low_frequency_first_offer_days_ahead": [3, 4],
                        "allow_d2_if_anchor_exists": True,
                        "emergency_first_offer_days_ahead": [1, 2],
                    },
                    "route_policy": {
                        "end_of_route_window_start": "16:00",
                        "prefer_near_base_at_end_of_route": True,
                        "bonus_near_base_score": 15,
                        "penalty_far_base_score": 10,
                        "reject_clear_inefficiency": True,
                    },
                    "fallback_policy": {
                        "suggest_alternative_slots_when_blocked": True,
                        "max_alternative_suggestions": 3,
                        "allow_extra_slot_start_or_end_route_for_emergency": True,
                    },
                    "clinic_overrides": [],
                },
            )
            clinica_base, clinica_ancora = self._seed_clinicas(
                db,
                clinica_base_coords=(-3.7320, -38.5270),
                clinica_ancora_coords=(-3.7325, -38.5275),
            )
            self._criar_agendamento(db, clinica_id=clinica_ancora.id, data="2099-05-19", hora="09:00")
            self._criar_agendamento(db, clinica_id=clinica_ancora.id, data="2099-05-21", hora="10:00")

            regras_rota = agenda._obter_regras_rota_agenda(db)
            with patch.object(agenda, "_obter_duracao_deslocamento_cacheado", return_value=(12, "mock")):
                politica = agenda._classificar_politica_oferta(
                    db,
                    clinica_id=clinica_base.id,
                    data_contato_iso="2099-05-19",
                    perfil_deslocamento="comercial",
                    regras_rota=regras_rota,
                )

            self.assertTrue(politica.get("base_proxima"))
            self.assertTrue(politica.get("ancora_d0"))
            self.assertTrue(politica.get("ancora_d2"))
            self.assertFalse(politica.get("prioridade_d0_aplicada"))
            self.assertEqual(politica.get("dias_preferenciais"), [2])
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_ancora_d2_fallback_mesma_cidade_com_um_agendamento_valido(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            self._seed_config(
                db,
                excecoes=[],
                regras_rota={
                    "base": {
                        "label": "Casa",
                        "address": "Endereco sintetico, Fortaleza - CE",
                        "zip_code": "60000-000",
                        "lat": None,
                        "lng": None,
                    },
                    "thresholds": {
                        "nearby_anchor_max_travel_min": 20,
                        "distant_clinic_min_travel_from_base_min": 35,
                        "low_frequency_max_bookings_30d": 3,
                        "max_insertion_detour_min": 25,
                        "safe_margin_min": 5,
                    },
                    "offer_policy": {
                        "default_first_offer_days_ahead": [2],
                        "distant_low_frequency_first_offer_days_ahead": [3, 4],
                        "allow_d2_if_anchor_exists": True,
                        "emergency_first_offer_days_ahead": [1, 2],
                    },
                    "route_policy": {
                        "end_of_route_window_start": "16:00",
                        "prefer_near_base_at_end_of_route": True,
                        "bonus_near_base_score": 15,
                        "penalty_far_base_score": 10,
                        "reject_clear_inefficiency": True,
                    },
                    "fallback_policy": {
                        "suggest_alternative_slots_when_blocked": True,
                        "max_alternative_suggestions": 3,
                        "allow_extra_slot_start_or_end_route_for_emergency": True,
                    },
                    "clinic_overrides": [],
                },
            )
            clinica_base, clinica_ancora = self._seed_clinicas(
                db,
                clinica_base_cidade="Fortaleza",
                clinica_ancora_cidade="Fortaleza",
            )
            self._criar_agendamento(db, clinica_id=clinica_ancora.id, data="2099-05-21", hora="09:00")

            payload = agenda.SugestaoProximidadePayload(
                clinica_id=clinica_base.id,
                data="2099-05-21",
                data_contato="2099-05-19",
                perfil_deslocamento="comercial",
                limite_minutos=25,
                janela_dias_proximidade=3,
                incluir_mesma_clinica=False,
            )

            with patch.object(agenda, "_obter_duracao_deslocamento_cacheado", return_value=(0, "sem_matriz")):
                resposta = agenda.sugerir_agendamento_proximo(
                    payload=payload,
                    db=db,
                    current_user=SimpleNamespace(id=1),
                )

            self.assertTrue(resposta["ok"])
            self.assertTrue(resposta["sugerir"])
            self.assertIsNotNone(resposta.get("item"))
            politica = resposta.get("politica_oferta") or {}
            self.assertTrue(politica.get("ancora_d2"))
            self.assertEqual(politica.get("datas_preferenciais"), ["2099-05-21"])
            self.assertEqual(str(resposta["item"].get("fonte_deslocamento") or ""), "fallback_mesma_cidade")
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_ancora_d2_fallback_cluster_mesma_cidade_quando_sem_matriz(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            self._seed_config(
                db,
                excecoes=[],
                regras_rota={
                    "base": {
                        "label": "Casa",
                        "address": "Endereco sintetico, Fortaleza - CE",
                        "zip_code": "60000-000",
                        "lat": None,
                        "lng": None,
                    },
                    "thresholds": {
                        "nearby_anchor_max_travel_min": 20,
                        "distant_clinic_min_travel_from_base_min": 35,
                        "low_frequency_max_bookings_30d": 3,
                        "max_insertion_detour_min": 25,
                        "safe_margin_min": 5,
                    },
                    "offer_policy": {
                        "default_first_offer_days_ahead": [2],
                        "distant_low_frequency_first_offer_days_ahead": [3, 4],
                        "allow_d2_if_anchor_exists": True,
                        "emergency_first_offer_days_ahead": [1, 2],
                    },
                    "route_policy": {
                        "end_of_route_window_start": "16:00",
                        "prefer_near_base_at_end_of_route": True,
                        "bonus_near_base_score": 15,
                        "penalty_far_base_score": 10,
                        "reject_clear_inefficiency": True,
                    },
                    "fallback_policy": {
                        "suggest_alternative_slots_when_blocked": True,
                        "max_alternative_suggestions": 3,
                        "allow_extra_slot_start_or_end_route_for_emergency": True,
                    },
                    "clinic_overrides": [],
                },
            )
            clinica_base, clinica_ancora = self._seed_clinicas(
                db,
                clinica_base_cidade="Fortaleza",
                clinica_ancora_cidade="Fortaleza",
            )
            clinica_ancora_2 = Clinica(
                nome="Casa Pet",
                ativo=True,
                cidade="Fortaleza",
                estado="CE",
                latitude=-3.7355,
                longitude=-38.5308,
            )
            db.add(clinica_ancora_2)
            db.commit()
            db.refresh(clinica_ancora_2)

            self._criar_agendamento(db, clinica_id=clinica_ancora.id, data="2099-05-21", hora="09:00")
            self._criar_agendamento(db, clinica_id=clinica_ancora_2.id, data="2099-05-21", hora="10:30")

            payload = agenda.SugestaoProximidadePayload(
                clinica_id=clinica_base.id,
                data="2099-05-21",
                data_contato="2099-05-19",
                perfil_deslocamento="comercial",
                limite_minutos=25,
                janela_dias_proximidade=3,
                incluir_mesma_clinica=False,
            )

            with patch.object(agenda, "_obter_duracao_deslocamento_cacheado", return_value=(0, "sem_matriz")):
                resposta = agenda.sugerir_agendamento_proximo(
                    payload=payload,
                    db=db,
                    current_user=SimpleNamespace(id=1),
                )

            self.assertTrue(resposta["ok"])
            self.assertTrue(resposta["sugerir"])
            self.assertIsNotNone(resposta.get("item"))
            politica = resposta.get("politica_oferta") or {}
            self.assertTrue(politica.get("ancora_d2"))
            self.assertEqual(politica.get("datas_preferenciais"), ["2099-05-21"])
            self.assertEqual(str(resposta["item"].get("fonte_deslocamento") or ""), "fallback_mesma_cidade")
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_ancora_d2_considera_status_em_atendimento(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            self._seed_config(db, excecoes=[])
            clinica_base, clinica_ancora = self._seed_clinicas(db)
            self._criar_agendamento(
                db,
                clinica_id=clinica_ancora.id,
                data="2099-05-21",
                hora="09:00",
                status="Em atendimento",
            )

            with patch.object(agenda, "_obter_duracao_deslocamento_cacheado", return_value=(12, "mock")):
                possui_ancora = agenda._existe_ancora_proxima_no_dia(
                    db,
                    clinica_id=clinica_base.id,
                    data_iso="2099-05-21",
                    limite_minutos=20,
                    perfil_deslocamento="comercial",
                )

            self.assertTrue(possui_ancora)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_ancora_d2_fallback_por_proximidade_geografica_com_cadastro_inconsistente(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            self._seed_config(db, excecoes=[])
            clinica_base, clinica_ancora = self._seed_clinicas(
                db,
                clinica_base_coords=(-3.7320, -38.5270),
                clinica_ancora_coords=(-3.7285, -38.5240),
                clinica_base_cidade="Fortaleza",
                clinica_base_estado="CE",
                clinica_ancora_cidade="Aldeota",
                clinica_ancora_estado="CE",
            )
            self._criar_agendamento(db, clinica_id=clinica_ancora.id, data="2099-05-21", hora="09:00")

            with patch.object(agenda, "_obter_duracao_deslocamento_cacheado", return_value=(0, "sem_matriz")):
                possui_ancora = agenda._existe_ancora_proxima_no_dia(
                    db,
                    clinica_id=clinica_base.id,
                    data_iso="2099-05-21",
                    limite_minutos=20,
                    perfil_deslocamento="comercial",
                )

            self.assertTrue(possui_ancora)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_rank_prioriza_deslocamento_antes_data_preferencial(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            self._seed_config(
                db,
                excecoes=[],
                regras_rota={
                    "base": {
                        "label": "Casa",
                        "address": "Endereco sintetico, Fortaleza - CE",
                        "zip_code": "60000-000",
                        "lat": -3.7319,
                        "lng": -38.5267,
                    },
                    "thresholds": {
                        "nearby_anchor_max_travel_min": 20,
                        "distant_clinic_min_travel_from_base_min": 35,
                        "low_frequency_max_bookings_30d": 3,
                        "max_insertion_detour_min": 25,
                        "safe_margin_min": 5,
                    },
                    "offer_policy": {
                        "default_first_offer_days_ahead": [2],
                        "distant_low_frequency_first_offer_days_ahead": [3, 4],
                        "allow_d2_if_anchor_exists": True,
                        "emergency_first_offer_days_ahead": [1, 2],
                    },
                    "route_policy": {
                        "end_of_route_window_start": "16:00",
                        "prefer_near_base_at_end_of_route": True,
                        "bonus_near_base_score": 15,
                        "penalty_far_base_score": 10,
                        "reject_clear_inefficiency": True,
                    },
                    "fallback_policy": {
                        "suggest_alternative_slots_when_blocked": True,
                        "max_alternative_suggestions": 3,
                        "allow_extra_slot_start_or_end_route_for_emergency": True,
                    },
                    "clinic_overrides": [],
                },
            )
            clinica_base = Clinica(
                nome="Vet World",
                ativo=True,
                latitude=-3.7320,
                longitude=-38.5270,
                cidade="Fortaleza",
                estado="CE",
            )
            clinica_ancora_longa = Clinica(
                nome="Celeiro",
                ativo=True,
                latitude=-3.8100,
                longitude=-38.6100,
                cidade="Fortaleza",
                estado="CE",
            )
            clinica_ancora_curta = Clinica(
                nome="Casa Pet",
                ativo=True,
                latitude=-3.7330,
                longitude=-38.5280,
                cidade="Fortaleza",
                estado="CE",
            )
            db.add_all([clinica_base, clinica_ancora_longa, clinica_ancora_curta])
            db.commit()
            db.refresh(clinica_base)
            db.refresh(clinica_ancora_longa)
            db.refresh(clinica_ancora_curta)

            # Data preferencial (D+2): 2099-05-21 -> deslocamento pior.
            self._criar_agendamento(
                db,
                clinica_id=clinica_ancora_longa.id,
                data="2099-05-21",
                hora="10:00",
                status="Agendado",
            )
            # Fora da data preferencial: 2099-05-22 -> deslocamento melhor.
            self._criar_agendamento(
                db,
                clinica_id=clinica_ancora_curta.id,
                data="2099-05-22",
                hora="10:00",
                status="Agendado",
            )

            payload = agenda.SugestaoProximidadePayload(
                clinica_id=clinica_base.id,
                data="2099-05-21",
                data_contato="2099-05-19",
                perfil_deslocamento="comercial",
                limite_minutos=60,
                janela_dias_proximidade=3,
                incluir_mesma_clinica=False,
            )

            def _duracao_side_effect(
                _db,
                *,
                origem_clinica_id: int,
                destino_clinica_id: int,
                perfil: str,
                permitir_estimativa_fallback: bool = True,
                cache=None,
                commit_cache=True,
            ):
                self.assertTrue(commit_cache, "Consultas de leitura preservam cache persistente")
                if int(destino_clinica_id) == int(clinica_ancora_longa.id):
                    return (53, "mock")
                if int(destino_clinica_id) == int(clinica_ancora_curta.id):
                    return (10, "mock")
                return (30, "mock")

            with patch.object(agenda, "_obter_duracao_deslocamento_cacheado", side_effect=_duracao_side_effect):
                resposta = agenda.sugerir_agendamento_proximo(
                    payload=payload,
                    db=db,
                    current_user=SimpleNamespace(id=1),
                )

            self.assertTrue(resposta["ok"])
            self.assertTrue(resposta["sugerir"])
            self.assertEqual(str(resposta["item"]["data"]), "2099-05-22")
            self.assertEqual(int(resposta["item"]["duracao_deslocamento_min"]), 10)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_sugestao_proximidade_ignora_ancora_passada_no_dia_atual(self) -> None:
        class DateTimeFixa(datetime):
            @classmethod
            def now(cls, tz=None):
                if tz is not None:
                    return cls(2099, 5, 20, 22, 38, 0, tzinfo=tz)
                return cls(2099, 5, 20, 22, 38, 0)

        tmpdir, db, engine = self._build_session()
        try:
            self._seed_config(db, excecoes=[])
            clinica_base, _ = self._seed_clinicas(db)
            self._criar_agendamento(
                db,
                clinica_id=clinica_base.id,
                data="2099-05-20",
                hora="13:30",
                status="Agendado",
            )

            payload = agenda.SugestaoProximidadePayload(
                clinica_id=clinica_base.id,
                data="2099-05-20",
                data_contato="2099-05-20",
                perfil_deslocamento="comercial",
                limite_minutos=25,
                janela_dias_proximidade=1,
                incluir_mesma_clinica=True,
            )

            with patch.object(agenda, "datetime", DateTimeFixa):
                resposta = agenda.sugerir_agendamento_proximo(
                    payload=payload,
                    db=db,
                    current_user=SimpleNamespace(id=1),
                )

            self.assertTrue(resposta["ok"])
            self.assertFalse(resposta["sugerir"])
            self.assertIsNone(resposta.get("item"))
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_sugestao_proximidade_ignora_ancora_sem_slot_operacional(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            self._seed_config(
                db,
                excecoes=[
                    {"data": "2099-05-23", "ativo": True, "inicio": "10:00", "fim": "11:00", "motivo": "Janela curta"},
                ],
            )
            clinica_base, clinica_ancora = self._seed_clinicas(db)
            self._criar_agendamento(
                db,
                clinica_id=clinica_ancora.id,
                data="2099-05-23",
                hora="10:30",
                status="Agendado",
            )

            payload = agenda.SugestaoProximidadePayload(
                clinica_id=clinica_base.id,
                data="2099-05-23",
                data_contato="2099-05-21",
                duracao_minutos=30,
                perfil_deslocamento="comercial",
                limite_minutos=25,
                janela_dias_proximidade=2,
                incluir_mesma_clinica=False,
            )

            with patch.object(agenda, "_obter_duracao_deslocamento_cacheado", return_value=(20, "mock")):
                resposta = agenda.sugerir_agendamento_proximo(
                    payload=payload,
                    db=db,
                    current_user=SimpleNamespace(id=1),
                )

            self.assertTrue(resposta["ok"])
            self.assertFalse(resposta["sugerir"])
            self.assertIsNone(resposta.get("item"))
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_sugestao_proximidade_soma_deslocamento_anterior_e_proximo_do_slot(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            self._seed_config(db, excecoes=[])
            clinica_base, clinica_ancora = self._seed_clinicas(db)
            ancora = self._criar_agendamento(
                db,
                clinica_id=clinica_ancora.id,
                data="2099-05-25",
                hora="10:00",
                status="Agendado",
            )

            payload = agenda.SugestaoProximidadePayload(
                clinica_id=clinica_base.id,
                data="2099-05-25",
                data_contato="2099-05-23",
                perfil_deslocamento="comercial",
                limite_minutos=60,
                janela_dias_proximidade=2,
                incluir_mesma_clinica=False,
            )

            def _mock_sugestoes_horario(
                payload: agenda.SugestaoHorarioPayload,
                db,
                current_user,
            ):
                self.assertEqual(str(payload.data), "2099-05-25")
                return {
                    "ok": True,
                    "items": [
                        {
                            "inicio": "2099-05-25 11:00",
                            "fim": "2099-05-25 11:30",
                            "tempo_deslocamento_total_min": 99,
                            "anterior": {
                                "agendamento_id": ancora.id,
                                "duracao_deslocamento_min": 12,
                                "fonte": "mock_prev",
                            },
                            "proximo": {
                                "agendamento_id": 999999,
                                "duracao_deslocamento_min": 8,
                                "fonte": "mock_next",
                            },
                        }
                    ],
                }

            with patch.object(agenda, "sugerir_horarios_agenda", side_effect=_mock_sugestoes_horario), patch.object(
                agenda, "_obter_duracao_deslocamento_cacheado", return_value=(0, "sem_matriz")
            ):
                resposta = agenda.sugerir_agendamento_proximo(
                    payload=payload,
                    db=db,
                    current_user=SimpleNamespace(id=1),
                )

            self.assertTrue(resposta["ok"])
            self.assertTrue(resposta["sugerir"])
            self.assertIsNotNone(resposta.get("item"))
            self.assertEqual(str(resposta["item"]["inicio"]), "11:00")
            self.assertEqual(int(resposta["item"]["duracao_deslocamento_min"]), 20)
            self.assertEqual(int(resposta["item"]["tempo_deslocamento_total_min"]), 20)
            self.assertEqual(int(resposta["item"]["duracao_deslocamento_anterior_min"]), 12)
            self.assertEqual(int(resposta["item"]["duracao_deslocamento_proximo_min"]), 8)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_sugestao_proximidade_nao_oferece_item_acima_do_limite(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            self._seed_config(db, excecoes=[])
            clinica_base, clinica_ancora = self._seed_clinicas(db)
            ancora = self._criar_agendamento(
                db,
                clinica_id=clinica_ancora.id,
                data="2099-05-25",
                hora="10:00",
                status="Agendado",
            )

            payload = agenda.SugestaoProximidadePayload(
                clinica_id=clinica_base.id,
                data="2099-05-25",
                data_contato="2099-05-23",
                perfil_deslocamento="comercial",
                limite_minutos=25,
                janela_dias_proximidade=2,
                incluir_mesma_clinica=False,
            )

            def _mock_sugestoes_horario(
                payload: agenda.SugestaoHorarioPayload,
                db,
                current_user,
            ):
                return {
                    "ok": True,
                    "items": [
                        {
                            "inicio": "2099-05-25 11:00",
                            "fim": "2099-05-25 11:30",
                            "tempo_deslocamento_total_min": 26,
                            "anterior": {
                                "agendamento_id": ancora.id,
                                "clinica": clinica_ancora.nome,
                                "duracao_deslocamento_min": 26,
                                "fonte": "mock_prev",
                            },
                            "proximo": None,
                        }
                    ],
                }

            with patch.object(agenda, "sugerir_horarios_agenda", side_effect=_mock_sugestoes_horario), patch.object(
                agenda, "_obter_duracao_deslocamento_cacheado", return_value=(0, "sem_matriz")
            ):
                resposta = agenda.sugerir_agendamento_proximo(
                    payload=payload,
                    db=db,
                    current_user=SimpleNamespace(id=1),
                )

            self.assertTrue(resposta["ok"])
            self.assertFalse(resposta["sugerir"])
            self.assertTrue(resposta.get("acima_do_limite"))
            self.assertIsNone(resposta.get("item"))
            self.assertIsNotNone(resposta.get("item_rejeitado"))
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_sugestoes_horario_domiciliar_usam_tutor_como_destino_operacional(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            self._seed_config(db, excecoes=[])
            _clinica_base, clinica_ancora = self._seed_clinicas(db)
            tutor = self._seed_tutor(db, nome="Ana Domiciliar")
            self._criar_agendamento(
                db,
                clinica_id=clinica_ancora.id,
                data="2099-05-25",
                hora="09:00",
                status="Agendado",
                clinica_nome=clinica_ancora.nome,
            )

            payload = agenda.SugestaoHorarioPayload(
                data="2099-05-25",
                origem_atendimento="domiciliar",
                tutor_id=tutor.id,
                duracao_minutos=30,
                intervalo_minutos=30,
                limite=8,
                perfil_deslocamento="comercial",
            )

            with patch.object(agenda, "_obter_duracao_deslocamento_operacional", return_value=(12, "mock")):
                resposta = agenda.sugerir_horarios_agenda(
                    payload=payload,
                    db=db,
                    current_user=SimpleNamespace(id=1),
                )

            self.assertTrue(resposta["ok"])
            self.assertEqual(str(resposta.get("origem_atendimento") or ""), "domiciliar")
            self.assertEqual(int(resposta.get("tutor_id") or 0), tutor.id)
            self.assertEqual(str(resposta.get("destino_operacional") or ""), f"Domicilio de {tutor.nome}")
            self.assertGreater(len(resposta.get("items") or []), 0)
            primeiro = resposta["items"][0]
            self.assertEqual(str(primeiro.get("destino_operacional_tipo") or ""), "domiciliar")
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_validacao_agendamento_domiciliar_exige_margem_segura_operacional(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            self._seed_config(db, excecoes=[])
            _clinica_base, clinica_ancora = self._seed_clinicas(db)
            tutor = self._seed_tutor(db, nome="Beatriz Rota")
            self._criar_agendamento(
                db,
                clinica_id=clinica_ancora.id,
                data="2099-05-25",
                hora="08:30",
                status="Agendado",
                duracao_minutos=20,
                clinica_nome=clinica_ancora.nome,
            )

            inicio_novo = datetime.fromisoformat("2099-05-25T09:30:00")
            novo = Agendamento(
                clinica_id=None,
                tutor_id=tutor.id,
                origem_atendimento="domiciliar",
                inicio=inicio_novo,
                fim=inicio_novo + timedelta(minutes=30),
                data="2099-05-25",
                hora="09:30",
                status="Agendado",
                tutor=tutor.nome,
            )

            with patch.object(agenda, "_obter_duracao_deslocamento_operacional", return_value=(39, "mock")):
                with self.assertRaises(HTTPException) as ctx:
                    agenda._validar_deslocamento_agendamento(db, novo)

            self.assertEqual(ctx.exception.status_code, 409)
            detail = ctx.exception.detail
            self.assertEqual(detail.get("codigo"), "CONFLITO_DESLOCAMENTO")
            self.assertEqual(int(detail.get("duracao_min")), 39)
            self.assertIn("destino_operacional", detail)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_sugestao_proximidade_domiciliar_reaproveita_ancora_operacional(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            self._seed_config(db, excecoes=[])
            _clinica_base, clinica_ancora = self._seed_clinicas(db)
            tutor = self._seed_tutor(db, nome="Carlos Tutor")
            ancora = self._criar_agendamento(
                db,
                clinica_id=clinica_ancora.id,
                data="2099-05-25",
                hora="10:00",
                status="Agendado",
                clinica_nome=clinica_ancora.nome,
            )

            payload = agenda.SugestaoProximidadePayload(
                origem_atendimento="domiciliar",
                tutor_id=tutor.id,
                data="2099-05-25",
                data_contato="2099-05-23",
                perfil_deslocamento="comercial",
                limite_minutos=60,
                janela_dias_proximidade=2,
                incluir_mesma_clinica=False,
            )

            def _mock_sugestoes_horario(
                payload: agenda.SugestaoHorarioPayload,
                db,
                current_user,
            ):
                self.assertEqual(str(payload.origem_atendimento), "domiciliar")
                self.assertEqual(int(payload.tutor_id or 0), tutor.id)
                return {
                    "ok": True,
                    "items": [
                        {
                            "inicio": "2099-05-25 11:00",
                            "fim": "2099-05-25 11:30",
                            "tempo_deslocamento_total_min": 18,
                            "anterior": {
                                "agendamento_id": ancora.id,
                                "clinica": clinica_ancora.nome,
                                "duracao_deslocamento_min": 18,
                                "fonte": "mock_prev",
                            },
                            "proximo": None,
                        }
                    ],
                }

            with patch.object(agenda, "sugerir_horarios_agenda", side_effect=_mock_sugestoes_horario):
                resposta = agenda.sugerir_agendamento_proximo(
                    payload=payload,
                    db=db,
                    current_user=SimpleNamespace(id=1),
                )

            self.assertTrue(resposta["ok"])
            self.assertTrue(resposta["sugerir"])
            self.assertEqual(str(resposta.get("origem_atendimento") or ""), "domiciliar")
            self.assertEqual(str((resposta.get("item") or {}).get("destino_operacional") or ""), f"Domicilio de {tutor.nome}")
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
