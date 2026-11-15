# Verificação do painel de Gestão

O código de Gestão corresponde à versão homologada no Stage compartilhado em 08/11. A revalidação de 15/11, sobre o main público vigente, passou em 103 testes de backend e migrações com SQLite e PostgreSQL 16 descartáveis, 24 testes de interface e roteamento, lint e TypeScript.

| ID | Evidência funcional local | Status |
| --- | --- | --- |
| G1 | Testes de permissões da API e de navegação, inclusive redirecionamento para login | Aprovado |
| G2 | Testes dos seis indicadores, dos recortes e da comparação anterior | Aprovado |
| G3 | Regressões financeiras de competência, recebimentos, previsões e dados ausentes | Aprovado |
| G4 | Simulação sem gravação, salvamento, releitura, concorrência e reversão transacional em bancos descartáveis | Aprovado |
| G5 | PostgreSQL 16, restrição dos papéis públicos e aplicação única da 101 após a versão mais recente | Aprovado |

O PR de promoção registra as evidências da instalação isolada, as verificações autenticadas e a comparação de árvores. O PR de restauração registra a preservação dos trabalhos paralelos.
