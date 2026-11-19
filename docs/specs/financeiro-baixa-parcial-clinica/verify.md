# Verificacao

| Criterio | Evidencia | Estado |
|---|---|---|
| BP-001/BP-002 | Teste backend registra R$ 300,00 numa OS de R$ 1.000,00, preserva `valor_final`, mantem status pendente e saldo de R$ 700,00 | aprovado localmente |
| BP-003/BP-004/BP-005 | Testes backend rejeitam clinicas diferentes/excedente e rateiam R$ 300,00 em OS de R$ 200,00 + R$ 500,00 + R$ 300,00 | aprovado localmente |
| BP-006/BP-007 | Testes de saldo esperado, locks/rollback existentes e repeticao da chave | aprovado localmente |
| BP-008/BP-010 | Lista e grupo retornam recebido R$ 300,00 e pendencia R$ 700,00; testes de busca/resumo continuam aprovados | aprovado localmente |
| BP-009 | Guardas de edicao/exclusao e desfazer aceitam recebimento parcial; regressao de ajuste de valor aprovada | aprovado localmente |
| BP-011 | Teste de interface desabilita recibo de quitacao e confirma baixa parcial | aprovado localmente |
| BP-012 | 79 testes backend focados, 57 testes frontend focados, suite frontend completa, TypeScript, ESLint e build de producao | aprovado localmente |
| Regressao backend ampla | Gate oficial `unittest discover`: 2.776 testes, 146 ignorados | aprovado localmente |
| Guardrail SDD | `spec.md` + `verify.md` reconhecidos para `financeiro-baixa-parcial-clinica` | aprovado localmente |
| Stage tecnico | Deploy do SHA `4bf03990b881fb24d105949b4d0878935ad158b2`, backend saudavel, canario autenticado e 46 testes descartaveis de ordens de servico no VPS | aprovado em Stage |
| Stage autenticado | Em uma OS explicitamente sintetica de R$ 300,00, o formulario aceitou R$ 100,00 sem gravar a operacao, exibiu baixa parcial, saldo restante de R$ 200,00, bloqueou recibo e alterou a acao para `Confirmar baixa parcial` | aprovado em Stage |
| Producao da funcionalidade original | PR `#45`, SHA `33aa37e3`, deploy `44428710832` | aprovado em producao |

## Correção de Cobranças — 2026-11-19

| Criterio | Evidencia | Estado |
|---|---|---|
| BP-013, abertura segura | Simulação de timeout nas rotas por OS, seguida de abertura por uma unica consulta em lote. Seleção incompleta ou alterada é rejeitada, e a API aceita somente IDs positivos e até 200 itens. | aprovado localmente |
| BP-013, recuperação | Uma leitura com timeout mantém o recebimento fechado e libera nova tentativa. Uma resposta atrasada após troca de aba não abre o formulário. | aprovado localmente |
| BP-014 | Depois de uma baixa de R$ 300,00 sobre R$ 1.000,00, a clínica reabre com a OS Parcial, o saldo de R$ 700,00 e o próximo formulário preenchido com R$ 700,00. Uma divergência verdadeira entre saldo e resumo continua bloqueada. | aprovado localmente |

Esta correção foi verificada com dados descartáveis. A homologação em Stage e a instalação em produção são etapas posteriores à validação local.

- Frontend: 74 testes focados no diff final, incluindo as respostas incompletas, repetidas, com outro destinatário ou com outro saldo. Suíte geral e testes Node aprovados. TypeScript, ESLint e build Next.js aprovados.
- Backend: 58 testes focados e 38 subtestes aprovados, incluindo o filtro autenticado por IDs e o contrato HTTP. Suíte completa em SQLite descartável aprovada.
- Guardrail SDD e `git diff --check` aprovados.

## Comandos executados

- `python -m pytest -q tests/test_ordens_servico_receber_lote.py tests/test_ordens_busca_resumo.py tests/test_ordens_servico_ajuste_valor.py tests/test_ordens_servico_domiciliar.py tests/test_recebimento_desconto_baixa_credito.py tests/test_os_responsavel_pagamento_migration.py`
- `npx tsc --noEmit`
- `npx vitest run app/financeiro/page.test.tsx lib/ordens-selection.test.ts`
- `npx eslint app/financeiro/page.tsx app/financeiro/page.test.tsx lib/ordens-selection.ts --max-warnings=0`
- `npm test && npm run build`
- `uv run --no-project --python 3.11 --with-requirements requirements.txt --with-requirements requirements-test.txt python -m unittest discover -s tests -p 'test_*.py'`
- avaliacao local de `scripts/ci/check_sdd_guardrail.py` com a lista real de arquivos alterados

Data da verificacao local: 2026-11-17 (America/Fortaleza).

## Verificacao em Stage

- PR de implementacao: `#34`.
- SHA instalado e conferido no VPS: `4bf03990b881fb24d105949b4d0878935ad158b2`.
- Workflow `Deploy to Stage (VPS)` `44054315133`: quality gate, deploy, backend health, canario autenticado, restauracao de backup e 46 testes descartaveis de ordens de servico aprovados.
- Rota autenticada `/financeiro`: 31 ordens carregadas; simulacao sem confirmacao na OS ficticia `TESTE-ROTINA-OUT26-P14`, alterando o valor de R$ 300,00 para R$ 100,00, apresentou saldo de R$ 200,00 e as restricoes esperadas para uma baixa ainda parcial.
- Nenhum recebimento foi confirmado ou persistido durante a homologacao de interface.
- O endpoint protegido de ordens respondeu `401` sem sessao, conforme esperado.

Data da verificacao em Stage: 2026-11-17 (America/Fortaleza).
