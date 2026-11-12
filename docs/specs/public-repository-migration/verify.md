# Verificação

Em 12/11/2026, os testes de frontend, migrações e controle do Maps passaram no Actions em main e stage. Localmente passaram 52 testes afetados pela anonimização, 13 testes de SHA imutável, 6 testes de preservação do Nginx e as verificações de isolamento do WhatsApp.

As branches main e stage exigem pull request e os dois checks do frontend. Exclusão e force push estão bloqueados. Somente o proprietário possui acesso de escrita. Workflows de contribuidores externos exigem aprovação.

Os ambientes staging e production aceitam apenas suas branches correspondentes. A migração da VPS e a validação de deploy ainda dependem das credenciais dos novos ambientes; não houve troca do origin nem intervenção na VPS.

O primeiro guardrail detectou documentação ausente da fixture do Maps. Esta correção repõe a estrutura necessária, sem trazer o histórico operacional privado.
