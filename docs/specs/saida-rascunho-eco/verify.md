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
