# Verificação

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
