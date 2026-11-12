import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "whatsapp-bot-gates-test-secret-key-1234567890")

from app.models.configuracao import Configuracao
from app.models.whatsapp_bot import WhatsAppBotConversaEstado
from app.services import whatsapp_bot_gates as gates


class WhatsAppBotGatesTest(unittest.TestCase):
    def _build_session_factory(self, tmpdir: str):
        db_path = Path(tmpdir) / "whatsapp-bot-gates-test.db"
        engine = create_engine(f"sqlite:///{db_path}")
        Configuracao.__table__.create(engine, checkfirst=True)
        WhatsAppBotConversaEstado.__table__.create(engine, checkfirst=True)
        return sessionmaker(bind=engine, autocommit=False, autoflush=False), engine

    # --- RF-008 -------------------------------------------------------

    def test_is_whatsapp_bot_enabled_exige_env_e_banco(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                with patch.object(gates, "SessionLocal", SessionFactory):
                    with patch.object(gates.settings, "WHATSAPP_BOT_ENABLED", False):
                        self.assertFalse(gates.is_whatsapp_bot_enabled())

                    with patch.object(gates.settings, "WHATSAPP_BOT_ENABLED", True):
                        self.assertFalse(gates.is_whatsapp_bot_enabled())

                        db = SessionFactory()
                        try:
                            db.add(Configuracao(whatsapp_bot_atendimento_habilitado=True))
                            db.commit()
                        finally:
                            db.close()

                        self.assertTrue(gates.is_whatsapp_bot_enabled())
            finally:
                engine.dispose()

    # --- RF-009 ---------------------------------------------------------

    def test_resolve_conversation_mode_sem_estado_usa_default_institucional(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                db = SessionFactory()
                try:
                    db.add(Configuracao(whatsapp_bot_modo="auto"))
                    db.commit()
                    self.assertEqual(gates.resolve_conversation_mode(db, "558588018899"), "auto")
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_resolve_conversation_mode_sem_configuracao_usa_suggest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                db = SessionFactory()
                try:
                    self.assertEqual(gates.resolve_conversation_mode(db, "558588018899"), "suggest")
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_resolve_conversation_mode_com_estado_por_conversa_sobrepoe_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                db = SessionFactory()
                try:
                    db.add(Configuracao(whatsapp_bot_modo="suggest"))
                    db.add(WhatsAppBotConversaEstado(wa_identity="558588018899", modo="off"))
                    db.commit()
                    self.assertEqual(gates.resolve_conversation_mode(db, "558588018899"), "off")
                finally:
                    db.close()
            finally:
                engine.dispose()

    # --- RF-010 ---------------------------------------------------------

    def test_is_locally_paused(self) -> None:
        now = datetime.now(timezone.utc)
        self.assertFalse(gates.is_locally_paused(None, now=now))
        estado_sem_pausa = WhatsAppBotConversaEstado(wa_identity="x", pausado_ate=None)
        self.assertFalse(gates.is_locally_paused(estado_sem_pausa, now=now))
        estado_pausado = WhatsAppBotConversaEstado(wa_identity="x", pausado_ate=now + timedelta(hours=1))
        self.assertTrue(gates.is_locally_paused(estado_pausado, now=now))
        estado_expirado = WhatsAppBotConversaEstado(wa_identity="x", pausado_ate=now - timedelta(minutes=1))
        self.assertFalse(gates.is_locally_paused(estado_expirado, now=now))

    def test_pause_conversation_cria_estado_e_usa_pause_hours_configurado(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                db = SessionFactory()
                try:
                    now = datetime.now(timezone.utc)
                    with patch.object(gates.settings, "WHATSAPP_BOT_HANDOFF_PAUSE_HOURS", 6):
                        gates.pause_conversation(db, "558588018899", now=now)
                    db.commit()

                    estado = gates.resolve_conversation_state(db, "558588018899")
                    self.assertIsNotNone(estado)
                    pausado_ate = estado.pausado_ate.replace(tzinfo=timezone.utc)
                    self.assertAlmostEqual(pausado_ate.timestamp(), (now + timedelta(hours=6)).timestamp(), delta=1)
                finally:
                    db.close()
            finally:
                engine.dispose()

    # --- RF-012 -----------------------------------------------------------

    def test_customer_service_window(self) -> None:
        now = datetime.now(timezone.utc)
        self.assertFalse(gates.is_customer_service_window_open(None, now=now))
        self.assertTrue(gates.is_customer_service_window_open(now - timedelta(hours=1), now=now))
        self.assertTrue(gates.is_customer_service_window_open(now - timedelta(hours=23, minutes=59), now=now))
        self.assertFalse(gates.is_customer_service_window_open(now - timedelta(hours=24, minutes=1), now=now))

    # --- RF-013 -----------------------------------------------------------

    def test_is_supported_message_type(self) -> None:
        self.assertTrue(gates.is_supported_message_type("text"))
        self.assertTrue(gates.is_supported_message_type("Text"))
        self.assertTrue(gates.is_supported_message_type(None))
        for tipo in ("audio", "image", "document", "sticker", "reaction", "interactive", "button"):
            self.assertFalse(gates.is_supported_message_type(tipo), tipo)

    # --- RF-011/RF-023: vocabulario -----------------------------------

    def test_detecta_pedido_humano(self) -> None:
        self.assertTrue(gates.detecta_pedido_humano("Quero falar com um atendente, por favor"))
        self.assertTrue(gates.detecta_pedido_humano("VOCÊ É UM ROBÔ?"))
        self.assertFalse(gates.detecta_pedido_humano("Qual o horário de funcionamento?"))
        self.assertFalse(gates.detecta_pedido_humano(""))

    def test_detecta_emergencia(self) -> None:
        self.assertTrue(gates.detecta_emergencia("Meu cachorro não está respirando!"))
        self.assertTrue(gates.detecta_emergencia("ele convulsionou agora"))
        self.assertFalse(gates.detecta_emergencia("queria marcar uma consulta de rotina"))
        self.assertFalse(gates.detecta_emergencia(""))



class WhatsAppBotPausaAssistidaTest(unittest.TestCase):
    """A pausa do envio assistido e separada da de handoff (2026-08-25).

    Medido em producao: uma resposta assistida silenciava o bot por 12h, e as
    mensagens seguintes do cliente viravam `suppressed/pausado`. As duas
    semanticas sao diferentes - handoff e "a equipe assumiu", envio assistido e
    "um atendente respondeu esta mensagem".
    """

    def _factory(self, tmpdir: str):
        db_path = Path(tmpdir) / "pausa-assistida.db"
        engine = create_engine(f"sqlite:///{db_path}")
        Configuracao.__table__.create(engine, checkfirst=True)
        WhatsAppBotConversaEstado.__table__.create(engine, checkfirst=True)
        return sessionmaker(bind=engine, autocommit=False, autoflush=False), engine

    def test_horas_explicitas_vencem_o_default_de_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    now = datetime.now(timezone.utc)
                    with patch.object(gates.settings, "WHATSAPP_BOT_HANDOFF_PAUSE_HOURS", 12):
                        gates.pause_conversation(db, "558599990001", now=now, horas=2)
                    db.commit()
                    estado = gates.resolve_conversation_state(db, "558599990001")
                    pausado = estado.pausado_ate.replace(tzinfo=timezone.utc)
                    self.assertAlmostEqual(
                        pausado.timestamp(), (now + timedelta(hours=2)).timestamp(), delta=2
                    )
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_sem_horas_preserva_o_comportamento_de_handoff(self) -> None:
        """Os demais chamadores nao passam `horas` e nao podem mudar."""
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    now = datetime.now(timezone.utc)
                    with patch.object(gates.settings, "WHATSAPP_BOT_HANDOFF_PAUSE_HOURS", 12):
                        gates.pause_conversation(db, "558599990002", now=now)
                    db.commit()
                    estado = gates.resolve_conversation_state(db, "558599990002")
                    pausado = estado.pausado_ate.replace(tzinfo=timezone.utc)
                    self.assertAlmostEqual(
                        pausado.timestamp(), (now + timedelta(hours=12)).timestamp(), delta=2
                    )
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_horas_invalidas_caem_no_default(self) -> None:
        for invalido in (0, -5):
            with self.subTest(horas=invalido):
                with tempfile.TemporaryDirectory() as tmpdir:
                    Factory, engine = self._factory(tmpdir)
                    try:
                        db = Factory()
                        try:
                            now = datetime.now(timezone.utc)
                            with patch.object(gates.settings, "WHATSAPP_BOT_HANDOFF_PAUSE_HOURS", 12):
                                gates.pause_conversation(db, "558599990003", now=now, horas=invalido)
                            db.commit()
                            estado = gates.resolve_conversation_state(db, "558599990003")
                            pausado = estado.pausado_ate.replace(tzinfo=timezone.utc)
                            self.assertAlmostEqual(
                                pausado.timestamp(), (now + timedelta(hours=12)).timestamp(), delta=2
                            )
                        finally:
                            db.close()
                    finally:
                        engine.dispose()

    def test_helper_da_pausa_assistida_e_curto_e_defensivo(self) -> None:
        with patch.object(gates.settings, "WHATSAPP_BOT_ASSISTED_SEND_PAUSE_HOURS", 3):
            self.assertEqual(gates._assisted_send_pause_hours(), 3)
        for invalido in (0, -1, "nao-numero", None):
            with self.subTest(valor=invalido):
                with patch.object(gates.settings, "WHATSAPP_BOT_ASSISTED_SEND_PAUSE_HOURS", invalido):
                    self.assertEqual(gates._assisted_send_pause_hours(), 0)

    def test_pausa_assistida_e_menor_que_a_de_handoff_por_default(self) -> None:
        """Se um dia os defaults se igualarem, a separacao perdeu o sentido."""
        self.assertLess(
            gates._assisted_send_pause_hours(), gates._pause_hours(),
            "a pausa do envio assistido precisa ser mais curta que a de handoff",
        )


if __name__ == "__main__":
    unittest.main()


class WhatsAppBotCortesiaTest(unittest.TestCase):
    """RF-P11: mensagem que nao pede resposta.

    A tabela que importa e NAO_CORTESIA: falso positivo cala o bot diante de
    uma pergunta de verdade. Ela e quase toda o resultado de um ataque
    adversarial (2026-08-25) que produziu 79 falsos positivos contra a primeira
    versao do detector - todos regressao permanente daqui em diante.
    """

    CORTESIA = [
        "Bom dia, obrigada.",
        "obrigada!",
        "Ok",
        "ok, obrigado",
        "Bom dia",
        "boa tarde",
        "blz",
        "perfeito, obrigada",
        "entendi, obrigado",
        "oi",
        "combinado",
        "ata",
        "de nada",
        "obrigada, boa semana",
        "Certo, obrigado. Abraco",
        "vlw",
        "boa, obrigado",
        "bom diaa",
        "obrigadaa",
        "oieee",
        "kkkk",
        "Obrigada Dra!",
        "Perfeito doutora, muito obrigada!",
        "Obrigada pela atencao",
        "que Deus abencoe",
        "Entao ta bom, obrigada!",
        "as ordens",
        "Show de bola",
        "Tenha um bom dia",
        "obrigada desde ja",
        "no aguardo",
        "pode deixar",
        "oi tudo bem entao ta",
    ]

    # Erro grave: o bot ficaria mudo. Quase todos vieram do ataque adversarial.
    NAO_CORTESIA = [
        "?",
        "??",
        "??!!",
        "???",
        "Ah é?",
        "Beleza pra vcs?",
        "Boa tarde, o laudo saiu?",
        "Boa, e aí?",
        "Bom dia\nOk pra vcs?\nObrigada",
        "Bom dia, e aí?",
        "Bom dia, segue a solicitacao",
        "Bom dia, voces fazem eco?",
        "Bom dia. Quanto custa o ecocardiograma?",
        "Certo então?",
        "Certo?",
        "Combinado?",
        "E aí?",
        "E então?",
        "Entendi, e aí?",
        "Fechado?",
        "Hum?",
        "Isso mesmo?",
        "Já?",
        "Oi, e aí?",
        "Ok pra vc?",
        "Ok pra vcs?",
        "Ok?",
        "Pfv?",
        "Pode ser pra vcs? / Ta bom pra amanhã? (NAO falharam - contraexemplo)",
        "Por favor?",
        "Sem problemas?",
        "Show, e aí?",
        "Sim?",
        "Só isso?",
        "Ta bom então?",
        "Ta bom pra senhora?",
        "Ta bom pra vocês?",
        "Ta certo?",
        "Ta ok?",
        "Tranquilo?",
        "Tudo bem pra vcs?",
        "Tudo certo então?",
        "Tudo certo?",
        "Uhum?",
        "aguardo?",
        "blz, ok?",
        "bom dia?",
        "bom dia\\ntudo bem?\\nvcs?",
        "certo?",
        "da certo?",
        "da pra?",
        "de boa?",
        "e ai?",
        "e o aguardo",
        "e o senhor?",
        "e pra vc?",
        "e vcs?",
        "gente, ja?",
        "gente?",
        "hum, ta certo?",
        "isso ai?",
        "ja viu?",
        "ja?",
        "mesmo?",
        "meu cachorro esta passando mal",
        "ne?",
        "o sr?",
        "obrigada mas preciso remarcar",
        "obrigada!! vc ta ai?",
        "obrigada, qual o valor?",
        "obrigada\\nso isso?",
        "oi, preciso agendar",
        "ok, e o eletro sai hoje?",
        "ok?",
        "onde voces ficam",
        "perfeito, pode agendar para quinta",
        "por favor?",
        "quero falar com atendente",
        "sim?",
        "so isso?",
        "so pra vcs?",
        "ta ai?",
        "ta bom pra vcs?",
        "ta?",
        "tudo certo?",
        "vc ta ai?",
        "É?",
        "é isso?",
        "ó só",
        "🆘",
    ]

    def test_reconhece_cortesia(self) -> None:
        for texto in self.CORTESIA:
            with self.subTest(texto=texto):
                self.assertTrue(gates.detecta_cortesia(texto), f"deveria ser cortesia: {texto!r}")

    def test_nao_engole_mensagem_de_verdade(self) -> None:
        for texto in self.NAO_CORTESIA:
            with self.subTest(texto=texto):
                self.assertFalse(gates.detecta_cortesia(texto), f"engoliu mensagem real: {texto!r}")

    def test_interrogacao_sempre_desqualifica(self) -> None:
        """Regra 1, isolada.

        A normalizacao apaga pontuacao, entao sem esta regra "ok" e "ok?"
        chegam identicos ao casamento - mensagens opostas. E a pergunta pode
        ser feita INTEIRA com palavras de cortesia ("ta ai?", "ja viu?"), caso
        em que o teste de "sobrou algo?" nao acusa nada.
        """
        for texto in ("ok?", "certo?", "bom dia?", "tudo bem?", "obrigada?", "ta ai?"):
            with self.subTest(texto=texto):
                self.assertFalse(gates.detecta_cortesia(texto))

    def test_sem_letra_nenhuma_nao_arrisca(self) -> None:
        """Regra 2. Emoji e pontuacao sozinhos sao ambiguos demais.

        Custa uma geracao em "\U0001f44d" para nao classificar "\U0001f198" como
        "nao pede resposta". Numa cardiologia veterinaria o custo dos dois
        erros nao e o mesmo.
        """
        for texto in ("?", "???", "!!!", "...", "\U0001f44d", "\U0001f198"):
            with self.subTest(texto=texto):
                self.assertFalse(gates.detecta_cortesia(texto))

    def test_alongamento_nao_precisa_de_variante_na_lista(self) -> None:
        for texto in ("bom diaaaa", "obrigadaaa", "okk", "vlww", "blza"):
            with self.subTest(texto=texto):
                self.assertTrue(gates.detecta_cortesia(texto))

    def test_vazio_nao_e_cortesia(self) -> None:
        for texto in ("", "   ", None):
            with self.subTest(texto=texto):
                self.assertFalse(gates.detecta_cortesia(texto))

    def test_fonte_ilegivel_erra_para_gerar_e_nao_derruba_o_worker(self) -> None:
        gates.carregar_termos_cortesia.cache_clear()
        try:
            with patch.object(gates, "CORTESIA_TERMOS_PATH", Path("/inexistente/cortesia.json")):
                self.assertEqual(gates.carregar_termos_cortesia(), ())
                self.assertFalse(gates.detecta_cortesia("obrigada"))
        finally:
            gates.carregar_termos_cortesia.cache_clear()
