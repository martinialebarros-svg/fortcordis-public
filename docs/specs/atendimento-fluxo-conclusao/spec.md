# Especificação

## Atalhos do atendimento

- A análise conjunta oferece o original que já está disponível para ouvir no atendimento. A escolha é explícita e aparece na seleção do conjunto. Enviar exige a ação de analisar, o consentimento, o vínculo com o paciente, o atendimento sincronizado e os limites de arquivo já vigentes. A seleção local deve acompanhar a troca ou o descarte do áudio. Um conjunto cujo envio já começou segue o fluxo de retomada existente.
- A revisão oferece uma ação de incorporação com a contagem dos itens aprovados e ainda disponíveis. A confirmação de cada trecho ou achado continua individual e é invalidada quando seu texto é editado. Um item bloqueado, sem evidência exigida, sem confirmação ou já incluído fica fora. Sugestões de conduta permanecem para avaliação.
- A incorporação preserva o conteúdo que já estava no formulário e acrescenta os trechos aceitos em uma única atualização. Se mais de uma fonte contribuir para o mesmo campo, todos os trechos aceitos são acrescentados em ordem. Para uma revisão de conjunto, consultar uma vez a versão atual do resultado antes da inclusão e bloquear a ação se a identidade, o estado ou o resultado não conferirem. Entradas já revisadas ficam disponíveis se o contexto do formulário rejeitar a inclusão.
- As pendências clínicas do fechamento e do radar levam à Consulta e focam o campo de destino, mesmo quando é preciso trocar de etapa ou aguardar o carregamento do editor. A navegação mantém os valores do formulário e os critérios de conclusão.

## Precisão do horário do atendimento

- O campo de data e hora permite visualizar e editar segundos no horário operacional de Fortaleza. O horário inicial de um novo encontro e o horário recebido da Agenda também mantêm segundos.
- A abertura e o salvamento, manual ou automático, conservam os segundos e as frações recebidas do servidor enquanto o horário permanecer sem edição. Uma edição do horário usa a precisão de segundo do campo, incluindo `:00` quando escolhido.
- Um rascunho local antigo com apenas o mesmo minuto do horário salvo mantém a precisão do registro. Mudanças explícitas do horário continuam permitidas.
- A conversão dos outros campos de data que usam minutos fica independente. A correção vale para salvamentos futuros e não reconstitui segundos que já foram perdidos.

## Comportamento

- RF-001: a abertura de resultados do assistente não pode substituir texto editado ou revisão pendente sem decisão explícita. Reabrir conteúdo idêntico preserva as edições e aprovações, sem confirmação adicional.
- RF-002: nova análise preserva a revisão anterior durante espera, erro e cancelamento. Somente uma resposta utilizável substitui os campos e achados, com novas aprovações obrigatórias.
- RF-003: abertura, salvamento, conclusão e herança de histórico só podem aplicar respostas ao contexto que originou a ação. Identidade e formulário devem ser hidratados juntos; erros antigos não podem atingir o atendimento atual.
- RF-004: ao trocar de atendimento, preservar cópias de edições não sincronizadas. Iniciar outro atendimento do mesmo paciente deve tentar salvar também quando o estado anterior é de erro.
- RF-005: atualizações parciais de triagem/diagnóstico preservam campos omitidos. Limpeza explícita continua permitida. O gate de conclusão considera os valores existentes mais as mudanças enviadas, sem perder a confirmação de pendências.
- RF-006: a navegação entre áreas mantém cabeçalho e navegação visíveis enquanto carrega o módulo solicitado, usando uma espera local.
- NFR-001: separar saúde e acesso da aplicação, comportamento observado e propostas de melhoria. Não atribuir perdas reais aos riscos reproduzidos somente em testes isolados.
- NFR-002: recomendações não podem dispensar revisão veterinária, inventar dados faltantes ou enviar documentos automaticamente.

## Critérios de aceitação

- CA-001: registrar as versões instaladas, saúde e acesso autenticado do assistente sem nova chamada à IA.
- CA-002: reproduzir e corrigir a sobrescrita de texto editado ao abrir uma revisão de lote; cancelar preserva a edição e confirmar aplica a revisão escolhida.
- CA-003: cada erro corrigido deve ter reprodução na base e regressão na candidata, incluindo respostas fora de ordem, atualização parcial e carregamento atrasado de módulo.
- CA-004: executar testes, verificação de tipos, lint, build e validação SDD.
- CA-005: entregar recomendações priorizadas com benefício, limite de segurança e distinção entre correção pronta e proposta.
- CA-006: manter produção e registros reais inalterados durante a revisão.

## Entrega autorizada em 15/11/2026

- Instalar e homologar somente as correções descritas acima, promover pelo PR protegido `stage -> main` e restaurar integralmente os trabalhos paralelos de Stage.
- Conferir fila, liberações dos responsáveis, SHAs, saúde, configuração, arquivos de runtime e lotes antes de cada instalação. Preservar IA desligada em Stage e a configuração atual de produção.
- O snapshot isolado é produção `91222f4437c2c5470264d6f95691028503477231` com os 14 arquivos desta entrega e os quatro documentos históricos `public-stage-vps-parity`, preservados para manter a rastreabilidade SDD. Esses documentos não incluem os trabalhos funcionais de Stage na promoção nem declaram encerradas suas pendências históricas.
- Após a promoção, restaurar a árvore de Stage `43b14787e48f8152b8b3656d827127284f8798c0` acrescida destas correções e do registro documental das verificações; comprovar igualdade de todos os arquivos paralelos.

- A regressão de recuperação em memória deve aguardar a criação assíncrona do link do original e conferir o endereço e o mesmo arquivo recuperado, além de preservar texto, aprovações e a ausência de nova incorporação automática.

## Restauração de Stage após a promoção de 15/11/2026

O ciclo usa uma instalação isolada para homologar e promover somente esta entrega. Depois da verificação de produção, Stage retorna à árvore compartilhada da base `43b14787e48f8152b8b3656d827127284f8798c0`, acrescida dos 14 caminhos desta entrega. Os 86 caminhos paralelos e todos os caminhos existentes fora do escopo devem permanecer idênticos por modo, tipo e blob à base compartilhada.

O código promovido permanece idêntico em produção e no Stage restaurado; apenas spec/verify recebem o registro real deste ciclo. A restauração mantém os workflows e testes dos trabalhos paralelos, configurações dos ambientes, dados de runtime e Nginx. IA permanece desligada em Stage. A composição da árvore não substitui a exigência de PR, checks, workflow completo e conferência da instalação final.

## Restauração da base compartilhada após os três atalhos

A composição de Stage parte da base compartilhada `4c70efc04183be1eb361a535d08eb365bd12d5df` e mantém os 59 caminhos paralelos exclusivos com o mesmo modo, tipo e conteúdo. Os dois documentos compartilhados de Atendimento retêm o conteúdo histórico e recebem os novos registros. Os outros 19 caminhos alterados pelos três atalhos correspondem ao snapshot homologado e promovido.

A implantação da restauração depende da verificação da promoção protegida. A conferência final compara a árvore e os arquivos paralelos instalados, além de saúde, acesso e configurações dos ambientes. A IA permanece desativada em Stage.
