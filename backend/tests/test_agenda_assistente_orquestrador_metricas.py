import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("SECRET_KEY", "agenda-assistente-orquestrador-metricas-test-secret-key-1234567890")

from app.api.v1.endpoints import agenda
from app.models.auditoria_evento import AuditoriaEvento
from app.models.clinica import Clinica


class AgendaAssistenteOrquestradorTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self._tmpdir.name) / "agenda-assistente-orquestrador.db"
        self._engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
        self._session_factory = sessionmaker(bind=self._engine, autocommit=False, autoflush=False)
        Clinica.__table__.create(self._engine, checkfirst=True)
        with self._session_factory() as db:
            db.add(Clinica(nome="Lemani", ativo=True))
            db.commit()

    def tearDown(self) -> None:
        self._engine.dispose()
        self._tmpdir.cleanup()

    def _admin(self):
        return SimpleNamespace(id=1, nome="Admin", email="admin@fortcordis.com", tem_papel=lambda p: p == "admin")

    def _panorama_mock(self, data_iso: str, *, categoria: str = "operacional", total_itens: int = 1) -> dict:
        itens = []
        for idx in range(total_itens):
            inicio_hora = 10 + idx
            item = {
                "inicio": f"{data_iso} {inicio_hora:02d}:00",
                "fim": f"{data_iso} {inicio_hora:02d}:20",
                "anterior": None if categoria == "data_vazia" else {},
                "proximo": None if categoria == "data_vazia" else {},
                "adjacente_ancora": categoria == "ancora",
                "adjacencia_tipo": "apos_ancora" if categoria == "ancora" else None,
            }
            itens.append(item)

        return {
            "ok": True,
            "data": data_iso,
            "items": itens,
            "motivo": "",
            "itens_ignorados_janela": 0,
            "tem_ancora_mesma_clinica_no_dia": categoria == "ancora",
            "tem_agendamentos_no_dia": categoria != "data_vazia",
        }

    def test_orquestrador_prioriza_data_proximidade_mesmo_fora_da_data_preferencial(self) -> None:
        payload = agenda.AssistenteOfertaPayload(
            clinica_id=1,
            data="2026-05-23",
            data_contato="2026-05-23",
            servico_id=1,
            duracao_minutos=30,
            intervalo_minutos=30,
            limite=8,
            perfil_deslocamento="comercial",
            limite_minutos=25,
        )
        proximidade_mock = {
            "ok": True,
            "sugerir": True,
            "mensagem": "mock proximidade",
            "politica_oferta": {
                "distante_base": True,
                "baixa_frequencia": True,
                "ancora_d2": False,
                "datas_preferenciais": ["2026-05-26", "2026-05-27"],
            },
            "item": {
                "data": "2026-05-24",
                "inicio": "10:00",
                "data_preferencial": False,
            },
        }

        def _mock_panorama(*, payload, db, current_user):
            mapa = {
                "2026-05-24": self._panorama_mock("2026-05-24", categoria="ancora", total_itens=3),
                "2026-05-26": self._panorama_mock("2026-05-26", categoria="ancora", total_itens=3),
                "2026-05-27": self._panorama_mock("2026-05-27", categoria="data_vazia", total_itens=3),
                "2026-05-23": self._panorama_mock("2026-05-23", categoria="operacional", total_itens=2),
            }
            return mapa[str(payload.data)]

        with self._session_factory() as db, patch.object(
            agenda, "sugerir_agendamento_proximo", return_value=proximidade_mock
        ), patch.object(
            agenda, "sugerir_horarios_agenda", side_effect=_mock_panorama
        ) as mocked_panorama, patch.object(
            agenda, "_registrar_evento_funil_assistente", return_value=None
        ):
            resposta = agenda.orquestrar_ofertas_assistente(
                payload=payload,
                request=None,
                db=db,
                current_user=self._admin(),
            )

        self.assertTrue(resposta["ok"])
        self.assertEqual(resposta["origem_data_automatica"], "proximidade")
        self.assertEqual(resposta["data_base"], "2026-05-24")
        datas_consultadas = [chamada.kwargs["payload"].data for chamada in mocked_panorama.call_args_list]
        self.assertEqual(datas_consultadas, ["2026-05-24", "2026-05-26", "2026-05-27", "2026-05-23"])
        datas_hierarquizadas = resposta["panorama_ofertas"]["datas_hierarquizadas"]
        self.assertEqual([item["categoria"] for item in datas_hierarquizadas], ["ancora", "ancora", "data_vazia"])
        self.assertEqual([item["data"] for item in datas_hierarquizadas], ["2026-05-24", "2026-05-26", "2026-05-27"])
        self.assertEqual(
            [item["hierarquia_data"] for item in resposta["panorama_ofertas"]["items"]],
            ["2026-05-24", "2026-05-24", "2026-05-26", "2026-05-26", "2026-05-27", "2026-05-27"],
        )

    def test_orquestrador_faz_fallback_para_data_politica_quando_data_proximidade_esta_sem_ofertas(self) -> None:
        payload = agenda.AssistenteOfertaPayload(
            clinica_id=1,
            data="2026-05-23",
            data_contato="2026-05-23",
            servico_id=1,
            duracao_minutos=30,
            intervalo_minutos=30,
            limite=8,
            perfil_deslocamento="comercial",
            limite_minutos=25,
        )
        proximidade_mock = {
            "ok": True,
            "sugerir": True,
            "mensagem": "mock proximidade",
            "politica_oferta": {
                "distante_base": True,
                "baixa_frequencia": True,
                "ancora_d2": False,
                "datas_preferenciais": ["2026-05-26", "2026-05-27"],
            },
            "item": {
                "data": "2026-05-24",
                "inicio": "10:00",
                "data_preferencial": False,
            },
        }

        def _mock_panorama(*, payload, db, current_user):
            mapa = {
                "2026-05-24": {"ok": True, "data": "2026-05-24", "items": [], "motivo": "sem oferta", "itens_ignorados_janela": 0},
                "2026-05-26": self._panorama_mock("2026-05-26", categoria="ancora", total_itens=2),
                "2026-05-27": self._panorama_mock("2026-05-27", categoria="ancora", total_itens=2),
                "2026-05-23": self._panorama_mock("2026-05-23", categoria="data_vazia", total_itens=2),
            }
            return mapa[str(payload.data)]

        with self._session_factory() as db, patch.object(
            agenda, "sugerir_agendamento_proximo", return_value=proximidade_mock
        ), patch.object(
            agenda, "sugerir_horarios_agenda", side_effect=_mock_panorama
        ) as mocked_panorama, patch.object(
            agenda, "_registrar_evento_funil_assistente", return_value=None
        ):
            resposta = agenda.orquestrar_ofertas_assistente(
                payload=payload,
                request=None,
                db=db,
                current_user=self._admin(),
            )

        self.assertTrue(resposta["ok"])
        self.assertEqual(resposta["origem_data_automatica"], "politica")
        self.assertEqual(resposta["data_base"], "2026-05-26")
        datas_consultadas = [chamada.kwargs["payload"].data for chamada in mocked_panorama.call_args_list]
        self.assertEqual(datas_consultadas, ["2026-05-24", "2026-05-26", "2026-05-27", "2026-05-23"])

    def test_orquestrador_faz_fallback_para_proxima_data_preferencial_quando_primeira_sem_ofertas(self) -> None:
        payload = agenda.AssistenteOfertaPayload(
            clinica_id=1,
            data="2026-05-23",
            data_contato="2026-05-23",
            servico_id=1,
            duracao_minutos=30,
            intervalo_minutos=30,
            limite=8,
            perfil_deslocamento="comercial",
            limite_minutos=25,
        )
        proximidade_mock = {
            "ok": True,
            "sugerir": False,
            "mensagem": "mock proximidade",
            "politica_oferta": {
                "distante_base": True,
                "baixa_frequencia": True,
                "ancora_d2": False,
                "datas_preferenciais": ["2026-05-26", "2026-05-27"],
            },
            "item": None,
        }

        def _mock_panorama(*, payload, db, current_user):
            mapa = {
                "2026-05-26": {"ok": True, "data": "2026-05-26", "items": [], "motivo": "sem janela", "itens_ignorados_janela": 0},
                "2026-05-27": self._panorama_mock("2026-05-27", categoria="ancora", total_itens=2),
                "2026-05-23": self._panorama_mock("2026-05-23", categoria="data_vazia", total_itens=2),
            }
            return mapa[str(payload.data)]

        with self._session_factory() as db, patch.object(
            agenda, "sugerir_agendamento_proximo", return_value=proximidade_mock
        ), patch.object(
            agenda, "sugerir_horarios_agenda", side_effect=_mock_panorama
        ) as mocked_panorama, patch.object(
            agenda, "_registrar_evento_funil_assistente", return_value=None
        ):
            resposta = agenda.orquestrar_ofertas_assistente(
                payload=payload,
                request=None,
                db=db,
                current_user=self._admin(),
            )

        self.assertTrue(resposta["ok"])
        self.assertEqual(resposta["origem_data_automatica"], "politica")
        self.assertEqual(resposta["data_base"], "2026-05-27")
        datas_consultadas = [chamada.kwargs["payload"].data for chamada in mocked_panorama.call_args_list]
        self.assertEqual(datas_consultadas, ["2026-05-26", "2026-05-27", "2026-05-23"])

    def test_orquestrador_faz_fallback_para_data_referencia_quando_datas_preferenciais_sem_oferta(self) -> None:
        payload = agenda.AssistenteOfertaPayload(
            clinica_id=1,
            data="2026-05-23",
            data_contato="2026-05-23",
            servico_id=1,
            duracao_minutos=30,
            intervalo_minutos=30,
            limite=8,
            perfil_deslocamento="comercial",
            limite_minutos=25,
        )
        proximidade_mock = {
            "ok": True,
            "sugerir": False,
            "mensagem": "mock proximidade",
            "politica_oferta": {
                "distante_base": True,
                "baixa_frequencia": True,
                "ancora_d2": False,
                "datas_preferenciais": ["2026-05-26", "2026-05-27"],
            },
            "item": None,
        }

        def _mock_panorama(*, payload, db, current_user):
            mapa = {
                "2026-05-26": {"ok": True, "data": "2026-05-26", "items": [], "motivo": "sem janela", "itens_ignorados_janela": 0},
                "2026-05-27": self._panorama_mock("2026-05-27", categoria="data_vazia", total_itens=2),
                "2026-05-23": self._panorama_mock("2026-05-23", categoria="ancora", total_itens=2),
            }
            return mapa[str(payload.data)]

        with self._session_factory() as db, patch.object(
            agenda, "sugerir_agendamento_proximo", return_value=proximidade_mock
        ), patch.object(
            agenda, "sugerir_horarios_agenda", side_effect=_mock_panorama
        ) as mocked_panorama, patch.object(
            agenda, "_registrar_evento_funil_assistente", return_value=None
        ):
            resposta = agenda.orquestrar_ofertas_assistente(
                payload=payload,
                request=None,
                db=db,
                current_user=self._admin(),
            )

        self.assertTrue(resposta["ok"])
        self.assertEqual(resposta["origem_data_automatica"], "manual")
        self.assertEqual(resposta["data_base"], "2026-05-23")
        datas_consultadas = [chamada.kwargs["payload"].data for chamada in mocked_panorama.call_args_list]
        self.assertEqual(datas_consultadas, ["2026-05-26", "2026-05-27", "2026-05-23"])

    def test_orquestrador_busca_dias_seguintes_quando_panorama_inicial_vazio(self) -> None:
        payload = agenda.AssistenteOfertaPayload(
            clinica_id=1,
            data="2030-06-01",
            data_contato="2030-06-01",
            servico_id=1,
            duracao_minutos=30,
            intervalo_minutos=30,
            limite=8,
            perfil_deslocamento="comercial",
            limite_minutos=25,
        )
        proximidade_mock = {
            "ok": True,
            "sugerir": False,
            "mensagem": "mock proximidade",
            "politica_oferta": {
                "distante_base": True,
                "baixa_frequencia": True,
                "ancora_d2": False,
                "datas_preferenciais": ["2030-06-04", "2030-06-05"],
            },
            "item": None,
        }

        def _mock_panorama(*, payload, db, current_user):
            mapa = {
                "2030-06-04": {"ok": True, "data": "2030-06-04", "items": [], "motivo": "sem horario util", "itens_ignorados_janela": 0},
                "2030-06-05": {"ok": True, "data": "2030-06-05", "items": [], "motivo": "sem horario util", "itens_ignorados_janela": 0},
                "2030-06-01": {"ok": True, "data": "2030-06-01", "items": [], "motivo": "sem horario util", "itens_ignorados_janela": 0},
                "2030-06-06": {"ok": True, "data": "2030-06-06", "items": [], "motivo": "sem horario util", "itens_ignorados_janela": 0},
                "2030-06-07": self._panorama_mock("2030-06-07", categoria="ancora", total_itens=2),
                "2030-06-08": self._panorama_mock("2030-06-08", categoria="data_vazia", total_itens=2),
            }
            return mapa.get(
                str(payload.data),
                {"ok": True, "data": str(payload.data), "items": [], "motivo": "sem horario util", "itens_ignorados_janela": 0},
            )

        with self._session_factory() as db, patch.object(
            agenda, "sugerir_agendamento_proximo", return_value=proximidade_mock
        ), patch.object(
            agenda, "sugerir_horarios_agenda", side_effect=_mock_panorama
        ) as mocked_panorama, patch.object(
            agenda, "_registrar_evento_funil_assistente", return_value=None
        ):
            resposta = agenda.orquestrar_ofertas_assistente(
                payload=payload,
                request=None,
                db=db,
                current_user=self._admin(),
            )

        self.assertTrue(resposta["ok"])
        self.assertEqual(resposta["origem_data_automatica"], "progressao_dias")
        self.assertEqual(resposta["data_base"], "2030-06-07")
        self.assertIn("busca progressiva", str(resposta.get("mensagem_panorama") or "").lower())
        datas_consultadas = [chamada.kwargs["payload"].data for chamada in mocked_panorama.call_args_list]
        self.assertEqual(
            datas_consultadas,
            ["2030-06-04", "2030-06-05", "2030-06-01", "2030-06-02", "2030-06-03", "2030-06-06", "2030-06-07", "2030-06-08"],
        )

    def test_orquestrador_varre_intervalo_candidato_e_empurra_data_vazia_para_terceiro_lugar(self) -> None:
        payload = agenda.AssistenteOfertaPayload(
            clinica_id=1,
            data="2030-06-08",
            data_contato="2030-06-08",
            servico_id=1,
            duracao_minutos=20,
            intervalo_minutos=30,
            limite=8,
            perfil_deslocamento="comercial",
            limite_minutos=20,
            janela_dias_proximidade=7,
        )
        proximidade_mock = {
            "ok": True,
            "sugerir": True,
            "mensagem": "mock proximidade",
            "politica_oferta": {
                "distante_base": True,
                "baixa_frequencia": True,
                "ancora_d2": False,
                "datas_preferenciais": ["2030-06-11"],
            },
            "item": {
                "data": "2030-06-12",
                "inicio": "14:00",
                "data_preferencial": False,
            },
        }

        def _mock_panorama(*, payload, db, current_user):
            mapa = {
                "2030-06-08": self._panorama_mock("2030-06-08", categoria="operacional", total_itens=2),
                "2030-06-09": self._panorama_mock("2030-06-09", categoria="ancora", total_itens=2),
                "2030-06-10": self._panorama_mock("2030-06-10", categoria="operacional", total_itens=2),
                "2030-06-11": self._panorama_mock("2030-06-11", categoria="data_vazia", total_itens=2),
                "2030-06-12": self._panorama_mock("2030-06-12", categoria="operacional", total_itens=2),
            }
            return mapa.get(
                str(payload.data),
                {"ok": True, "data": str(payload.data), "items": [], "motivo": "sem horario util", "itens_ignorados_janela": 0},
            )

        with self._session_factory() as db, patch.object(
            agenda, "sugerir_agendamento_proximo", return_value=proximidade_mock
        ), patch.object(
            agenda, "sugerir_horarios_agenda", side_effect=_mock_panorama
        ) as mocked_panorama, patch.object(
            agenda, "_registrar_evento_funil_assistente", return_value=None
        ):
            resposta = agenda.orquestrar_ofertas_assistente(
                payload=payload,
                request=None,
                db=db,
                current_user=self._admin(),
            )

        self.assertTrue(resposta["ok"])
        datas_consultadas = [chamada.kwargs["payload"].data for chamada in mocked_panorama.call_args_list]
        self.assertEqual(datas_consultadas, ["2030-06-12", "2030-06-11", "2030-06-08", "2030-06-09", "2030-06-10"])
        datas_hierarquizadas = resposta["panorama_ofertas"]["datas_hierarquizadas"]
        self.assertEqual(
            [item["categoria"] for item in datas_hierarquizadas],
            ["ancora", "operacional", "data_vazia"],
        )
        self.assertEqual(
            [item["data"] for item in datas_hierarquizadas],
            ["2030-06-09", "2030-06-12", "2030-06-11"],
        )
        self.assertEqual(
            [item["hierarquia_data"] for item in resposta["panorama_ofertas"]["items"]],
            ["2030-06-09", "2030-06-09", "2030-06-12", "2030-06-12", "2030-06-11", "2030-06-11"],
        )


class AgendaAssistenteMetricasTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self._tmpdir.name) / "agenda-assistente-metricas.db"
        self._engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
        self._session_factory = sessionmaker(bind=self._engine, autocommit=False, autoflush=False)
        AuditoriaEvento.__table__.create(self._engine, checkfirst=True)

    def tearDown(self) -> None:
        self._engine.dispose()
        self._tmpdir.cleanup()

    def _admin(self):
        return SimpleNamespace(id=1, nome="Admin", email="admin@fortcordis.com", tem_papel=lambda p: p == "admin")

    def test_metricas_funil_agrega_por_etapa_perfil_e_clinica(self) -> None:
        eventos = [
            AuditoriaEvento(
                modulo="agenda",
                entidade="assistente_agendamento",
                acao="ASSISTENTE_AGENDA_OFERTA_GERADA",
                detalhes_json='{"perfil_usuario":"nao_admin","clinica_id":10,"clinica_nome":"Casa Pet"}',
                created_at=datetime(2026, 5, 23, 12, 0, 0),
            ),
            AuditoriaEvento(
                modulo="agenda",
                entidade="assistente_agendamento",
                acao="ASSISTENTE_AGENDA_ACEITE",
                detalhes_json='{"perfil_usuario":"nao_admin","clinica_id":10,"clinica_nome":"Casa Pet"}',
                created_at=datetime(2026, 5, 23, 12, 5, 0),
            ),
            AuditoriaEvento(
                modulo="agenda",
                entidade="assistente_agendamento",
                acao="ASSISTENTE_AGENDA_SOLICITACAO_EXCECAO",
                detalhes_json='{"perfil_usuario":"admin","clinica_id":12,"clinica_nome":"Vet World"}',
                created_at=datetime(2026, 5, 24, 9, 0, 0),
            ),
        ]
        with self._session_factory() as db:
            db.add_all(eventos)
            db.commit()
            resposta = agenda.obter_metricas_funil_assistente(
                data_inicio="2026-05-23",
                data_fim="2026-05-24",
                db=db,
                current_user=self._admin(),
            )

        totais = resposta["totais_por_etapa"]
        self.assertEqual(totais["oferta_gerada"], 1)
        self.assertEqual(totais["aceite"], 1)
        self.assertEqual(totais["solicitacao_excecao"], 1)
        self.assertEqual(resposta["por_perfil"]["nao_admin"]["aceite"], 1)
        self.assertEqual(resposta["por_perfil"]["admin"]["solicitacao_excecao"], 1)


if __name__ == "__main__":
    unittest.main()
