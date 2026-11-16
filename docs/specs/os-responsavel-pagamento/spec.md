# Especificacao

- RF-001 / CA-001: ao optar por gerar OS no upload avulso de eletrocardiograma, oferecer escolha explicita entre **Clinica parceira** e **Veterinario parceiro**. Clinica permanece o padrao compativel com o comportamento anterior.
- RF-002 / CA-002: a opcao de veterinario exige parceiro ativo selecionado. Se houver clinica no laudo, usar a tabela vigente daquela clinica e preservar o vinculo no laudo. No caso sem clinica, usar a tabela padrao de Fortaleza para o servico e horario, exigindo preco positivo.
- RF-003 / CA-003: persistir na OS o tipo, identificador, nome e contatos do responsavel no momento da emissao. Incluir a escolha na identidade idempotente do upload e na auditoria da criacao.
- RF-004 / CA-004: agrupar cobrancas por veterinario no Financeiro. O portal financeiro da clinica continua restrito as OS cobradas da clinica. A conferencia fiscal apresenta o nome do veterinario e deixa os dados fiscais do tomador em aberto.
- RF-005 / CA-005: as ordens existentes conservam os vinculos e as regras legadas. A migracao e aditiva e idempotente.
- RF-006 / CA-006: receber OS do veterinario pelo valor devido, sem usar ou gerar credito do tutor ou da clinica. A emissao apenas cria a pendencia.
