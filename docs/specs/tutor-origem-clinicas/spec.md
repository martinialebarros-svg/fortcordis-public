# Especificação

## Requisitos

- RF-001: ao abrir a seção de origem ou focar seu campo, carregar sugestões das clínicas ativas retornadas por `/clinicas`, usando `listarTodasClinicas` com paginação e cache por sessão existentes.
- RF-002: oferecer os nomes em uma lista nativa de sugestões associada ao campo, sem trocar automaticamente o valor preenchido. A escolha grava o nome no contrato textual `origem_cadastro` existente.
- RF-003: manter origem opcional, texto livre, observações e situação da identificação. Carregar sugestões não salva, cria ou vincula registros.
- RF-004: carregar apenas quando necessário. Falhas devem permitir digitar e salvar, com aviso e tentativa explícita de recarregar as sugestões. Não atualizar estado após desmontagem.
- RF-005: aplicar o comportamento aos consumidores existentes de `TutorIdentificacaoFields`, preservando valores antigos e a origem previamente sugerida pela Agenda.

## Critérios de aceitação

- CA-001: uma clínica retornada pelo catálogo aparece nas sugestões e seu nome pode ser salvo como origem do tutor.
- CA-002: a lista inclui clínicas além da primeira página, respeitando o endpoint existente.
- CA-003: abrir/carregar as sugestões preserva a origem existente e permite outra origem em texto livre.
- CA-004: erro de leitura não bloqueia o campo e uma nova tentativa recupera as sugestões.
- CA-005: cadastro mínimo, identificação e consumidores existentes continuam funcionando; abrir o formulário sem usar origem não consulta clínicas.

## Contratos e limites

O backend permanece autoritativo sobre clínicas ativas e permissões. Não adicionar `clinica_id` ao tutor: a origem é uma descrição, não um vínculo assistencial ou financeiro. A aparência e filtragem das sugestões seguem o suporte nativo do navegador a `datalist`.
