# Especificação

| Critério | Comportamento |
| --- | --- |
| CA-001 | O detalhe de um laudo publicado permite suspender e retomar o download. A lista interna mostra o estado suspenso. A operação exige permissão de edição de Laudos, é idempotente e registra a alteração em auditoria na mesma transação. |
| CA-002 | A clínica e o veterinário continuam vendo o registro, com indicação de que o laudo está em correção. O servidor recusa a emissão de autorizações e o download com autorização emitida antes da suspensão ou com sessão do portal, usando HTTP 423. |
| CA-003 | O link ativo recebido no WhatsApp mostra a suspensão e deixa de emitir autorizações enquanto o laudo estiver em correção. Depois da retomada, o mesmo link volta a entregar o PDF publicado. A publicação para novos destinatários e o aviso de disponibilidade aguardam a retomada. |
| CA-004 | Salvar uma correção ou substituir o PDF deixa a pausa em vigor. A edição e a consulta interna, a revisão do rascunho de eco e o acesso do tutor seguem seus fluxos. As datas e os destinatários da publicação são preservados pela pausa. |
| CA-005 | A migração adiciona o estado por laudo e mantém habilitado o download dos laudos existentes. A verificação local cobre PostgreSQL e SQLite. |

`PUT /api/v1/laudos/{id}/portal/download-suspenso` recebe `{"suspenso": true}` ou `{"suspenso": false}` e devolve `portal_download_suspenso`. O detalhe e a listagem interna incluem esse estado. Nos portais e no link da clínica, o campo `download_suspenso` reflete o efeito para o solicitante. A rota de entrega do arquivo consulta o estado persistido antes de servir os bytes e registra apenas os downloads que passaram por essa verificação.

A retomada usa o PDF salvo pelo fluxo de edição contratado. Ela depende da revisão do operador e conserva as autorizações de destinatários já concedidas.

O detalhe recebe `portal_pode_suspender_download` do servidor. Um exame liberado pelo Atendimento também habilita o controle, mesmo com o laudo em “Finalizado”.

O detalhe usa `portal_pode_suspender_download` para reconhecer também exames liberados pelo Atendimento cujo laudo mantém status interno Finalizado.
