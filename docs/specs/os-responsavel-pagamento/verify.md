# Verificacao

| Criterio | Evidencia | Status |
| --- | --- | --- |
| CA-001 | Teste da pagina cobre padrao clinica e troca explicita para veterinario. | validado localmente |
| CA-002 | Testes de interface e servidor cobrem OS de veterinario com e sem clinica, preco na previa e preservacao do vinculo no laudo. | validado localmente |
| CA-003 | Teste transacional confirma campos do responsavel, resumo da OS, auditoria e conflito de idempotencia ao trocar o pagador. | validado localmente |
| CA-004 | Teste do servidor confirma chave `veterinario:<id>`, nome do grupo, destinatario serializado e contato do profissional; testes do Financeiro permanecem aprovados. | validado localmente |
| CA-005 | Teste da migracao executa o upgrade duas vezes e confirma vinculos, valores esperados das colunas novas e ausencia de criacao de tabela indevida. | validado localmente |
| CA-006 | A baixa de OS do veterinario omite o controle de credito de terceiros. O teste rejeita excedente e verifica rollback do recebimento. A emissao apenas cria a pendencia. | validado localmente |

A revisao de publicacao passou em 85 testes focados de backend, 74 de frontend, ciclo de migracao SQLite, lint focado, tipos e build Next.js. Nos testes locais, 22 casos que exigem PostgreSQL ficaram para CI. A suite anterior a esta revisao passou com 2.737 testes de frontend.
