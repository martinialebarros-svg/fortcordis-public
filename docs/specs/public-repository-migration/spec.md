# Requisitos

- Histórico independente para main e stage.
- Exclusão de bancos, logs e evidências operacionais do código público.
- Testes sem credenciais de deploy.
- Secrets de deploy restritos aos ambientes e branches correspondentes.
- Diagnóstico de falhas de serviços consultado na VPS.

- Fixtures mantidas em docs/specs conservam os quatro documentos exigidos pelo guardrail SDD.
- Jobs com acesso à VPS exigem a respectiva variável de repositório STAGING_DEPLOY_ENABLED=true ou PRODUCTION_DEPLOY_ENABLED=true. A ativação ocorre somente após cadastrar secrets, migrar o origin e validar o acesso.
- O primeiro deploy público de produção deve manter a política vigente de preservação do Nginx: a mensagem do commit de merge inclui `[preserve-nginx]`, consumida pelo workflow existente.
- Backups, diagnósticos locais e diretórios privados da VPS devem ser ignorados pelo Git, além dos arquivos de ambiente e bancos já excluídos.
