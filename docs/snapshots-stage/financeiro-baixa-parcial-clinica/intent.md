# Baixa parcial de valores em aberto de uma clinica

## Problema

O Financeiro exigia que o total informado coincidisse exatamente com a soma das ordens de servico selecionadas. Assim, um pagamento de R$ 300,00 para uma clinica com R$ 1.000,00 em aberto nao podia ser registrado sem ajustar artificialmente uma OS.

## Resultado desejado

Permitir que o usuario registre o valor efetivamente recebido, mantenha o restante em aberto e consiga completar ou desfazer o recebimento depois, sem alterar o valor original das OS e sem criar credito indevido.

## Fora do escopo

- baixa parcial de dividas de destinatarios diferentes no mesmo lote;
- alteracao do valor original da OS para representar pagamento;
- envio de recibo de quitacao enquanto ainda houver saldo em aberto;
- publicacao em Stage ou producao nesta entrega local.
