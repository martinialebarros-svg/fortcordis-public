import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "whatsapp-bot-metrics-test-secret-key-1234567890")

from app.api.v1.endpoints import whatsapp_bot
from app.models.configuracao import Configuracao
from app.models.whatsapp_bot import WhatsAppBotSolicitacao
from app.models.whatsapp_bot import WhatsAppBotResposta
from app.services import whatsapp_bot_metrics_service as metrics


class WhatsAppBotMetricsTest(unittest.TestCase):
    def _factory(self, tmpdir: str):
        db_path = Path(tmpdir) / "whatsapp-bot-metrics-test.db"
        engine = create_engine(f"sqlite:///{db_path}")
        for table in (WhatsAppBotResposta.__table__, WhatsAppBotSolicitacao.__table__, Configuracao.__table__):
            table.create(engine, checkfirst=True)
        return sessionmaker(bind=engine, autocommit=False, autoflush=False), engine

    def _add(
        self,
        db,
        *,
        job_id,
        decisao,
        motivo=None,
        match_type="tutor",
        texto_gerado=None,
        texto_enviado=None,
        feedback=None,
        latencia_ms=None,
        input_tokens=0,
        output_tokens=0,
        wa_identity="558599990001",
        created_at=None,
    ):
        db.add(
            WhatsAppBotResposta(
                job_id=job_id,
                wa_identity=wa_identity,
                conversation_id=f"conv-{job_id}",
                decisao=decisao,
                motivo=motivo,
                match_type=match_type,
                texto_gerado=texto_gerado,
                texto_enviado=texto_enviado,
                feedback=feedback,
                latencia_ms=latencia_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                created_at=created_at or datetime.now(timezone.utc),
            )
        )

    def test_aceite_distingue_envio_limpo_de_envio_editado(self) -> None:
        """O endpoint grava feedback positivo mesmo quando houve edicao.

        Portanto o feedback sozinho superestima o aceite limpo; a metrica
        deriva "editado" de texto_enviado != texto_gerado.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    db.add(Configuracao())
                    self._add(db, job_id=1, decisao="sent", texto_gerado="A", texto_enviado="A", feedback="positivo")
                    self._add(db, job_id=2, decisao="sent", texto_gerado="A", texto_enviado="B editado", feedback="positivo")
                    self._add(db, job_id=3, decisao="draft", texto_gerado="C", feedback="negativo")
                    db.commit()
                    resultado = metrics.coletar_metricas_observacao(db)
                finally:
                    db.close()

                geral = resultado["geral"]
                self.assertEqual(geral["aceitos"], 2)
                self.assertEqual(geral["aceitos_sem_edicao"], 1)
                self.assertEqual(geral["aceitos_editados"], 1)
                self.assertEqual(geral["descartados"], 1)
                self.assertEqual(geral["decididos"], 3)
                self.assertAlmostEqual(geral["taxa_aceite"], 0.6667, places=3)
                self.assertAlmostEqual(geral["taxa_aceite_sem_edicao"], 0.3333, places=3)
                self.assertAlmostEqual(geral["taxa_edicao_entre_aceitos"], 0.5, places=3)
                self.assertAlmostEqual(geral["taxa_descarte"], 0.3333, places=3)
            finally:
                engine.dispose()

    def test_rascunho_pendente_nao_entra_no_denominador_do_aceite(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    db.add(Configuracao())
                    self._add(db, job_id=1, decisao="sent", texto_gerado="A", texto_enviado="A", feedback="positivo")
                    for i in range(5):
                        self._add(db, job_id=10 + i, decisao="draft", texto_gerado="pendente")
                    db.commit()
                    resultado = metrics.coletar_metricas_observacao(db)
                finally:
                    db.close()

                geral = resultado["geral"]
                self.assertEqual(geral["pendentes"], 5)
                self.assertEqual(geral["decididos"], 1)
                self.assertEqual(geral["taxa_aceite"], 1.0)
            finally:
                engine.dispose()

    def test_bloqueios_agregam_por_motivo(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    db.add(Configuracao())
                    self._add(db, job_id=1, decisao="blocked", motivo="diagnostico")
                    self._add(db, job_id=2, decisao="blocked", motivo="diagnostico")
                    self._add(db, job_id=3, decisao="blocked", motivo="valor_fora_tabela")
                    self._add(db, job_id=4, decisao="handoff", motivo="emergencia")
                    self._add(db, job_id=5, decisao="suppressed", motivo="janela_fechada")
                    self._add(db, job_id=6, decisao="draft", texto_gerado="ok")
                    db.commit()
                    resultado = metrics.coletar_metricas_observacao(db)
                finally:
                    db.close()

                geral = resultado["geral"]
                self.assertEqual(geral["bloqueios_por_motivo"], {"diagnostico": 2, "valor_fora_tabela": 1})
                self.assertEqual(geral["handoff_por_motivo"], {"emergencia": 1})
                self.assertEqual(geral["supressao_por_motivo"], {"janela_fechada": 1})
                # 3 bloqueados sobre (1 rascunho + 3 bloqueados)
                self.assertEqual(geral["taxa_bloqueio"], 0.75)
                # contencao: 1 rascunho sobre (1 rascunho + 3 bloqueados + 1 handoff)
                self.assertEqual(geral["taxa_contencao"], 0.2)
            finally:
                engine.dispose()

    def test_quebra_por_persona_e_por_faixa_de_horario(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    db.add(Configuracao())
                    self._add(db, job_id=1, decisao="sent", match_type="tutor",
                              texto_gerado="A", texto_enviado="A", feedback="positivo")
                    self._add(db, job_id=2, decisao="draft", match_type="clinica",
                              texto_gerado="B", feedback="negativo")
                    self._add(db, job_id=3, decisao="handoff", match_type=None,
                              motivo="identidade_nao_resolvida")
                    db.commit()
                    # Expediente deterministico: alterna dentro/fora por linha.
                    with patch.object(
                        metrics._ClassificadorDeFaixa,
                        "classificar",
                        side_effect=["expediente", "fora_expediente", "expediente"],
                        autospec=False,
                    ):
                        resultado = metrics.coletar_metricas_observacao(db)
                finally:
                    db.close()

                self.assertEqual(set(resultado["por_persona"]), {"tutor", "clinica", "nao_resolvido"})
                self.assertEqual(resultado["por_persona"]["tutor"]["aceitos"], 1)
                self.assertEqual(resultado["por_persona"]["clinica"]["descartados"], 1)
                self.assertEqual(resultado["por_persona"]["nao_resolvido"]["handoffs"], 1)
                self.assertEqual(set(resultado["por_faixa_horario"]), {"expediente", "fora_expediente"})
                self.assertIn("tutor:expediente", resultado["por_persona_e_faixa"])
                self.assertIn("clinica:fora_expediente", resultado["por_persona_e_faixa"])
            finally:
                engine.dispose()

    def test_latencia_p50_p95_e_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    db.add(Configuracao())
                    for i, lat in enumerate([100, 200, 300, 400, 5000]):
                        self._add(db, job_id=i + 1, decisao="draft", texto_gerado="x",
                                  latencia_ms=lat, input_tokens=1000, output_tokens=100)
                    db.commit()
                    resultado = metrics.coletar_metricas_observacao(db)
                finally:
                    db.close()

                geral = resultado["geral"]
                self.assertEqual(geral["amostras_latencia"], 5)
                self.assertEqual(geral["latencia_p50_ms"], 300)
                self.assertEqual(geral["latencia_p95_ms"], 5000)
                self.assertEqual(geral["input_tokens"], 5000)
                self.assertEqual(geral["output_tokens"], 500)
            finally:
                engine.dispose()

    def test_custo_nao_configurado_nao_finge_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    db.add(Configuracao())
                    self._add(db, job_id=1, decisao="draft", texto_gerado="x",
                              input_tokens=1_000_000, output_tokens=1_000_000)
                    db.commit()
                    with patch.object(metrics.settings, "WHATSAPP_BOT_INPUT_COST_PER_MILLION", 0.0):
                        with patch.object(metrics.settings, "WHATSAPP_BOT_OUTPUT_COST_PER_MILLION", 0.0):
                            sem_taxa = metrics.coletar_metricas_observacao(db)
                    with patch.object(metrics.settings, "WHATSAPP_BOT_INPUT_COST_PER_MILLION", 2.0):
                        with patch.object(metrics.settings, "WHATSAPP_BOT_OUTPUT_COST_PER_MILLION", 8.0):
                            com_taxa = metrics.coletar_metricas_observacao(db)
                finally:
                    db.close()

                self.assertFalse(sem_taxa["geral"]["custo_configurado"])
                self.assertIsNone(sem_taxa["geral"]["custo_total"])
                self.assertTrue(com_taxa["geral"]["custo_configurado"])
                self.assertAlmostEqual(com_taxa["geral"]["custo_total"], 10.0, places=6)
                self.assertAlmostEqual(com_taxa["geral"]["custo_por_conversa"], 10.0, places=6)
            finally:
                engine.dispose()

    def test_janela_exclui_respostas_antigas(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    db.add(Configuracao())
                    agora = datetime.now(timezone.utc)
                    self._add(db, job_id=1, decisao="draft", texto_gerado="recente", created_at=agora)
                    self._add(db, job_id=2, decisao="draft", texto_gerado="antigo",
                              created_at=agora - timedelta(days=30))
                    db.commit()
                    resultado = metrics.coletar_metricas_observacao(db, dias=7)
                finally:
                    db.close()
                self.assertEqual(resultado["total_respostas"], 1)
                self.assertEqual(resultado["janela_dias"], 7)
            finally:
                engine.dispose()

    def test_checklist_de_auto_nunca_autoriza_sozinho(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    db.add(Configuracao())
                    self._add(db, job_id=1, decisao="sent", match_type="tutor",
                              texto_gerado="A", texto_enviado="A", feedback="positivo")
                    db.commit()
                    resultado = metrics.coletar_metricas_observacao(db)
                finally:
                    db.close()

                checklist = resultado["pronto_para_decidir_auto"]
                self.assertFalse(checklist["amostra_suficiente_nas_duas_personas"])
                self.assertEqual(checklist["decididos_por_persona"], {"tutor": 1})
                self.assertEqual(checklist["personas_com_amostra_suficiente"], [])
                self.assertIn("autorizacao humana explicita", checklist["observacao"])
            finally:
                engine.dispose()

    def test_classificador_memoizado_equivale_a_funcao_original(self) -> None:
        """A memoizacao existe para nao consultar a agenda por linha.

        O resultado precisa ser identico ao de `is_within_operating_window`,
        que e a fonte da RF-033 - senao a faixa de horario da metrica passaria
        a divergir do texto que o cliente recebe no handoff.
        """
        from app.services.whatsapp_bot_handoff_service import is_within_operating_window

        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    db.add(Configuracao())
                    db.commit()

                    classificador = metrics._ClassificadorDeFaixa(db)
                    base = datetime(2026, 8, 24, tzinfo=timezone.utc)  # segunda
                    divergencias = []
                    # Sete dias x 24 horas cobre dia util, sabado, domingo,
                    # antes de abrir, dentro e depois de fechar.
                    for dia in range(7):
                        for hora in range(24):
                            momento = base + timedelta(days=dia, hours=hora)
                            esperado = (
                                "expediente"
                                if is_within_operating_window(db, now=momento)
                                else "fora_expediente"
                            )
                            obtido = classificador.classificar(momento)
                            if obtido != esperado:
                                divergencias.append((momento.isoformat(), esperado, obtido))
                finally:
                    db.close()
                self.assertEqual(divergencias, [], "memoizacao divergiu da fonte da RF-033")
            finally:
                engine.dispose()

    def test_classificador_consulta_a_agenda_uma_unica_vez(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    db.add(Configuracao())
                    agora = datetime.now(timezone.utc)
                    for i in range(25):
                        self._add(db, job_id=i + 1, decisao="draft", texto_gerado="x",
                                  created_at=agora - timedelta(hours=i))
                    db.commit()
                    with patch.object(
                        metrics,
                        "_agenda_configuration_rules",
                        wraps=metrics._agenda_configuration_rules,
                    ) as espiao:
                        resultado = metrics.coletar_metricas_observacao(db)
                finally:
                    db.close()

                self.assertEqual(resultado["total_respostas"], 25)
                self.assertEqual(espiao.call_count, 1, "regras da agenda recarregadas por linha")
            finally:
                engine.dispose()

    def test_endpoint_e_somente_leitura(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    db.add(Configuracao())
                    self._add(db, job_id=1, decisao="draft", texto_gerado="x")
                    db.commit()
                    antes = db.query(WhatsAppBotResposta).count()
                    payload = whatsapp_bot.metricas_observacao(
                        dias=7, db=db, current_user=SimpleNamespace(id=1)
                    )
                    depois = db.query(WhatsAppBotResposta).count()
                finally:
                    db.close()

                self.assertEqual(antes, depois)
                self.assertIn("geral", payload)
                self.assertIn("por_persona", payload)
                self.assertIn("pronto_para_decidir_auto", payload)
            finally:
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
