# FortCordis - orientacoes para agentes

## Fluxo de entrega: stage-first

`main` e produção e faz deploy automatico a cada push. Por isso, **nenhuma
feature entra direto em `main`**:

- PR de feature/fix: base `stage`.
- Produção recebe depois, pelo **PR de promocao** `stage -> main`
  (titulo `chore(release): promover <resumo>`), mergeado com merge commit —
  squash faria `main` divergir de `stage` e criaria conflito na promocao
  seguinte.
- Hotfix urgente de produção e a unica excecao: branch `hotfix/<slug>` ou label
  `hotfix` no PR, mirando `main`. Depois de mergear o hotfix, faca o backport
  para `stage` na hora: a promocao seguinte resolve conflito em favor de `stage`
  por default e pode desfazer a correcao sem avisar.

### Promova pelo PR, nao pelo script

`scripts/promote_stage_to_main.sh` termina em `git push origin HEAD:main`, e
`main` nao tem protecao de branch. Os dois guards de promocao rodam em
`on: pull_request`, entao **o script nao dispara nenhum dos dois**:

- `.github/workflows/branch-flow-guard.yml` sinaliza com falha qualquer PR que
  mire `main` fora das condicoes acima.
- `.github/workflows/promotion-verify-guard.yml` barra promocao que leve
  criterio de aceitacao ainda `pendente` na matriz do `verify.md` das features
  no diff. Tem label de excecao (`promocao-com-pendencia`) para quando a
  promocao com pendencia for consciente.

Na pratica o script e um bypass silencioso do segundo gate: ele empurra para
produção sem que ninguem seja avisado da pendencia. Promova pelo PR. O script
segue no repo como escape hatch, e de quem o usa se espera saber que esta
pulando a verificacao.

Detalhes e passos manuais de configuracao: `docs/RUNBOOK-STAGE-PROD.md`.

## Uma worktree por sessao

Mais de um agente trabalha neste repo ao mesmo tempo. Um clone git tem **um**
HEAD e **um** index: duas sessoes no mesmo diretorio se atropelam sempre —
`git checkout` de uma troca a branch da outra, `git add` de uma leva arquivo da
outra para o commit errado.

Por isso: **trabalhe em worktree propria, nunca no clone principal**. O clone
principal nao e workspace de ninguem.

- Claude Code: `EnterWorktree` no inicio da sessao.
- Codex e afins: `git worktree add` antes de comecar.

Cuidado com o ponto de partida: o default do `EnterWorktree` ramifica de
`origin/main`, que neste fluxo esta atras de `stage`. Feature e fix saem de
`stage` — depois de criar a worktree, `git reset --hard origin/stage`, ou
configure `worktree.baseRef: head` em `.claude/settings.json` com a sessao
partindo de `stage`.

Se ainda assim aparecer no seu diff arquivo que voce nao editou, e sinal de
tree compartilhada: nao commite por cima. Confira `git worktree list` e
`git log` antes.

## Mudanca de codigo exige artefatos SDD

Alteracao em `backend/`, `frontend/` ou `scripts/` precisa vir acompanhada de
`docs/specs/<feature-slug>/` com `intent.md`, `spec.md`, `plan.md` e
`verify.md` — `spec.md` e `verify.md` alterados no mesmo diff. O gate
`.github/workflows/sdd-guardrail.yml` reprova o PR sem isso. Processo completo
em `docs/SDD-WORKFLOW.md`.
