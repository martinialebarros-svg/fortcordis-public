"""Reconhecimento exato de avisos institucionais revisados, nunca de sintomas.

Não usa substrings nem inferência: qualquer texto adicional segue a triagem
normal. A normalização tolera apenas apresentação (acentos, emoji, pontuação).
"""
import re
import unicodedata

AVISOS = (
    """Olá! Você entrou em contato com a Vetplus Especialidades fora do nosso expediente.
Responderemos sua mensagem assim que possível dentro do nosso horário:
Segunda a Sexta: 08h às 12h e das 14h às 18h.
Sábados: 08h às 12h.
Se este for um caso de emergência agora, recomendamos procurar o hospital 24h de sua preferência""",
    """Olá, tudo bem? Agradecemos a sua mensagem. Não estamos disponíveis no momento, mas responderemos assim que possível.
Fora do horário de funcionamento!
Seg à Sexta 08h às 12h 15h às 18h
Sábado 08h às 12h 15h às 17h
Se achar que é EMERGÊNCIA/URGÊNCIA, leve seu pet para uma Clínica 24 horas mais próxima. Obrigada!""",
    """Agradecemos sua mensagem. Não estamos disponíveis no momento, mas responderemos assim que possível.
Nosso atendimento é nos dias de Segunda, Terça e Sexta (13:30h às 18:00h) e aos Sábados (8:00h às 17:00h).
Em caso de emergência fora do nosso horário de atendimento, indicamos levar o seu pet a uma clínica ou hospital 24 horas.""",
    "Agradecemos sua mensagem. Não estamos disponíveis no momento, mas entraremos em contato assim que possível.",
    "Casa Pet Ce agradece seu contato. Como podemos ajudar?",
    "Lynda Pet Clinica agradece o seu contato! Como posso ajudar? Assim que possível iremos tirar suas dúvidas!",
    "Consultório Animale Petshop agradece seu contato. Como podemos ajudar?",
    # Avisos completos revisados na auditoria de 26/09 a 02/10/2026.
    """Olá!! Seja Bem Vindo a *Clínica Veterinária Popular Vitoria's Pet*

Dispomos de serviços a PREÇO POPULAR:
Consultas, Vacinas,Exames laboratoriais e de Imagem, Cirurgias eletivas e de emergência, Testes rápidos, Farmácia completa e muito mais !!! 🏅🐾

_Nossos horários de funcionamento:_
_Segunda a Sexta de 8 as 18h_
_Sábado 8 as 12h_

‎Agradecemos seu contato. Como podemos ajudar?""",
    """Agradecemos sua mensagem. Não estamos disponíveis no momento, mas responderemos assim que possível.

Se for emergência buscar atendimento veterinário mais próximo e disponível.

🕐 HORÁRIO DE FUNCIONAMENTO DA LOJA

🛑 *SEGUNDA A SÁBADO*
🕐 08:00 ÀS 12:00
🕐 14:00 ÀS 19:00

🛑 *DOMINGO E FERIADOS*
🕐 08:00 às 12:00
🕐 A TARDE - FECHADO

🐶😻❤️""",
    """A gente tá descansando agora 🌙 Nosso atendimento é:

📅 Seg a sex: 9h às 18h
📅 Sábado: 8h às 17h

⚠️ Se for emergência agora (sangramento, convulsão, dificuldade pra respirar ou ingestão de algo tóxico), procure um pronto-socorro veterinário 24h imediatamente.

Mas se puder esperar até abrirmos, deixa tudo registrado aqui — assim eu já organizo seu atendimento e você fica no topo da fila da manhã ⭐""",
    """Olá!! estamos fora do horário de atendimento

Em caso de emergência fora do horário de funcionamento, indicamos se dirigir às clínicas 24horas mais próximas.

Nosso horário de funcionamento é:
Seg-sex das 08h as 18h
Sáb das 08h as 12h

Conosco a saúde do seu pet tem Vitória garantida 🥇""",
    """Olá, tudo bem?! No momento não estamos disponíveis.

Nosso horário de funcionamento:

*Segundas:* 13:30h às 17:30h
*Terça a Sábado:* 08:30h às 17:30h
* Domingo:* Fechado

Em caso de emergência, sugerimos levar o seu pet em uma clínica 24h.""",
)


def _normalizar(texto):
    texto = unicodedata.normalize('NFKD', str(texto or '').casefold())
    texto = ''.join(c for c in texto if not unicodedata.combining(c))
    return ' '.join(re.findall(r'[a-z0-9]+', texto))


_AVISOS = frozenset(_normalizar(texto) for texto in AVISOS)


def mensagem_automatica(item):
    return (not item.get('from_me') and item.get('type') == 'text'
            and _normalizar(item.get('body')) in _AVISOS)


def sem_aviso_automatico(item):
    # Cópia transitória: conserva data/tipo/direção e limites do agrupamento.
    # A mensagem original continua intacta no WhatsApp para auditoria.
    return {**item, 'body': ''} if mensagem_automatica(item) else item
