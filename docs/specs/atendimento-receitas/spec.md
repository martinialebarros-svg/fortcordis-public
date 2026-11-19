# Contrato das receitas no atendimento

- CA-01 — Cada item tem posologia por campos ou em texto corrido. O texto digitado é persistido e exibido na prévia, no PDF, na impressão e no histórico sem combinar os dois formatos. A emissão exige conteúdo quando o formato escolhido é texto corrido.
- CA-02 — O botão Nova receita cria outro rascunho em branco no mesmo atendimento. O seletor mostra todas as receitas. Editar e gerar o PDF usam o alvo selecionado. A troca protege edições ainda pendentes.
- CA-03 — Adicionar item manual também aparece logo após o último medicamento. Ao clicar, o nome do novo item recebe o foco.
- CA-04 — Receitas legadas continuam no formato por campos. O texto acompanha a cópia por adendo e as alterações entram no histórico. O endpoint legado de PDF continua servindo a receita do dia.

O payload dos itens aceita `posologia_texto` como texto ou nulo. Texto não nulo seleciona o formato corrido e pode estar vazio em rascunho. Nulo seleciona os campos estruturados. A migração adiciona uma coluna de texto anulável à tabela existente.
