"""RF-P19: indicar clinica parceira perto do tutor.

A RF-P17 orientava o tutor a "procurar a clinica de sua preferencia" sem dizer
QUAL -- resposta correta e inutil. Aqui ela vira acionavel.

O risco desta feature nao e o cliente: e a PERSONA ERRADA. Uma clinica
parceira perguntando onde ficam as outras receberia o mapa da rede de um
concorrente. Por isso a tool e exclusiva de tutor por allowlist, nao por
instrucao de prompt.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "whatsapp-bot-clinica-proxima-test-secret-123")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.clinica import Clinica
from app.models.tutor import Tutor
from app.services import whatsapp_bot_tools as tools
from app.services.whatsapp_bot_generation import _corpo_de_clinica_proxima
from app.services.whatsapp_bot_guardrails import avaliar_resposta, turno_a_partir_dos_resultados

# Coordenadas reais de Fortaleza, para a distancia ter significado.
ALDEOTA = (-3.7420, -38.4950)
MESSEJANA = (-3.8300, -38.4900)
CENTRO = (-3.7280, -38.5270)


class ClinicaProximaTest(unittest.TestCase):
    def _factory(self, tmpdir):
        engine = create_engine(f"sqlite:///{Path(tmpdir) / 'cp.db'}")
        for t in (Clinica.__table__, Tutor.__table__):
            t.create(engine, checkfirst=True)
        return sessionmaker(bind=engine, autocommit=False, autoflush=False), engine

    def _seed(self, db):
        db.add(Clinica(nome="Vet Aldeota", bairro="Aldeota", cidade="Fortaleza", endereco="Rua A, 100",
                       telefone="8533331111", latitude=ALDEOTA[0], longitude=ALDEOTA[1], ativo=1))
        db.add(Clinica(nome="Vet Messejana", bairro="Messejana", endereco="Rua B, 200",
                       telefone="8533332222", latitude=MESSEJANA[0], longitude=MESSEJANA[1], ativo=1))
        db.add(Clinica(nome="Vet Centro", bairro="Centro", endereco="Rua C, 300",
                       telefone="8533333333", latitude=CENTRO[0], longitude=CENTRO[1], ativo=1))
        db.add(Clinica(nome="Vet Desativada", bairro="Aldeota", endereco="Rua D, 400",
                       telefone="8533334444", latitude=ALDEOTA[0], longitude=ALDEOTA[1], ativo=0))
        db.commit()

    def _tutor(self, db, **kwargs):
        tutor = Tutor(nome="Maria", ativo=1, **kwargs)
        db.add(tutor)
        db.commit()
        return tutor

    # --- persona -----------------------------------------------------------

    def test_clinica_nao_ve_a_rede_de_parceiras(self) -> None:
        """O risco central: entregar o mapa da rede a um concorrente."""
        with tempfile.TemporaryDirectory() as tmp:
            Factory, engine = self._factory(tmp)
            try:
                db = Factory()
                try:
                    self._seed(db)
                    ctx = tools.WhatsAppBotToolContext(db=db, match_type="clinica", clinica_id=1)
                    res = tools.buscar_clinica_parceira(ctx, bairro="Aldeota")
                    self.assertFalse(res["ok"])
                    self.assertNotIn("Vet Aldeota", str(res))
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_tool_nao_existe_na_allowlist_da_persona_clinica(self) -> None:
        """Defesa por construcao, nao por instrucao de prompt."""
        self.assertIn("buscar_clinica_parceira", tools.TOOLS_POR_PERSONA["tutor"])
        self.assertNotIn("buscar_clinica_parceira", tools.TOOLS_POR_PERSONA["clinica"])

    # --- busca por bairro --------------------------------------------------

    def test_bairro_informado_ganha_de_qualquer_calculo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            Factory, engine = self._factory(tmp)
            try:
                db = Factory()
                try:
                    self._seed(db)
                    # Tutor mora na Aldeota, mas PERGUNTOU por Messejana.
                    tutor = self._tutor(db, latitude=ALDEOTA[0], longitude=ALDEOTA[1])
                    ctx = tools.WhatsAppBotToolContext(db=db, match_type="tutor", tutor_id=tutor.id)
                    res = tools.buscar_clinica_parceira(ctx, bairro="messejana")
                    self.assertEqual(res["criterio"], "bairro")
                    self.assertEqual(res["itens"][0]["nome"], "Vet Messejana")
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_bairro_casa_sem_acento_e_sem_caixa(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            Factory, engine = self._factory(tmp)
            try:
                db = Factory()
                try:
                    db.add(Clinica(nome="Vet Parangaba", bairro="Parangaba",
                                   endereco="Rua E, 1", telefone="8533335555", ativo=1))
                    db.commit()
                    tutor = self._tutor(db)
                    ctx = tools.WhatsAppBotToolContext(db=db, match_type="tutor", tutor_id=tutor.id)
                    for escrito in ("PARANGABA", "parangaba", "  Parangaba  "):
                        with self.subTest(escrito=escrito):
                            res = tools.buscar_clinica_parceira(ctx, bairro=escrito)
                            self.assertEqual(res["criterio"], "bairro")
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_bairro_sem_parceira_nao_sugere_outro_bairro(self) -> None:
        """Trocar a pergunta seria pior que nao responder.

        O tutor tem coordenadas; a estrategia por distancia existe. Mesmo
        assim ela NAO entra: quem perguntou por um bairro especifico nao quer
        uma clinica do outro lado da cidade sem ser avisado.
        """
        with tempfile.TemporaryDirectory() as tmp:
            Factory, engine = self._factory(tmp)
            try:
                db = Factory()
                try:
                    self._seed(db)
                    tutor = self._tutor(db, latitude=ALDEOTA[0], longitude=ALDEOTA[1])
                    ctx = tools.WhatsAppBotToolContext(db=db, match_type="tutor", tutor_id=tutor.id)
                    res = tools.buscar_clinica_parceira(ctx, bairro="Barra do Ceara")
                    self.assertEqual(res["criterio"], "sem_clinica_no_bairro")
                    self.assertEqual(res["itens"], [])
                    self.assertNotIn("Vet Aldeota", str(res))
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_clinica_inativa_nunca_e_sugerida(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            Factory, engine = self._factory(tmp)
            try:
                db = Factory()
                try:
                    self._seed(db)
                    tutor = self._tutor(db)
                    ctx = tools.WhatsAppBotToolContext(db=db, match_type="tutor", tutor_id=tutor.id)
                    res = tools.buscar_clinica_parceira(ctx, bairro="Aldeota")
                    nomes = [i["nome"] for i in res["itens"]]
                    self.assertIn("Vet Aldeota", nomes)
                    self.assertNotIn("Vet Desativada", nomes)
                finally:
                    db.close()
            finally:
                engine.dispose()

    # --- busca por distancia -----------------------------------------------

    def test_sem_bairro_usa_coordenadas_do_tutor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            Factory, engine = self._factory(tmp)
            try:
                db = Factory()
                try:
                    self._seed(db)
                    tutor = self._tutor(db, latitude=MESSEJANA[0], longitude=MESSEJANA[1])
                    ctx = tools.WhatsAppBotToolContext(db=db, match_type="tutor", tutor_id=tutor.id)
                    res = tools.buscar_clinica_parceira(ctx)
                    self.assertEqual(res["criterio"], "distancia")
                    self.assertEqual(res["itens"][0]["nome"], "Vet Messejana")
                    self.assertEqual(res["itens"][0]["distancia_km"], "0.0")
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_tutor_sem_coordenadas_pede_o_bairro(self) -> None:
        """`precisa_bairro` nao e erro: e a pergunta que falta."""
        with tempfile.TemporaryDirectory() as tmp:
            Factory, engine = self._factory(tmp)
            try:
                db = Factory()
                try:
                    self._seed(db)
                    tutor = self._tutor(db)
                    ctx = tools.WhatsAppBotToolContext(db=db, match_type="tutor", tutor_id=tutor.id)
                    res = tools.buscar_clinica_parceira(ctx)
                    self.assertTrue(res["ok"])
                    self.assertEqual(res["criterio"], "precisa_bairro")
                finally:
                    db.close()
            finally:
                engine.dispose()

    # --- allowlist de campo ------------------------------------------------

    def test_whatsapp_vem_antes_do_telefone(self) -> None:
        """E o canal por onde a clinica de fato se comunica (27/08).

        `whatsapps` e coluna JSON: aceita lista e string serializada.
        """
        with tempfile.TemporaryDirectory() as tmp:
            Factory, engine = self._factory(tmp)
            try:
                db = Factory()
                try:
                    db.add(Clinica(nome="Com WPP", bairro="Aldeota", cidade="Fortaleza",
                                   endereco="R, 1", telefone="8533331111",
                                   whatsapps=["85999998888"], ativo=1))
                    db.add(Clinica(nome="So Telefone", bairro="Meireles", cidade="Fortaleza",
                                   endereco="R, 2", telefone="8533332222",
                                   whatsapps=[], ativo=1))
                    db.commit()
                    tutor = self._tutor(db)
                    ctx = tools.WhatsAppBotToolContext(db=db, match_type="tutor", tutor_id=tutor.id)

                    com = tools.buscar_clinica_parceira(ctx, bairro="Aldeota")["itens"][0]
                    self.assertEqual(com["whatsapp"], "85999998888")
                    self.assertIn("WhatsApp (85) 99999-8888",
                                  _corpo_de_clinica_proxima({"ok": True, "criterio": "bairro",
                                                             "itens": [com]}))

                    so_tel = tools.buscar_clinica_parceira(ctx, bairro="Meireles")["itens"][0]
                    self.assertIsNone(so_tel["whatsapp"])
                    frase = _corpo_de_clinica_proxima({"ok": True, "criterio": "bairro",
                                                       "itens": [so_tel]})
                    self.assertIn("telefone (85) 3333-2222", frase)
                    self.assertNotIn("WhatsApp", frase)
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_whatsapps_serializado_como_string_tambem_funciona(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            Factory, engine = self._factory(tmp)
            try:
                db = Factory()
                try:
                    db.add(Clinica(nome="String", bairro="Centro", cidade="Fortaleza",
                                   endereco="R, 3", whatsapps='["85988887777"]', ativo=1))
                    db.commit()
                    tutor = self._tutor(db)
                    ctx = tools.WhatsAppBotToolContext(db=db, match_type="tutor", tutor_id=tutor.id)
                    item = tools.buscar_clinica_parceira(ctx, bairro="Centro")["itens"][0]
                    self.assertEqual(item["whatsapp"], "85988887777")
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_bairro_homonimo_em_outra_cidade_e_desempatado_por_distancia(self) -> None:
        """Defeito real do cadastro (26/08): "Centro" tem 10 clinicas em 5
        cidades. Um tutor de Caucaia dizendo "Centro" nao pode receber a de
        Maranguape, a ~40 km, anunciada como "a mais perto de voce".
        """
        CAUCAIA = (-3.7360, -38.6530)
        MARANGUAPE = (-3.8900, -38.6850)
        with tempfile.TemporaryDirectory() as tmp:
            Factory, engine = self._factory(tmp)
            try:
                db = Factory()
                try:
                    db.add(Clinica(nome="Amo Pet", bairro="Centro", cidade="Maranguape",
                                   endereco="R. M, 1", telefone="8533331111",
                                   latitude=MARANGUAPE[0], longitude=MARANGUAPE[1], ativo=1))
                    db.add(Clinica(nome="Super Pet", bairro="Centro", cidade="Caucaia",
                                   endereco="R. C, 1", telefone="8533332222",
                                   latitude=CAUCAIA[0], longitude=CAUCAIA[1], ativo=1))
                    db.commit()
                    tutor = self._tutor(db, latitude=CAUCAIA[0], longitude=CAUCAIA[1])
                    ctx = tools.WhatsAppBotToolContext(db=db, match_type="tutor", tutor_id=tutor.id)
                    res = tools.buscar_clinica_parceira(ctx, bairro="Centro")
                    self.assertTrue(res["ordenado_por_distancia"])
                    self.assertEqual(res["itens"][0]["nome"], "Super Pet")
                    self.assertEqual(res["itens"][0]["cidade"], "Caucaia")
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_sem_coordenadas_do_tutor_nao_afirma_proximidade(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            Factory, engine = self._factory(tmp)
            try:
                db = Factory()
                try:
                    self._seed(db)
                    tutor = self._tutor(db)  # sem lat/long
                    ctx = tools.WhatsAppBotToolContext(db=db, match_type="tutor", tutor_id=tutor.id)
                    res = tools.buscar_clinica_parceira(ctx, bairro="Aldeota")
                    self.assertFalse(res["ordenado_por_distancia"])
                    frase = _corpo_de_clinica_proxima(res)
                    self.assertNotIn("mais perto", frase)
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_payload_nao_carrega_dado_comercial_da_clinica(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            Factory, engine = self._factory(tmp)
            try:
                db = Factory()
                try:
                    db.add(Clinica(nome="Vet X", bairro="Aldeota", endereco="Rua A, 1",
                                   telefone="8533331111", cnpj="12345678000199",
                                   tabela_preco_id=4, preco_personalizado_base=999,
                                   observacoes="negociacao interna", ativo=1))
                    db.commit()
                    tutor = self._tutor(db)
                    ctx = tools.WhatsAppBotToolContext(db=db, match_type="tutor", tutor_id=tutor.id)
                    res = tools.buscar_clinica_parceira(ctx, bairro="Aldeota")
                    self.assertEqual(
                        set(res["itens"][0].keys()),
                        {"nome", "bairro", "cidade", "endereco", "whatsapp", "telefone"},
                    )
                    texto = str(res).lower()
                    for proibido in ("cnpj", "12345678", "999", "negociacao", "tabela_preco"):
                        self.assertNotIn(proibido, texto, proibido)
                finally:
                    db.close()
            finally:
                engine.dispose()


class FraseTest(unittest.TestCase):
    def test_uma_clinica(self) -> None:
        frase = _corpo_de_clinica_proxima({
            "ok": True, "criterio": "bairro",
            "ordenado_por_distancia": True,
            "itens": [{"nome": "Vet Aldeota", "bairro": "Aldeota", "cidade": "Fortaleza",
                       "endereco": "Rua A, 100", "telefone": "8533331111"}],
        })
        self.assertIn("Vet Aldeota", frase)
        self.assertIn("em Fortaleza", frase)
        self.assertIn("(85) 3333-1111", frase)
        self.assertIn("Rua A, 100", frase)

    def test_no_maximo_duas_para_nao_virar_despejo(self) -> None:
        itens = [{"nome": f"Vet {i}", "bairro": "X", "endereco": "R, 1",
                  "telefone": "8533331111"} for i in range(5)]
        frase = _corpo_de_clinica_proxima({"ok": True, "criterio": "distancia", "itens": itens})
        self.assertIn("Vet 0", frase)
        self.assertIn("Vet 1", frase)
        self.assertNotIn("Vet 2", frase)

    def test_pede_bairro_sem_inventar_clinica(self) -> None:
        frase = _corpo_de_clinica_proxima({"ok": True, "criterio": "precisa_bairro", "itens": []})
        self.assertIn("bairro", frase)
        self.assertNotIn("Vet", frase)

    def test_bairro_sem_parceira_encaminha(self) -> None:
        frase = _corpo_de_clinica_proxima({
            "ok": True, "criterio": "sem_clinica_no_bairro",
            "bairro_consultado": "Barra do Ceará", "itens": [],
        })
        self.assertIn("Barra do Ceará", frase)
        # Nao inventa parceira nem promete indicacao que nao existe. O
        # encaminhamento para humano vem do sufixo da RF-024, fora daqui.
        self.assertIn("não temos", frase)
        self.assertNotIn("Vet", frase)


class GuardrailDaClinicaProximaTest(unittest.TestCase):
    """A resposta que a tool autoriza tem de PASSAR pelo guardrail.

    Sem alimentar `tem_endereco_na_fonte` e `telefones_permitidos` a partir de
    `buscar_clinica_parceira`, a RF-022 barraria a propria resposta que a tool
    produziu: `endereco_sem_fonte` por citar logradouro, `contato_fora_da_fonte`
    por citar telefone. A feature ficaria muda em producao e nenhum teste
    avisaria -- foi exatamente o que a verificacao por mutacao apontou.
    """

    RESULTADO = ("buscar_clinica_parceira", {
        "ok": True, "criterio": "bairro",
        "itens": [{"nome": "Vet Aldeota", "bairro": "Aldeota", "cidade": "Fortaleza",
                   "endereco": "Rua Antonio, 100",
                   "whatsapp": "85999998888", "telefone": "8533331111"}],
    })

    def _avaliar(self, texto, resultados):
        return avaliar_resposta(
            texto=texto, intent="clinica_proxima", modo="suggest",
            turno=turno_a_partir_dos_resultados("tutor", resultados),
        )

    def test_endereco_e_whatsapp_da_parceira_sao_aprovados(self) -> None:
        """O WhatsApp e o numero que a resposta cita de fato (27/08).

        Ancorar so `telefone` deixaria a RF-022 barrar a propria resposta que
        a tool autorizou -- e a mutacao mostrou que nenhum teste pegava isso.
        """
        texto = (
            "Atendimento automático da FortCordis: a clínica parceira mais perto de você "
            "é Vet Aldeota, no bairro Aldeota, em Fortaleza (Rua Antonio, 100), "
            "WhatsApp (85) 99999-8888. Se quiser falar com uma pessoa, é só pedir."
        )
        veredito = self._avaliar(texto, [self.RESULTADO])
        self.assertTrue(veredito.aprovado, veredito.motivo)

    def test_telefone_fixo_da_parceira_tambem_e_aprovado(self) -> None:
        texto = (
            "A clínica parceira é Vet Aldeota, Rua Antonio, 100, telefone (85) 3333-1111."
        )
        veredito = self._avaliar(texto, [self.RESULTADO])
        self.assertTrue(veredito.aprovado, veredito.motivo)

    def test_o_mesmo_texto_sem_a_tool_e_barrado(self) -> None:
        """Contraprova: a aprovacao vem da FONTE, nao da forma do texto."""
        texto = (
            "A clínica parceira mais perto é Vet Aldeota, Rua Antonio, 100, "
            "telefone (85) 3333-1111."
        )
        veredito = self._avaliar(texto, [("consultar_horario_funcionamento", {"ok": True})])
        self.assertFalse(veredito.aprovado)

    def test_telefone_de_outra_clinica_continua_barrado(self) -> None:
        """A ancoragem libera o que a tool devolveu, nao telefone qualquer."""
        texto = (
            "A clínica parceira mais perto é Vet Aldeota, Rua Antonio, 100, "
            "telefone (85) 3333-9999."
        )
        veredito = self._avaliar(texto, [self.RESULTADO])
        self.assertFalse(veredito.aprovado)
        self.assertEqual(veredito.motivo, "contato_fora_da_fonte")


if __name__ == "__main__":
    unittest.main()
