# Saída do editor de ecocardiograma

Ao clicar em **Voltar para laudos**, o usuário deve conseguir sair do editor e retomar as medidas salvas. Em Stage, o botão manteve a URL em `/laudos/novo` sem feedback, embora o rascunho tenha sido recuperado ao usar o histórico do navegador.

A correção abrange o editor de laudos novos e os links internos que passam pela mesma guarda. A saída precisa preservar o contrato de confirmação do rascunho e a decisão sobre imagens pendentes.


## Recuperação pendente — 25/11/2026

Martiniano autorizou corrigir o bloqueio dos menus quando o editor aguarda a escolha sobre um rascunho recuperável. Nesse estado, sair deve preservar a cópia já salva e permitir acessar outros menus sem exigir retomada ou início de outra cópia.

O escopo inclui os editores de ecocardiograma novo e existente, que compartilham a mesma pré-condição de salvamento. A correção não altera dados clínicos, contratos de API, emissão, atualização oficial ou a proteção de alterações ainda não confirmadas. A entrega desta etapa é local; publicação segue o fluxo separado de Stage e produção.
