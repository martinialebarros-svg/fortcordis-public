import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "whatsapp-bot-tools-test-secret-key-1234567890")

from app.core.portal_release import PORTAL_RELEASED_STATUS
from app.models.atendimento_clinico import AtendimentoClinico
from app.models.clinica import Clinica
from app.models.configuracao import Configuracao
from app.models.laudo import Exame, Laudo
from app.models.paciente import Paciente
from app.models.servico import Servico
from app.models.tutor import Tutor
from app.services import whatsapp_bot_tools as tools

LOCAL_TZ = ZoneInfo("America/Fortaleza")


class WhatsAppBotToolContextTest(unittest.TestCase):
    """Escopo que pode ser None e escopo que vaza."""

    def test_persona_tutor_exige_tutor_id(self) -> None:
        with self.assertRaises(tools.WhatsAppBotToolError):
            tools.WhatsAppBotToolContext(db=None, match_type="tutor", tutor_id=None)

    def test_persona_clinica_exige_clinica_id(self) -> None:
        with self.assertRaises(tools.WhatsAppBotToolError):
            tools.WhatsAppBotToolContext(db=None, match_type="clinica", clinica_id=None)

    def test_escopo_cruzado_e_recusado(self) -> None:
        with self.assertRaises(tools.WhatsAppBotToolError):
            tools.WhatsAppBotToolContext(
                db=None, match_type="tutor", tutor_id=1, clinica_id=2
            )
        with self.assertRaises(tools.WhatsAppBotToolError):
            tools.WhatsAppBotToolContext(
                db=None, match_type="clinica", clinica_id=2, tutor_id=1
            )

    def test_match_type_invalido_e_recusado(self) -> None:
        with self.assertRaises(tools.WhatsAppBotToolError):
            tools.WhatsAppBotToolContext(db=None, match_type="staff", tutor_id=1)


class WhatsAppBotDispatcherTest(unittest.TestCase):
    def test_nome_fora_da_allowlist_falha_fechado(self) -> None:
        ctx = tools.WhatsAppBotToolContext(db=None, match_type="tutor", tutor_id=1)
        resultado = tools.execute_bot_tool(ctx, "relatorio_debitos_pendentes")
        self.assertFalse(resultado["ok"])
        self.assertIn("nao disponivel", resultado["error"])

    def test_dispatcher_descarta_argumento_nao_previsto(self) -> None:
        """Escopo nunca pode chegar como argumento do modelo."""
        ctx = tools.WhatsAppBotToolContext(db=None, match_type="tutor", tutor_id=1)
        with patch.object(tools, "consultar_dados_institucionais", return_value={"ok": True}) as mock:
            tools.TOOLS_POR_PERSONA["tutor"]["consultar_dados_institucionais"] = mock
            try:
                tools.execute_bot_tool(
                    ctx, "consultar_dados_institucionais", {"tutor_id": 99, "clinica_id": 99}
                )
            finally:
                tools.TOOLS_POR_PERSONA["tutor"]["consultar_dados_institucionais"] = (
                    tools.consultar_dados_institucionais
                )
        mock.assert_called_once_with(ctx)


class WhatsAppBotToolsDbTest(unittest.TestCase):
    def _factory(self, tmpdir: str):
        db_path = Path(tmpdir) / "whatsapp-bot-tools-test.db"
        engine = create_engine(f"sqlite:///{db_path}")
        for table in (
            Configuracao.__table__,
            Servico.__table__,
            Clinica.__table__,
            Tutor.__table__,
            Paciente.__table__,
            Laudo.__table__,
            Exame.__table__,
            AtendimentoClinico.__table__,
        ):
            table.create(engine, checkfirst=True)
        return sessionmaker(bind=engine, autocommit=False, autoflush=False), engine

    # --- dados institucionais --------------------------------------------

    def test_cadastro_institucional_vazio_falha_fechado(self) -> None:
        """Regressao medida em stage (2026-08-23).

        Existia linha de `Configuracao` com endereco, telefone e e-mail
        vazios, e a tool devolvia `ok=True`. Isso dava fonte valida sem dado:
        a prontidao ficava verde e a RF-020 aceitava o turno como ancorado.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    db.add(Configuracao(cidade="Fortaleza", estado="CE"))
                    db.commit()
                    ctx = tools.WhatsAppBotToolContext(db=db, match_type="tutor", tutor_id=1)
                    res = tools.consultar_dados_institucionais(ctx)
                    self.assertFalse(res["ok"])
                    self.assertFalse(res["tem_endereco"])
                    self.assertFalse(res["tem_contato"])
                    # Cidade/estado sozinhos nao sao endereco publicavel.
                    self.assertEqual(
                        sorted(res["campos_vazios"]), ["email", "endereco", "telefone"]
                    )
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_so_telefone_preenchido_habilita_contato_e_nao_endereco(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    db.add(Configuracao(telefone="(85) 3333-4444"))
                    db.commit()
                    ctx = tools.WhatsAppBotToolContext(db=db, match_type="tutor", tutor_id=1)
                    res = tools.consultar_dados_institucionais(ctx)
                    self.assertTrue(res["ok"])
                    self.assertTrue(res["tem_contato"])
                    self.assertFalse(res["tem_endereco"])
                    self.assertIsNone(res["endereco"])
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_espaco_em_branco_nao_conta_como_dado(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    db.add(Configuracao(endereco="   ", telefone="\t"))
                    db.commit()
                    ctx = tools.WhatsAppBotToolContext(db=db, match_type="tutor", tutor_id=1)
                    res = tools.consultar_dados_institucionais(ctx)
                    self.assertFalse(res["ok"])
                finally:
                    db.close()
            finally:
                engine.dispose()

    # --- horario ---------------------------------------------------------

    def test_horario_em_dia_util_devolve_janela(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    db.add(Configuracao())
                    db.commit()
                    ctx = tools.WhatsAppBotToolContext(db=db, match_type="tutor", tutor_id=1)
                    hoje = datetime.now(LOCAL_TZ).date()
                    # Proxima segunda-feira.
                    segunda = hoje + timedelta(days=(1 - hoje.isoweekday()) % 7)
                    res = tools.consultar_horario_funcionamento(ctx, data=segunda.isoformat())
                    self.assertTrue(res["ok"])
                    self.assertTrue(res["aberto"])
                    self.assertEqual(res["inicio"], "08:00")
                    self.assertEqual(res["fim"], "14:00")
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_horario_em_domingo_nao_devolve_horario(self) -> None:
        """Feriado/fechado herda a janela semanal em `_agenda_day_window`.

        Se o payload devolvesse `inicio`/`fim` nesse caso, o bot diria
        "hoje funcionamos de 08:00 as 14:00" num dia fechado.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    db.add(Configuracao())
                    db.commit()
                    ctx = tools.WhatsAppBotToolContext(db=db, match_type="tutor", tutor_id=1)
                    hoje = datetime.now(LOCAL_TZ).date()
                    domingo = hoje + timedelta(days=(7 - hoje.isoweekday()) % 7)
                    res = tools.consultar_horario_funcionamento(ctx, data=domingo.isoformat())
                    self.assertTrue(res["ok"])
                    self.assertFalse(res["aberto"])
                    self.assertIsNone(res["inicio"])
                    self.assertIsNone(res["fim"])
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_data_fora_da_janela_consultavel_e_recusada(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    ctx = tools.WhatsAppBotToolContext(db=db, match_type="tutor", tutor_id=1)
                    res = tools.consultar_horario_funcionamento(ctx, data="2029-01-01")
                    self.assertFalse(res["ok"])
                    res = tools.consultar_horario_funcionamento(ctx, data="nao-e-data")
                    self.assertFalse(res["ok"])
                finally:
                    db.close()
            finally:
                engine.dispose()

    # --- preco -----------------------------------------------------------

    def test_preco_tutor_usa_tabela_e_ignora_preco_negociado(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    db.add(Configuracao(cidade="Fortaleza"))
                    db.add(
                        Servico(
                            nome="Ecocardiograma",
                            ativo=True,
                            preco_fortaleza_comercial=420,
                            preco_rm_comercial=480,
                            preco_domiciliar_comercial=560,
                        )
                    )
                    db.commit()
                    ctx = tools.WhatsAppBotToolContext(db=db, match_type="tutor", tutor_id=1)
                    # Tutor so e cotado em domiciliar; ver RF-P15.
                    res = tools.consultar_preco_tabela(
                        ctx, servico_nome="eco", regiao="domiciliar"
                    )
                    self.assertTrue(res["ok"])
                    self.assertEqual(res["itens"][0]["valor"], "560.00")
                    self.assertEqual(res["itens"][0]["fonte"], "tabela:preco_domiciliar_comercial")
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_preco_zero_nao_entra_no_payload(self) -> None:
        """`to_decimal` do precos_service transforma NULL em 0.00 em silencio.

        "R$ 0,00" e um resultado alcancavel e nunca deve ser enviavel.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    db.add(Servico(nome="Servico sem preco", ativo=True))
                    db.commit()
                    # Persona clinica: na de tutor a regiao muda o caminho (RF-P15).
                    clinica = Clinica(nome="Teste", tabela_preco_id=1)
                    db.add(clinica)
                    db.commit()
                    ctx = tools.WhatsAppBotToolContext(
                        db=db, match_type="clinica", clinica_id=clinica.id
                    )
                    res = tools.consultar_preco_tabela(ctx)
                    self.assertFalse(res["ok"])
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_preco_nao_aceita_parametro_de_clinica(self) -> None:
        """Vazamento de preco negociado impossivel por construcao."""
        import inspect

        assinatura = inspect.signature(tools.consultar_preco_tabela)
        self.assertNotIn("clinica_id", assinatura.parameters)
        self.assertNotIn("clinica_nome", assinatura.parameters)

    # --- preco por regiao (RF-P14) ---------------------------------------

    def _seed_catalogo_regiao(self, db):
        db.add(Servico(nome="Ecocardiograma", ativo=True,
                       preco_fortaleza_comercial=180, preco_rm_comercial=200))
        db.add(Servico(nome="Consulta + Eletro", ativo=True,
                       preco_fortaleza_comercial=300, preco_rm_comercial=0))
        db.commit()

    def test_regiao_vem_do_cadastro_da_clinica_nao_do_modelo(self) -> None:
        """Defeito medido em producao (2026-08-25).

        `regiao` era parametro preenchido pelo MODELO, que nao tem nenhum dado
        no prompt para decidir; o silencio dele virava "fortaleza". A clinica
        Pet Sanus Caucaia (tabela 2) recebia preco de Fortaleza, R$ 20 a R$ 50
        abaixo da tabela dela.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    self._seed_catalogo_regiao(db)
                    clinica = Clinica(nome="Pet Sanus Caucaia", tabela_preco_id=2)
                    db.add(clinica)
                    db.commit()
                    ctx = tools.WhatsAppBotToolContext(
                        db=db, match_type="clinica", clinica_id=clinica.id
                    )
                    # O modelo manda "fortaleza" -- e tem de ser ignorado.
                    res = tools.consultar_preco_tabela(ctx, servico_nome="eco", regiao="fortaleza")
                    self.assertTrue(res["ok"])
                    self.assertEqual(res["regiao"], "rm")
                    self.assertEqual(res["itens"][0]["valor"], "200.00")
                    self.assertEqual(res["itens"][0]["fonte"], "tabela:preco_rm_comercial")
                    self.assertTrue(res["regiao_do_cadastro"])
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_clinica_sem_tabela_definida_cai_em_fortaleza(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    self._seed_catalogo_regiao(db)
                    clinica = Clinica(nome="Sem tabela", tabela_preco_id=None)
                    db.add(clinica)
                    db.commit()
                    ctx = tools.WhatsAppBotToolContext(
                        db=db, match_type="clinica", clinica_id=clinica.id
                    )
                    res = tools.consultar_preco_tabela(ctx, servico_nome="eco")
                    self.assertEqual(res["regiao"], "fortaleza")
                    self.assertEqual(res["itens"][0]["valor"], "180.00")
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_tabela_personalizada_nao_cota_preco(self) -> None:
        """Tabela fora de {1,2,3} e negociada: fora da allowlist da RF-019."""
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    self._seed_catalogo_regiao(db)
                    clinica = Clinica(nome="Aracati", tabela_preco_id=4)
                    db.add(clinica)
                    db.commit()
                    ctx = tools.WhatsAppBotToolContext(
                        db=db, match_type="clinica", clinica_id=clinica.id
                    )
                    res = tools.consultar_preco_tabela(ctx, servico_nome="eco")
                    self.assertFalse(res["ok"])
                    self.assertEqual(res["motivo"], "tabela_personalizada")
                    self.assertNotIn("itens", res)
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_servico_sem_preco_na_regiao_falha_fechado(self) -> None:
        """`Consulta + Eletro` nao tem preco RM em producao.

        Responder com os vizinhos trocaria a pergunta por outra sem avisar.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    self._seed_catalogo_regiao(db)
                    clinica = Clinica(nome="RM", tabela_preco_id=2)
                    db.add(clinica)
                    db.commit()
                    ctx = tools.WhatsAppBotToolContext(
                        db=db, match_type="clinica", clinica_id=clinica.id
                    )
                    res = tools.consultar_preco_tabela(ctx, servico_nome="consulta com eletro")
                    self.assertFalse(res["ok"])
                    self.assertEqual(res["motivo"], "sem_preco_na_regiao")
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_tutor_nunca_recebe_tabela_praticada_com_clinica(self) -> None:
        """RF-P15: tabelas 1 e 2 sao preco B2B, que a clinica parceira remarca.

        Passa-lo ao consumidor final subcotaria a propria clinica contra ela
        mesma. Regra do negocio: atendimento em clinica e tratado pela clinica
        de preferencia do cliente, nao pela FortCordis.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    self._seed_catalogo_regiao(db)
                    ctx = tools.WhatsAppBotToolContext(db=db, match_type="tutor", tutor_id=1)
                    for regiao in (None, "fortaleza", "rm"):
                        with self.subTest(regiao=regiao):
                            res = tools.consultar_preco_tabela(
                                ctx, servico_nome="eco", **({} if regiao is None else {"regiao": regiao})
                            )
                            # `ok: True` para a intent ter fonte e o turno poder
                            # RESPONDER. Com `ok: False` virava `blocked`, e
                            # `blocked` nao envia nada -- o tutor recebia
                            # silencio (medido em stage, 26/08).
                            self.assertTrue(res["ok"])
                            self.assertEqual(res["orientacao"], "escolher_tipo_atendimento")
                            self.assertEqual(res["itens"], [])
                            # O que nao pode mudar: nenhum valor de tabela
                            # praticada com clinica no payload inteiro.
                            self.assertNotIn("180", str(res))
                            self.assertNotIn("200", str(res))
                            self.assertNotIn("valor", str(res).lower())
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_tutor_e_cotado_em_domiciliar(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    db.add(Servico(nome="Ecocardiograma", ativo=True,
                                   preco_fortaleza_comercial=180,
                                   preco_domiciliar_comercial=350))
                    db.commit()
                    ctx = tools.WhatsAppBotToolContext(db=db, match_type="tutor", tutor_id=1)
                    res = tools.consultar_preco_tabela(
                        ctx, servico_nome="eco", regiao="domiciliar"
                    )
                    self.assertTrue(res["ok"])
                    self.assertEqual(res["itens"][0]["valor"], "350.00")
                    self.assertFalse(res["regiao_do_cadastro"])
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_mapa_de_tabela_do_bot_nao_diverge_da_fatura(self) -> None:
        """Guarda de deriva: o mapa foi DUPLICADO de `precos_service`.

        Importar `calcular_preco_servico` traria junto o preco negociado, que
        esta fora da allowlist -- por isso a duplicacao. O que nao pode e o bot
        cotar por um criterio e a fatura por outro. Este teste amarra os dois.
        """
        from app.services.precos_service import _preco_tabela_padrao

        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    servico = Servico(
                        nome="Sonda", ativo=True,
                        preco_fortaleza_comercial=111,
                        preco_rm_comercial=222,
                        preco_domiciliar_comercial=333,
                    )
                    db.add(servico)
                    db.commit()
                    for tabela_id, regiao in tools._TABELA_PRECO_REGIAO.items():
                        with self.subTest(tabela_id=tabela_id):
                            coluna = tools._REGIAO_COLUNAS[regiao]
                            esperado = getattr(servico, coluna)
                            da_fatura = _preco_tabela_padrao(
                                db, Clinica(tabela_preco_id=tabela_id), servico, "comercial"
                            )
                            self.assertEqual(
                                float(da_fatura), float(esperado),
                                f"tabela {tabela_id}: bot usa {coluna}, fatura discorda",
                            )
                finally:
                    db.close()
            finally:
                engine.dispose()

    # --- status de laudo -------------------------------------------------

    def _seed_laudo(self, db, *, tutor_nome, pet_nome, laudo_status, exame_status, clinica_id=None):
        tutor = Tutor(nome=tutor_nome, ativo=1)
        db.add(tutor)
        db.commit()
        pet = Paciente(nome=pet_nome, tutor_id=tutor.id, ativo=1)
        db.add(pet)
        db.commit()
        laudo = Laudo(
            paciente_id=pet.id,
            veterinario_id=1,
            tipo="exame",
            titulo="Eco",
            status=laudo_status,
            clinic_id=clinica_id,
        )
        db.add(laudo)
        db.commit()
        exame = Exame(
            paciente_id=pet.id,
            laudo_id=laudo.id,
            tipo_exame="Ecocardiograma",
            status=exame_status,
        )
        db.add(exame)
        db.commit()
        return tutor, pet, laudo, exame

    def test_laudo_finalizado_nao_e_pronto(self) -> None:
        """"Finalizado" e aguardando_liberacao, nao publicado."""
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    tutor, _, _, _ = self._seed_laudo(
                        db, tutor_nome="Maria", pet_nome="Thor",
                        laudo_status="Finalizado", exame_status="Concluido",
                    )
                    ctx = tools.WhatsAppBotToolContext(db=db, match_type="tutor", tutor_id=tutor.id)
                    res = tools.consultar_status_laudo(ctx)
                    self.assertTrue(res["ok"])
                    self.assertEqual(res["itens"][0]["status_cliente"], "ainda_nao")
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_laudo_liberado_no_portal_e_pronto(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    tutor, _, _, _ = self._seed_laudo(
                        db, tutor_nome="Maria", pet_nome="Thor",
                        laudo_status=PORTAL_RELEASED_STATUS, exame_status="Concluido",
                    )
                    ctx = tools.WhatsAppBotToolContext(db=db, match_type="tutor", tutor_id=tutor.id)
                    res = tools.consultar_status_laudo(ctx)
                    self.assertEqual(res["itens"][0]["status_cliente"], "pronto")
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_exame_liberado_sem_laudo_liberado_tambem_e_pronto(self) -> None:
        """A liberacao e por EXAME; o filtro do portal e um OR assimetrico."""
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    tutor, _, _, _ = self._seed_laudo(
                        db, tutor_nome="Maria", pet_nome="Thor",
                        laudo_status="Rascunho", exame_status=PORTAL_RELEASED_STATUS,
                    )
                    ctx = tools.WhatsAppBotToolContext(db=db, match_type="tutor", tutor_id=tutor.id)
                    res = tools.consultar_status_laudo(ctx)
                    self.assertEqual(res["itens"][0]["status_cliente"], "pronto")
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_tutor_nao_ve_laudo_de_outro_tutor(self) -> None:
        """CA-023."""
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    tutor_a, _, _, _ = self._seed_laudo(
                        db, tutor_nome="Maria", pet_nome="Thor",
                        laudo_status=PORTAL_RELEASED_STATUS, exame_status="Concluido",
                    )
                    self._seed_laudo(
                        db, tutor_nome="Joao", pet_nome="Rex",
                        laudo_status=PORTAL_RELEASED_STATUS, exame_status="Concluido",
                    )
                    ctx = tools.WhatsAppBotToolContext(db=db, match_type="tutor", tutor_id=tutor_a.id)
                    res = tools.consultar_status_laudo(ctx)
                    nomes = {item["pet_nome"] for item in res["itens"]}
                    self.assertEqual(nomes, {"Thor"})
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_clinica_nao_ve_laudo_de_outra_clinica(self) -> None:
        """CA-023, lado clinica (filtro por Laudo.clinic_id)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    self._seed_laudo(
                        db, tutor_nome="Maria", pet_nome="Thor",
                        laudo_status=PORTAL_RELEASED_STATUS, exame_status="Concluido",
                        clinica_id=10,
                    )
                    self._seed_laudo(
                        db, tutor_nome="Joao", pet_nome="Rex",
                        laudo_status=PORTAL_RELEASED_STATUS, exame_status="Concluido",
                        clinica_id=20,
                    )
                    ctx = tools.WhatsAppBotToolContext(db=db, match_type="clinica", clinica_id=10)
                    res = tools.consultar_status_laudo(ctx)
                    nomes = {item["pet_nome"] for item in res["itens"]}
                    self.assertEqual(nomes, {"Thor"})
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_payload_de_laudo_nao_carrega_campo_clinico(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    tutor, pet, laudo, exame = self._seed_laudo(
                        db, tutor_nome="Maria", pet_nome="Thor",
                        laudo_status=PORTAL_RELEASED_STATUS, exame_status="Concluido",
                    )
                    laudo.diagnostico = "Endocardiose de valva mitral estagio B2"
                    laudo.descricao = "AE/Ao 2.1, DIVEdN 1.9"
                    exame.resultado = "refluxo mitral moderado"
                    db.commit()

                    ctx = tools.WhatsAppBotToolContext(db=db, match_type="tutor", tutor_id=tutor.id)
                    res = tools.consultar_status_laudo(ctx)
                    chaves = set(res["itens"][0].keys())
                    self.assertEqual(
                        chaves, {"tipo_exame", "pet_nome", "status_cliente", "data_solicitacao"}
                    )
                    texto = str(res).lower()
                    for proibido in ("endocardiose", "ae/ao", "divedn", "refluxo", "diagnostico"):
                        self.assertNotIn(proibido, texto, proibido)
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_pet_inativo_nao_entra(self) -> None:
        """Falar de pet inativo em resposta automatica e o pior erro possivel."""
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    tutor, pet, _, _ = self._seed_laudo(
                        db, tutor_nome="Maria", pet_nome="Thor",
                        laudo_status=PORTAL_RELEASED_STATUS, exame_status="Concluido",
                    )
                    pet.ativo = 0
                    db.commit()
                    ctx = tools.WhatsAppBotToolContext(db=db, match_type="tutor", tutor_id=tutor.id)
                    res = tools.consultar_status_laudo(ctx)
                    self.assertFalse(res["ok"])
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_sem_registro_nao_afirma_ainda_nao(self) -> None:
        """Negar existencia de exame que pode existir em outro escopo seria
        afirmar algo sem fonte."""
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    ctx = tools.WhatsAppBotToolContext(db=db, match_type="tutor", tutor_id=999)
                    res = tools.consultar_status_laudo(ctx)
                    self.assertFalse(res["ok"])
                finally:
                    db.close()
            finally:
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
