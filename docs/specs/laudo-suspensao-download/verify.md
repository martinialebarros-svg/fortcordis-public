# Verificação

| Critério | Estado | Evidência local |
| --- | --- | --- |
| CA-001 | aprovado localmente | Chrome com API simulada confirmou ações no detalhe e na ultrassonografia abdominal, persistência após recarregar e selo apenas no item suspenso da lista. O teste HTTP real recusou a escrita com credencial de parceiro e conferiu um evento de auditoria por mudança efetiva. |
| CA-002 | aprovado localmente | O teste HTTP exercitou clínica e veterinário, inclusive a tentativa com sessão e autorizações criadas antes da pausa. Todas retornaram 423 e preservaram os marcadores de download. O Chrome mostrou o aviso em ambos os portais. |
| CA-003 | aprovado localmente | O teste HTTP abriu o link antigo antes e durante a pausa, confirmou o bloqueio e conferiu os bytes da versão atualizada após retomar. O aviso por WhatsApp e a publicação foram recusados enquanto suspenso. O Chrome também mostrou a recusa ao clicar em um botão deixado aberto antes da pausa. |
| CA-004 | aprovado localmente | O teste HTTP confirmou a preservação do acesso do tutor, da revisão do editor, dos vínculos e do estado suspenso durante o salvamento. A suíte de laudos inclui substituição de PDF de ECG. O botão interno de PDF permaneceu disponível no Chrome. |
| CA-005 | aprovado localmente | Migração 20261119_113 aplicada duas vezes em SQLite e PostgreSQL 16 descartáveis. Laudos anteriores e novos começam com download habilitado, e a repetição preservou uma suspensão feita depois da primeira execução. |

`backend/tests/test_portal_access_http_flow.py` registra o cenário de suspensão, correção e retomada. As suítes de Laudos e Portal passaram com 392 testes e os quatro testes de concorrência do editor foram executados no PostgreSQL local. O frontend passou com 2.968 testes Vitest, 23 testes Node e build de produção. O guardrail de especificações e a revisão do diff passaram.

A homologação em Stage foi concluída no SHA `5256f4f8a266aa910da1ba93d3d34870e9dcf0bd`, instalado pelo workflow [44571365443](https://github.com/martinialebarros-svg/fortcordis-public/actions/runs/44571365443). O workflow terminou com sucesso, preservou e restaurou os seis arquivos de runtime e passou no teste de restauração do backup. O código instalado e os chunks servidos foram conferidos no domínio canônico e nos aliases.

O cenário autenticado usou somente dados fictícios: suspensão idempotente, recusa para usuário externo, bloqueio de clínica/parceiro/link e de autorizações anteriores, correção do PDF mantendo a pausa, preservação do acesso interno e do tutor, retomada no mesmo link com os bytes corrigidos e auditoria de ambas as ações. As autorizações de curta duração expiradas durante a interrupção de conectividade continuaram recusadas com 401; novas autorizações entregaram o PDF corrigido. A interface exibiu a mensagem de correção durante a pausa e o arquivo após retomar. Os registros fictícios foram removidos, preservando a auditoria. Nenhuma mensagem foi enviada.

A promoção `stage -> main` está registrada na [PR #61](https://github.com/martinialebarros-svg/fortcordis-public/pull/61), commit `a5e3fcb8af4e8be807955da43ca852bfa251bcda`. A instalação é rastreada pelo [workflow 44748775443](https://github.com/martinialebarros-svg/fortcordis-public/actions/runs/44748775443); as evidências operacionais de SHA instalado, smoke autenticado, runtime e arquivos servidos são mantidas separadamente do resultado local dos testes.

A árvore de restauração parte desse commit de produção e recompõe os 36 caminhos paralelos de Stage `4d0b7918c9aaf191aaa76286482f4de3f091931a`. Os 1.467 caminhos fora do escopo da suspensão foram comparados por objeto Git e preservados. A combinação passou em seis testes HTTP, 26 testes do visualizador e TypeScript; os dois testes a menos no visualizador são diferenças preexistentes entre Stage e produção, mantidas na restauração. O helper temporário de validação remota não integra a entrega.

A compatibilidade com a liberação pelo Atendimento foi coberta no cenário HTTP de suspensão e no visualizador. Passaram 20 testes do backend e 28 testes do visualizador, incluindo o caso de laudo “Finalizado” com exame publicado.

A regressão do fluxo de Atendimento verifica o controle no detalhe e o ciclo completo com laudo Finalizado e exame liberado. Os dados fictícios representam essa combinação suportada.
