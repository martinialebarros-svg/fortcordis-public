# Verificação

Implementação e verificações locais concluídas em 23/11/2026. Base `origin/stage` em `812c5adb35f5802c86d45f619a4308d09b33745f`, branch `codex/tutor-origem-clinicas`.

| Critério | Estado | Evidência |
| --- | --- | --- |
| CA-001 | aprovado local | Integrações de Tutores e Agenda verificam a opção do catálogo e o payload `origem_cadastro` com o nome escolhido |
| CA-002 | aprovado local | Componente consulta duas páginas (500 + 1) e oferece a última clínica |
| CA-003 | aprovado local | Componente preserva origem, observações e identificação; aceita nome sugerido, outra origem e vazio; Agenda preserva a origem inicial até edição |
| CA-004 | aprovado local | Erro simulado mantém campo editável e nova tentativa recupera lista sem apagar texto |
| CA-005 | aprovado local | 29 testes passaram em cinco arquivos: campo, Tutores, novo paciente, rotina ágil da Agenda e cache de catálogos; leitura só inicia ao abrir/focar origem |

## Comandos e evidências

- `npx vitest run components/TutorIdentificacaoFields.test.tsx app/tutores/page.test.tsx app/pacientes/novo/page.test.tsx app/agenda/NovoAgendamentoModal.tutor-rotina-agil.test.tsx lib/stable-catalog-cache.test.ts`: 5 arquivos, 29 testes aprovados.
- `npm run lint`: aprovado, sem avisos.
- `npx tsc --noEmit`: aprovado.
- `npm run build`: aprovado, 46 páginas geradas. Aviso de antiguidade do banco Browserslist; nenhuma dependência alterada.
- `git diff --check`: aprovado.
- `evaluate_guardrail` de `scripts/ci/check_sdd_guardrail.py`, sobre diff local e arquivos novos: aprovado para `tutor-origem-clinicas`.

O primeiro ensaio identificou uma espera insuficiente no novo teste de erro: capturava o status de carregamento antes da mensagem de falha. A espera foi corrigida, e os cinco arquivos passaram na reexecução. Não houve alteração de comportamento para acomodar o teste.

Não houve teste manual em navegador; as sugestões usam `datalist` nativo, cuja apresentação depende do navegador. Os testes de interação usam DOM simulado e respostas fictícias; não acessam registros reais. Backend e schema inalterados, sem necessidade de testes de banco neste escopo.

Sem commit, push, homologação remota ou publicação neste ciclo. Publicação segue o fluxo posterior para Stage e produção.

## Publicação solicitada

Em 23/11/2026, o usuário autorizou publicar esta alteração. Baselines reconferidos: produção `9afca565621103f6af243b38c0098deabd4796a2` e Stage `812c5adb35f5802c86d45f619a4308d09b33745f`. Os 38 caminhos de trabalhos paralelos são preservados em snapshot e excluídos temporariamente da árvore de promoção; serão restaurados em Stage após a produção. Somente os oito caminhos próprios podem diferir da produção anterior. Sem alteração de workflow, banco ou configurações de ambiente.

Homologação remota e resultados finais do deploy serão registrados após execução.

Pré-publicação da árvore isolada: `npm test` aprovado com 164 arquivos / 2.900 testes Vitest e 23 testes Node. `npm run lint`, `npx tsc --noEmit`, guardrail SDD contra Stage e produção e guard de critérios da promoção aprovados. Preflight remoto confirmou serviços ativos, sete filas por ambiente sem trabalhos ativos e configuração/runtime preservados em manifesto privado. O delta de produção contém exatamente os oito caminhos próprios.
