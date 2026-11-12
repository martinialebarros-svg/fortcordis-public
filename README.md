# Fort Cordis

Sistema de operação clínica veterinária com FastAPI, Next.js e serviço de WhatsApp.

O código publicado começa com um histórico independente. As configurações locais
podem ser preparadas a partir dos arquivos `.env.example` de cada serviço.

## Desenvolvimento

- Backend em `backend/`, com dependências em `requirements.txt` e `requirements-test.txt`.
- Frontend em `frontend/`, com instalação por `npm ci` e testes por `npm test`.
- Serviço WhatsApp em `whatsapp-stage-backend/`.
- Especificações de mudanças em `docs/specs/`, seguindo `docs/SDD-WORKFLOW.md`.
- O preenchimento de dados de demonstração exige `SEED_ADMIN_PASSWORD` no ambiente.

## Entrega

Mudanças entram por pull request em `stage`. A promoção para produção ocorre por
pull request de `stage` para `main`. O GitHub Actions executa os testes em
`ubuntu-latest`. Os jobs de deploy usam os ambientes `staging` e `production`,
com credenciais e branches autorizadas configuradas no GitHub.
