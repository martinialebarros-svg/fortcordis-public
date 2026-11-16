# Plano

1. Adicionar campos de responsavel financeiro a `ordens_servico`, preservando dados e indices.
2. Validar a escolha no servidor, persistir o responsavel, incluir a escolha na idempotencia e na auditoria e calcular o preco do catalogo conforme o vinculo do laudo.
3. Adicionar o seletor ao upload de eletrocardiograma, bloquear combinacoes incompletas e exibir a confirmacao de nome e valor antes do envio.
4. Adaptar listagem, agrupamento, contato e baixa no Financeiro para reconhecer o veterinario, sem confundir credito de clinica.
5. Cobrir migracao, criacao para os dois responsaveis, retry, agrupamento, contato e interface com dados sinteticos. Executar testes focados, tipos, lint, build e guardrail SDD.

Em reversao, manter os campos de banco. Caso ja existam OS emitidas para veterinario, preservar a interpretacao do responsavel no Financeiro e nas exportacoes mesmo com a criacao desabilitada.
