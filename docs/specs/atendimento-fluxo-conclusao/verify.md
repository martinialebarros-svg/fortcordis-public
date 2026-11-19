# Verificação

## Precisão do horário — 15/11/2026

- Regressão na base `9af367ab`: sete testes evidenciaram descarte de segundos na abertura, no horário inicial e na recuperação de rascunho antigo. A candidata passou nos 62 testes focados de horário, rascunho, contexto e pendências.
- A ficha sintética em SQLite foi aberta pela interface compilada, com a API real local. Editar só a queixa pelo salvamento automático preservou `17:59:35.970744` no banco. A edição manual por teclado para `17:59:36` e, depois, para `17:59:00` foi salva e confirmada ao reabrir e consultar o banco.
- O campo mostrou os segundos sem corte na janela de 1280 px. Treze testes de persistência parcial e fuso horário no backend passaram. O build inclui verificação de tipos e lint.
- O teste teve uma única ficha fictícia em banco temporário. Stage e produção não receberam a alteração.

## Atalhos do atendimento — 15/11/2026

| Critério | Evidência local com dados fictícios |
| --- | --- |
| Usar a gravação do atendimento na análise conjunta | Testes do lote e do assistente conferem o mesmo arquivo original ao lado dos PDFs. Exercitam consentimento, validação, retirada após descarte, isolamento da seleção por atendimento e tentativa de envio interrompida. Arquivos distintos de mesmos metadados permanecem na seleção. |
| Incorporar todos os itens aprovados | O teste combina trecho e achado para o mesmo campo e verifica uma única consulta ao conjunto. O texto inclui a origem do achado, as aprovações continuam individuais e ficam fora itens já adicionados, editados após aprovação, sem fonte ou com evidência insuficiente. Revisão revogada ou contexto diferente impede aplicação. |
| Manter o conteúdo existente | O callback real da página preserva o texto anterior, acrescenta todos os trechos do mesmo campo em ordem e preserva o prognóstico. Uma troca de paciente ou de contexto invalida o callback anterior. |
| Ir diretamente à pendência | Testes usam o radar, o editor e os callbacks da página. Confirmam navegação de Documentos para Consulta mesmo com editor carregando, foco na etapa correta, preservação da revisão consolidada e foco no prognóstico com outras pendências em aberto. |

A checagem focal final passou em 179 testes, em 21 arquivos. A compilação de produção do frontend, incluindo lint e verificação de tipos, passou. A revisão de código independente conferiu elegibilidade, identidade dos arquivos e foco do editor. A validação desta rodada cobre a implementação local. Homologação instalada e publicação são etapas separadas.

A primeira execução geral teve oito falhas em três arquivos de Laudos. Os mesmos arquivos passaram isoladamente na base pública exata, com 75 testes aprovados. A execução completa final, com quatro workers após a compilação, passou nos 2.726 testes Vitest e 23 testes Node, sem alterações em Laudos ou na configuração de testes. O guardrail SDD e a inspeção do diff passaram.

## Ambiente observado em 15/11/2026

- Produção `91222f44` e Stage `43b14787` conferidos no servidor em 15/11/2026, com saúde e prontidão HTTP 200 e acesso anônimo ao assistente HTTP 401.
- Configuração do assistente e serviços ativos conferidos: IA ligada na produção, desligada no Stage; modelo de análise `gpt-6.1-sol`, esforço `max`, transcrição `gpt-transcribe`. Nenhuma chamada de transcrição ou análise realizada nesta auditoria.
- Acesso autenticado ao assistente HTTP 200, vínculo de identidade e componentes servidos conferidos. Hash dos arquivos JavaScript servidos igual ao da instalação. Sessão temporária de conferência encerrada.
- Interface autenticada de produção inspecionada no Chrome sem editar formulário ou escolher paciente. Consulta, Exames, Prescrição e Documentos abriram; console consultado sem erros. Primeira troca para Exames, Prescrição e Documentos mostrou o carregamento da página inteira.

## Erros reproduzidos e corrigidos localmente

| Erro | Evidência e correção |
| --- | --- |
| Abrir lote substituía a transcrição editada sem aviso | Duas regressões falharam na base. Exigir decisão para texto diferente; reabrir a mesma revisão preserva edições/aprovações |
| Nova análise apagava a revisão antes de obter resposta | Falhas de salvamento/API e espera reproduzidas. Preservar revisão em erro, retorno incompleto e cancelamento; trocar somente com resultado preparado e exigir novas aprovações |
| Respostas atrasadas afetavam outro contexto do atendimento | Callbacks reais executados com respostas fora de ordem; seis cenários falharam na base. Separar geração do contexto aplicado da tentativa de navegação, hidratar identidade/formulário juntos e proteger salvar/finalizar/herdar |
| Troca de registro removia cópia local não sincronizada | Preservar backup antes da troca e remover somente após confirmação do conteúdo salvo. Falha de armazenamento bloqueia troca com aviso e mantém formulário/cópia |
| Atualização parcial apagava dados omitidos de triagem/diagnóstico | Reprodução em SQLite temporário: alteração isolada apagava sinais vitais/diagnósticos do mesmo bloco. Atualizar somente campos enviados; manter limpeza explícita e validar conclusão sobre o estado composto |
| Carregamento de uma área ocultava a página inteira | Observado em três áreas de produção e reproduzido com carregador real do App Router. Três testes falharam antes e passaram com espera local; cabeçalho/navegação permanecem visíveis |

## Validação

- Frontend completo: **156 arquivos, 2.697 testes Vitest e 23 testes Node aprovados**. Após o último ajuste de atualização de histórico, **21 testes focais de contexto** passaram novamente (incluem um caso novo).
- Assistente: dez regressões novas cobrem transcrição, revisão, campos e achados editados, erro/cancelamento e reapresentação de aprovações. A suíte completa inclui a cobertura existente de lote, áudio, identidade e incorporação.
- Backend: **60 testes aprovados**, incluindo nove novos de atualização parcial, finalização transacional, ciclo clínico, vínculo com Agenda, auditoria e edição após alta. SQLite temporário; sem banco real ou provedor externo.
- Build final e verificação de tipos posterior aprovados; hashes confirmam que os nove arquivos de código/teste não mudaram durante essa compilação. Lint dos arquivos alterados aprovado. Uma verificação de tipos iniciada junto de um build encontrou tipos temporários ausentes; foi repetida sequencialmente após o build e passou, sem alteração de código para contornar o erro.
- SDD: função oficial `evaluate_guardrail` aprovada para o diff local incluindo arquivos novos. `git diff --check` aprovado.
- Revisão independente cruzada do frontend e backend concluída. Dois casos de borda detectados na primeira implementação foram corrigidos e rechecados: abertura malsucedida durante save/primeiro POST e armazenamento local indisponível.

As evidências operacionais locais ficam em `output/atendimento-fluxo-auditoria-20261115/`, ignorado pelo Git. Incluem saúde, smoke autenticado sem conteúdo clínico, logs de validação e hashes dos nove arquivos de código/teste da candidata.

## Limites e pendências

- Nenhuma perda real de prontuário foi observada. Os riscos de corrupção/sobrescrita foram reproduzidos apenas em cenários isolados.
- A conferência de produção não retranscreveu áudio nem reanalisou exame, e não certifica fidelidade clínica. Nenhum conteúdo real foi enviado à IA ou WhatsApp.
- A candidata foi validada por testes locais. A homologação instalada e a publicação foram autorizadas em seguida pelo usuário em 15/11/2026; a autorização não é evidência de instalação. Os resultados de Stage devem ser conferidos antes da promoção.
- Edição simultânea entre abas/aparelhos ainda aceita a última escrita; detecção de conflito é proposta separada.
- Recomendações para reduzir passos estão em `plan.md`; não foram implementadas nem aprovadas como novo desenho de produto nesta rodada.

## Publicação

A auditoria inicial não publicou. A preparação deste novo ciclo confirmou as liberações explícitas de Laudos, Gestão, Maps e Backup, fila sem deploy concorrente, os dois SHAs de base, serviços saudáveis e zero lotes ativos em ambos os ambientes. O backup local estava sem trava ativa. Testes locais ou leitura de produção não equivalem à instalação da candidata.

As evidências de instalação, homologação e restauração serão registradas nas PRs deste ciclo e em `output/atendimento-fluxo-release-20261115/`, sem dados clínicos no repositório público. Antes de promover, exigir workflow completo, testes da instalação em SQLite descartável/rede bloqueada, contratos HTTP fictícios, acesso autenticado, hashes das fontes e dos arquivos servidos e navegação em Stage. Antes de encerrar, exigir a restauração e a igualdade dos arquivos paralelos.

## Ajuste de sincronização do teste na CI

A primeira CI da PR pública #9 teve 2.697 testes aprovados e uma falha na recuperação de revisão em memória: o nome do arquivo e a transcrição já estavam restaurados, mas o link ainda não estava presente na consulta síncrona, compatível com a criação da URL em um efeito posterior do componente filho. Vinte execuções focais locais não reproduziram a falha. O teste passou a aguardar o próprio link e a conferir seu `href` e o objeto `File` original; as demais verificações foram mantidas. O componente de produção não foi alterado para contornar o teste. Após o ajuste, 91 testes de sete arquivos do assistente/áudio e o lint focal passaram. A execução completa da CI deve passar novamente antes de qualquer instalação.

## Homologação e produção verificadas em 15/11/2026

Esta seção atualiza as pendências de instalação descritas acima. A candidata pública foi homologada e promovida; a restauração de Stage está preparada e ainda depende de instalação e verificação final.

- Stage: PR #9, SHA `5713379f57a5263c087e25565e66c41e46085f56`, [workflow completo aprovado](https://github.com/martinialebarros-svg/fortcordis-public/actions/runs/43709264667), com job de instalação executado. CI completa: 2.698 testes Vitest e 23 Node aprovados.
- Produção: promoção protegida PR #10, SHA `e37c190d2585a8469bca4a26a3a2c02b2431ffa0`, [workflow completo aprovado](https://github.com/martinialebarros-svg/fortcordis-public/actions/runs/43711076744), com merge commit e política `[preserve-nginx]` confirmada (`enable_http2=0`, `reload=0`).
- Em cada instalação: 60 testes backend e seis contratos HTTP fictícios aprovados sobre as fontes instaladas, em SQLite descartável e com rede bloqueada. Acesso autenticado 200, anônimo 401, identidade vinculada, 18 arquivos servidos com hash igual ao build e quatro marcadores da entrega conferidos.
- Chrome autenticado em Stage: Consulta, Exames, Prescrição e Documentos carregaram. Espera local observada nas três áreas mantendo cabeçalho e navegação. Console sem erros. Os fingerprints da ficha fictícia, paciente, tutor e auditoria não mudaram antes/depois; não houve edição clínica.
- Gates operacionais: canary autenticado e teste de backup/restauração aprovados. Agenda 5/5 em ambos; p95 de 281,11 ms em Stage e 459,77 ms em produção, abaixo de 1.200 ms.
- Hashes dos arquivos de runtime, SQLite local, configuração fora da identidade da publicação e Nginx iguais ao preflight em ambos os ambientes. IA desativada em Stage; configuração ativa da produção preservada. Sessão temporária de verificação em produção encerrada.
- Nenhuma nova transcrição/análise paga, envio de arquivo clínico, WhatsApp ou edição de prontuário real. Esta verificação não certifica fidelidade clínica nem implementa as propostas futuras de redução de passos.

## Restauração preparada; instalação final pendente

A árvore compartilhada preserva os 86 caminhos paralelos e os 1.430 caminhos existentes fora dos 14 caminhos da entrega, comparados por modo/tipo/blob. Os outros 12 caminhos próprios devem ser idênticos à produção; somente spec/verify recebem evidências e o contrato de restauração. O diff contra a base compartilhada permanece restrito aos 14 caminhos próprios.

Antes de declarar o ciclo encerrado, exigir todos os checks da PR de restauração, workflow completo com instalação executada, SHA/árvore instalados, teste de acesso autenticado, código e arquivos servidos, configuração/runtime, saúde, zero lote ativo e nova prova de igualdade dos caminhos preservados. O resultado final será anexado à PR de restauração e às evidências operacionais privadas, sem registrar dados clínicos no repositório público.

## Homologação dos três atalhos em Stage em 15/11/2026

A PR #15 instalou `a9ded2ea52f8814a0a4ec504b83617fd52bada80`. O [workflow de Stage](https://github.com/martinialebarros-svg/fortcordis-public/actions/runs/43734112360) terminou com sucesso. No Chrome autenticado, uma gravação WAV original entrou na seleção ao lado de um PDF fictício e foi retirada sem remover o exame. Os atalhos de pendências focaram diagnóstico, prognóstico e anamnese ao voltar de Documentos. A ficha fictícia, paciente, tutor e auditoria permaneceram iguais.

A incorporação usou uma réplica com os mesmos bytes do frontend instalado e uma API totalmente fictícia. Um trecho e um achado aprovados foram aplicados em uma ação, com preservação das anotações anteriores e origem do exame. A observação sem aprovação não entrou. Uma consulta revalidou o conjunto antes da inclusão. Os 43 assets públicos conferidos correspondiam à instalação e 160 testes fixados às fontes desse SHA passaram. O CSP da réplica bloqueou o service worker por desenho. A interface real em Stage não apresentou erros no console.

Canary autenticado e teste de backup/restauração aprovados. Agenda 5/5 com p95 de 308,99 ms, abaixo de 1.200 ms. A IA de Stage permaneceu desativada, sem envio a provedor ou alteração clínica real.

## Provas da restauração dos três atalhos

A árvore preparada preserva 59 caminhos paralelos exclusivos e 1.430 caminhos existentes fora do escopo. Os outros 19 caminhos próprios são idênticos à árvore promovida pela [PR #16](https://github.com/martinialebarros-svg/fortcordis-public/pull/16). Nos dois documentos compartilhados, o histórico da base de Stage permanece integral. A árvore preparada não prova instalação. As verificações finais de produção e da restauração serão registradas nas respectivas PRs depois da execução, incluindo SHA, workflow, saúde, runtime e igualdade dos arquivos no servidor.
