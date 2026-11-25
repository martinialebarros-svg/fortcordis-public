# Verificação

| Critério | Estado | Evidência |
| --- | --- | --- |
| CA-001 | aprovado localmente | Chrome com Next.js compilado. Botão e transição pendente chegam a `/laudos`. A retomada conserva as medidas e habilita a emissão. |
| CA-002 | aprovado localmente | Chrome confirma saída pelo menu. O cenário com HTTP 503 mantém a medida nova no editor, exibe aviso e permite salvar e sair na repetição. |
| CA-003 | aprovado localmente | Chrome confirma aviso e botão desabilitado enquanto a transição está pendente. Outra navegação cancela a alternativa. |
| CA-004 | aprovado localmente | O teste confere a sequência dos eventos no console, com alternativa apenas quando necessária e sem solicitação de rota após falha de salvamento. |

A suíte de frontend passou com 2.906 casos Vitest e 23 casos Node. Build, tipos e guardrail SDD foram verificados localmente. A instalação e a coleta de marcos em Stage ficam para a etapa de publicação. A origem exata da falha observada em Stage continua em aberto.

## Como repetir localmente

Na pasta `frontend`, com Google Chrome disponível:

```sh
npm ci
API_BACKEND_URL=http://127.0.0.1:19464 npm run build
npm run test:echo-draft-navigation
```

O teste inicia o Next.js compilado na porta 19465 e uma API simulada na porta 19464, ambas no loopback. Dados do teste ficam em memória.


## Correção de recuperação pendente — 25/11/2026

A autorização atual é corrigir localmente a navegação sem perder o rascunho. Os resultados acima são históricos e não homologam esta revisão.

| Critério | Estado | Evidência desta revisão |
| --- | --- | --- |
| CA-005 | aprovado localmente | Nos dois editores, Voltar e Agenda navegam durante recovery sem PUT/POST/close, preservando UUID, revisão, snapshot e ponteiro. A reabertura oferece a mesma cópia e a retomada recupera valores literais. O hook libera beforeunload nessa condição. |
| CA-006 | aprovado localmente | Edição ativa espera salvamento; HTTP 503 mantém dados e tela. Após retomada, beforeunload protege mudanças e volta a liberar após confirmação. Origem obsoleta e emissão/atualização pendente permanecem preservadas sem reenviar ou alterar o oficial. |

Stage, produção e navegação autenticada no Safari não foram executados nesta etapa. A causa deste bloqueio de recuperação foi identificada; isso não resolve retrospectivamente a indeterminação do episódio de navegação registrado acima.

### Verificações desta revisão

- `vitest run app/laudos/echo-draft-existing-page.test.tsx app/laudos/echo-draft-new-page.test.tsx`: 47 testes aprovados, incluindo nove regressões novas.
- `vitest run app/laudos/hooks/useEchoEditorDraft.test.tsx`: 36 testes aprovados, incluindo dois casos novos (novo e existente) de beforeunload antes/depois da retomada.
- `vitest run --maxWorkers=4`: 168 arquivos e 2.994 testes aprovados.
- `node --test`: 23 testes aprovados.
- `npm run lint`, `tsc --noEmit` e `npm run build`: aprovados.
- `git diff --check` e `evaluate_guardrail` sobre os arquivos do diff de trabalho: aprovados; feature SDD qualificada `saida-rascunho-eco`.
- Revisão adicional do diff sem achados acionáveis.

Os testes de página usam jsdom com API e roteador simulados; comprovam a decisão de navegação e a preservação da cópia, não a navegação real autenticada do build candidato. Não foi operado um laudo real para teste manual desta revisão. Homologação em Stage e publicação ficam para a etapa solicitada de release.

Base: `origin/stage` `ae266e31fa3be8e3b2140c892e6fdcade334d18b`, worktree `echo-draft-exit-recovery`, branch `codex/echo-draft-exit-recovery`. A validação acima foi concluída antes de commit, push ou deploy.


## Publicação autorizada — 25/11/2026

Martiniano solicitou publicar após concluir as tarefas em andamento no GitHub. Preparação do release iniciada, com monitoramento das filas e de outra publicação Fort Cordis em curso. A correção será isolada dos trabalhos paralelos de Stage e estes serão restaurados após a promoção. Evidências de instalação e homologação serão registradas ao final; ainda não há afirmação de publicação desta revisão.
