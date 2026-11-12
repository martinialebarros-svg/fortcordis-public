import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "whatsapp-bot-piloto-test-secret-key-1234567890")

from app.models.clinica import Clinica
from app.models.configuracao import Configuracao
from app.models.whatsapp_bot import WhatsAppBotSolicitacao
from app.models.whatsapp_bot import WhatsAppBotClinicaEstado, WhatsAppBotConversaEstado
from app.services import whatsapp_bot_gates as gates


class WhatsAppBotPilotoClinicaTest(unittest.TestCase):
    """Fase 2 do piloto por clinica: resolucao de modo com tres niveis."""

    def _factory(self, tmpdir: str):
        db_path = Path(tmpdir) / "piloto.db"
        engine = create_engine(f"sqlite:///{db_path}")
        for table in (
            Configuracao.__table__,
            Clinica.__table__,
            WhatsAppBotConversaEstado.__table__,
            WhatsAppBotClinicaEstado.__table__,
        ):
            table.create(engine, checkfirst=True)
        return sessionmaker(bind=engine, autocommit=False, autoflush=False), engine

    def _cenario(self, db, *, participacao="todos", modo_institucional="suggest"):
        db.add(
            Configuracao(
                whatsapp_bot_modo=modo_institucional,
                whatsapp_bot_participacao=participacao,
            )
        )
        db.add(Clinica(id=7, nome="Clinica Parceira", ativo=True))
        db.commit()

    def _resolver(self, db, *, match_type="clinica", clinica_id=7, modo_atual="suggest"):
        return gates.resolve_modo_efetivo(
            db,
            wa_identity="558588018899",
            match_type=match_type,
            clinica_id=clinica_id,
            modo_atual=modo_atual,
        )

    # --- CA-P01: postura `todos` preserva o comportamento atual -----------

    def test_todos_sem_linha_de_clinica_nao_bloqueia(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    self._cenario(db, participacao="todos")
                    modo, bloqueio = self._resolver(db)
                finally:
                    db.close()
                self.assertEqual(modo, "suggest")
                self.assertIsNone(bloqueio)
            finally:
                engine.dispose()

    # --- CA-P02: piloto sem habilitacao e `fora_do_piloto` ----------------

    def test_piloto_sem_linha_de_clinica_bloqueia(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    self._cenario(db, participacao="piloto")
                    modo, bloqueio = self._resolver(db)
                finally:
                    db.close()
                self.assertEqual(modo, "off")
                self.assertEqual(bloqueio, "fora_do_piloto")
            finally:
                engine.dispose()

    # --- CA-P03: clinica habilitada gera normalmente ----------------------

    def test_piloto_com_clinica_habilitada_gera(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    self._cenario(db, participacao="piloto")
                    db.add(WhatsAppBotClinicaEstado(clinica_id=7, modo="suggest"))
                    db.commit()
                    modo, bloqueio = self._resolver(db)
                finally:
                    db.close()
                self.assertEqual(modo, "suggest")
                self.assertIsNone(bloqueio)
            finally:
                engine.dispose()

    # --- CA-P04: `off` explicito vale mesmo com postura `todos` -----------

    def test_clinica_off_explicito_bloqueia_mesmo_em_todos(self) -> None:
        """`off` da clinica e decisao, nao ausencia: vale nas duas posturas."""
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    self._cenario(db, participacao="todos")
                    db.add(WhatsAppBotClinicaEstado(clinica_id=7, modo="off"))
                    db.commit()
                    modo, bloqueio = self._resolver(db)
                finally:
                    db.close()
                self.assertEqual(modo, "off")
                self.assertEqual(bloqueio, "clinica_desabilitada")
            finally:
                engine.dispose()

    # --- CA-P05: conversa vence clinica, nas duas direcoes ----------------

    def test_conversa_vence_clinica_off(self) -> None:
        """Atendente liga o bot numa conversa de clinica desabilitada."""
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    self._cenario(db, participacao="piloto")
                    db.add(WhatsAppBotClinicaEstado(clinica_id=7, modo="off"))
                    db.add(WhatsAppBotConversaEstado(wa_identity="558588018899", modo="suggest"))
                    db.commit()
                    modo, bloqueio = self._resolver(db, modo_atual="suggest")
                finally:
                    db.close()
                self.assertEqual(modo, "suggest")
                self.assertIsNone(bloqueio, "conversa explicita tem que vencer a clinica")
            finally:
                engine.dispose()

    def test_conversa_off_vence_clinica_habilitada(self) -> None:
        """O caminho inverso ja e barrado antes, em `_process_job`.

        Aqui o que importa e que a participacao NAO reabra: com estado de
        conversa explicito, a funcao devolve o que o chamador trouxe.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    self._cenario(db, participacao="piloto")
                    db.add(WhatsAppBotClinicaEstado(clinica_id=7, modo="suggest"))
                    db.add(WhatsAppBotConversaEstado(wa_identity="558588018899", modo="off"))
                    db.commit()
                    modo, bloqueio = self._resolver(db, modo_atual="off")
                finally:
                    db.close()
                self.assertEqual(modo, "off")
                self.assertIsNone(bloqueio)
            finally:
                engine.dispose()

    # --- CA-P06: tutor no piloto ------------------------------------------

    def test_piloto_tutor_sem_opt_in_bloqueia(self) -> None:
        """Tutor nao tem agrupamento: em piloto so entra por conversa."""
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    self._cenario(db, participacao="piloto")
                    modo, bloqueio = self._resolver(db, match_type="tutor", clinica_id=None)
                finally:
                    db.close()
                self.assertEqual(modo, "off")
                self.assertEqual(bloqueio, "fora_do_piloto")
            finally:
                engine.dispose()

    def test_piloto_tutor_com_opt_in_gera(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    self._cenario(db, participacao="piloto")
                    db.add(WhatsAppBotConversaEstado(wa_identity="558588018899", modo="suggest"))
                    db.commit()
                    modo, bloqueio = self._resolver(db, match_type="tutor", clinica_id=None)
                finally:
                    db.close()
                self.assertEqual(modo, "suggest")
                self.assertIsNone(bloqueio)
            finally:
                engine.dispose()

    # --- CB-P04: escrituracao do worker nao pode virar opt-in -------------

    def test_pausa_grava_modo_nulo_e_nao_fura_o_piloto(self) -> None:
        """A linha da pausa nao pode valer como override.

        Sem `modo=None` no construtor E sem remover o default do model, o
        SQLAlchemy grava "suggest" sozinho: ele pula atributo None no INSERT
        e deixa o default Python disparar. A conversa fora do piloto passaria
        a ser atendida na mensagem seguinte.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    self._cenario(db, participacao="piloto")
                    gates.pause_conversation(db, "558588018899")
                    db.commit()
                    gravado = (
                        db.query(WhatsAppBotConversaEstado)
                        .filter(WhatsAppBotConversaEstado.wa_identity == "558588018899")
                        .one()
                    )
                    self.assertIsNone(gravado.modo)
                    self.assertIsNotNone(gravado.pausado_ate)
                    modo, bloqueio = self._resolver(db, match_type="tutor", clinica_id=None)
                finally:
                    db.close()
                self.assertEqual(modo, "off")
                self.assertEqual(bloqueio, "fora_do_piloto")
            finally:
                engine.dispose()

    def test_handoff_grava_modo_nulo_e_nao_fura_o_piloto(self) -> None:
        """Emergencia e pedido de humano passam por aqui.

        Pior que a pausa: `set_handoff_motivo` nao preenche `pausado_ate`, e
        `handoff_motivo` nao e portao em lugar nenhum - entao a proxima
        mensagem do mesmo numero ja chegaria ao gerador.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    self._cenario(db, participacao="piloto")
                    gates.set_handoff_motivo(db, "558588018899", "emergencia")
                    db.commit()
                    gravado = (
                        db.query(WhatsAppBotConversaEstado)
                        .filter(WhatsAppBotConversaEstado.wa_identity == "558588018899")
                        .one()
                    )
                    self.assertIsNone(gravado.modo)
                    self.assertEqual(gravado.handoff_motivo, "emergencia")
                    modo, bloqueio = self._resolver(db, match_type="tutor", clinica_id=None)
                finally:
                    db.close()
                self.assertEqual(modo, "off")
                self.assertEqual(bloqueio, "fora_do_piloto")
            finally:
                engine.dispose()

    def test_pausa_nao_desliga_clinica_habilitada(self) -> None:
        """A correcao nao pode passar do ponto: quem esta no piloto continua."""
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    self._cenario(db, participacao="piloto")
                    db.add(WhatsAppBotClinicaEstado(clinica_id=7, modo="suggest"))
                    gates.set_handoff_motivo(db, "558588018899", "pedido_humano")
                    db.commit()
                    modo, bloqueio = self._resolver(db, match_type="clinica", clinica_id=7)
                finally:
                    db.close()
                self.assertEqual(modo, "suggest")
                self.assertIsNone(bloqueio)
            finally:
                engine.dispose()

    def test_opt_in_deliberado_sobrevive_a_pausa_posterior(self) -> None:
        """Modo escolhido por gente continua vencendo o portao do piloto."""
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    self._cenario(db, participacao="piloto")
                    db.add(WhatsAppBotConversaEstado(wa_identity="558588018899", modo="suggest"))
                    db.commit()
                    gates.pause_conversation(db, "558588018899")
                    db.commit()
                    gravado = (
                        db.query(WhatsAppBotConversaEstado)
                        .filter(WhatsAppBotConversaEstado.wa_identity == "558588018899")
                        .one()
                    )
                    self.assertEqual(gravado.modo, "suggest")
                    modo, bloqueio = self._resolver(db, match_type="tutor", clinica_id=None)
                finally:
                    db.close()
                self.assertEqual(modo, "suggest")
                self.assertIsNone(bloqueio)
            finally:
                engine.dispose()

    # --- CB-P01: identidade ambigua ---------------------------------------

    def test_identidade_nao_resolvida_em_piloto_bloqueia_sem_inventar_clinica(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    self._cenario(db, participacao="piloto")
                    db.add(WhatsAppBotClinicaEstado(clinica_id=7, modo="suggest"))
                    db.commit()
                    modo, bloqueio = self._resolver(db, match_type=None, clinica_id=None)
                finally:
                    db.close()
                self.assertEqual(modo, "off")
                self.assertEqual(bloqueio, "fora_do_piloto")
            finally:
                engine.dispose()

    # --- CB-P03: voltar de piloto para todos preserva os `off` ------------

    def test_voltar_para_todos_preserva_off_explicito(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    self._cenario(db, participacao="todos")
                    db.add(WhatsAppBotClinicaEstado(clinica_id=7, modo="off"))
                    db.commit()
                    _, bloqueio = self._resolver(db)
                finally:
                    db.close()
                self.assertEqual(bloqueio, "clinica_desabilitada")
            finally:
                engine.dispose()

    # --- postura invalida falha para o lado seguro ------------------------

    def test_participacao_desconhecida_cai_em_todos(self) -> None:
        """O valor seguro aqui e o que NAO muda comportamento.

        `piloto` e decisao deliberada; nunca pode nascer de leitura suja.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    self._cenario(db, participacao="valor-invalido")
                    self.assertEqual(gates.resolve_participacao(db), "todos")
                    _, bloqueio = self._resolver(db)
                finally:
                    db.close()
                self.assertIsNone(bloqueio)
            finally:
                engine.dispose()

    # --- CA-P09: caminho barrado nao chama LLM ----------------------------

    def test_bloqueio_nao_chama_provider(self) -> None:
        """NFR-P02: barrar nao pode custar token nem consulta de dado."""
        from app.services import whatsapp_bot_generation as generation

        provider = Mock()
        provider.generate = Mock(side_effect=AssertionError("provider nao pode ser chamado"))

        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    self._cenario(db, participacao="piloto")
                    resultado = generation.gerar_resposta(
                        db,
                        wa_identity="558588018899",
                        corpo_mensagem="qual o horario?",
                        modo="suggest",
                        provider=provider,
                    )
                finally:
                    db.close()
                self.assertEqual(resultado.decisao, "suppressed")
                self.assertEqual(resultado.motivo, "fora_do_piloto")
                self.assertIsNone(resultado.texto_gerado)
                provider.generate.assert_not_called()
            finally:
                engine.dispose()


if __name__ == "__main__":
    unittest.main()


class WhatsAppBotPilotoEndpointsTest(unittest.TestCase):
    """RF-P07: leitura e escrita da participacao por clinica."""

    def _factory(self, tmpdir: str):
        db_path = Path(tmpdir) / "piloto-endpoints.db"
        engine = create_engine(f"sqlite:///{db_path}")
        for table in (
            Configuracao.__table__,
            Clinica.__table__,
            WhatsAppBotConversaEstado.__table__,
            WhatsAppBotClinicaEstado.__table__,
        ):
            table.create(engine, checkfirst=True)
        return sessionmaker(bind=engine, autocommit=False, autoflush=False), engine

    def _user(self, admin=True):
        from types import SimpleNamespace

        return SimpleNamespace(id=1, tem_papel=lambda papel: admin and papel == "admin")

    def test_listagem_deriva_participa_da_postura(self) -> None:
        """Sem linha, o mesmo estado significa coisas opostas nas duas posturas.

        Por isso `participa` e derivado no backend: deixar a tela inferir
        convidaria a errar justo no campo que decide exposicao.
        """
        from app.api.v1.endpoints import whatsapp_bot as endpoints

        for postura, esperado in (("todos", True), ("piloto", False)):
            with tempfile.TemporaryDirectory() as tmpdir:
                Factory, engine = self._factory(tmpdir)
                try:
                    db = Factory()
                    try:
                        db.add(Configuracao(whatsapp_bot_participacao=postura))
                        db.add(Clinica(id=7, nome="Parceira", ativo=True))
                        db.commit()
                        r = endpoints.listar_participacao_das_clinicas(db=db, current_user=self._user())
                    finally:
                        db.close()
                    self.assertEqual(r["participacao"], postura)
                    self.assertEqual(len(r["clinicas"]), 1)
                    self.assertIsNone(r["clinicas"][0]["modo"])
                    self.assertEqual(r["clinicas"][0]["participa"], esperado, postura)
                finally:
                    engine.dispose()

    def test_put_cria_e_atualiza_a_linha(self) -> None:
        from app.api.v1.endpoints import whatsapp_bot as endpoints

        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    db.add(Configuracao(whatsapp_bot_participacao="piloto"))
                    db.add(Clinica(id=7, nome="Parceira", ativo=True))
                    db.commit()
                    endpoints.atualizar_participacao_da_clinica(
                        7,
                        endpoints.WhatsAppBotClinicaEstadoUpdateRequest(modo="suggest", observacao="piloto"),
                        db=db,
                        current_user=self._user(),
                    )
                    endpoints.atualizar_participacao_da_clinica(
                        7,
                        endpoints.WhatsAppBotClinicaEstadoUpdateRequest(modo="off"),
                        db=db,
                        current_user=self._user(),
                    )
                    linhas = db.query(WhatsAppBotClinicaEstado).all()
                    self.assertEqual(len(linhas), 1, "PUT nao pode duplicar linha")
                    self.assertEqual(linhas[0].modo, "off")
                    self.assertEqual(linhas[0].habilitado_por_id, 1)
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_put_recusa_modo_invalido_e_clinica_inexistente(self) -> None:
        from fastapi import HTTPException

        from app.api.v1.endpoints import whatsapp_bot as endpoints

        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    db.add(Clinica(id=7, nome="Parceira", ativo=True))
                    db.commit()
                    with self.assertRaises(HTTPException) as ctx:
                        endpoints.atualizar_participacao_da_clinica(
                            7,
                            endpoints.WhatsAppBotClinicaEstadoUpdateRequest(modo="invalido"),
                            db=db,
                            current_user=self._user(),
                        )
                    self.assertEqual(ctx.exception.status_code, 422)

                    with self.assertRaises(HTTPException) as ctx2:
                        endpoints.atualizar_participacao_da_clinica(
                            999,
                            endpoints.WhatsAppBotClinicaEstadoUpdateRequest(modo="suggest"),
                            db=db,
                            current_user=self._user(),
                        )
                    self.assertEqual(ctx2.exception.status_code, 404)
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_clinica_inativa_nao_aparece_na_listagem(self) -> None:
        """CB-P02: linha de participacao nao ressuscita clinica desativada."""
        from app.api.v1.endpoints import whatsapp_bot as endpoints

        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    db.add(Configuracao(whatsapp_bot_participacao="piloto"))
                    db.add(Clinica(id=7, nome="Desativada", ativo=False))
                    db.add(WhatsAppBotClinicaEstado(clinica_id=7, modo="suggest"))
                    db.commit()
                    r = endpoints.listar_participacao_das_clinicas(db=db, current_user=self._user())
                finally:
                    db.close()
                self.assertEqual(r["clinicas"], [])
            finally:
                engine.dispose()


    def test_delete_devolve_ao_padrao_e_e_idempotente(self) -> None:
        """"Sem marcacao" e `off` sao estados DIFERENTES em `todos`.

        Sem o DELETE, marcar uma clinica para testar era irreversivel pela
        interface: o admin ficava preso entre dois estados quando o original
        era um terceiro.
        """
        from app.api.v1.endpoints import whatsapp_bot as endpoints

        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    db.add(Configuracao(whatsapp_bot_participacao="todos"))
                    db.add(Clinica(id=7, nome="Parceira", ativo=True))
                    db.commit()

                    endpoints.atualizar_participacao_da_clinica(
                        7,
                        endpoints.WhatsAppBotClinicaEstadoUpdateRequest(modo="off"),
                        db=db,
                        current_user=self._user(),
                    )
                    r = endpoints.listar_participacao_das_clinicas(db=db, current_user=self._user())
                    self.assertFalse(r["clinicas"][0]["participa"], "off exclui em `todos`")

                    endpoints.remover_participacao_da_clinica(7, db=db, current_user=self._user())
                    r = endpoints.listar_participacao_das_clinicas(db=db, current_user=self._user())
                    self.assertIsNone(r["clinicas"][0]["modo"])
                    self.assertTrue(
                        r["clinicas"][0]["participa"],
                        "sem marcacao tem que voltar a herdar o padrao institucional",
                    )
                    self.assertEqual(db.query(WhatsAppBotClinicaEstado).count(), 0)

                    # idempotente: remover de novo nao pode explodir
                    endpoints.remover_participacao_da_clinica(7, db=db, current_user=self._user())
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_sem_marcacao_e_off_so_coincidem_no_piloto(self) -> None:
        """A diferenca some em `piloto` - e e por isso que passa despercebida."""
        from app.api.v1.endpoints import whatsapp_bot as endpoints

        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    db.add(Configuracao(whatsapp_bot_participacao="piloto"))
                    db.add(Clinica(id=7, nome="Parceira", ativo=True))
                    db.commit()

                    sem_marcacao = endpoints.listar_participacao_das_clinicas(
                        db=db, current_user=self._user()
                    )["clinicas"][0]["participa"]
                    endpoints.atualizar_participacao_da_clinica(
                        7,
                        endpoints.WhatsAppBotClinicaEstadoUpdateRequest(modo="off"),
                        db=db,
                        current_user=self._user(),
                    )
                    com_off = endpoints.listar_participacao_das_clinicas(
                        db=db, current_user=self._user()
                    )["clinicas"][0]["participa"]
                finally:
                    db.close()
                self.assertEqual(sem_marcacao, com_off, "em piloto os dois ficam de fora")
                self.assertFalse(com_off)
            finally:
                engine.dispose()


class WhatsAppBotMetricaPorClinicaTest(unittest.TestCase):
    """Fase 4: sem quebra por clinica o retorno do piloto nao e atribuivel."""

    def _factory(self, tmpdir: str):
        from app.models.whatsapp_bot import WhatsAppBotJob, WhatsAppBotResposta

        db_path = Path(tmpdir) / "metrica-clinica.db"
        engine = create_engine(f"sqlite:///{db_path}")
        for table in (
            Configuracao.__table__,
            Clinica.__table__,
            WhatsAppBotJob.__table__,
            WhatsAppBotResposta.__table__, WhatsAppBotSolicitacao.__table__,
        ):
            table.create(engine, checkfirst=True)
        return sessionmaker(bind=engine, autocommit=False, autoflush=False), engine

    def _resposta(self, db, *, clinica_id, decisao, feedback=None, identidade="5585900000001"):
        from datetime import datetime, timezone

        from app.models.whatsapp_bot import WhatsAppBotJob, WhatsAppBotResposta

        job = WhatsAppBotJob(
            wa_identity=identidade,
            conversation_id="c1",
            wa_message_id=f"wamid.{identidade}.{decisao}.{clinica_id}",
            status="done",
            scheduled_for=datetime.now(timezone.utc),
        )
        db.add(job)
        db.commit()
        db.add(
            WhatsAppBotResposta(
                job_id=job.id,
                wa_identity=identidade,
                conversation_id="c1",
                decisao=decisao,
                motivo="teste",
                match_type="clinica",
                clinica_id=clinica_id,
                feedback=feedback,
            )
        )
        db.commit()

    def test_metrica_separa_clinica_boa_de_clinica_ruim(self) -> None:
        """O agregado esconde justamente o que o piloto precisa enxergar."""
        from app.services.whatsapp_bot_metrics_service import coletar_metricas_observacao

        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    db.add(Configuracao())
                    db.commit()
                    # clinica 1 aceita, clinica 2 descarta
                    self._resposta(db, clinica_id=1, decisao="sent", feedback="positivo", identidade="5585900000001")
                    self._resposta(db, clinica_id=1, decisao="sent", feedback="positivo", identidade="5585900000002")
                    self._resposta(db, clinica_id=2, decisao="draft", feedback="negativo", identidade="5585900000003")
                    m = coletar_metricas_observacao(db, dias=7)
                finally:
                    db.close()

                por_clinica = m["por_clinica"]
                self.assertIn("1", por_clinica)
                self.assertIn("2", por_clinica)
                self.assertEqual(por_clinica["1"]["aceitos"], 2)
                self.assertEqual(por_clinica["1"]["descartados"], 0)
                self.assertEqual(por_clinica["2"]["aceitos"], 0)
                self.assertEqual(por_clinica["2"]["descartados"], 1)
                # conversas distintas contadas por clinica, nao herdadas do geral
                self.assertEqual(por_clinica["1"]["conversas_distintas"], 2)
                self.assertEqual(por_clinica["2"]["conversas_distintas"], 1)
            finally:
                engine.dispose()

    def test_resposta_sem_clinica_nao_polui_a_quebra(self) -> None:
        """Tutor e identidade nao resolvida ficam so no agregado."""
        from app.services.whatsapp_bot_metrics_service import coletar_metricas_observacao

        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    db.add(Configuracao())
                    db.commit()
                    self._resposta(db, clinica_id=None, decisao="handoff")
                    m = coletar_metricas_observacao(db, dias=7)
                finally:
                    db.close()
                self.assertEqual(m["por_clinica"], {})
                self.assertEqual(m["total_respostas"], 1)
            finally:
                engine.dispose()
