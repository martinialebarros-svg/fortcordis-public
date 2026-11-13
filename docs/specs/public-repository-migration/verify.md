# Verificação

Em 12/11/2026, os testes de frontend, migrações e controle do Maps passaram no Actions em main e stage. A preparação inicial também validou localmente 52 testes afetados pela anonimização, 13 testes de SHA imutável, 6 testes de preservação do Nginx e o isolamento do WhatsApp.

As branches main e stage exigem pull request e os dois checks do frontend. Exclusão e force push estão bloqueados. Somente o proprietário possui acesso de escrita. Workflows de contribuidores externos exigem aprovação. Os ambientes staging e production aceitam apenas suas branches correspondentes.

## Homologação

A execução 43253412175 instalou o commit público 1f1fe387 em staging. O quality-gate, a conexão SSH, os testes de saúde, o canário autenticado e a restauração de backup passaram. Os arquivos de dados locais foram preservados.

## Preparação de produção

O origin de produção foi migrado para o repositório público, com backup das alterações locais e manutenção do código instalado em 1b2957d5. Os cinco segredos necessários foram cadastrados no ambiente production, sem publicação de valores.

A revisão de liberação mantém `[preserve-nginx]` na mensagem do merge: o workflow lê essa marca do SHA aprovado e evita alterar ou recarregar o Nginx. A validação do primeiro deploy público de produção será registrada no respectivo workflow após o merge.

## Escopo desta revisão

Esta revisão altera apenas as exclusões de arquivos locais e a documentação da migração; não modifica código de aplicação, workflow ou dependências. A conferência com `git check-ignore` aprovou 13 exemplos privados e preservou 4 controles versionáveis. Os 6 testes existentes de `test_prod_nginx_preserve_workflow.py` passaram, incluindo a preservação do Nginx no deploy e no rollback.
