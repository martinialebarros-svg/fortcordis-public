# Plano de implementação

1. Ajustar o contrato de validação, os prompts de extração e síntese e a apresentação dos resultados existentes para utilizar o vínculo estabelecido pelo envio. Preservar a identificação lida como informação documental.
2. Adaptar a serialização e a retomada dos conjuntos antigos. Remover a dependência das decisões adicionais de identidade e permitir a síntese com fontes já concluídas. Conservar os controles de usuário, paciente e integridade.
3. Simplificar o painel de anexos e as condições de revisão dos achados. Atualizar o tratamento de revisões recuperadas em memória e a ação de atualização da síntese.
4. Executar regressões com dados fictícios, testes dos percursos principais, lint, tipos, build e guardrail SDD. Revisar o diff integrado para detectar bloqueios remanescentes e aprovações indevidas.

## Reversibilidade

A alteração usa a estrutura existente de lotes e resultados. A leitura original e os registros históricos são preservados. Uma eventual reversão de código recupera o comportamento anterior, mantendo os anexos e as decisões clínicas já registradas. A homologação deve verificar o contrato compatível entre backend e frontend antes da publicação.
