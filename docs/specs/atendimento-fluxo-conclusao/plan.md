# Plano

## Implementação dos três atalhos

1. Integrar a seleção do áudio disponível ao fluxo de composição e envio do lote.
2. Compartilhar os critérios de elegibilidade entre incorporação individual e em lote e acrescentar os textos ao estado do formulário em uma única ação.
3. Associar cada pendência clínica ao campo que a resolve e focar o controle quando o editor estiver montado.
4. Verificar os fluxos com exemplos fictícios, incluindo troca de contexto, envio interrompido, revogação de revisão e navegação entre etapas.

As mudanças estão na interface e reutilizam o contrato de análise e salvamento. Para revertê-las, retirar os três atalhos em código e seus testes, sem migração ou transformação de registros.

1. Conferir contexto, repositório atual, versões instaladas e saúde.
2. Observar a navegação autenticada sem editar ou finalizar atendimentos reais.
3. Auditar em paralelo o fechamento, o assistente e os contratos backend; confirmar hipóteses com testes fictícios.
4. Aplicar correções mínimas e revisar o diff; nenhuma publicação automática.
5. Validar as correções e registrar os limites da auditoria.
6. Apresentar um fluxo recomendado com menos passos, mantendo revisão clínica explícita e separando propostas maiores da entrega.

## Reversão

Alterações locais, sem migração ou alteração de dados. Cada correção poderá ser retirada do diff independentemente; preservam-se as evidências dos testes. Uma publicação futura seguirá a fila e os controles atuais do ambiente responsável.

## Recomendações de fluxo da auditoria

Fluxo recomendado: **abrir paciente → gravar/anexar → analisar conjunto → revisar e incorporar → concluir**. A revisão clínica permanece explícita; documentos e comunicação dependem da decisão do veterinário.

| Prioridade | Proposta | Redução de trabalho | Limite preservado |
| --- | --- | --- | --- |
| 1 | Usar a gravação atual diretamente no conjunto | Elimina baixar o áudio e selecioná-lo novamente na área de lote | Reutiliza o original e exige ação explícita de envio |
| 1 | Adicionar todos os itens já revisados em uma ação | Com N itens, troca N botões de inclusão por um, mantendo as N conferências | Fontes, identidade, bloqueios e aprovações individuais continuam obrigatórios |
| 1 | Clicar em uma pendência e chegar ao campo | Evita procurar campo entre etapa, cartão e área | Abre e foca o campo mantendo os valores do formulário |
| 2 | Uma ação principal de conclusão e resumo final | Tornar evidente que Finalizar já salva; evitar repetir Salvar e checkboxes antes da conclusão | Manter confirmação de pendências e revisão de diagnóstico, conduta e prognóstico |
| 2 | Preparar documentos selecionados ao concluir | Evita navegar repetidamente entre Prescrição, Exames, Documentos e WhatsApp | Prévia e escolha explícita dos documentos/destinatário antes de enviar |
| 2 | Reanalisar o conjunto com o atendimento atualizado, reaproveitando originais | Evita selecionar e enviar de novo fontes cujo contexto salvo mudou | Criar revisão nova e invalidar aprovações antigas; preservar o histórico |
| 2 | Detectar edição mais recente em outra aba ou aparelho | Evita retrabalho e sobrescrita quando alterna computador/celular | Exige contrato de revisão/conflito; não implementar como simples preferência pela última escrita |
| 2 | Atualizar listas e histórico sem bloquear a conclusão já persistida | Reduz a espera por consultas auxiliares repetidas antes e depois de finalizar | A confirmação de salvamento e conclusão continua obrigatória; falha de atualização auxiliar deve ser identificada separadamente |

Atalhos já disponíveis: **Ver todos os campos** reduz navegação do editor, **Finalizar atendimento** já executa o salvamento antes da conclusão e **Gerar PDF** salva o documento em edição. A lista de campos pendentes deve distinguir requisito de conclusão e recomendação de preenchimento, sem exigir 100% por padrão.

Para um redesenho maior, um piloto opcional de EGM pode ajudar a comparar as etapas e verificar se a redução de cliques preserva as confirmações clínicas. Não foi executado nesta rodada; depende de pedido explícito e complementa o SDD existente.

## Ciclo de publicação autorizado

1. Reservar a janela com Laudos, Gestão, Maps e Backup e conferir estado atual.
2. Transferir somente os arquivos revisados para worktree própria do clone público limpo, iniciada de `origin/stage`; nenhum histórico privado é enviado.
3. Preparar o snapshot isolado e a árvore de restauração antes de instalar; abrir PR para Stage e aguardar todos os checks.
4. Instalar em Stage, aguardar workflow terminal e validar SHA, fontes, arquivos servidos, configuração, testes isolados da instalação, contratos HTTP fictícios e navegação autenticada.
5. Com evidências de Stage aprovadas e fila ainda livre, abrir promoção `stage -> main`, aguardar gates e usar merge commit preservando Nginx.
6. Verificar produção e restaurar os trabalhos paralelos via PR para Stage; aguardar workflow completo e conferir runtime, fontes e igualdade dos arquivos preservados.
7. Encerrar a reserva somente após a restauração validada. Registrar evidências na descrição das PRs e no relatório operacional; nenhuma chamada clínica paga ou comunicação integra este ciclo.

Reversão do ciclo: preservar referências e árvores dos dois ambientes; qualquer correção/reversão usa PR e os mesmos controles, sem push direto em branches protegidas nem redução de gates.
