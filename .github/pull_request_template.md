## Fluxo de entrega (stage-first)

- Base deste PR: `stage` (feature/fix). Produção (`main`) recebe depois, pelo
  PR de promocao `stage -> main` — nao por `scripts/promote_stage_to_main.sh`,
  que da push direto e pula os guards (ver CLAUDE.md).
- Excecao: hotfix urgente de produção pode mirar `main` direto, usando branch
  `hotfix/<slug>` ou a label `hotfix` (ver `.github/workflows/branch-flow-guard.yml`).

## Resumo

Descreva em poucas linhas o que foi alterado.

## Artefatos SDD (obrigatorio para mudanca de codigo)

- Feature SDD: `docs/specs/<feature-slug>/`
- [ ] `intent.md` atualizado
- [ ] `spec.md` atualizado
- [ ] `plan.md` atualizado
- [ ] `verify.md` atualizado

Links:

- Spec: <!-- caminho absoluto no repo -->
- Verify: <!-- caminho absoluto no repo -->

## Checklist Tecnico

- [ ] Testes locais relevantes executados
- [ ] Sem secrets hardcoded
- [ ] Sem alteracoes fora do escopo
