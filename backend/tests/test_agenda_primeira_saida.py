"""Primeira chegada do dia considera casa, relógio e piso municipal."""

import json
import os
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "agenda-primeira-saida-test-secret-key-1234567890")

from app.api.v1.endpoints import agenda
from app.core.agenda_route_rules import normalizar_agenda_rota_regras
from app.models.agendamento import Agendamento
from app.models.configuracao import Configuracao
from app.models.paciente import Paciente
from app.models.tutor import Tutor
from app.services.geocoding_service import GeocodeResult
from tests import test_agenda_sugestao_janela_operacional as fixtures


class _DateTimeMeta(type):
    def __instancecheck__(cls, value):
        # Datetimes read from SQLite still need to pass isinstance in agenda.py.
        return isinstance(value, datetime)


def _relogio_fixo(ano, mes, dia, hora, minuto, segundo=0):
    class DateTimeFixa(datetime, metaclass=_DateTimeMeta):
        @classmethod
        def now(cls, tz=None):
            valor = cls(ano, mes, dia, hora, minuto, segundo)
            return valor.replace(tzinfo=tz) if tz else valor

    return DateTimeFixa


class AgendaPrimeiraSaidaTest(unittest.TestCase):
    _build_session = fixtures.AgendaSugestaoJanelaOperacionalTest._build_session
    _seed_config = fixtures.AgendaSugestaoJanelaOperacionalTest._seed_config
    _seed_clinicas = fixtures.AgendaSugestaoJanelaOperacionalTest._seed_clinicas
    _criar_agendamento = fixtures.AgendaSugestaoJanelaOperacionalTest._criar_agendamento

    def setUp(self):
        self.tmpdir, self.db, self.engine = self._build_session()
        self._seed_config(self.db, excecoes=[])
        self.clinica, self.outra = self._seed_clinicas(self.db)
        self.user = SimpleNamespace(id=1, nome="Teste", tem_papel=lambda _: False)
        self._configurar_base()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        self.tmpdir.cleanup()

    def _configurar_base(self, *, latitude=-3.7305, longitude=-38.5216, margem=5, pisos=None):
        config = self.db.query(Configuracao).first()
        config.agenda_rota_regras = json.dumps({
            "base": {
                "label": "Origem de teste",
                "address": "Endereço sintético",
                "zip_code": "60000-000",
                "lat": latitude,
                "lng": longitude,
            },
            "thresholds": {"safe_margin_min": margem},
            "route_policy": {"first_appointment_city_floors": pisos or {}},
        })
        self.db.commit()

    def _sugerir(self, data="2099-05-25", *, intervalo=5, preferencia=None):
        payload = agenda.SugestaoHorarioPayload(
            data=data,
            clinica_id=self.clinica.id,
            duracao_minutos=30,
            intervalo_minutos=intervalo,
            limite=50,
            perfil_deslocamento="comercial",
            preferencia=preferencia,
        )
        return agenda.sugerir_horarios_agenda(payload, self.db, self.user)

    @staticmethod
    def _horarios(resposta):
        return [datetime.strptime(item["inicio"], "%Y-%m-%d %H:%M") for item in resposta["items"]]

    def _novo(self, data, hora, *, duracao=30):
        inicio = datetime.fromisoformat(f"{data}T{hora}:00")
        return Agendamento(
            clinica_id=self.clinica.id,
            inicio=inicio,
            fim=inicio + timedelta(minutes=duracao),
            data=data,
            hora=hora,
            status="Reservado",
        )

    def _criar_inativo_para_reativacao(self, *, hora="11:00", status="Cancelado"):
        Paciente.__table__.create(self.engine, checkfirst=True)
        tutor = Tutor(nome="Tutor sintetico", telefone="85911110001")
        self.db.add(tutor)
        self.db.flush()
        paciente = Paciente(nome="Paciente sintetico", tutor_id=tutor.id)
        self.db.add(paciente)
        self.db.flush()
        agendamento = self._novo("2099-05-25", hora)
        agendamento.status = status
        agendamento.tutor_id = tutor.id
        agendamento.paciente_id = paciente.id
        self.db.add(agendamento)
        self.db.commit()
        return agendamento

    def _patch_reativacao(self, agendamento_id, *, confirmar_expirada=False):
        app = FastAPI()
        app.include_router(agenda.router, prefix="/agenda")
        sessions = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)

        def db_isolado():
            with sessions() as db:
                yield db

        app.dependency_overrides[agenda.get_db] = db_isolado
        app.dependency_overrides[agenda.get_current_user] = lambda: self.user
        with patch.object(agenda, "datetime", _relogio_fixo(2099, 5, 25, 12, 0)), patch.object(
            agenda, "registrar_auditoria", return_value=None
        ), patch.object(agenda, "_notificar_agenda_update", return_value=None), TestClient(app) as client:
            return client.patch(
                f"/agenda/{agendamento_id}/status",
                params={"status": "Agendado", "confirmar_slot_reserva_expirada": confirmar_expirada},
            )

    def test_patch_reativa_primeiro_atendimento_ja_iniciado_sem_nova_saida_da_base(self):
        for status in ("Cancelado", "Expirado"):
            with self.subTest(status=status):
                agendamento = self._criar_inativo_para_reativacao(status=status)
                intervalo_original = (agendamento.inicio, agendamento.fim)
                with patch.object(
                    agenda, "estimar_deslocamento", return_value=(10.0, 30, "google_distance_matrix_traffic")
                ) as rota_base:
                    resposta = self._patch_reativacao(
                        agendamento.id, confirmar_expirada=status == "Expirado"
                    )
                self.assertEqual(resposta.status_code, 200, resposta.text)
                self.assertEqual(resposta.json()["status"], "Agendado")
                rota_base.assert_not_called()
                self.db.refresh(agendamento)
                self.assertEqual(agendamento.status, "Agendado")
                self.assertEqual((agendamento.inicio, agendamento.fim), intervalo_original)
                self.db.delete(agendamento)
                self.db.commit()

    def test_patch_reativa_cancelado_no_instante_original_do_inicio(self):
        agendamento = self._criar_inativo_para_reativacao(hora="12:00")
        with patch.object(
            agenda, "estimar_deslocamento", return_value=(10.0, 30, "google_distance_matrix_traffic")
        ) as rota_base:
            resposta = self._patch_reativacao(agendamento.id)
        self.assertEqual(resposta.status_code, 200, resposta.text)
        rota_base.assert_not_called()
        self.db.refresh(agendamento)
        self.assertEqual(agendamento.status, "Agendado")

    def test_patch_reativacao_expirada_ja_iniciada_ainda_exige_confirmacao(self):
        agendamento = self._criar_inativo_para_reativacao(status="Expirado")
        resposta = self._patch_reativacao(agendamento.id)
        self.assertEqual(resposta.status_code, 409, resposta.text)
        self.assertEqual(resposta.json()["detail"]["codigo"], "CONFIRMACAO_REATIVACAO_RESERVA_EXPIRADA")
        self.db.refresh(agendamento)
        self.assertEqual(agendamento.status, "Expirado")

    def test_patch_reativacao_futura_preserva_limite_de_primeira_saida(self):
        agendamento = self._criar_inativo_para_reativacao(hora="12:15")
        with patch.object(
            agenda, "estimar_deslocamento", return_value=(10.0, 30, "google_distance_matrix_traffic")
        ):
            resposta = self._patch_reativacao(agendamento.id)
        self.assertEqual(resposta.status_code, 409, resposta.text)
        self.assertEqual(resposta.json()["detail"]["codigo"], "PRIMEIRA_SAIDA_INVIAVEL")
        self.assertEqual(resposta.json()["detail"]["inicio_minimo_primeira_saida"], "2099-05-25 12:35")
        self.db.refresh(agendamento)
        self.assertEqual(agendamento.status, "Cancelado")

    def test_patch_reativacao_futura_sem_rota_confiavel_continua_bloqueada(self):
        agendamento = self._criar_inativo_para_reativacao(hora="13:00")
        with patch.object(agenda, "estimar_deslocamento", return_value=(10.0, 25, "heuristica_haversine")):
            resposta = self._patch_reativacao(agendamento.id)
        self.assertEqual(resposta.status_code, 409, resposta.text)
        self.assertEqual(resposta.json()["detail"]["codigo"], "PRIMEIRA_SAIDA_INVIAVEL")
        self.db.refresh(agendamento)
        self.assertEqual(agendamento.status, "Cancelado")

    def test_patch_reativacao_ja_iniciada_preserva_bloqueio_de_slot_ocupado(self):
        agendamento = self._criar_inativo_para_reativacao()
        self._criar_agendamento(
            self.db, clinica_id=self.clinica.id, data="2099-05-25", hora="11:00"
        )
        resposta = self._patch_reativacao(agendamento.id)
        self.assertEqual(resposta.status_code, 409, resposta.text)
        self.assertIn("Horario indisponivel", resposta.json()["detail"])
        self.db.refresh(agendamento)
        self.assertEqual(agendamento.status, "Cancelado")

    def test_patch_reativacao_ja_iniciada_preserva_bloqueio_de_agenda_fechada(self):
        agendamento = self._criar_inativo_para_reativacao()
        config = self.db.query(Configuracao).first()
        config.agenda_excecoes = json.dumps([{"data": "2099-05-25", "ativo": False}])
        self.db.commit()
        resposta = self._patch_reativacao(agendamento.id)
        self.assertEqual(resposta.status_code, 422, resposta.text)
        self.assertIn("Agenda fechada", resposta.json()["detail"])
        self.db.refresh(agendamento)
        self.assertEqual(agendamento.status, "Cancelado")

    def test_patch_reativacao_ja_iniciada_preserva_conflito_com_proximo_atendimento(self):
        agendamento = self._criar_inativo_para_reativacao()
        self._criar_agendamento(
            self.db, clinica_id=self.outra.id, data="2099-05-25", hora="11:45"
        )
        with patch.object(
            agenda, "estimar_deslocamento", return_value=(10.0, 30, "google_distance_matrix_traffic")
        ), patch.object(agenda, "_obter_duracao_deslocamento_operacional", return_value=(75, "mock")):
            resposta = self._patch_reativacao(agendamento.id)
        self.assertEqual(resposta.status_code, 409, resposta.text)
        self.assertEqual(resposta.json()["detail"]["codigo"], "CONFLITO_DESLOCAMENTO")
        self.db.refresh(agendamento)
        self.assertEqual(agendamento.status, "Cancelado")

    def test_pisos_municipais_configuraveis_normalizam_acentos_e_horarios(self):
        regras = normalizar_agenda_rota_regras({
            "route_policy": {"first_appointment_city_floors": {
                " MARACANAÚ ": "09:15",
                "Aquiraz": "08:45",
                "Eusébio": "25:00",
            }}
        })
        pisos = regras["route_policy"]["first_appointment_city_floors"]
        self.assertEqual(pisos["maracanau"], "09:15")
        self.assertEqual(pisos["aquiraz"], "08:45")
        self.assertEqual(pisos["eusebio"], "09:00")

    def test_base_residencial_sem_default_exige_configuracao_persistida(self):
        base = normalizar_agenda_rota_regras(None)["base"]
        self.assertEqual(base["address"], "")
        self.assertEqual(base["zip_code"], "")

        config = self.db.query(Configuracao).first()
        config.agenda_rota_regras = json.dumps({"base": base})
        self.db.commit()
        with patch.object(agenda, "estimar_deslocamento") as rota:
            resposta = self._sugerir(preferencia={"hora_inicio": "08:00", "hora_fim": "10:00"})
            with self.assertRaises(HTTPException) as erro:
                agenda._validar_deslocamento_agendamento(self.db, self._novo("2099-05-25", "09:00"))
        rota.assert_not_called()
        self.assertEqual(resposta["items"], [])
        self.assertEqual(erro.exception.detail["codigo"], "PRIMEIRA_SAIDA_INVIAVEL")

    def test_piso_configurado_para_outro_municipio_limita_sugestao(self):
        self._configurar_base(pisos={"Aquiraz": "08:45"})
        self.clinica.cidade = "Aquiraz"
        self.db.commit()
        with patch.object(agenda, "estimar_deslocamento", return_value=(2.0, 5, "google_distance_matrix_traffic")):
            resposta = self._sugerir(preferencia={"hora_inicio": "08:00", "hora_fim": "10:00"})
        horarios = self._horarios(resposta)
        self.assertTrue(horarios)
        self.assertTrue(all(inicio >= datetime(2099, 5, 25, 8, 45) for inicio in horarios))

    def test_hoje_0824_nao_oferece_primeiro_atendimento_sem_tempo_de_chegada(self):
        with patch.object(agenda, "datetime", _relogio_fixo(2099, 5, 25, 8, 24)), patch.object(
            agenda, "estimar_deslocamento", return_value=(8.0, 20, "google_distance_matrix_traffic")
        ):
            resposta = self._sugerir("2099-05-25", preferencia={"hora_inicio": "08:00", "hora_fim": "10:00"})
        horarios = self._horarios(resposta)
        self.assertTrue(horarios)
        self.assertTrue(all(inicio >= datetime(2099, 5, 25, 8, 49) for inicio in horarios))
        self.assertNotIn(datetime(2099, 5, 25, 8, 30), horarios)

    def test_primeiro_atendimento_futuro_usa_abertura_mais_viagem_em_cidade_sem_piso(self):
        for cidade in ("Fortaleza", "Aquiraz"):
            with self.subTest(cidade=cidade):
                self.clinica.cidade = cidade
                self.db.commit()
                with patch.object(agenda, "estimar_deslocamento", return_value=(10.0, 25, "google_distance_matrix_traffic")):
                    resposta = self._sugerir(preferencia={"hora_inicio": "08:00", "hora_fim": "10:00"})
                horarios = self._horarios(resposta)
                self.assertTrue(horarios)
                self.assertTrue(all(inicio >= datetime(2099, 5, 25, 8, 30) for inicio in horarios))

    def test_pisos_de_caucaia_maracanau_eusebio_itaitinga(self):
        casos = (
            ("Caucaia", "08:30"),
            ("Maracanaú", "09:00"),
            (" MARACANAU ", "09:00"),
            ("Maracanaú - CE", "09:00"),
            ("Eusébio", "09:00"),
            ("EUSEBIO", "09:00"),
            ("Eusébio - Ceará", "09:00"),
            ("Itaitinga", "09:00"),
        )
        for cidade, piso in casos:
            with self.subTest(cidade=cidade):
                self.clinica.cidade = cidade
                self.db.commit()
                with patch.object(agenda, "estimar_deslocamento", return_value=(2.0, 5, "google_distance_matrix_traffic")):
                    resposta = self._sugerir(preferencia={"hora_inicio": "08:00", "hora_fim": "10:00"})
                horarios = self._horarios(resposta)
                self.assertTrue(horarios)
                limite = datetime.fromisoformat(f"2099-05-25T{piso}:00")
                self.assertTrue(all(inicio >= limite for inicio in horarios))

    def test_piso_do_ce_nao_se_aplica_a_municipio_de_outra_uf(self):
        self.clinica.cidade = "Maracanau"
        self.clinica.estado = "SP"
        self.db.commit()
        with patch.object(agenda, "estimar_deslocamento", return_value=(2.0, 5, "google_distance_matrix_traffic")):
            resposta = self._sugerir(preferencia={"hora_inicio": "08:00", "hora_fim": "09:00"})
        horarios = self._horarios(resposta)
        self.assertTrue(horarios)
        self.assertTrue(all(inicio < datetime(2099, 5, 25, 9, 0) for inicio in horarios))

    def test_viagem_longa_prevalece_sobre_piso_municipal(self):
        self.clinica.cidade = "Caucaia"
        self.db.commit()
        with patch.object(agenda, "estimar_deslocamento", return_value=(40.0, 95, "google_distance_matrix_traffic")):
            resposta = self._sugerir(preferencia={"hora_inicio": "08:00", "hora_fim": "11:00"})
        horarios = self._horarios(resposta)
        self.assertTrue(horarios)
        self.assertTrue(all(inicio >= datetime(2099, 5, 25, 9, 40) for inicio in horarios))

    def test_piso_municipal_tambem_e_validado_no_salvamento(self):
        for cidade, cedo, borda in (
            ("Caucaia", "08:25", "08:30"),
            ("Maracanau", "08:55", "09:00"),
            ("Eusébio", "08:55", "09:00"),
            ("Itaitinga", "08:55", "09:00"),
        ):
            with self.subTest(cidade=cidade):
                self.clinica.cidade = cidade
                self.db.commit()
                with patch.object(agenda, "estimar_deslocamento", return_value=(2.0, 5, "google_distance_matrix_traffic")):
                    with self.assertRaises(HTTPException) as erro:
                        agenda._validar_deslocamento_agendamento(self.db, self._novo("2099-05-25", cedo))
                    self.assertEqual(erro.exception.status_code, 409)
                    self.assertEqual(erro.exception.detail["codigo"], "PRIMEIRA_SAIDA_INVIAVEL")
                    self.assertIsNone(
                        agenda._validar_deslocamento_agendamento(self.db, self._novo("2099-05-25", borda))
                    )

    def test_rota_indisponivel_falha_fechada_na_sugestao_e_escrita(self):
        for resultado in (
            (0.0, 0, "indefinido"),
            (10.0, 25, "heuristica_haversine"),
            (10.0, 25, "heuristica_mesma_cidade"),
            (42.0, 95, "heuristica_regional"),
        ):
            self.db.info.pop("_agenda_primeira_saida_deslocamento", None)
            with self.subTest(resultado=resultado), patch.object(
                agenda, "estimar_deslocamento", return_value=resultado
            ):
                resposta = self._sugerir(preferencia={"hora_inicio": "08:00", "hora_fim": "10:00"})
                with self.assertRaises(HTTPException) as erro:
                    agenda._validar_deslocamento_agendamento(self.db, self._novo("2099-05-25", "09:00"))
                self.assertEqual(resposta["items"], [])
                self.assertTrue(str(resposta.get("motivo") or "").strip())
                self.assertEqual(erro.exception.status_code, 409)
                self.assertEqual(erro.exception.detail["codigo"], "PRIMEIRA_SAIDA_INVIAVEL")

    def test_base_residencial_sem_coordenadas_usa_endereco_geocodificado(self):
        self._configurar_base(latitude=None, longitude=None)
        agenda._geocodificar_base_primeira_saida.cache_clear()
        geocode_result = GeocodeResult(
            latitude=-3.7305,
            longitude=-38.5216,
            endereco_normalizado="Endereço sintético, Fortaleza, CE",
            place_id="place-teste",
            bairro="Centro",
            cidade="Fortaleza",
            estado="CE",
            cep="60000000",
        )
        with patch.object(agenda.settings, "LOGISTICA_ALLOW_LIVE_GOOGLE_LOOKUPS_ON_READ", True), patch.object(
            agenda.settings, "GOOGLE_MAPS_API_KEY", "chave-sintetica"
        ), patch.object(
            agenda, "geocodificar_endereco_google", return_value=geocode_result
        ) as geocodificar, patch.object(
            agenda, "estimar_deslocamento", return_value=(8.0, 20, "google_distance_matrix_traffic")
        ):
            resposta = self._sugerir(preferencia={"hora_inicio": "08:00", "hora_fim": "10:00"})
        self.assertTrue(resposta["items"])
        self.assertTrue(all(inicio >= datetime(2099, 5, 25, 8, 25) for inicio in self._horarios(resposta)))
        geocodificar.assert_called_once()
        self.assertIn("Endereço sintético", geocodificar.call_args.args[0])
        agenda._geocodificar_base_primeira_saida.cache_clear()

    def test_base_sem_coordenadas_e_sem_google_falha_fechada(self):
        self._configurar_base(latitude=None, longitude=None)
        with patch.object(agenda.settings, "LOGISTICA_ALLOW_LIVE_GOOGLE_LOOKUPS_ON_READ", False), patch.object(
            agenda, "estimar_deslocamento"
        ) as rota:
            resposta = self._sugerir(preferencia={"hora_inicio": "08:00", "hora_fim": "10:00"})
            with self.assertRaises(HTTPException) as erro:
                agenda._validar_deslocamento_agendamento(self.db, self._novo("2099-05-25", "09:00"))
        rota.assert_not_called()
        self.assertEqual(resposta["items"], [])
        self.assertEqual(erro.exception.detail["codigo"], "PRIMEIRA_SAIDA_INVIAVEL")

    def test_sem_geolocalizacao_de_destino_nao_oferece_e_nao_salva(self):
        self.clinica.latitude = None
        self.clinica.longitude = None
        self.db.commit()
        with self.assertRaises(HTTPException) as consulta:
            self._sugerir()
        self.assertEqual(consulta.exception.status_code, 422)
        with self.assertRaises(HTTPException) as escrita:
            agenda._validar_deslocamento_agendamento(self.db, self._novo("2099-05-25", "10:00"))
        self.assertIn(escrita.exception.status_code, (409, 422))
        payload = agenda.AgendamentoCreate(
            clinica_id=self.clinica.id,
            inicio="2099-05-25T10:00:00",
            fim="2099-05-25T10:30:00",
            status="Reservado",
        )
        with self.assertRaises(HTTPException):
            agenda.criar_agendamento(payload, request=SimpleNamespace(), db=self.db, current_user=self.user)
        self.assertEqual(self.db.query(Agendamento).count(), 0)

    def test_segundos_nao_arredondam_chegada_para_baixo(self):
        with patch.object(agenda, "datetime", _relogio_fixo(2099, 5, 25, 8, 24, 59)), patch.object(
            agenda, "estimar_deslocamento", return_value=(8.0, 20, "google_distance_matrix_traffic")
        ):
            resposta = self._sugerir("2099-05-25", preferencia={"hora_inicio": "08:00", "hora_fim": "09:30"})
            cedo = self._novo("2099-05-25", "08:49")
            with self.assertRaises(HTTPException) as erro:
                agenda._validar_deslocamento_agendamento(self.db, cedo)
        self.assertTrue(all(inicio >= datetime(2099, 5, 25, 8, 50) for inicio in self._horarios(resposta)))
        self.assertEqual(erro.exception.status_code, 409)

    def test_oferta_que_envelhece_e_rejeitada_no_salvamento(self):
        with patch.object(agenda, "datetime", _relogio_fixo(2099, 5, 25, 8, 24)), patch.object(
            agenda, "estimar_deslocamento", return_value=(8.0, 20, "google_distance_matrix_traffic")
        ):
            resposta = self._sugerir("2099-05-25", preferencia={"hora_inicio": "08:00", "hora_fim": "10:00"})
        horarios = self._horarios(resposta)
        self.assertIn(datetime(2099, 5, 25, 8, 50), horarios)

        payload = agenda.AgendamentoCreate(
            clinica_id=self.clinica.id,
            inicio="2099-05-25T08:50:00",
            fim="2099-05-25T09:20:00",
            status="Reservado",
        )
        with patch.object(agenda, "datetime", _relogio_fixo(2099, 5, 25, 8, 30)), patch.object(
            agenda, "estimar_deslocamento", return_value=(8.0, 20, "google_distance_matrix_traffic")
        ):
            with self.assertRaises(HTTPException) as erro:
                agenda.criar_agendamento(payload, request=SimpleNamespace(), db=self.db, current_user=self.user)
        self.assertEqual(erro.exception.status_code, 409)
        self.assertEqual(erro.exception.detail["codigo"], "PRIMEIRA_SAIDA_INVIAVEL")
        self.assertEqual(self.db.query(Agendamento).count(), 0)

    def test_revalidacao_do_aceite_usa_slot_exato_e_relogio_atual(self):
        payload = agenda.ValidarOfertaAssistentePayload(
            inicio="2099-05-25 08:50",
            clinica_id=self.clinica.id,
            duracao_minutos=30,
        )
        with patch.object(agenda, "datetime", _relogio_fixo(2099, 5, 25, 8, 24)), patch.object(
            agenda, "estimar_deslocamento", return_value=(8.0, 20, "google_distance_matrix_traffic")
        ):
            valida = agenda.validar_oferta_assistente_agenda(payload, db=self.db, current_user=self.user)
        with patch.object(agenda, "datetime", _relogio_fixo(2099, 5, 25, 8, 30)), patch.object(
            agenda, "estimar_deslocamento", return_value=(8.0, 20, "google_distance_matrix_traffic")
        ):
            vencida = agenda.validar_oferta_assistente_agenda(payload, db=self.db, current_user=self.user)
        self.assertTrue(valida["valido"])
        self.assertFalse(vencida["valido"])
        self.assertEqual(vencida["codigo"], "PRIMEIRA_SAIDA_INVIAVEL")
        self.assertEqual(vencida["inicio_minimo_primeira_saida"], "2099-05-25 08:55")
        self.assertNotIn("Endereço sintético", str(vencida))

    def test_agendamento_intermediario_usa_vizinho_anterior_e_nao_casa(self):
        self._criar_agendamento(self.db, clinica_id=self.clinica.id,
                               data="2099-05-25", hora="08:00", duracao_minutos=30)
        # A rota residencial longa não se aplica ao segundo atendimento.
        with patch.object(agenda, "estimar_deslocamento", return_value=(40.0, 95, "google_distance_matrix_traffic")):
            resposta = self._sugerir(preferencia={"hora_inicio": "08:35", "hora_fim": "09:35"})
            agenda._validar_deslocamento_agendamento(self.db, self._novo("2099-05-25", "08:35"))
        self.assertIn(datetime(2099, 5, 25, 8, 35), self._horarios(resposta))

    def test_edicao_de_primeiro_domicilio_revalida_novo_tutor_sem_mudar_horario(self):
        tutor_original = Tutor(
            nome="Tutor proximo", telefone="85911110001",
            endereco="Rua sintética", numero="1", cidade="Fortaleza", estado="CE",
            cep="60000001", latitude=-3.7319, longitude=-38.5267, ativo=1,
        )
        tutor_distante = Tutor(
            nome="Tutor distante", telefone="85911110002",
            endereco="Rua sintética", numero="2", cidade="Fortaleza", estado="CE",
            cep="60000002", latitude=-3.9000, longitude=-38.8000, ativo=1,
        )
        self.db.add_all([tutor_original, tutor_distante])
        self.db.commit()
        inicio = datetime(2099, 5, 25, 8, 30)
        reserva = Agendamento(
            origem_atendimento="domiciliar",
            tutor_id=tutor_original.id,
            clinica_id=None,
            inicio=inicio,
            fim=inicio + timedelta(minutes=30),
            data="2099-05-25",
            hora="08:30",
            status="Reservado",
        )
        self.db.add(reserva)
        self.db.commit()

        with patch.object(
            agenda, "estimar_deslocamento", return_value=(20.0, 45, "google_distance_matrix_traffic")
        ):
            with self.assertRaises(HTTPException) as erro:
                agenda.atualizar_agendamento(
                    reserva.id,
                    agenda.AgendamentoUpdate(tutor_id=tutor_distante.id),
                    request=SimpleNamespace(), db=self.db, current_user=self.user,
                )
        self.assertEqual(erro.exception.status_code, 409)
        self.assertEqual(erro.exception.detail["codigo"], "PRIMEIRA_SAIDA_INVIAVEL")
        self.db.rollback()
        self.db.refresh(reserva)
        self.assertEqual(reserva.tutor_id, tutor_original.id)


if __name__ == "__main__":
    unittest.main()
