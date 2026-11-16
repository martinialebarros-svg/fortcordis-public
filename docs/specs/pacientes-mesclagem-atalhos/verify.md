# Verificação

| Critério | Evidência | Status |
| --- | --- | --- |
| CA-001 | Testes da carteira e da central verificam seleção exata de dois códigos, preenchimento e inversão. A seleção e o destino foram conferidos também no Chrome local. A ficha encaminha um único código pelo mesmo contrato. | validado localmente |
| CA-002 | Teste do diálogo verifica prévia e adiamento sem chamar confirmação. No Chrome local, revisei e guardei uma dupla fictícia, fechei com Escape e confirmei o foco devolvido ao botão e a queixa ainda presente. | validado localmente |
| CA-003 | Testes da central cobrem tutores distintos com códigos visíveis, bloqueio, 403, aceite com motivo e histórico. A prévia de tutores diferentes foi conferida no Chrome local. | validado localmente |

Dezesseis testes focados, checagem de tipos, lint, build Next.js e guardrail SDD aprovados. A validação no navegador usou a aplicação compilada e respostas de API fictícias confinadas à máquina local. O backend, seus contratos e os registros reais não foram alterados. Validação de Stage e publicação aguardam entrega.

Na promoção, dois ciclos da verificação completa interromperam a instalação na confirmação de documentos do teste existente de revisão de raça. O fixture agora aguarda a resposta simulada e os efeitos do React com `act` antes de interagir, além de verificar que a confirmação está habilitada antes dos dois cliques. As verificações da requisição única e da decisão persistida continuam no teste. O ajuste é restrito ao teste e a esta evidência.
