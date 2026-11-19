# Verificação local

| Critério | Estado | Evidência |
| --- | --- | --- |
| CA-01 | validado | Chrome com API e banco locais confirmou reabertura, prévia e impressão. A extração e a inspeção visual dos PDFs conferiram acentos, caracteres especiais, quebras e ausência dos campos inativos. Os testes cobrem rejeição de posologia em branco na emissão e paginação do texto longo. |
| CA-02 | validado | Chrome criou uma receita adicional vazia e baixou dois PDFs com conteúdos distintos no mesmo atendimento fictício. No atendimento novo, o primeiro clique abriu a receita do dia. O teste de reconciliação preservou a digitação e os IDs quando itens foram editados e reordenados durante o salvamento. |
| CA-03 | validado | Chrome encontrou o botão imediatamente após o último cartão e confirmou o foco no nome do medicamento recém-adicionado. |
| CA-04 | validado | Migração aplicada duas vezes em SQLite e PostgreSQL locais, com registro legado e texto multilinha verificados. Os testes cobriram cópia, auditoria, payload antigo e rota legada do PDF. |

Suíte de Atendimento com 437 testes de backend aprovados, incluindo os cenários executados separadamente em PostgreSQL, e 216 testes de frontend aprovados. TypeScript, ESLint nos arquivos alterados, consistência do diff e guardrail SDD aprovados. A validação usou dados fictícios. Homologação em Stage e publicação em produção seguem fora da entrega local.
