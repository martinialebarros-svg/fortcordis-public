# Contrato de saída do editor de ecocardiograma

- CA-001. Após confirmação do rascunho, o botão abre `/laudos`. Se a URL de origem ainda estiver ativa após quatro segundos, o navegador abre o mesmo destino por navegação de documento. A retomada recupera as medidas e habilita **Emitir laudo**.
- CA-002. O link interno preserva seu destino e usa a mesma confirmação do rascunho. Uma falha de confirmação mantém o editor aberto, com o preenchimento e o aviso para tentar novamente.
- CA-003. A espera de navegação exibe feedback e impede ações duplicadas. Sair por outra rota, desmontar o editor ou mudar a conta invalida a alternativa pendente.
- CA-004. Desenvolvimento, loopback e Stage expõem marcos locais no console para identificar início, confirmação do rascunho, solicitação da rota e eventual uso da alternativa. As mensagens contêm apenas rótulos fixos.
