# Contrato de saída do editor de ecocardiograma

- CA-001. Após confirmação do rascunho, o botão abre `/laudos`. Se a URL de origem ainda estiver ativa após quatro segundos, o navegador abre o mesmo destino por navegação de documento. A retomada recupera as medidas e habilita **Emitir laudo**.
- CA-002. O link interno preserva seu destino e usa a mesma confirmação do rascunho. Uma falha de confirmação mantém o editor aberto, com o preenchimento e o aviso para tentar novamente.
- CA-003. A espera de navegação exibe feedback e impede ações duplicadas. Sair por outra rota, desmontar o editor ou mudar a conta invalida a alternativa pendente.
- CA-004. Desenvolvimento, loopback e Stage expõem marcos locais no console para identificar início, confirmação do rascunho, solicitação da rota e eventual uso da alternativa. As mensagens contêm apenas rótulos fixos.


## Recuperação pendente — contrato adicional de 25/11/2026

- CA-005. Em ambos os editores, quando o estado é `recovery`, Voltar e links internos devem navegar ao destino solicitado sem tentar salvar, retomar, fechar, descartar ou substituir a cópia recuperável. O identificador guardado no navegador, a revisão e o snapshot salvos permanecem iguais. Reabrir o mesmo contexto deve oferecer a mesma cópia e permitir recuperar seus valores literais. A guarda de `beforeunload` não deve emitir um aviso de alterações não salvas apenas porque o formulário ainda não recuperado difere da cópia salva.
- CA-006. A exceção limita-se à escolha de recuperação pendente. Após retomada ou durante edição normal, a saída continua aguardando a confirmação das alterações atuais; falha de salvamento mantém o preenchimento na tela e permite tentar novamente. Continuam válidas as verificações de proprietário, atualização em curso e arquivos pendentes. Nenhuma emissão ou atualização oficial ocorre ao sair.

O fallback de quatro segundos de CA-001 continua específico ao editor novo. O editor existente conserva o botão de retorno ao detalhe do laudo e os destinos dos links internos; não se amplia aqui o mecanismo do roteador.
