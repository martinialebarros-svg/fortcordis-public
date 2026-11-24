# Plano

1. Reusar o carregador paginado/cacheado de clínicas no campo compartilhado, com leitura sob demanda e lista nativa de sugestões.
2. Preservar contrato textual e dados preenchidos; permitir repetição da leitura após falha sem bloquear cadastro.
3. Verificar catálogo paginado, preservação de valores, recuperação e payload do cadastro. Executar testes relacionados, lint, tipos, build e guardrail SDD conforme o impacto.
4. Registrar evidências em `verify.md`, sem commit, push ou publicação neste pedido.

Rollback: restaurar o componente anterior e seus testes/documentos desta mudança. Não há migração nem transformação de dados persistidos.
