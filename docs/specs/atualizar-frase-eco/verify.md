# Verificação

Implementação e validação local concluídas em 26/11/2026. Sem commit, push ou publicação em Stage/produção.

| Critério | Estado | Evidência |
| --- | --- | --- |
| CA-01 | aprovado localmente | Testes nos modos preset/compositor verificam um único PUT com ID, título, texto, tags, patologias e ordem. Sem criação, salvamento de preset ou alteração de outros campos do laudo. |
| CA-02 | aprovado localmente | Sucesso desabilita novo envio sem edição; “Usar frase” recupera o texto atualizado do banco local. Falha mantém texto/ID e permite retentativa; nenhuma mensagem de sucesso falso. Edição que coincide com outra frase preserva o ID original. |
| CA-03 | aprovado localmente | Testes com frase inativa, texto vazio/inalterado e promessa pendente. Atualização, criação e propagação ficam indisponíveis durante o envio; digitar durante o PUT preserva a nova edição. |
| CA-04 | aprovado localmente | Testes de ambos os modos, conclusão composta sem botão de atualização e criação de nova frase com texto revisado, sem PUT. Regressões de composição existentes aprovadas. |

## Verificações

- `npx vitest run app/laudos/components/EcocardiogramaEstruturadoEditor.test.tsx`: 17 testes aprovados na versão final (oito existentes e nove adicionados).
- Suíte completa Vitest: 171 arquivos e 3.096 testes aprovados antes da inclusão final da regressão de criação de nova frase, depois coberta pela execução focada acima.
- `node --test`: 23 testes aprovados. A primeira chamada `npm test -- --maxWorkers=4` passou o argumento ao Node por causa do encadeamento do script; o erro de invocação foi corrigido executando os testes Node separadamente.
- `npm run lint`, `npx tsc --noEmit` e `npm run build`: aprovados. Aviso preexistente de base Browserslist desatualizada no build.
- `git diff --check` e `evaluate_guardrail` incluindo os arquivos novos: aprovados, feature qualificada `atualizar-frase-eco`.
- Revisão do diff e do contrato existente `PUT /frases-ecocardiograma-estruturado-teste/frases/{id}` concluída; sem alteração de backend, dados clínicos padrão, migração ou emissão de laudo.

Os testes de interação usam jsdom, fixtures fictícias e API simulada. Não houve homologação visual em navegador autenticado ou escrita em bancos reais; a verificação manual integrada fica para a homologação em Stage. Nenhum laudo salvo é atualizado pela operação de catálogo.

Base: `origin/stage` `33b9f20714380b5ca865b3905ac06326514637bc`, remoto público `martinialebarros-svg/fortcordis-public`, branch `codex/atualizar-frase-eco`, worktree `/Users/martiniano/.codex/worktrees/atualizar-frase/fortcordis-public`.

## Publicação autorizada — 26/11/2026

Martiniano autorizou publicar em Stage, validar e promover para produção. A candidata será isolada dos 38 caminhos paralelos de Stage, preservados no snapshot integrado e restaurados após a promoção. A publicação usará PR de feature para Stage e PR direto Stage→main, sem bypass do guardrail. Preservar Nginx e runtime. Homologação instalada e resultados de produção serão registrados nas evidências privadas de release.
