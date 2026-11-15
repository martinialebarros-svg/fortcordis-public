# Especificação

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
- O snapshot isolado é produção `91222f4437c2c5470264d6f95691028503477231` com os 13 arquivos desta entrega e os quatro documentos históricos `public-stage-vps-parity`, preservados para manter a rastreabilidade SDD. Esses documentos não incluem os trabalhos funcionais de Stage na promoção nem declaram encerradas suas pendências históricas.
- Após a promoção, restaurar a árvore de Stage `43b14787e48f8152b8b3656d827127284f8798c0` acrescida destas correções e do registro documental das verificações; comprovar igualdade de todos os arquivos paralelos.
