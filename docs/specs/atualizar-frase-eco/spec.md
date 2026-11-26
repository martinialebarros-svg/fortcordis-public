# Especificação

- RF-01: exibir “Atualizar frase” nos aspectos com seleção de frase única, tanto no modo preset quanto no compositor.
- RF-02: salvar somente o texto editado no ID da frase ativa selecionada, preservando título e metadados pelo contrato existente de PUT. Não criar outra frase nem alterar o texto de outros aspectos.
- RF-03: desabilitar atualização sem seleção válida, com texto vazio ou igual ao banco e durante salvamento individual, criação ou propagação em lote. Exibir “Atualizando...” durante a requisição.
- RF-04: manter a seleção ao editar, inclusive se o texto passar a coincidir com outra frase do banco. Atualizar o banco local apenas após sucesso, mantendo o texto do laudo e eventuais edições feitas durante a requisição.
- RF-05: informar o alcance nos presets vinculados, mostrar sucesso após o PUT e preservar edição/seleção com opção de tentar novamente em caso de falha.
- RF-06: preservar “Usar frase”, “Salvar como nova frase” e a conclusão composta, sem atualização automática do banco ao digitar nem emissão/salvamento de laudos reais.

## Critérios de aceitação

CA-01: atualização explícita envia um único PUT com ID/texto/metadados corretos, sem POST nem alteração de outros aspectos.
CA-02: seleção e texto permanecem íntegros após sucesso e falha; repetir o salvamento sem nova edição fica indisponível.
CA-03: entradas inválidas e requisições concorrentes não oferecem atualização; nova edição durante o envio não é descartada.
CA-04: ação disponível nos modos preset/compositor e compatível com a criação de nova frase; sem atualização de conclusão composta.
