# Plano

1. Conferir seleção efetiva, atualização existente, contrato da API e testes do editor.
2. Reutilizar a sincronização por aspecto com estado de salvamento individual, feedback e proteção das demais operações de escrita do banco.
3. Fixar a seleção efetiva ao editar e adicionar botão com informação sobre os presets vinculados.
4. Exercitar atualização, falha/retentativa, validação e concorrência com fixtures fictícias; rodar lint, tipos, build e guardrail SDD.

Rollback: reverter somente o diff desta feature. Sem migração ou mudança no contrato da API. Nenhuma escrita em bancos/ambientes reais durante a validação local.
