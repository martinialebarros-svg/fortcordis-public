# Plano

1. Pesquisar fontes primárias pediátricas e consenso; conferir tabelas/suplementos, métodos e população.
2. Implementar política pediátrica no backend e frontend, com confirmação de aquisição e proteção contra intervalos adultos.
3. Integrar editor, prévia e PDF, incluindo proveniência e persistência do protocolo.
4. Testar limites clínicos, regressões, paridade, PDF sintético; executar tipos, lint, build e guardrail SDD.

Sem migração, alteração do catálogo ou edição de registros reais. Rollback: reverter os arquivos desta feature; valores originais de exames e catálogo são preservados. Publicação segue PR para Stage e promoção para main, após validação e autorização aplicável.

## Continuação de legibilidade e cores

1. Reorganizar cartões com pares de campos e metadados abaixo.
2. Derivar posição numérica exclusivamente na apresentação, reutilizando faixas elegíveis e medidas normalizadas; manter guardas e motivos de indisponibilidade.
3. Verificar posições, limites, entradas inválidas, métodos incompatíveis e comportamento adulto; renderizar casos fictícios em desktop/celular.
4. Publicar a correção pelo fluxo já autorizado Stage → produção, preservando os trabalhos paralelos de Stage e verificando os arquivos servidos.
