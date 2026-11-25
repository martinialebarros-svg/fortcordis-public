# Verificação

Implementação e validação local concluídas em 25/11/2026. Worktree isolada `/Users/martiniano/.codex/worktrees/echo-feline-kitten-references/fortcordis-public`, branch `codex/echo-feline-kitten-references`, base `origin/stage` em `ae266e31fa3be8e3b2140c892e6fdcade334d18b`.

| Critério | Estado | Evidência |
| --- | --- | --- |
| CA-001 | aprovado local | Caso sintético de 3 meses/1,3 kg, catálogo vazio e completo, protocolo confirmado; 18 chaves disponíveis conforme método |
| CA-002 | aprovado local | Testes de 6/16 semanas, 41/113 dias, idade vaga, estimada, faixas Unicode, peso inválido, métodos incompatíveis e remoção explícita de idade |
| CA-003 | aprovado local | 18 intervalos conferidos com Suplemento 1; conversão cm→mm; IC dos limites e Tabela 2 excluídos; revisão independente sem bloqueador |
| CA-004 | aprovado local | Catálogo bruto preservado abaixo da cobertura, referências adultas bloqueadas para juvenil, contexto recalculado e nenhum limite pediátrico persistido no catálogo |
| CA-005 | aprovado local | Comparação/prévia neutras, roundtrip do protocolo, exclusão de limites da IA e dois PDFs fictícios renderizados e inspecionados visualmente |

## Testes e verificações

- Backend: `python -m pytest backend/tests/test_echo_feline_pediatric.py backend/tests/test_echo_reference_resolver.py backend/tests/test_echo_low_weight_reference.py backend/tests/test_pdf_laudo_low_weight.py backend/tests/test_pdf_laudo_echo_measurements.py backend/tests/test_ai_echo_reference_safety.py backend/tests/test_echo_feline_diastolic.py backend/tests/test_echo_canine_diastolic.py -q`: **163 testes e 866 subtestes aprovados**. Executado com `/Users/martiniano/fortcordis-v2/backend/venv/bin/python`; 18 avisos de depreciação preexistentes.
- Frontend completo: `npx vitest run --maxWorkers=2 && node --test`: **170 arquivos / 3.021 testes Vitest e 23 testes Node aprovados**.
- `npm run lint`, `npx tsc --noEmit`, `npm run build`: aprovados; build gerou 46 páginas. Aviso de antiguidade da base Browserslist; nenhuma atualização de dependência realizada.
- `git diff --check` e guardrail SDD sobre arquivos alterados/novos: aprovados.
- Revisão independente de dados numéricos, unidades, elegibilidade, catálogo adulto, persistência e PDF: sem bloqueadores após correções.

## Evidência visual

PDFs sintéticos de modo M e 2D em `output/pdf/exemplo-ficticio-felino-3-meses-modo-m.pdf` e `output/pdf/exemplo-ficticio-felino-3-meses-2d.pdf` (artefatos locais ignorados pelo Git). Quatro páginas renderizadas com Poppler e inspecionadas: tabelas, unidades, intervalos, DOI e nota de coorte legíveis, sem sobreposição ou corte. Referências numéricas neutras, marcadas com asterisco para a nota bibliográfica. Dimensão Ao no nível da AP permanece sem intervalo.

Não houve teste manual em navegador autenticado nem homologação remota. Interações da tela foram verificadas por testes DOM com respostas fictícias. Nenhum laudo real foi alterado ou emitido; não houve migração nem escrita no catálogo de referências.

## Ocorrências resolvidas

- Parsers Python/TS inicialmente divergiam sobre `(estimada)` e repetição de unidades. Foram alinhados; sinais e travessões Unicode são preservados para impedir que `1–2 semanas` vire `12 semanas`.
- Faixa simples potencialmente juvenil (ex.: `1–2 meses`) agora bloqueia o catálogo adulto, sem habilitar RI pediátrico. `1–2 anos` não recebe contexto pediátrico.
- Limpeza explícita de idade `None` remove a referência anterior; idade omitida preserva o contexto para idempotência.
- Teste adicional encontrou captura tardia do catálogo quando o peso estava fora da cobertura: o frontend preserva os valores originais antes de aplicar os bloqueios.
- Primeira suíte frontend completa executada durante a revisão/geração visual teve essa falha e timeouts de 5 s em páginas extensas com efeitos em cascata. Os 79 testes dessas páginas passaram isolados e a suíte completa posterior passou com dois workers, sem alteração dos testes legados ou seus timeouts.

## Estado de publicação

Publicação autorizada pelo usuário em 25/11/2026 ("pode publicar"). Segue o fluxo de PR de feature para Stage, homologação e promoção direta `stage -> main` com merge commit. A diferença preexistente entre `origin/main` (`b0c1f51`) e `origin/stage` (`ae266e3`) contém 38 caminhos paralelos: o candidato de produção isola esta feature; o conteúdo paralelo será preservado e restaurado em Stage após a promoção. Resultados remotos serão registrados na evidência de release; autorização não é evidência de deploy concluído.

## Ocorrências de CI durante a publicação

- PR #72, primeira tentativa: falha isolada no teste fiscal preexistente (estado de botão). Os 12 arquivos relacionados são idênticos a `main`; 12 repetições do caso e três execuções do arquivo fiscal completo passaram localmente. Causa exata não reproduzida; nenhuma fonte fiscal alterada.
- Segunda tentativa: todos os 2.938 testes Vitest aprovados, mas erro assíncrono em temporizador de novo laudo após desmontagem (`window is not defined`). Duas regressões locais reproduziram temporizador pendente e agendamento por resposta tardia. A correção cancela os quatro temporizadores temporários na saída e impede novo agendamento após desmontagem, preservando as durações e os critérios de teste.
- Correção de temporizadores: 120 testes das cinco páginas afetadas aprovados, incluindo as duas regressões; lint dos arquivos aprovado e revisão independente sem bloqueador. Regressões usam os handles reais dos avisos, evitando interferência do relógio global nos testes existentes.
