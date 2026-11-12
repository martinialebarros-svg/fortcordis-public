# WhatsApp Stage Backend (Node.js + TypeScript)

Backend minimal para stage local, integrando com WhatsApp Cloud API (Meta), com webhook validado por assinatura, persistencia em Postgres e endpoints de conversa/agente.

## Stack

- Node.js 18+
- TypeScript + Express
- PostgreSQL (`pg`)
- Axios (Graph API)
- Dotenv

## Estrutura

```text
.
+- docker-compose.yml
+- Dockerfile
+- package.json
+- tsconfig.json
+- .env.example
+- migrations/
¦  +- init.sql
+- scripts/
¦  +- smoke-tests.sh
¦  +- test-whatsapp-retry.ts
+- src/
   +- app.ts
   +- index.ts
   +- middleware/
   +- controllers/
   +- services/
   +- db/
   ¦  +- migrate.ts
   +- models/
   +- utils/
```

## Setup rapido

1. Copie as variaveis:

```bash
cp .env.example .env
```

2. Preencha os valores reais em `.env`.

3. Suba o Postgres:

```bash
docker-compose up -d db
```

4. Instale dependencias:

```bash
npm install
```

5. Rode migration:

```bash
npm run migrate
```

6. Rode API em dev:

```bash
npm run dev
```

API sobe em `http://localhost:3000` por padrao.

## Robustez de webhook e mensageria

- `POST /webhook` persiste evento bruto em `webhook_events` antes de processar (`payload_hash` SHA-256 do raw body).
- Eventos duplicados sao deduplicados por `payload_hash`.
- Processamento usa bloqueio transacional (`FOR UPDATE`) por `webhook_events.id`.
- Mensagens inbound usam `ON CONFLICT (wa_message_id) DO NOTHING`.
- Status inbound atualiza `messages.status` e grava historico em `message_status_events`.
- Claim/unclaim usa transacao + lock da conversa para reduzir race conditions.
- Cleanup automatico de `webhook_events` com janela de retencao configuravel e metrica de execucao em `webhook_event_cleanup_runs`.
- Logs com redacao de campos sensiveis (token/authorization/secret/signature/payload) e truncamento de metadados extensos.

## Rodar tudo via Docker Compose (opcional)

```bash
docker-compose up -d --build
```

## Endpoints principais

- `GET /health` (inclui estado do worker de cleanup em `observability.webhookEventsCleanup`)
- `GET /webhook` (verificacao Meta)
- `POST /webhook` (mensagens/status/contacts com `X-Hub-Signature-256`)
- `GET /conversations`
- `GET /conversations/:id/messages`
- `POST /conversations/:id/messages`
- `POST /conversations/:id/claim`
- `POST /conversations/:id/unclaim`
- `GET /agents`
- `POST /agents`
- `POST /automation/agenda/reservations` (envia `reserva_de_agendamento` com quick replies)
- `POST /automation/templates` (envia modelo de texto aprovado, com idempotencia e referencia de dominio)
- `POST /automation/document-templates` (recebe PDF em memoria, faz upload na Cloud API e envia
  modelo de recibo ou laudo domiciliar com cabecalho de documento). O modelo
  `laudo_domiciliar_pdf_tutor` usa pt_BR, categoria Utilidade, cabecalho DOCUMENT
  e variaveis nome do tutor/pet. Habilitar `WHATSAPP_HOME_REPORT_TEMPLATE_ENABLED=true`
  apenas depois de aprovado na conta Meta daquele ambiente.

## Autenticacao e ACL

- Rotas protegidas: `/conversations*`, `/agents*` e `/automation*`.
- A API aceita `Authorization: Bearer <token>` e valida o usuario no backend principal via `GET ${API_BACKEND_URL}/api/v1/auth/me`.
- Opcionalmente, automacoes podem usar `X-WhatsApp-Internal-Token` quando `WHATSAPP_INTERNAL_API_TOKEN` estiver configurado.
- Guardrail de producao: se `NODE_ENV/APP_ENV` indicar producao e `WHATSAPP_API_AUTH_ENABLED=false`, o processo falha no startup por padrao.
- Override excepcional: `WHATSAPP_ENFORCE_AUTH_IN_PRODUCTION=false` (nao recomendado).
- ACL por papel (opcional):
- `WHATSAPP_ALLOWED_PAPEIS` para leituras (`GET/HEAD/OPTIONS`).
- `WHATSAPP_WRITE_ALLOWED_PAPEIS` para escritas (`POST/PUT/PATCH/DELETE`).
- Se listas vazias, qualquer usuario autenticado pode acessar.
- Recomendacao stage/producao: `admin,recepcao,veterinario,cardiologista`.
- No deploy VPS padrao do projeto, `WHATSAPP_INTERNAL_API_TOKEN` e ACL defaults sao preenchidos automaticamente se estiverem em branco.

## Smoke tests

O script inclui:

- verificacao `GET /webhook`
- assinatura invalida (`401`)
- webhook duplicado (idempotencia de `webhook_events` + `messages`)
- upsert de conversa com disparos concorrentes
- historico de status (`messages.status` + `message_status_events`)
- claim/unclaim
- teste auxiliar de retry/erro estruturado da Graph API (`scripts/test-whatsapp-retry.ts`)

Execucao padrao:

```bash
bash scripts/smoke-tests.sh
```

Com `BASE_URL` customizado:

```bash
BASE_URL=http://localhost:3000 bash scripts/smoke-tests.sh
```

Para habilitar o teste opcional de falha de persistencia (espera `503`):

```bash
RUN_PERSIST_FAILURE_TEST=true bash scripts/smoke-tests.sh
```

Para smoke com auth habilitada, passe um dos metodos:

```bash
API_AUTH_BEARER_TOKEN="<jwt>" bash scripts/smoke-tests.sh
```

```bash
WHATSAPP_INTERNAL_API_TOKEN="<internal_token>" bash scripts/smoke-tests.sh
```

## Scripts npm

```bash
npm run smoke
npm run test:whatsapp-retry
npm run test:reservation-template
npm run test:approved-templates
npm run test:document-templates
```

## Observacoes

- `POST /webhook` exige assinatura valida por padrao.
- Respostas de botao da Agenda sao aceitas somente quando payload, remetente e `PHONE_NUMBER_ID`
  correspondem ao envio persistido; o callback ao backend principal usa o token interno.
- Modelo da Agenda: `WHATSAPP_RESERVATION_TEMPLATE_NAME=reserva_de_agendamento` e
  `WHATSAPP_RESERVATION_TEMPLATE_LANGUAGE=pt_BR`.
- Documentos aceitam apenas `application/pdf`, assinatura `%PDF`, nome seguro e ate 8 MiB. O binario
  nao e persistido; ficam registrados somente hash, nome, ID de midia e ID da mensagem.
- Os quatro modelos financeiros possuem IDs registrados no catalogo e tiveram a aprovacao confirmada
  operacionalmente antes do cutover. O servico nao consulta o status da Meta em tempo real.
- Para debug local sem assinatura (nao recomendado), use `WEBHOOK_ALLOW_UNSIGNED=true` no `.env`.
- Retencao de eventos webhook:
  - `WHATSAPP_WEBHOOK_EVENTS_CLEANUP_ENABLED` (default `true`)
  - `WHATSAPP_WEBHOOK_EVENTS_RETENTION_DAYS` (default `30`)
  - `WHATSAPP_WEBHOOK_EVENTS_CLEANUP_INTERVAL_MINUTES` (default `60`)
  - `WHATSAPP_WEBHOOK_EVENTS_CLEANUP_BATCH_SIZE` (default `2000`)
- TODO: validar constraints `NOT VALID` de `audit_logs` em janela de manutencao.
