# Plano

1. Derivar o valor recebido de pagamentos vinculados a transacoes financeiras ainda ativas.
2. Expor `valor_recebido`, `valor_em_aberto` e `recebimento_parcial` nas OS sem migracao de dados.
3. Aceitar no recebimento em lote um total menor que o saldo selecionado quando todas as OS pertencerem a mesma clinica responsavel.
4. Aplicar o pagamento primeiro nas OS mais antigas, quitando-as ate que a ultima alocacao fique parcial.
5. Manter OS parcialmente recebida como pendente e impedir edicao, cancelamento ou exclusao ate desfazer os recebimentos.
6. Atualizar totais, cobrancas, PDF de pendencias e interface para usar o saldo, nao o valor original.
7. Proteger a operacao parcial com chave contra repeticao e validar o saldo conferido pelo cliente sob lock.
8. Cobrir o exemplo R$ 1.000,00 / R$ 300,00, quitacao posterior, rateio entre OS, concorrencia e regressao de baixas integrais.

## Falha segura e reversao

O lote continua atomico: qualquer divergencia ou erro desfaz todas as gravacoes da solicitacao. A rota existente de desfazer cancela todos os recebimentos ativos daquela OS e restaura o saldo integral. Como o saldo e derivado e nao ha nova coluna, nao existe migracao de banco a reverter.

## Correção no fluxo de Cobranças

1. Acrescentar o filtro por IDs à consulta autenticada de OS e usar uma só leitura para conferir o lote. Preservar a validação de seleção completa e a conferência de concorrência no recebimento.
2. Comparar os totais de Cobranças com os saldos das OS e testar a reabertura da clínica, inclusive a próxima baixa do saldo.
3. Validar recuperação de falha, descarte de resposta após troca de aba e rejeição de dados alterados. O filtro é opcional e pode ser revertido junto com a interface sem migração.
