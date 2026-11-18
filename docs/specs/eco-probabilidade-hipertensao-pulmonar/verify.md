# Verificação — Módulo HP e selo

## Matriz de aceitação para promoção

Validação em 16/11/2026, horário de Fortaleza. A candidata pública foi instalada em Stage pelo [deploy 43991776854](https://github.com/martinialebarros-svg/fortcordis-public/actions/runs/43991776854), concluído com sucesso no SHA `ff734f257b437e65b953b00491297889bffe4a68`, após a [PR #30](https://github.com/martinialebarros-svg/fortcordis-public/pull/30).

| ID | Status | Evidência |
| --- | --- | --- |
| HP-01 | aprovado | 86 fixtures compartilhadas verificam matriz, limites, TRV não mensurável e independência da PSAP; paridade nos dois sentidos entre Python e TypeScript. |
| HP-02 | aprovado | Regressões de campos incompletos, obstrução, falta de revisão e espécie não suportada; PDF local felino permanece descritivo, sem classe canina. |
| HP-03 | aprovado | Testes de contagem única por sítio, aceitação explícita das sugestões positivas e preservação de sítios não avaliados. |
| HP-04 | aprovado | Testes de RPAD, TA/TE, pico inicial de IP, unidades e entradas inválidas; importação não fornece confirmações clínicas. |
| HP-05 | aprovado | Regressões de edição, reimportação e recuperação literal. Em Stage, editar TRV de 3,6 para 3,4 m/s retirou a confirmação; a reconfirmação explícita permitiu salvar e reabrir com selo válido. |
| HP-06 | aprovado | Regressões de codec, novo/edição, rascunhos, blanks/zero e notas; probe instalado aprovou 15 casos de ciclo de vida. Salvamento e reabertura do laudo sintético #62 conferidos pela interface de Stage. |
| HP-07 | aprovado | Três PDFs locais, seis páginas, aprovados em semântica e inspeção visual. Em Stage, prévia sem reconfirmação omite classe/PSAP válidas; prévia confirmada e PDF emitido têm texto idêntico, exceto a marca de prévia. Referências após análise qualitativa e conclusão sintética preservada. |
| HP-08 | aprovado | Regressões do contexto e filtro do assistente, com rede e credenciais desativadas, preservam as restrições caninas/felinas e o contexto bruto para HP. Não houve chamada a provedor de IA. |
| HP-09 | aprovado | Componente compartilhado novo/edição; na interface autenticada de Stage, Tab levou da aquisição da IT ao seletor da VSVD. Janela de 618 px, página de 603 px, sem rolagem horizontal e com campos legíveis. Captura `stage-hp-confirmed.jpg`. |
| HP-10 | aprovado | 2.881 testes Vitest em 163 arquivos, 235 focados, 23 Node, tipos/lint/build aprovados; 255 casos backend cobertos conforme detalhe abaixo; 172 verificações de interoperabilidade. CI da PR #30 concluído e probe da instalação aprovado. |
| HP-11 | aprovado | Regressões específicas de DIVEd, SIVd e coorte ambígua, sem conversão dupla ou geração automática do selo. Stage #62 manteve classificação alta com DIVEd 32 mm e SIVd 7 mm; a mudança de TRV exigiu nova confirmação no cartão e na prévia. |
| HP-12 | aprovado | Candidata `ab24ab61050d787017e244117dfa2cfa5442bff0`: apenas 35 caminhos HP/SDD diferem da base pública `d7f12bc141223c1249aab39b68557ee73d4010b9`; 1.422 outros blobs/modos preservados. Árvore de restauração preparada a partir de `42ba7abd807d991d58268fb1dd260ca961113861`, preservando 1.460 caminhos alheios e limitando os oito caminhos alterados a HP/cache/teste/SDD. |

## Evidências e alcance

Os artefatos locais estão em `output/hp-public-release-20261116/`, ignorado pelo Git; não fazem parte do repositório público.

- `backend-hp-tests.json` registra a rodada de 255 testes: 254 passaram e uma asserção ainda esperava o identificador antigo do cache. Após alinhar a asserção à versão v38, esse caso passou em `backend-cache-rerun.json`; não se apresenta a primeira rodada como integralmente aprovada.
- `frontend-qa-result.json`, logs `frontend-*.log` e `stamp-interop.json` documentam os gates locais e 86 casos em cada sentido Python/TypeScript. A instalação local compartilhada não contém `playwright-core`, que não participa desses gates; os checks da PR #30 também passaram com a instalação do CI.
- `stage-public-deploy.json`, `stage-public-runtime.json` e `stage-public-preservation.json` comprovam conclusão do instalador, SHA esperado, seis arquivos de runtime preservados, configuração preservada e produção anterior estável durante a instalação de Stage. O teste de recuperação do backup e o canary autenticado do instalador passaram; o canary não substitui a conferência específica de HP.
- `stage-public-installed-hp-tests.json`: 23 testes, 99 subcasos e 15 casos de ciclo de vida aprovados no código instalado, com Python 3.10.12, dados temporários e nenhuma chamada externa ou acesso ao banco clínico. `stage-public-served-smoke.json` confirma domínios, proteção anônima e bytes dos arquivos JavaScript servidos.
- `stage-ui-validation.json` registra salvamento/reabertura, invalidação/reconfirmação, navegação por teclado e largura da tela. `stage-ui-pdf-analysis.json` verifica os três PDFs baixados pela interface: prévia sem revisão, prévia confirmada e PDF emitido. A igualdade textual entre a prévia confirmada e o PDF emitido exclui somente a marca “PRÉVIA - NÃO EMITIDO”. As seis páginas desses três PDFs foram inspecionadas visualmente, sem sobreposição ou corte de texto; a inspeção não equivale à validação em todos os dispositivos.
- `candidate-public-scope-proof.json` e `expected-restored-tree.json` comprovam o escopo e a preparação da restauração. A árvore preparada deve ser recalculada após este registro documental, mantendo a mesma comparação de blobs/modos fora de HP. Ainda não é evidência de Stage restaurado.

## Checklist operacional obrigatório após a promoção

Estas etapas de implantação permanecem abertas neste registro; o aceite funcional em Stage não as conclui.

- [ ] Promover pelo PR direto `stage → main`, com merge commit e `[preserve-nginx]`, após renovar fila, janela, backup, lotes e refs.
- [ ] Aguardar todos os jobs de produção e conferir SHA instalado, saúde, preservação dos dados/configuração e comportamento do módulo no ambiente publicado.
- [ ] Restaurar Stage por PR usando o snapshot paralelo e a árvore preparada atualizada; comparar todos os blobs/modos fora das alterações autorizadas de HP.
- [ ] Aguardar o deploy da restauração, conferir o SHA instalado e a estabilidade da produção, registrar as evidências e só então liberar a janela compartilhada.

## Limites da evidência

Dados exclusivamente sintéticos. A conferência autenticada descrita acima ocorreu em Stage. Não houve teste clínico real nem envio ao portal ou a destinatários externos. Os testes locais de renderização compartilhada não comprovam uma publicação no portal. Produção e restauração de Stage ainda precisam das evidências do checklist operacional. A classificação continua sujeita à revisão veterinária.

## Validação local do layout em tabela — 18/11/2026

- Os 111 testes focados de HP, medidas/cache e PDFs ecocardiográficos passaram, com 490 subtestes. A regressão de paginação verifica observação extensa, integridade das linhas e um único cabeçalho da avaliação por página.
- Foram gerados cinco laudos sintéticos: canino confirmado, canino pendente, felino descritivo, caso com observação longa e caso com HP desativada. A inspeção das páginas confirmou alinhamento com as demais tabelas e continuação sem cortes ou cabeçalho duplicado.
- A prévia e a emissão locais têm o mesmo conteúdo, descontada a marca de prévia. A conclusão precede as tabelas, a bibliografia permanece após a análise qualitativa e os resultados de HP e PSAP respeitam os critérios existentes.
- Amostra visual em `output/pdf/avaliacao-hipertensao-pulmonar.pdf`, ignorada pelo Git. A validação deste ajuste é local.
