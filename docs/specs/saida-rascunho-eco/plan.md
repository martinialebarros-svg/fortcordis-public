# Plano de entrega

1. Proteger a confirmação do rascunho e verificar se a navegação cliente saiu da origem.
2. Documentar o fluxo e testar no Chrome com o Next.js compilado, uma API local descartável e dados fictícios. Exercitar o botão, link de menu, salvamento rejeitado e navegação cliente que não conclui.
3. Usar os marcos do console para comparar o resultado em Stage quando a candidata for instalada. Reverter o diff de frontend se a saída regressar.


## Correção da recuperação pendente — 25/11/2026

1. Usar o estado de recuperação já existente para distinguir uma cópia salva aguardando escolha de um formulário em edição. Não remover o bloqueio de gravação do hook nesse estado.
2. Ajustar a condição de confirmação antes de navegar nos dois editores e evitar o falso aviso de `beforeunload` enquanto a escolha de recuperação está pendente. Manter o identificador do workspace, o snapshot persistido e a escolha explícita de recuperação; após retomada, a guarda de alterações não salvas volta a valer.
3. Acrescentar regressões de Voltar e menus, saída/reabertura/retomada com a mesma cópia e falha de gravação durante edição ativa. Usar apenas dados fictícios e API simulada.
4. Executar testes focais e verificações de frontend/SDD compatíveis com o repositório; revisar o diff. Registrar os resultados atuais separadamente das evidências históricas.

Rollback: reverter as condições de saída e os testes correspondentes, sem migração, restauração de dados ou alteração de registros clínicos. Stage e produção permanecem etapas posteriores.
