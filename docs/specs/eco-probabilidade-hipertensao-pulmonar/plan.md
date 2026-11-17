# Plano — Publicação pública do módulo HP

1. Registrar os snapshots públicos e preparar worktree própria a partir de Stage. Aplicar somente os hunks revisados de HP sobre a árvore atual de produção, sem importar histórico privado.
2. Validar matriz, unidades, selo, importação, rascunhos e projeções do assistente/PDF, usando dados sintéticos. Executar testes frontend/backend, tipos, lint, build e paridade Python/TypeScript.
3. Publicar candidata isolada por PR para Stage após checar fila, reserva, backup, lotes e versão instalada. Conferir o fluxo autenticado de laudo sintético e o PDF.
4. Promover por PR direto Stage→main com merge commit e preservação de Nginx. Aguardar resultado terminal e verificar versão instalada, serviços, dados e resultado do módulo.
5. Restaurar Stage por PR preservando todos os arquivos paralelos por blob e modo; repetir provas de instalação e estabilidade de produção. Liberar a janela somente após restauração confirmada.

Rollback: restaurar o snapshot público anterior pelo mesmo fluxo protegido se houver falha; não restaurar banco por código e não sobrescrever dados de runtime. Sem migração do módulo. O backup e a preservação de arquivos permanecem parte do instalador existente.
