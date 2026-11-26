# Verificação

Entrega inicial e validação local concluídas em 26/11/2026. As afirmações desta seção descrevem a etapa local; a publicação autorizada e as evidências instaladas estão registradas abaixo.

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

### Homologação instalada em Stage — 26/11/2026

PR81, Stage `6d97f6806bd4a068301b98da9e730895efeb49c3`, workflow `45904153974`: todos os jobs concluídos com sucesso, incluindo canário autenticado geral e ensaio de backup/restore. Os 44 caminhos do escopo instalado coincidem com a candidata (33 presentes e 11 ausências confirmadas). Três domínios/aliases, 22 bundles, health/ready200 e API protegida401 aprovados. Dez verificações do contrato instalado da API usam armazenamento temporário: persistência do texto, ID/título/metadados, ausência de duplicata, aspectos alheios preservados e preset usando o texto revisado. Catálogos reais, configurações, Nginx, originais e lotes preservados por hashes; produção não reiniciou durante Stage.

Chrome com componente real e API/dados fictícios passou em 1440/1024/390/320 px, nos modos preset e compositor, com atualização, falha e retentativa, sem overflow. Capturas de desktop e celular revisadas. A página completa autenticada não foi testada: o navegador Stage redirecionou a login. Nenhuma credencial foi solicitada nem frase real modificada.

Candidata isolada: 3.014 Vitest + 23 Node; restauração integrada: 3.097 Vitest + 23 Node; lint/tipos/build aprovados em ambas. O PR82 promoveu a candidata para main `23ce0465748d1cdb46425de4e0d3ed398dcb8545`; a instalação de produção e a posterior restauração de Stage seguem em acompanhamento. A restauração conserva exatamente os 38 caminhos paralelos previamente preservados e inclui main na ancestralidade.

Evidências privadas: `/Users/martiniano/Documents/Codex/2026-11-26/atualizar-frase-release/`, especialmente `stage-workflows.json`, `stage-served.json`, `stage-api.json`, `stage-installed-scope.json`, `stage-homologated-preservation.json` e `visual-results.json`. O resultado final de produção/restauração será consolidado em `final-summary.json`; somente arquivos existentes e aprovados constituem evidência.
