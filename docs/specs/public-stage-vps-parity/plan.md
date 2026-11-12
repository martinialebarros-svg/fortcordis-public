# Plano

1. Comparar a revisão instalada com a origem usada na cópia pública.
2. Restaurar somente arquivos de código e testes da revisão instalada em uma cópia de trabalho isolada.
3. Revisar padrões de credenciais e validar paridade e testes.
4. Integrar por pull request em stage após os checks obrigatórios.
5. Migrar a origem na VPS apenas após backup local, mantendo o deploy desativado até cadastrar credenciais e validar o primeiro deploy.

Reversão: reverter o PR de paridade no repositório público. Esta mudança não altera arquivos nem serviços na VPS.
