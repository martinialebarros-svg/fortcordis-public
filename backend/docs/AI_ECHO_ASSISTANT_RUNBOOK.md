# Assistente de Laudo por Voz - instalação e operação

## Escopo

MVP de homologação para ecocardiografia veterinária. O assistente transcreve,
estrutura e devolve sugestões ao formulário; não salva, finaliza, assina nem libera
laudos.

## Configuração local

1. Copie somente as variáveis necessárias de `backend/.env.example` para o arquivo
   local não versionado.
2. Configure uma chave de projeto de desenvolvimento em `OPENAI_API_KEY`.
3. Mantenha `AI_ECHO_ASSISTANT_ENABLED=false` até executar as migrations e testes.
4. Execute:

```bash
cd backend
./venv/bin/python -c "from migrations.runner import run_migrations; run_migrations()"
./venv/bin/uvicorn app.main:app --reload
```

5. Habilite `AI_ECHO_ASSISTANT_ENABLED=true` e reinicie o backend.
6. Inicie o frontend com `npm run dev`.

Os testes automatizados usam mocks e nunca precisam de uma chamada real.

## Uso clínico

1. Abra um laudo de ecocardiograma em edição.
2. Selecione **Ditado assistido por IA**.
3. Grave ou envie o áudio e confirme a transcrição.
4. Edite a transcrição, se necessário.
5. Gere as sugestões.
6. Revise alertas, números, unidades, texto atual e texto sugerido.
7. Edite, rejeite ou selecione individualmente os campos e medidas.
8. Escolha substituir, inserir abaixo ou aceitar apenas campos vazios.
9. Aplique ao rascunho.
10. Volte ao formulário, revise e salve pelo fluxo normal.

## Homologação

- nunca use dados reais ou oficiais;
- use paciente, tutor e clínica artificiais;
- confirme a migration `20260725_56`;
- confirme que a feature está habilitada somente no backend de stage;
- valide criação, upload, transcrição, edição, estruturação, aplicação seletiva,
  auditoria e exclusão;
- confirme que o laudo permanece `Rascunho`;
- confirme que o fluxo manual funciona com a flag desligada;
- não copie valores de segredo em logs, terminal ou relatório.

O canary vivo e descartável pode ser disparado por um commit de `stage` cuja
mensagem contenha `[ai-echo-canary]`. Ele usa áudio sintético versionado, não
imprime transcrição ou conteúdo clínico, não persiste o `Laudo` e remove a sessão
artificial ao final.

## Observabilidade segura

Os logs podem conter IDs, etapa, duração, status, código de erro, provedor, modelo e
versão de prompt. Não devem conter áudio, transcrição, texto integral do laudo,
nomes, contatos ou chave.

Se a transcrição terminar e a estruturação falhar, consulte `last_error.code`.
`invalid_structured_output` significa que a resposta não obedeceu ao contrato e
não deve ser descrita como indisponibilidade da API. Sugestões repetidas para a
mesma `field_key` são consolidadas: permanece a de maior confiança e a revisão
mostra `duplicate_field_suggestion`. `provider_unavailable` fica reservado a
falhas efetivas não classificadas do provedor.

Afirmações explícitas de exame normal expandem frases normais para os aspectos
qualitativos, sem gerar medidas. A expressão "demais parâmetros ecocardiográficos
dentro da normalidade" completa apenas campos não contraditos por achados ditados.
No cenário "disfunção diastólica grau 1, padrão senil", o backend preserva essa
alteração no campo diastólico e na conclusão, completa os demais campos e registra
`global_normality_expanded` para revisão obrigatória.

## Retenção

O arquivo temporário usa `UPLOAD_DIR/ai_echo_audio` ou fallback local. O worker
remove itens expirados em intervalo configurável. A exclusão manual permanece
disponível antes da expiração. Transcrição, sugestões e auditoria permanecem para
rastreabilidade clínica até existir política de retenção de prontuário definida.

## Rollback

Rollback imediato e reversível:

1. defina `AI_ECHO_ASSISTANT_ENABLED=false`;
2. reinicie somente o backend de homologação;
3. confirme que o botão desapareceu e o editor manual continua íntegro.

Rollback de código:

1. reverta o commit do módulo em `stage`;
2. execute quality gate e deploy novamente;
3. deixe as tabelas aditivas inertes para preservar auditoria.

Rollback de schema é permitido apenas em banco vazio ou após backup confirmado,
porque `downgrade()` remove todas as tabelas `ai_echo_*`.

## Limitações do MVP

- fila em memória: reinício marca processamento interrompido para nova tentativa;
- limite de duração de arquivo enviado depende também do metadado do navegador; o
  backend sempre impõe limite de bytes;
- não há streaming em tempo real;
- isolamento organizacional usa `clinic_id` existente e proprietário estrito da
  sessão; uma entidade SaaS de organização ainda não existe no produto;
- não há conversão de unidade nem cálculo automático;
- o gradiente tricúspide sem campo equivalente aparece para revisão manual;
- custo estimado só é calculado quando taxas administrativas são configuradas;
- referências ecocardiográficas permanecem auxiliares e não são aplicadas pelo
  assistente.

## Próxima fase

- fila durável com idempotência e cancelamento;
- política de retenção clínica configurável por organização;
- entidade SaaS de organização e política explícita multi-tenant;
- avaliações com áudio sintético e WER numérico por termo;
- transcrição incremental opcional;
- painel de métricas de feedback por campo e aprendizado supervisionado futuro;
- dashboard administrativo de uso, aceitação, edição, latência e custos.

## Referências da integração

- Speech-to-text: `https://developers.openai.com/api/docs/guides/speech-to-text`
- Structured Outputs: `https://developers.openai.com/api/docs/guides/structured-outputs`
