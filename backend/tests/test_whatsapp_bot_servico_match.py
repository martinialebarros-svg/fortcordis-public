"""Casamento pedido<->catalogo e a frase de preco montada a partir dele.

O catalogo usado aqui e o de producao em 2026-08-25, copiado literalmente.
Nao substituir por nomes sinteticos: o defeito que originou estes testes so
aparece com esses nomes reais, porque depende de `Ecocardiograma` cair
depois de tres combinacoes na ordem alfabetica.
"""

import os
import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "whatsapp-bot-servico-match-test-secret-key-123")

from app.services import whatsapp_bot_servico_match as match
from app.services.whatsapp_bot_generation import _corpo_de_preco

CATALOGO_PRODUCAO = [
    ("Consulta", "230.00"),
    ("Consulta + Eco", "410.00"),
    ("Consulta + Eco + Eletro", "480.00"),
    ("Consulta + Eletro", "300.00"),
    ("Eco + Eletro", "250.00"),
    ("Eco + Eletro + PA", "290.00"),
    ("Eco + PA", "220.00"),
    ("Ecocardiograma", "180.00"),
    ("Eletro + PA", "160.00"),
    ("Eletrocardiograma", "120.00"),
    ("Pressão arterial", "40.00"),
]


class _Servico:
    def __init__(self, nome: str, valor: str) -> None:
        self.nome = nome
        self.valor = valor


def _payload(pergunta):
    """Reproduz a selecao de `consultar_preco_tabela` sem tocar no banco."""
    ativos = [_Servico(n, v) for n, v in CATALOGO_PRODUCAO]
    pedido = match.procedimentos_do_pedido(pergunta)
    if pedido:
        ranqueados = match.ordenar_candidatos(ativos, pedido=pedido)
        candidatos = [s for s, _g, _c in ranqueados]
        graus = {id(s): g for s, g, _c in ranqueados}
    else:
        candidatos = sorted(
            ativos,
            key=lambda s: (len(match.procedimentos_do_servico(s.nome)) or 99, s.nome),
        )
        graus = {}
    itens = [
        {"servico": s.nome, "valor": s.valor, "aderencia": graus.get(id(s), 0)}
        for s in candidatos[:8]
    ]
    return {"ok": True, "itens": itens, "pedido": sorted(pedido)}


class VocabularioTest(unittest.TestCase):
    def test_sinonimos_do_cliente_convergem_para_o_mesmo_procedimento(self) -> None:
        for termo in [
            "eco",
            "ecocardiograma",
            "ecocardiografia",
            "ecodopplercardiograma",
            "ecodoppler",
            "eco doppler",
            "ecocardio",
            "eco do coração",
            "doppler cardíaco",
            "ultrassom do coração",
            "us cardíaco",
        ]:
            with self.subTest(termo=termo):
                self.assertEqual(
                    match.procedimentos_do_pedido(termo), frozenset({"ecocardiograma"})
                )

        for termo in ["eletro", "eletrocardiograma", "ECG", "ecg", "traçado"]:
            with self.subTest(termo=termo):
                self.assertEqual(
                    match.procedimentos_do_pedido(termo), frozenset({"eletrocardiograma"})
                )

        for termo in ["PA", "pressão", "pressão arterial", "aferição de pressão"]:
            with self.subTest(termo=termo):
                self.assertEqual(
                    match.procedimentos_do_pedido(termo), frozenset({"pressao_arterial"})
                )

    def test_ecg_nao_vira_ecocardiograma(self) -> None:
        """"ECG" comeca com "ec" e termina em "g" -- vizinhanca perigosa de "eco"."""
        self.assertNotIn("ecocardiograma", match.procedimentos_do_pedido("ECG"))

    def test_fronteira_de_palavra_impede_falso_positivo_em_preco(self) -> None:
        """Sem acento, "preco" contem "eco"; "para"/"pacote" contem "pa".

        Casamento por substring pura transformaria "qual o preço da consulta"
        num pedido de ecocardiograma e "para o meu cachorro" num pedido de
        pressao arterial.
        """
        self.assertEqual(
            match.procedimentos_do_pedido("qual o preço da consulta"),
            frozenset({"consulta"}),
        )
        self.assertEqual(
            match.procedimentos_do_pedido("queria saber o preço"), frozenset()
        )
        self.assertEqual(
            match.procedimentos_do_pedido("é para o meu cachorro"), frozenset()
        )
        self.assertEqual(match.procedimentos_do_pedido("vocês têm pacote?"), frozenset())
        self.assertEqual(match.procedimentos_do_pedido("bom dia, tudo bem?"), frozenset())

    def test_composicao_do_catalogo(self) -> None:
        self.assertEqual(
            match.procedimentos_do_servico("Ecocardiograma"), frozenset({"ecocardiograma"})
        )
        self.assertEqual(
            match.procedimentos_do_servico("Consulta + Eco + Eletro"),
            frozenset({"consulta", "ecocardiograma", "eletrocardiograma"}),
        )
        self.assertEqual(
            match.procedimentos_do_servico("Eco + PA"),
            frozenset({"ecocardiograma", "pressao_arterial"}),
        )


class SelecaoTest(unittest.TestCase):
    def test_regressao_eco_avulso_nao_e_escondido_pelo_alfabeto(self) -> None:
        """Defeito do piloto: "quanto custa o eco" cotava R$ 410 em vez de R$ 180.

        A ordem alfabetica punha `Consulta + Eco`, `Consulta + Eco + Eletro` e
        `Eco + Eletro` na frente, e o corte em tres eliminava `Ecocardiograma`.
        """
        itens = _payload("eco")["itens"]
        self.assertEqual(itens[0]["servico"], "Ecocardiograma")
        self.assertEqual(itens[0]["valor"], "180.00")
        self.assertEqual(itens[0]["aderencia"], match.AFINIDADE_EXATA)

    def test_combinacao_pedida_ganha_do_avulso(self) -> None:
        itens = _payload("consulta com eco")["itens"]
        self.assertEqual(itens[0]["servico"], "Consulta + Eco")
        self.assertEqual(itens[0]["aderencia"], match.AFINIDADE_EXATA)

    def test_empate_prefere_o_servico_mais_simples(self) -> None:
        """"consulta e eco" nao pode puxar `Consulta + Eco + Eletro` primeiro."""
        itens = _payload("consulta e eco")["itens"]
        self.assertEqual(itens[0]["servico"], "Consulta + Eco")

    def test_servico_sem_relacao_com_o_pedido_sai_do_payload(self) -> None:
        nomes = [item["servico"] for item in _payload("eco")["itens"]]
        self.assertNotIn("Eletrocardiograma", nomes)
        self.assertNotIn("Pressão arterial", nomes)
        self.assertNotIn("Consulta", nomes)


class FraseTest(unittest.TestCase):
    def test_correspondencia_exata_responde_sozinha(self) -> None:
        for pergunta, esperado in [
            ("eco", "Ecocardiograma custa R$ 180,00."),
            ("ecodopplercardiograma", "Ecocardiograma custa R$ 180,00."),
            ("ultrassom do coração", "Ecocardiograma custa R$ 180,00."),
            ("ECG", "Eletrocardiograma custa R$ 120,00."),
            ("consulta com eco", "Consulta + Eco custa R$ 410,00."),
            ("eco e eletro", "Eco + Eletro custa R$ 250,00."),
        ]:
            with self.subTest(pergunta=pergunta):
                # `startswith`: o aviso de plantao (RF-P18) vem depois e e
                # verificado no seu proprio teste.
                self.assertTrue(
                    _corpo_de_preco(_payload(pergunta)).startswith(esperado),
                    _corpo_de_preco(_payload(pergunta)),
                )

    def test_frase_nao_lista_combinacoes_nao_pedidas(self) -> None:
        """O excesso de opcoes foi o que gerou confusao no piloto."""
        frase = _corpo_de_preco(_payload("eco"))
        self.assertNotIn("480", frase)
        self.assertNotIn("410", frase)
        # A intencao e "um preco so". Contar "R$" diz isso melhor que a
        # ausencia de ";", que passou a aparecer por outro motivo.
        self.assertEqual(frase.count("R$"), 1, frase)

    def test_pergunta_generica_comeca_pelos_servicos_simples(self) -> None:
        frase = _corpo_de_preco(_payload(None))
        self.assertIn("Consulta: R$ 230,00", frase)
        self.assertIn("Ecocardiograma: R$ 180,00", frase)
        self.assertNotIn("Consulta + Eco", frase)

    def test_payload_vazio_devolve_string_vazia(self) -> None:
        """Sem string o chamador cai na redacao do modelo, nao numa frase capenga."""
        self.assertEqual(_corpo_de_preco(None), "")
        self.assertEqual(_corpo_de_preco({"ok": True, "itens": []}), "")


class EtiquetaRegiaoTest(unittest.TestCase):
    """A base da cotacao fica visivel quando vem do cadastro (persona clinica).

    Sem a etiqueta, uma clinica com `tabela_preco_id` errado passaria
    despercebida: a frase traria so o numero, e quem revisa o rascunho nao
    teria como notar que a tabela e outra.
    """

    def _res(self, **extra):
        base = {
            "ok": True,
            "itens": [{"servico": "Ecocardiograma", "valor": "200.00", "aderencia": 3}],
            "pedido": ["ecocardiograma"],
        }
        base.update(extra)
        return base

    def test_clinica_de_rm_ve_a_tabela_na_frase(self) -> None:
        frase = _corpo_de_preco(self._res(regiao="rm", regiao_do_cadastro=True))
        self.assertTrue(
            frase.startswith("Ecocardiograma custa R$ 200,00 (tabela Região Metropolitana)."),
            frase,
        )

    def test_clinica_de_fortaleza_tambem_ve(self) -> None:
        """Etiquetar so RM nao pegaria a clinica de RM cadastrada como Fortaleza."""
        frase = _corpo_de_preco(self._res(regiao="fortaleza", regiao_do_cadastro=True))
        self.assertIn("(tabela Clínicas Fortaleza)", frase)

    def test_tutor_nao_recebe_etiqueta(self) -> None:
        frase = _corpo_de_preco(self._res(regiao="fortaleza", regiao_do_cadastro=False))
        self.assertTrue(frase.startswith("Ecocardiograma custa R$ 200,00."), frase)
        self.assertNotIn("(tabela", frase)


class AvisoDePlantaoTest(unittest.TestCase):
    """RF-P18: o bot le apenas as colunas `_comercial`, nunca as de plantao.

    Sem qualificar o valor, um cliente perguntando preco num domingo a noite
    receberia o valor de horario comercial como se fosse o dele.
    """

    def test_toda_resposta_com_valor_qualifica_o_horario(self) -> None:
        for pergunta in ("eco", "consulta com eco", None):
            with self.subTest(pergunta=pergunta):
                frase = _corpo_de_preco(_payload(pergunta))
                self.assertIn("horário comercial", frase)
                self.assertIn("plantão", frase)
                self.assertIn("secretaria", frase)

    def test_avisa_mesmo_em_servico_sem_plantao_cadastrado(self) -> None:
        """Em 26/08 so `Consulta` e `Eco + Eletro` tinham plantao preenchido.

        Avisar so neles daria a entender que os outros nao tem plantao,
        quando a celula e que esta vazia.
        """
        self.assertIn("plantão", _corpo_de_preco(_payload("ecocardiograma")))

    def test_concordancia_acompanha_a_quantidade_de_valores(self) -> None:
        self.assertIn("Esse é o valor", _corpo_de_preco(_payload("eco")))
        self.assertIn("Esses são os valores", _corpo_de_preco(_payload(None)))

    def test_resposta_sem_valor_nao_recebe_o_aviso(self) -> None:
        """A orientacao "domiciliar ou em clinica?" nao cita valor nenhum."""
        frase = _corpo_de_preco({"ok": True, "orientacao": "escolher_tipo_atendimento",
                                 "itens": []})
        self.assertNotIn("plantão", frase)
        self.assertNotIn("R$", frase)


if __name__ == "__main__":
    unittest.main()
