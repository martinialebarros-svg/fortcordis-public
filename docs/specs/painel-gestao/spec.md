# Especificação do painel de Gestão

- G1. A navegação e a API de Gestão são restritas a administradores. O domínio institucional encaminha a rota ao aplicativo, que exige sessão.
- G2. O painel apresenta contribuição por hora, ocupação, cancelamentos, prazo de recebimento, concentração de receita e caixa projetado. O período anterior tem a mesma duração. Os filtros por clínica e região restringem o recorte, mas a capacidade e a disponibilidade da jornada continuam globais.
- G3. Os cálculos distinguem competência, caixa confirmado, previsões e premissas. Sem dados suficientes, o indicador é parcial ou indisponível. Campos em branco representam informação desconhecida. Zero informado é um valor explícito.
- G4. Simular recalcula os indicadores sem gravação. Salvar confirma a substituição do cenário-base, verifica a revisão, registra a auditoria e permite reler os valores no recorte correspondente. Os valores informados não são projetados para o período anterior. A descrição e a recorrência dos movimentos manuais aparecem nos detalhes.
- G5. A migração aditiva 20261025_101 cria a tabela privada de premissas com RLS no PostgreSQL, sem dados iniciais. O executor aplica a versão faltante mesmo depois de versões posteriores e conserva o histórico já aplicado.
