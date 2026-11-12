# Spec Driven Development (SDD) no FortCordis

Este documento define como usamos IA com previsibilidade no projeto.

## Objetivo

Trocar fluxo de "prompt improvisado" por um ciclo com especificacao clara, implementacao incremental e verificacao objetiva.

## Ciclo SDD (4 etapas)

1. Intencao
- Definir problema, objetivo, nao objetivos, restricoes e risco.
- Artefato: `docs/specs/<feature-slug>/intent.md`.

2. Especificacao
- Traduzir intencao em requisitos testaveis e contratos tecnicos.
- Artefato: `docs/specs/<feature-slug>/spec.md`.

3. Plano
- Quebrar implementacao em fases pequenas e reversiveis.
- Artefato: `docs/specs/<feature-slug>/plan.md`.

4. Verificacao
- Confirmar item a item que o entregue bate com o especificado.
- Artefato: `docs/specs/<feature-slug>/verify.md`.

## Estrutura padrao

```text
docs/specs/
  README.md
  templates/
    intent.md
    spec.md
    plan.md
    verify.md
  <feature-slug>/
    intent.md
    spec.md
    plan.md
    verify.md
```

## Definition of Ready (DoR)

Nao iniciar implementacao sem:
- `intent.md` preenchido e aprovado.
- `spec.md` com requisitos funcionais e criterios de aceitacao.
- `plan.md` com fases, ordem e estrategia de rollback.
- Dependencias e riscos mapeados.

## Definition of Done (DoD)

Nao encerrar tarefa sem:
- `verify.md` preenchido com rastreabilidade entre criterio e evidencia.
- Testes automatizados e manuais executados (ou justificativa documentada).
- Escopo fora do combinado explicitamente registrado.
- PR com checklist SDD completo.

## Granularidade recomendada

Quebre por camadas, sempre que fizer sentido:
- Fase 1: banco/migracoes.
- Fase 2: backend/API/servicos.
- Fase 3: frontend/estado/UX.
- Fase 4: integracao, observabilidade e hardening.

Cada fase deve ter:
- objetivo claro;
- criterios de aceite proprios;
- plano de teste;
- impacto de rollback.

## Prompt base para IA (copiar e adaptar)

```text
Contexto:
- Projeto: FortCordis
- Feature: <feature-slug>
- Arquivos de referencia: <paths>

Objetivo:
- <objetivo em 1-2 frases>

Requisitos obrigatorios (spec.md):
- RF-001 ...
- RF-002 ...

Restricoes:
- Nao mudar contratos fora do escopo.
- Manter compatibilidade com dados atuais.

Entregavel desta iteracao:
- <fase atual do plan.md>

Criterios de aceitacao para validar:
- CA-001 ...
- CA-002 ...
```

## Fluxo de PR

- Todo PR deve linkar os quatro artefatos SDD.
- Revisor valida primeiro `spec.md` e `verify.md`, depois o diff.
- Mudanca sem spec pode ser aceita apenas para hotfix critico, com justificativa no PR e retro-documentacao em seguida.

## Metricas para acompanhar

- Taxa de retrabalho por feature.
- Bugs pos-merge por modulo.
- Lead time de implementacao.
- Percentual de PRs com checklists SDD completos.
