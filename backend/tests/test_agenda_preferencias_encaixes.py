"""Preferencias restringem a busca antes do ranking; encaixes preservam duracoes."""
import json
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

from app.api.v1.endpoints import agenda
from app.core.agenda_route_rules import normalizar_agenda_rota_regras
from app.models.agendamento import Agendamento
from app.models.configuracao import Configuracao
from app.models.servico import Servico
from app.schemas.agenda_preferencia import AgendaPreferencia
from tests import test_agenda_sugestao_janela_operacional as fixtures


class AgendaPreferenciasEncaixesTest(unittest.TestCase):
    _build_session = fixtures.AgendaSugestaoJanelaOperacionalTest._build_session
    _seed_config = fixtures.AgendaSugestaoJanelaOperacionalTest._seed_config
    _seed_clinicas = fixtures.AgendaSugestaoJanelaOperacionalTest._seed_clinicas
    _criar_agendamento = fixtures.AgendaSugestaoJanelaOperacionalTest._criar_agendamento

    def setUp(self):
        # O teste foca preferencias/encaixes; primeira viagem deterministica.
        patcher = patch.object(
            agenda, "estimar_deslocamento",
            return_value=(2.0, 5, "google_distance_matrix_traffic"),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.tmpdir, self.db, self.engine = self._build_session()
        self._seed_config(self.db, excecoes=[])
        self.clinica, self.outra = self._seed_clinicas(self.db)
        self.servico = Servico(nome="Ecocardiograma", duracao_minutos=40, ativo=True)
        self.db.add(self.servico)
        self.db.commit()
        self.user = SimpleNamespace(id=1, nome="Teste", tem_papel=lambda _: False)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        self.tmpdir.cleanup()

    def configurar(self, **thresholds):
        config = self.db.query(Configuracao).first()
        regras = json.loads(config.agenda_rota_regras or "{}")
        regras["thresholds"] = thresholds
        config.agenda_rota_regras = json.dumps(regras)
        self.db.commit()

    def reservar(self, hora, data="2099-05-25", duracao=40):
        return self._criar_agendamento(self.db, clinica_id=self.clinica.id,
                                      data=data, hora=hora, duracao_minutos=duracao)

    def sugerir(self, **kwargs):
        campos = dict(data="2099-05-25", clinica_id=self.clinica.id, servico_id=self.servico.id,
                      intervalo_minutos=30, limite=50)
        campos.update(kwargs)
        return agenda.sugerir_horarios_agenda(agenda.SugestaoHorarioPayload(**campos), self.db, self.user)

    def test_schema_valida_formatos_turno_e_limite_de_31_dias(self):
        valida = AgendaPreferencia(data_inicio="2099-07-01", data_fim="2099-07-31", turno="manha")
        self.assertTrue(valida.permite_data("2099-07-31"))
        self.assertFalse(valida.permite_data("2099-08-01"))
        self.assertEqual(AgendaPreferencia(hora_inicio="09:00").limites_horarios(), (9 * 60, 24 * 60))
        self.assertEqual(AgendaPreferencia(turno="manha", hora_inicio="09:00").limites_horarios(), (9 * 60, 12 * 60))
        for campos in [
            {"data_inicio": "2099-07-01"}, {"data_fim": "2099-07-01"},
            {"data_inicio": "2099-07-01", "data_fim": "2099-08-01"},
            {"data_inicio": "2099-02-30", "data_fim": "2099-03-01"},
            {"hora_fim": "10:00"},
            {"hora_inicio": "24:00", "hora_fim": "10:00"},
            {"hora_inicio": "11:00", "hora_fim": "10:00"},
            {"turno": "manha", "hora_inicio": "12:00"},
            {"turno": "tarde", "hora_inicio": "09:00", "hora_fim": "11:00"},
            {"turno": "noite"},
        ]:
            with self.subTest(campos=campos), self.assertRaises(ValidationError):
                AgendaPreferencia(**campos)

    def test_eco_40_gera_limites_exatos_nos_dois_lados_da_ancora(self):
        self.reservar("09:30")
        items = self.sugerir()["items"]
        adjacentes = {item["inicio"][-5:]: item for item in items if item["adjacente_ancora"]}
        self.assertEqual(set(adjacentes), {"08:45", "10:15"})
        for item in adjacentes.values():
            self.assertEqual(item["risco"], 0)
            self.assertEqual(datetime.fromisoformat(item["fim"]) - datetime.fromisoformat(item["inicio"]), timedelta(minutes=40))
            novo = Agendamento(clinica_id=self.clinica.id, inicio=datetime.fromisoformat(item["inicio"]),
                               fim=datetime.fromisoformat(item["fim"]), status="Agendado")
            self.assertIsNone(agenda._validar_deslocamento_agendamento(self.db, novo))
        self.assertNotIn("2099-05-25 10:10", {item["inicio"] for item in items})

    def test_cadeia_quatro_ecos_40_mais_5_sem_remarcar_existentes(self):
        primeiro = self.reservar("08:30")
        originais = {primeiro.id: (primeiro.inicio, primeiro.fim)}
        for hora_esperada in ["09:15", "10:00", "10:45"]:
            item = self.sugerir(limite=1)["items"][0]
            self.assertEqual(item["inicio"][-5:], hora_esperada)
            with patch.object(agenda, "registrar_auditoria"), patch.object(agenda, "_notificar_agenda_update"):
                resultado = agenda.criar_agendamento(
                    agenda.AgendamentoCreate(clinica_id=self.clinica.id, servico_id=self.servico.id,
                                             inicio=item["inicio"], fim=item["fim"], status="Reservado"),
                    request=SimpleNamespace(), db=self.db, current_user=self.user,
                )
            salvo = self.db.get(Agendamento, resultado["id"])
            self.assertEqual(salvo.fim - salvo.inicio, timedelta(minutes=40))
            for agendamento_id, intervalo in originais.items():
                existente = self.db.get(Agendamento, agendamento_id)
                self.assertEqual((existente.inicio, existente.fim), intervalo)
            originais[salvo.id] = (salvo.inicio, salvo.fim)
        self.assertEqual(salvo.fim.strftime("%H:%M"), "11:25")

    def test_transicao_zero_e_independente_da_margem_de_viagem(self):
        self.configurar(same_location_transition_min=0, safe_margin_min=35)
        self.reservar("09:30")
        items = self.sugerir(preferencia={"hora_inicio": "10:10", "hora_fim": "12:00"}, limite=1)["items"]
        self.assertEqual(items[0]["inicio"][-5:], "10:10")
        self.assertEqual(items[0]["risco"], 0)
        agenda._validar_deslocamento_agendamento(self.db, Agendamento(
            clinica_id=self.clinica.id, inicio=datetime(2099, 5, 25, 10, 10),
            fim=datetime(2099, 5, 25, 10, 50), status="Agendado"))
        regras = normalizar_agenda_rota_regras({"thresholds": {"same_location_transition_min": 0, "safe_margin_min": 0}})
        self.assertEqual(regras["thresholds"]["same_location_transition_min"], 0)
        self.assertEqual(regras["thresholds"]["safe_margin_min"], 0)

    def test_validacao_final_rejeita_quatro_minutos_de_transicao(self):
        self.reservar("09:30")
        with self.assertRaises(HTTPException) as erro:
            agenda._validar_deslocamento_agendamento(self.db, Agendamento(
                clinica_id=self.clinica.id, inicio=datetime(2099, 5, 25, 10, 14),
                fim=datetime(2099, 5, 25, 10, 54), status="Agendado"))
        self.assertEqual(erro.exception.status_code, 409)
        self.assertEqual(erro.exception.detail["same_location_transition_min"], 5)

    def test_mesma_referencia_sem_geo_ainda_exige_transicao(self):
        self.reservar("09:30")
        self.clinica.latitude = None
        self.clinica.longitude = None
        self.db.commit()
        with self.assertRaises(HTTPException) as erro:
            agenda._validar_deslocamento_agendamento(self.db, Agendamento(
                clinica_id=self.clinica.id, inicio=datetime(2099, 5, 25, 10, 10),
                fim=datetime(2099, 5, 25, 10, 50), status="Agendado"))
        self.assertEqual(erro.exception.detail["same_location_transition_min"], 5)

    def test_edicao_cadastral_preserva_intervalo_legado_sem_revalidar_transicao(self):
        self.reservar("09:30")
        legado = self.reservar("10:10")
        original = (legado.inicio, legado.fim)
        with patch.object(agenda, "_validar_deslocamento_agendamento") as validar, patch.object(
            agenda, "registrar_auditoria"
        ), patch.object(agenda, "_notificar_agenda_update"):
            agenda.atualizar_agendamento(
                legado.id, agenda.AgendamentoUpdate(observacoes="Contato atualizado"),
                request=SimpleNamespace(), db=self.db, current_user=self.user)
        validar.assert_not_called()
        self.assertEqual((legado.inicio, legado.fim), original)
        self.assertEqual(legado.observacoes, "Contato atualizado")

    def test_preferencia_antes_topk_ancora_tarde_nao_oculta_manha(self):
        self.reservar("15:00")
        result = self.sugerir(preferencia={"turno": "manha"}, limite=1)
        self.assertEqual(len(result["items"]), 1)
        self.assertFalse(result["tem_ancora_mesma_clinica_no_dia"])
        self.assertLessEqual(result["items"][0]["fim"][-5:], "12:00")
        self.assertEqual(agenda._classificar_panorama_data_assistente(result), "operacional")

    def test_limite_real_de_hoje_preserva_borda_antes_do_proximo_slot_regular(self):
        self.configurar(same_location_transition_min=7, safe_margin_min=5)
        self.reservar("08:20")  # Termina 09:00; a borda exata e 09:07.

        class DataMeta(type):
            def __instancecheck__(cls, value):
                return isinstance(value, datetime)

        class AgoraFixo(datetime, metaclass=DataMeta):
            @classmethod
            def now(cls, tz=None):
                valor = cls(2099, 5, 25, 9, 1)
                return valor.replace(tzinfo=tz) if tz else valor

        # O relogio fixo preserva os datetimes devolvidos pelo SQLite.
        with patch.object(agenda, "datetime", AgoraFixo):
            result = self.sugerir(intervalo_minutos=15, limite=1)
        self.assertEqual(result["items"][0]["inicio"], "2099-05-25 09:07")
        self.assertEqual(result["items"][0]["risco"], 0)

    def test_excecao_estreita_de_rota_independe_da_grade_na_oferta_e_escrita(self):
        self._criar_agendamento(self.db, clinica_id=self.outra.id, data="2099-05-25",
                               hora="08:30", duracao_minutos=40)
        self.reservar("12:00")

        def deslocamento(_db, *, origem, destino, **kwargs):
            return (0, "mesmo_destino") if agenda._destinos_operacionais_mesma_referencia(origem, destino) else (38, "teste")

        for grade_visual in [5, 120]:
            self.db.query(Configuracao).first().agenda_rota_regras = json.dumps({
                "thresholds": {"max_neighbor_travel_min": 30, "nearby_anchor_max_travel_min": 20, "safe_margin_min": 5},
                "rendering_policy": {"slot_interval_min": grade_visual},
            })
            self.db.commit()
            with self.subTest(grade_visual=grade_visual), patch.object(
                agenda, "_obter_duracao_deslocamento_operacional", side_effect=deslocamento
            ):
                items = self.sugerir(intervalo_minutos=15)["items"]
                self.assertIn("2099-05-25 10:45", {item["inicio"] for item in items})
                self.assertNotIn("2099-05-25 10:30", {item["inicio"] for item in items})
                agenda._validar_deslocamento_agendamento(self.db, Agendamento(
                    clinica_id=self.clinica.id, inicio=datetime(2099, 5, 25, 10, 45),
                    fim=datetime(2099, 5, 25, 11, 25), status="Agendado"))
                with self.assertRaises(HTTPException):
                    agenda._validar_deslocamento_agendamento(self.db, Agendamento(
                        clinica_id=self.clinica.id, inicio=datetime(2099, 5, 25, 10, 30),
                        fim=datetime(2099, 5, 25, 11, 10), status="Agendado"))

    def test_preferencia_contem_servico_completo_e_data_exata(self):
        pref = dict(data_inicio="2099-05-25", data_fim="2099-05-25", turno="tarde", hora_inicio="14:10", hora_fim="15:20")
        items = self.sugerir(preferencia=pref)["items"]
        self.assertTrue(items)
        self.assertTrue(all(i["inicio"][-5:] >= "14:10" and i["fim"][-5:] <= "15:20" for i in items))
        self.assertEqual(self.sugerir(data="2099-05-26", preferencia=pref)["items"], [])
        self.assertEqual(self.sugerir(preferencia={"hora_inicio": "14:00", "hora_fim": "14:30"})["items"], [])

    def test_data_especifica_vazia_a_partir_de_nove_filtra_antes_do_top_oito(self):
        data = "2099-10-16"
        sem_filtro = self.sugerir(data=data, intervalo_minutos=15, limite=8)
        self.assertEqual(len(sem_filtro["items"]), 8)
        self.assertTrue(any(item["inicio"] < f"{data} 09:00" for item in sem_filtro["items"]))

        preferencia = dict(data_inicio=data, data_fim=data, hora_inicio="09:00")
        resposta = self.sugerir(data=data, preferencia=preferencia, intervalo_minutos=15, limite=8)
        self.assertEqual(len(resposta["items"]), 8)
        self.assertGreater(resposta["total_encontrados"], 8)
        self.assertIn(f"{data} 09:00", {item["inicio"] for item in resposta["items"]})
        self.assertEqual(resposta["janela"], {"inicio": f"{data} 09:00", "fim": f"{data} 18:00"})
        for item in resposta["items"]:
            inicio = datetime.fromisoformat(item["inicio"])
            fim = datetime.fromisoformat(item["fim"])
            self.assertEqual(inicio.date().isoformat(), data)
            self.assertGreaterEqual(inicio.strftime("%H:%M"), "09:00")
            self.assertLessEqual(fim.strftime("%H:%M"), "18:00")
            self.assertEqual(fim - inicio, timedelta(minutes=40))
        self.assertEqual(self.sugerir(data="2099-10-17", preferencia=preferencia)["items"], [])

    def test_a_partir_de_sem_tempo_para_servico_nao_amplia_janela(self):
        data = "2099-10-16"
        preferencia = dict(data_inicio=data, data_fim=data, hora_inicio="17:30")
        resposta = self.sugerir(data=data, preferencia=preferencia, intervalo_minutos=15, limite=8)
        self.assertEqual(resposta["items"], [])
        self.assertEqual(resposta["total_encontrados"], 0)
        self.assertEqual(resposta["janela"], {"inicio": f"{data} 17:30", "fim": f"{data} 18:00"})

    def test_assistente_respeita_data_e_a_partir_de_sem_busca_em_outros_dias(self):
        data = "2099-10-16"
        preferencia = dict(data_inicio=data, data_fim=data, hora_inicio="09:00")
        with patch.object(agenda, "sugerir_agendamento_proximo", return_value={"politica_oferta": {}}), patch.object(
            agenda, "sugerir_horarios_agenda", wraps=agenda.sugerir_horarios_agenda
        ) as sugerir, patch.object(agenda, "_registrar_evento_funil_assistente"):
            resposta = agenda.orquestrar_ofertas_assistente(
                agenda.AssistenteOfertaPayload(clinica_id=self.clinica.id, servico_id=self.servico.id,
                                               data=data, preferencia=preferencia, intervalo_minutos=15, limite=8),
                request=None, db=self.db, current_user=self.user)
        self.assertEqual(sugerir.call_count, 1)
        self.assertEqual(sugerir.call_args.kwargs["payload"].data, data)
        items = resposta["panorama_ofertas"]["items"]
        self.assertEqual(len(items), 2)
        self.assertTrue(all(item["inicio"].startswith(data) and item["inicio"][-5:] >= "09:00" for item in items))
        self.assertEqual(resposta["panorama_ofertas"]["datas_hierarquizadas"][0]["data"], data)

    def test_proximidade_consulta_intervalo_declarado_alem_do_horizonte_legado(self):
        self.reservar("10:00", data="2099-07-31")
        preferencia = dict(data_inicio="2099-07-01", data_fim="2099-07-31", turno="manha")
        with patch.object(agenda, "_classificar_politica_oferta", return_value={}):
            result = agenda.sugerir_agendamento_proximo(
                agenda.SugestaoProximidadePayload(clinica_id=self.clinica.id, servico_id=self.servico.id,
                                                  data="2099-05-25", preferencia=preferencia,
                                                  intervalo_minutos=30, limite_sugestoes_operacionais=1),
                self.db, self.user)
        self.assertTrue(result["sugerir"])
        self.assertEqual(result["item"]["data"], "2099-07-31")

    def test_orquestrador_limita_busca_aos_31_dias_sem_expandir_sem_resultado(self):
        consultadas = []
        def panorama(*, payload, **kwargs):
            consultadas.append(payload.data)
            self.assertEqual(payload.preferencia.turno, "manha")
            return {"ok": True, "items": [], "total_encontrados": 0}
        with patch.object(agenda, "sugerir_agendamento_proximo", return_value={"politica_oferta": {}}), patch.object(
            agenda, "sugerir_horarios_agenda", side_effect=panorama
        ), patch.object(agenda, "_registrar_evento_funil_assistente"):
            result = agenda.orquestrar_ofertas_assistente(
                agenda.AssistenteOfertaPayload(clinica_id=self.clinica.id, data="2099-05-25",
                                               preferencia=dict(data_inicio="2099-07-01", data_fim="2099-07-31", turno="manha")),
                request=None, db=self.db, current_user=self.user)
        self.assertEqual(len(consultadas), 31)
        self.assertEqual((consultadas[0], consultadas[-1]), ("2099-07-01", "2099-07-31"))
        self.assertEqual(result["panorama_ofertas"]["items"], [])
        self.assertIn("dentro da preferencia", result["mensagem_panorama"])


if __name__ == "__main__":
    unittest.main()
