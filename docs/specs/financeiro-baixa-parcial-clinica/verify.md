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
| Producao | Nao solicitada nesta entrega | pendente |

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
