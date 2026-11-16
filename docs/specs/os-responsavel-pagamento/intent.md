# Responsavel pelo pagamento da ordem de servico

Em exames encaminhados por parceiros, a clinica do atendimento e o profissional que assumiu a cobranca podem ser pessoas diferentes. O fluxo atual vincula toda OS de eletrocardiograma a clinica, mesmo quando o veterinario parceiro deve pagar.

O objetivo e permitir escolher **Clinica parceira** ou **Veterinario parceiro** ao gerar a OS, mantendo a clinica como contexto do caso e registrando separadamente o responsavel financeiro. A escolha nao registra pagamento, nao envia mensagem e nao altera ordens antigas.

O preco segue a tabela da clinica quando vinculada. Sem clinica, a OS do veterinario usa a tabela padrao de Fortaleza para o servico e horario selecionados. Tabelas individuais e troca de responsavel apos a emissao ficam fora do escopo.

Riscos principais: misturar dividas da clinica e do veterinario no Financeiro, duplicar OS em retry, atribuir credito excedente a clinica errada e perder a rastreabilidade da escolha.
