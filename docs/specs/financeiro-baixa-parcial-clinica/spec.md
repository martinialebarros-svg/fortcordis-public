# Especificacao

## Regras funcionais

- BP-001: o valor original e o desconto da OS permanecem inalterados; o saldo e `valor_final - soma dos pagamentos ativos`.
- BP-002: um pagamento positivo menor que o saldo selecionado registra baixa parcial e mantem o restante em aberto.
- BP-003: a baixa parcial em lote aceita somente OS da mesma clinica responsavel pelo pagamento.
- BP-004: o valor e alocado por `data_atendimento` crescente e, em empate, por identificador crescente. OS antigas sao quitadas antes da OS que recebe a fracao restante.
- BP-005: o total informado nao pode exceder o saldo selecionado. Baixa parcial nao gera credito.
- BP-006: o cliente envia valor e saldo esperados. O servidor bloqueia as OS, recalcula os saldos e rejeita qualquer divergencia antes de gravar.
- BP-007: cada solicitacao parcial usa uma identificacao persistida nas transacoes. Reutilizar a mesma identificacao e recusado para evitar duplicidade.
- BP-008: OS com saldo parcial continua com status persistido `Pendente`, mas a API e a interface informam `recebimento_parcial`, valor recebido e saldo em aberto.
- BP-009: edicao de valores, cancelamento e exclusao sao bloqueados enquanto existir recebimento ativo. Desfazer cancela todos os recebimentos ativos da OS.
- BP-010: totais de cobranca, resumo financeiro, mensagem e PDF de pendencias usam o saldo em aberto.
- BP-011: recibo de quitacao pelo WhatsApp fica indisponivel enquanto o lote ou a OS continuar parcial.
- BP-012: baixas integrais existentes, multiplas formas, taxas, credito do cliente, auditoria, notificacao pos-commit e rollback permanecem compativeis.
- BP-013: `Receber pendentes` e `Receber selecionadas` conferem até 200 OS pendentes em uma única leitura, comparando os dados atuais com a seleção. Seleção alterada ou incompleta bloqueia a abertura. Em falha de leitura, o operador pode tentar abrir novamente sem enviar o recebimento.
- BP-014: os detalhes de Cobranças conferem o total do destinatário somando o saldo das OS pendentes em centavos. Usam o valor original apenas quando a API não informa o saldo. Divergências reais de saldo continuam bloqueando o detalhe.

## Contrato

Itens de `PATCH /ordens-servico/receber-lote` aceitam `saldo_em_aberto_esperado`; o lote aceita `idempotency_key`. A resposta inclui OS afetadas, OS quitadas, OS ainda parciais, valor recebido, saldo restante e indicador `baixa_parcial`.

`PATCH /ordens-servico/{id}/receber` aceita os mesmos campos de conferencia para completar ou registrar uma fracao do saldo de uma unica OS.

As leituras de OS acrescentam `valor_recebido`, `valor_em_aberto` e `recebimento_parcial` sem remover campos anteriores.

`GET /ordens-servico` aceita o filtro opcional repetido `os_ids` (IDs positivos, até 200 por chamada). O filtro combina com os demais filtros e mantém o contrato e as permissões da listagem. A confirmação usa o mesmo `PATCH /ordens-servico/receber-lote` com valor e saldo esperados.
