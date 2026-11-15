# Plano de entrega

1. Compor a candidata apenas com as mudanças de Gestão sobre a base atual de produção.
2. Validar cálculos, autorização, migração, persistência concorrente e interface com dados fictícios e bancos descartáveis.
3. Preservar a árvore compartilhada e instalar a candidata isolada em Stage. Conferir versão, testes da instalação, API e interface autenticadas.
4. Promover a candidata testada pelo PR protegido de Stage para main. Confirmar instalação, migração, acesso autenticado e preservação.
5. Restaurar integralmente a árvore compartilhada de Stage com os documentos de Gestão. Verificar a instalação da restauração e liberar a janela.
