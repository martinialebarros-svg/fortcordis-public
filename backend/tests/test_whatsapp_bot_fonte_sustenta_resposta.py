"""Invariante: o que uma tool AUTORIZA, o guardrail nao pode barrar.

Duas vezes na RF-P19 a integracao com a RF-022 passou verde sem nenhum teste
cobrindo. Nas duas, o efeito em producao seria o mesmo: o bot mudo justamente
na intent nova, com a suite inteira verde. A primeira foi encontrada por
mutacao; a segunda reapareceu porque o teste que eu escrevi cobria o campo
antigo (`telefone`) e nao o novo (`whatsapp`).

O padrao e sempre o mesmo: `turno_a_partir_dos_resultados` traduz o payload da
tool nos conjuntos que a RF-022 consulta (`valores_permitidos`,
`horarios_permitidos`, `telefones_permitidos`, `ceps_permitidos`,
`tem_endereco_na_fonte`). Se essa traducao faltar ou
ficar desatualizada, o guardrail recusa a propria resposta que a tool
sustentou -- e nenhum teste de tool ou de renderizacao percebe, porque cada um
olha so o seu lado.

Este arquivo testa a JUNCAO, para todas as tools, e falha quando uma tool nova
entra sem cobertura.
"""

import hashlib
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "whatsapp-bot-fonte-guardrail-test-secret-123")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.portal_release import PORTAL_RELEASED_STATUS
from app.models.assistente_ia import AssistenteIAConhecimentoDocumento
from app.models.atendimento_clinico import AtendimentoClinico
from app.models.clinica import Clinica
from app.models.configuracao import Configuracao
from app.models.laudo import Exame, Laudo
from app.models.paciente import Paciente
from app.models.servico import Servico
from app.models.tutor import Tutor
from app.services import assistente_ia_autonomy as autonomy
from app.services import whatsapp_bot_tools as tools
from app.services.whatsapp_bot_guardrails import (
    avaliar_resposta,
    turno_a_partir_dos_resultados,
)

LOCAL_TZ = ZoneInfo("America/Fortaleza")


def _proxima_segunda() -> str:
    hoje = datetime.now(LOCAL_TZ).date()
    return (hoje + timedelta(days=(1 - hoje.isoweekday()) % 7)).isoformat()


class FonteSustentaRespostaTest(unittest.TestCase):
    """Cada caso: roda a tool DE VERDADE, monta o turno com o payload literal,
    e exige que uma resposta citando aquele dado seja APROVADA."""

    def _db(self, tmpdir):
        engine = create_engine(f"sqlite:///{Path(tmpdir) / 'fonte.db'}")
        for tabela in (
            Configuracao.__table__, Servico.__table__, Clinica.__table__,
            Tutor.__table__, Paciente.__table__, Laudo.__table__, Exame.__table__,
            AtendimentoClinico.__table__, AssistenteIAConhecimentoDocumento.__table__,
        ):
            tabela.create(engine, checkfirst=True)
        db = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
        db.add(Configuracao(cidade="Fortaleza", estado="CE",
                            endereco="Rua Exemplo, 123, CEP 60000-000",
                            telefone="8533334444", email="contato@fortcordis.com"))
        db.add(Servico(nome="Ecocardiograma", ativo=True,
                       preco_fortaleza_comercial=180, preco_domiciliar_comercial=350))
        db.add(Clinica(nome="Vet Aldeota", bairro="Aldeota", cidade="Fortaleza",
                       endereco="Rua Antonio, 100", whatsapps=["85999998888"],
                       telefone="8533331111", latitude=-3.742, longitude=-38.495, ativo=1))
        tutor = Tutor(nome="Maria", whatsapp="5585999990001", ativo=1)
        db.add(tutor)
        db.commit()
        pet = Paciente(nome="Thor", tutor_id=tutor.id, ativo=1)
        db.add(pet)
        db.commit()
        laudo = Laudo(paciente_id=pet.id, veterinario_id=1, tipo="exame", titulo="Eco",
                      status=PORTAL_RELEASED_STATUS)
        db.add(laudo)
        db.commit()
        db.add(Exame(paciente_id=pet.id, laudo_id=laudo.id, tipo_exame="Ecocardiograma",
                     status="Concluido"))
        db.commit()
        return db, engine, tutor

    def _verificar(self, *, tool, args, intent, texto, persona="tutor", clinica_id=None):
        with tempfile.TemporaryDirectory() as tmpdir:
            db, engine, tutor = self._db(tmpdir)
            try:
                if persona == "tutor":
                    ctx = tools.WhatsAppBotToolContext(db=db, match_type="tutor",
                                                       tutor_id=tutor.id)
                else:
                    alvo = clinica_id or db.query(Clinica).first().id
                    ctx = tools.WhatsAppBotToolContext(db=db, match_type="clinica",
                                                       clinica_id=alvo)
                resultado = tools.TOOLS_POR_PERSONA[persona][tool](ctx, **args)
                self.assertTrue(resultado.get("ok"), f"{tool} devolveu ok=False: {resultado}")
                turno = turno_a_partir_dos_resultados(persona, [(tool, resultado)])
            finally:
                db.close()
                engine.dispose()

        veredito = avaliar_resposta(texto=texto, intent=intent, modo="suggest", turno=turno)
        self.assertTrue(
            veredito.aprovado,
            f"{tool} autorizou o dado, mas o guardrail recusou "
            f"({veredito.motivo}: {veredito.detalhe}). "
            f"Falta traducao em `turno_a_partir_dos_resultados`.",
        )

    # --- um caso por tool --------------------------------------------------

    def test_preco_tabela(self) -> None:
        self._verificar(
            tool="consultar_preco_tabela",
            args={"servico_nome": "eco", "regiao": "domiciliar"},
            intent="preco_servico",
            texto="Atendimento automático: Ecocardiograma custa R$ 350,00.",
        )

    def test_horario_funcionamento(self) -> None:
        self._verificar(
            tool="consultar_horario_funcionamento",
            args={"data": _proxima_segunda()},
            intent="horario_funcionamento",
            texto="Atendimento automático: nesse dia atendemos das 08:00 às 14:00.",
        )

    def test_dados_institucionais_endereco_e_telefone(self) -> None:
        self._verificar(
            tool="consultar_dados_institucionais",
            args={},
            intent="endereco",
            texto=(
                "Atendimento automático: ficamos na Rua Exemplo, 123, "
                "CEP 60000-000. Telefone (85) 3333-4444."
            ),
        )

    def test_status_laudo(self) -> None:
        self._verificar(
            tool="consultar_status_laudo",
            args={"pet_nome": "Thor"},
            intent="status_laudo",
            texto="Atendimento automático: o Ecocardiograma de Thor está pronto.",
        )

    def test_conhecimento_institucional(self) -> None:
        """Esta tool nao alimenta nenhum conjunto de ancoragem -- por desenho.

        Ela sustenta a intent (`_FONTE_EXIGIDA_POR_INTENT`), mas nao autoriza
        valor, horario, telefone nem endereco. Ate 27/08 havia um ramo que
        ligava `tem_trecho_conhecimento`; a mutacao mostrou que remove-lo nao
        quebrava nada, e a investigacao revelou por que: `tem_fonte` era
        `bool(tools_ok) or tem_trecho_conhecimento`, e `tools_ok` recebe toda
        tool com `ok: True` -- entao o `or` nunca decidia. A flag foi removida.

        O que este caso protege continua valendo: a intent `area_atendimento`
        exige esta tool como fonte, e a resposta que a cita passa.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            db, engine, tutor = self._db(tmpdir)
            try:
                conteudo = (
                    "A area de atendimento da FortCordis cobre Fortaleza e toda a "
                    "regiao metropolitana. O atendimento domiciliar tambem atende "
                    "os municipios da regiao metropolitana de Fortaleza."
                )
                db.add(AssistenteIAConhecimentoDocumento(
                    id="doc-fonte-1", titulo="Area de atendimento", conteudo=conteudo,
                    categoria="institucional", fonte="manual da equipe",
                    conteudo_sha256=hashlib.sha256(conteudo.encode("utf-8")).hexdigest(),
                    criado_por_id=1, status="active",
                ))
                db.commit()
                ctx = tools.WhatsAppBotToolContext(db=db, match_type="tutor",
                                                   tutor_id=tutor.id)
                # Sem rede: se a busca depender de embeddings, o teste quebra em
                # vez de passar por um caminho que producao nao usa offline.
                with patch.object(autonomy, "_embed_texts",
                                  side_effect=AssertionError("nao deve chamar embeddings")):
                    resultado = tools.buscar_conhecimento_institucional(
                        ctx, consulta="area de atendimento"
                    )
                self.assertTrue(resultado.get("trechos"), f"busca vazia: {resultado}")
                turno = turno_a_partir_dos_resultados(
                    "tutor", [("buscar_conhecimento_institucional", resultado)]
                )
            finally:
                db.close()
                engine.dispose()
        veredito = avaliar_resposta(
            texto="Atendimento automático: atendemos Fortaleza e região metropolitana.",
            intent="area_atendimento", modo="suggest", turno=turno,
        )
        self.assertTrue(veredito.aprovado, f"{veredito.motivo}: {veredito.detalhe}")

    def test_clinica_parceira_endereco_e_whatsapp(self) -> None:
        self._verificar(
            tool="buscar_clinica_parceira",
            args={"bairro": "Aldeota"},
            intent="clinica_proxima",
            texto=(
                "Atendimento automático: a clínica parceira mais perto é Vet Aldeota, "
                "no bairro Aldeota, em Fortaleza (Rua Antonio, 100), "
                "WhatsApp (85) 99999-8888."
            ),
        )

    def test_clinica_parceira_telefone_fixo(self) -> None:
        """Cobre o campo de reserva. A lacuna que reapareceu foi exatamente
        esta: o teste cobria um campo e a ancoragem tinha ganhado outro."""
        self._verificar(
            tool="buscar_clinica_parceira",
            args={"bairro": "Aldeota"},
            intent="clinica_proxima",
            texto=(
                "Atendimento automático: a clínica parceira é Vet Aldeota, "
                "Rua Antonio, 100, telefone (85) 3333-1111."
            ),
        )


class CompletudeTest(unittest.TestCase):
    """Guarda que torna a lacuna impossivel de repetir em silencio.

    Tool nova entra em `TOOLS_POR_PERSONA` e este teste quebra ate alguem
    escrever o caso correspondente acima. E a unica parte do arquivo que
    protege contra o ERRO FUTURO, nao contra os dois ja corrigidos.
    """

    def test_toda_tool_tem_caso_de_juncao(self) -> None:
        cobertas = set()
        for nome_teste in dir(FonteSustentaRespostaTest):
            if not nome_teste.startswith("test_"):
                continue
            corpo = getattr(FonteSustentaRespostaTest, nome_teste).__code__
            cobertas.update(
                c for c in corpo.co_consts if isinstance(c, str) and c in _TODAS_AS_TOOLS
            )

        faltando = _TODAS_AS_TOOLS - cobertas
        self.assertFalse(
            faltando,
            "Tool sem caso em FonteSustentaRespostaTest: "
            f"{sorted(faltando)}.\n"
            "Toda tool precisa de um caso provando que uma resposta citando o "
            "dado que ela devolve PASSA no guardrail. Sem isso, faltar a "
            "traducao em `turno_a_partir_dos_resultados` deixa o bot mudo "
            "naquela intent com a suite verde -- aconteceu duas vezes na "
            "RF-P19.",
        )


_TODAS_AS_TOOLS = {
    nome
    for tools_da_persona in tools.TOOLS_POR_PERSONA.values()
    for nome in tools_da_persona
}


if __name__ == "__main__":
    unittest.main()
