from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

from pydantic import Field
from pydantic_settings import BaseSettings

ENV_FILE_PATH = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    DATABASE_URL: str
    # Limites por processo da API. Em PostgreSQL, evitam que conexoes degradadas
    # acumulem espera indefinida e respeitam o teto do pooler gerenciado.
    DATABASE_POOL_SIZE: int = Field(default=5, ge=1)
    DATABASE_MAX_OVERFLOW: int = Field(default=5, ge=0)
    DATABASE_POOL_TIMEOUT_SECONDS: int = Field(default=15, ge=1)
    DATABASE_POOL_RECYCLE_SECONDS: int = Field(default=1800, ge=1)
    DATABASE_CONNECT_TIMEOUT_SECONDS: int = Field(default=10, ge=1)
    DATABASE_POOL_PRE_PING: bool = True
    APP_ENV: str = "development"
    # `all` mantem o comportamento local legado. Em producao, o systemd
    # executa a API como `api` e os trabalhos assincronos como `worker`.
    FORTCORDIS_PROCESS_ROLE: Literal["all", "api", "worker"] = "all"
    SECRET_KEY: str = "change-me"
    ENFORCE_STRONG_SECRET_KEY_IN_PRODUCTION: bool = True
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 720
    AUTH_COOKIE_NAME: str = "fortcordis_session"
    AUTH_COOKIE_PATH: str = "/"
    AUTH_COOKIE_SAMESITE: str = "lax"
    AUTH_COOKIE_SECURE: bool = False
    AUTH_COOKIE_DOMAIN: Optional[str] = None
    AUTH_PROVIDER: Literal["legacy", "supabase"] = "legacy"
    SUPABASE_URL: str = ""
    SUPABASE_PUBLISHABLE_KEY: str = ""
    # Exclusivamente no servidor; necessario apenas para administrar/importar contas.
    SUPABASE_SECRET_KEY: str = ""
    SUPABASE_AUTH_TIMEOUT_SECONDS: int = Field(default=5, ge=1, le=30)
    SUPABASE_REFRESH_COOKIE_NAME: str = "fortcordis_refresh"
    SUPABASE_REFRESH_COOKIE_MAX_AGE: int = Field(default=2592000, ge=60)
    CSRF_PROTECTION_ENABLED: bool = True
    CSRF_COOKIE_NAME: str = "fortcordis_csrf"
    CSRF_HEADER_NAME: str = "x-csrf-token"
    CSRF_TRUST_SAME_SITE_FETCH_METADATA: bool = True
    UPLOAD_DIR: str = "/opt/fortcordis/uploads"
    GOOGLE_MAPS_API_KEY: str = ""
    # Temporary, explicit operational release. Removing it and restarting all
    # API/worker processes restores the persisted fail-closed cost policy.
    GOOGLE_MAPS_COST_EMERGENCY_RELEASE: bool = False
    # Stage-first rollout: resolve Agenda locally; ask for consent only when a
    # provider would actually be called. This does not authorize paid traffic.
    GOOGLE_MAPS_AGENDA_CACHE_FIRST: bool = False
    # Explicit server rollout. False permits finite, internally recorded human
    # Agenda executions only when the persisted policy is monitor. Extras and
    # background jobs never inherit this operational authorization.
    GOOGLE_MAPS_AGENDA_REQUIRE_CONFIRMATION: bool = True
    # Persisted routes do not expire just because time passed. Location changes
    # still invalidate them; age-based expiry requires an explicit opt-in.
    GOOGLE_ROUTES_CACHE_EXPIRE_BY_AGE: bool = False
    GOOGLE_ROUTES_CACHE_MAX_AGE_DAYS: int = 30
    GOOGLE_MAPS_USAGE_METRICS_RETENTION_DAYS: int = 90
    LOGISTICA_FORCE_REFRESH_HEURISTICA_COM_API_KEY: bool = False
    LOGISTICA_ALLOW_LIVE_GOOGLE_LOOKUPS_ON_READ: bool = True
    LOGISTICA_GOOGLE_TRAFFIC_AWARE: bool = False
    REQUIRE_STRONG_SECRET_KEY: bool = False
    REQUIRE_UP_TO_DATE_MIGRATIONS: bool = False
    ALLOW_PERMISSION_MATRIX_FALLBACK: bool = False
    ALLOW_LEGACY_PLAIN_PASSWORDS: bool = False
    UPLOAD_DEDUPE_METRICS_RETENTION_DAYS: int = 90
    UPLOAD_DEDUPE_METRICS_AUTOCLEAN_ENABLED: bool = True
    UPLOAD_DEDUPE_METRICS_AUTOCLEAN_INTERVAL_HOURS: int = 24
    UPLOAD_DEDUPE_METRICS_AUTOCLEAN_TIMEOUT_SECONDS: int = 120
    UPLOAD_DEDUPE_METRICS_AUTOCLEAN_STARTUP_JITTER_SECONDS: int = 120
    UPLOAD_DEDUPE_METRICS_CLEANUP_BATCH_SIZE: int = 5000
    UPLOAD_DEDUPE_CLEANUP_RUNS_RETENTION_DAYS: int = 90
    RUNTIME_HTTP_5XX_ALERT_WINDOW_MINUTES: int = 5
    RUNTIME_HTTP_5XX_ALERT_THRESHOLD: int = 20
    RUNTIME_HTTP_LATENCY_WINDOW_MINUTES: int = 30
    RUNTIME_HTTP_LATENCY_MAX_SAMPLES_PER_ENDPOINT: int = 2000
    RUNTIME_HTTP_LATENCY_PRIORITY_ENDPOINTS: str = (
        "/api/v1/atendimentos,/api/v1/relatorios,/api/v1/fiscal,/api/v1/logistica"
    )
    # Rotas de leitura que precisam de uma metrica isolada, sem agregar subrotas
    # (por exemplo detalhes, PDFs ou mutacoes da mesma familia).
    RUNTIME_HTTP_LATENCY_EXACT_ENDPOINTS: str = (
        "/api/v1/ordens-servico,/api/v1/ordens-servico/cobrancas,"
        "/api/v1/agenda,/api/v1/agenda/relacionados,"
        "/api/v1/agenda/resumo-financeiro,/api/v1/agenda/configuracao,"
        "/api/v1/agenda/stream"
    )
    # PERF-17: historico administrativo sem URL, payload ou identificadores clinicos.
    # A escrita e tolerante a falhas para nunca bloquear uma resposta da aplicacao.
    RUNTIME_HTTP_LATENCY_PERSIST_ENABLED: bool = True
    RUNTIME_HTTP_LATENCY_RETENTION_DAYS: int = Field(default=14, ge=1, le=90)
    RUNTIME_HTTP_LATENCY_CLEANUP_INTERVAL_SECONDS: int = Field(default=21600, ge=60, le=86400)
    RUNTIME_HTTP_LATENCY_QUERY_MAX_SAMPLES: int = Field(default=20000, ge=100, le=100000)
    RUNTIME_HTTP_LATENCY_RELEASE_ID: str = ""
    WEB_PUSH_VAPID_PUBLIC_KEY: str = ""
    WEB_PUSH_VAPID_PRIVATE_KEY: str = ""
    WEB_PUSH_VAPID_CLAIMS_SUB: str = "mailto:suporte@fortcordis.local"
    WEB_PUSH_GROUP_WINDOW_SECONDS: int = 90
    WEB_PUSH_SCHEDULER_ENABLED: bool = True
    WEB_PUSH_SCHEDULER_POLL_SECONDS: int = 30
    WEB_PUSH_SCHEDULER_DISTRIBUTED_LOCK_ENABLED: bool = True
    WEB_PUSH_SCHEDULER_DISTRIBUTED_LOCK_KEY: int = 80433001
    WEB_PUSH_PENDING_REMINDER_DEFAULT_HOURS: int = 6
    ASSISTENTE_AGENDA_TOKEN: str = ""
    ASSISTENTE_AGENDA_MAX_WINDOW_DAYS: int = 14
    WHATSAPP_AGENDA_ENABLED: bool = False
    WHATSAPP_AGENDA_SERVICE_URL: str = "http://127.0.0.1:3010"
    WHATSAPP_AGENDA_INTERNAL_TOKEN: str = ""
    WHATSAPP_AGENDA_TIMEOUT_SECONDS: int = 15
    WHATSAPP_REMINDER_SCHEDULER_POLL_SECONDS: int = 300
    WHATSAPP_REMINDER_SCHEDULER_DISTRIBUTED_LOCK_ENABLED: bool = True
    WHATSAPP_REMINDER_SCHEDULER_DISTRIBUTED_LOCK_KEY: int = 80433002
    WHATSAPP_REMINDER_WINDOW_HOURS: int = 24
    WHATSAPP_REMINDER_MIN_LEAD_MINUTES: int = 45
    WHATSAPP_REMINDER_MAX_ATTEMPTS: int = 3
    WHATSAPP_REMINDER_RECIPIENT_TYPE: str = "clinica"
    # Ativar somente depois da aprovação do modelo com serviço nas duas WABAs.
    WHATSAPP_REMINDER_SERVICE_TEMPLATE_ENABLED: bool = False
    WHATSAPP_BOT_ENABLED: bool = False
    # Liberacao operacional independente do modo escolhido na interface.
    WHATSAPP_BOT_AUTO_SEND_ENABLED: bool = False
    WHATSAPP_BOT_PROCESSING_LEASE_SECONDS: int = 900
    WHATSAPP_BOT_MODEL: str = "gpt-5.6-sol"
    WHATSAPP_BOT_PROMPT_VERSION: str = "whatsapp-bot-v1"
    WHATSAPP_BOT_DEBOUNCE_SECONDS: int = 12
    WHATSAPP_BOT_SCHEDULER_POLL_SECONDS: int = 5
    WHATSAPP_BOT_SCHEDULER_DISTRIBUTED_LOCK_ENABLED: bool = True
    WHATSAPP_BOT_SCHEDULER_DISTRIBUTED_LOCK_KEY: int = 80433003
    WHATSAPP_BOT_MAX_ATTEMPTS: int = 3
    WHATSAPP_BOT_HANDOFF_PAUSE_HOURS: int = 12
    # Pausa do ENVIO ASSISTIDO, deliberadamente separada da de handoff. As
    # duas semanticas sao diferentes: handoff de emergencia significa "a
    # equipe vai ligar, o bot sai da frente"; envio assistido significa
    # apenas "um atendente respondeu esta mensagem". Usar 12h para o
    # segundo deixa o cliente sem bot por meio dia depois de UMA resposta.
    WHATSAPP_BOT_ASSISTED_SEND_PAUSE_HOURS: int = 0
    # Memoria de conversa: quantas mensagens anteriores vao ao prompt.
    # `0` desliga sem deploy. Teto real em `whatsapp_bot_prompt`.
    WHATSAPP_BOT_HISTORICO_MENSAGENS: int = 8
    WHATSAPP_BOT_MAX_REPLIES_PER_CONVERSATION_DAY: int = 20
    WHATSAPP_BOT_MAX_TOKENS_PER_DAY: int = 100000
    WHATSAPP_BOT_MAX_REPLY_CHARS: int = 900
    # Fase 6 (P6.5): custo por milhao de tokens do bot. Default 0.0, como
    # em AI_ECHO_*_COST_PER_MILLION - com 0.0 o painel reporta tokens e
    # marca o custo como nao configurado, em vez de exibir R$ 0,00 como
    # se fosse gratuito.
    WHATSAPP_BOT_INPUT_COST_PER_MILLION: float = 0.0
    WHATSAPP_BOT_OUTPUT_COST_PER_MILLION: float = 0.0
    WHATSAPP_BOT_RECONCILE_EVERY_CYCLES: int = 60
    WHATSAPP_BOT_RECONCILE_WINDOW_MINUTES: int = 30
    PUBLIC_APP_BASE_URL: str = ""
    AGENDA_FORMALIZACAO_INVITE_DEFAULT_HOURS: int = 72
    OPENAI_API_KEY: str = ""
    ASSISTENTE_IA_ENABLED: bool = True
    ASSISTENTE_IA_MODEL: str = "gpt-5.6-sol"
    ASSISTENTE_IA_MAX_TOOL_LOOPS: int = 6
    ASSISTENTE_IA_ACTION_TTL_MINUTES: int = 15
    ASSISTENTE_IA_VOICE_TRANSCRIPTION_MODEL: str = "gpt-4o-transcribe"
    ASSISTENTE_IA_VOICE_MAX_BYTES: int = 10 * 1024 * 1024
    ASSISTENTE_IA_VOICE_MAX_SECONDS: int = 60
    ASSISTENTE_IA_EMBEDDING_MODEL: str = "text-embedding-3-small"
    ASSISTENTE_IA_SEMANTIC_SEARCH_ENABLED: bool = True
    # Assistência do atendimento: ativação e validação clínica independentes do laudo.
    ATENDIMENTO_IA_ENABLED: bool = False
    ATENDIMENTO_IA_MODEL: str = "gpt-6.1-sol"
    ATENDIMENTO_IA_REASONING_EFFORT: str = "max"
    ATENDIMENTO_IA_TRANSCRIPTION_MODEL: str = "gpt-transcribe"
    ATENDIMENTO_IA_TIMEOUT_SECONDS: int = 180
    AI_ECHO_ASSISTANT_ENABLED: bool = False
    AI_PROVIDER: str = "openai"
    AI_TRANSCRIPTION_MODEL: str = "gpt-4o-transcribe"
    AI_STRUCTURING_MODEL: str = "gpt-5.6-sol"
    AI_AUDIO_RETENTION_HOURS: int = 2
    AI_ECHO_AUDIO_MAX_BYTES: int = 20 * 1024 * 1024
    AI_ECHO_AUDIO_MAX_SECONDS: int = 600
    AI_ECHO_MAX_ATTEMPTS: int = 3
    AI_ECHO_MONTHLY_SESSION_LIMIT: int = 100
    AI_ECHO_PROVIDER_TIMEOUT_SECONDS: int = 90
    AI_ECHO_REASONING_EFFORT: str = "low"
    AI_ECHO_MAX_OUTPUT_TOKENS: int = 8000
    AI_ECHO_CLEANUP_INTERVAL_MINUTES: int = 15
    AI_ECHO_STRUCTURING_INPUT_COST_PER_MILLION: float = 0.0
    AI_ECHO_STRUCTURING_OUTPUT_COST_PER_MILLION: float = 0.0
    ASSISTENTE_IA_SCHEDULER_ENABLED: bool = True
    ASSISTENTE_IA_SCHEDULER_POLL_SECONDS: int = 30
    ASSISTENTE_IA_SCHEDULER_DISTRIBUTED_LOCK_ENABLED: bool = True
    ASSISTENTE_IA_SCHEDULER_DISTRIBUTED_LOCK_KEY: int = 80433002
    PORTAL_CHALLENGE_EXPIRE_MINUTES: int = 15
    PORTAL_SESSION_TOKEN_EXPIRE_MINUTES: int = 30
    PORTAL_DOWNLOAD_TOKEN_EXPIRE_MINUTES: int = 5
    PORTAL_MAX_CHALLENGE_ATTEMPTS: int = 5
    PORTAL_CLINIC_INVITE_AUTH_ENABLED: bool = True
    PORTAL_CLINIC_PASSWORD_LOGIN_ENABLED: bool = True
    PORTAL_CLINIC_LEGACY_CODE_LOGIN_ENABLED: bool = True
    PORTAL_CLINIC_INVITE_EXPIRE_HOURS: int = 72
    PORTAL_CLINIC_TRUSTED_SESSION_HOURS: int = 8
    PORTAL_CLINIC_REFRESH_COOKIE_NAME: str = "fortcordis_portal_clinic_refresh"
    PORTAL_CLINIC_REFRESH_COOKIE_PATH: str = "/"
    PORTAL_CLINIC_REFRESH_COOKIE_SAMESITE: str = "lax"
    PORTAL_CLINIC_REFRESH_COOKIE_SECURE: bool = False
    PORTAL_CLINIC_REFRESH_COOKIE_DOMAIN: Optional[str] = None
    PORTAL_CLINIC_EMAIL_CHALLENGE_EXPIRE_MINUTES: int = 15
    PORTAL_CLINIC_MFA_EXPIRE_MINUTES: int = 10
    PORTAL_CLINIC_PASSWORD_RESET_EXPIRE_MINUTES: int = 30
    PORTAL_CLINIC_MAX_AUTH_ATTEMPTS: int = 5
    PORTAL_CLINIC_RELEASE_SLA_HOURS: int = 48
    # Link direto por exame no aviso de WhatsApp da clinica. Desligada, o aviso sai
    # exatamente como antes (modelo portalReportAvailable, sem link).
    PORTAL_CLINIC_EXAM_LINK_ENABLED: bool = False
    # Base publica do link (ex.: https://app.fortcordis.com.br). Vazia usa a
    # base_url da requisicao.
    PORTAL_CLINIC_EXAM_LINK_BASE_URL: str = ""
    # Computador da recepcao conectado em modo laudos, sem senha. Desligada, so a
    # CRIACAO de confianca e cortada - as existentes continuam valendo.
    PORTAL_CLINIC_DEVICE_TRUST_ENABLED: bool = False
    # Dias SEM USO ate a confianca cair. Cada acesso empurra o prazo para frente.
    # 30 dias: definido pelo usuario em 18/09/2026. Clinica que encaminha exame
    # com alguma regularidade renova sozinha; quem sumiu por um mes inteiro
    # perde o acesso da maquina, que e o comportamento desejado.
    PORTAL_CLINIC_DEVICE_TRUST_INACTIVITY_DAYS: int = 30
    # Cookie proprio: nao pode colidir com PORTAL_CLINIC_REFRESH_COOKIE_NAME, que
    # e de um gerente logado com senha, possivelmente na mesma maquina.
    PORTAL_CLINIC_DEVICE_TRUST_COOKIE_NAME: str = "fortcordis_portal_clinic_device"
    PORTAL_PARTNER_INVITE_AUTH_ENABLED: bool = True
    PORTAL_PARTNER_PASSWORD_LOGIN_ENABLED: bool = True
    PORTAL_PARTNER_REFRESH_COOKIE_NAME: str = "fortcordis_portal_partner_refresh"
    PORTAL_DEBUG_EXPOSE_CODE: bool = False
    PORTAL_EMAIL_SMTP_HOST: str = ""
    PORTAL_EMAIL_SMTP_PORT: int = 587
    PORTAL_EMAIL_SMTP_USERNAME: str = ""
    PORTAL_EMAIL_SMTP_PASSWORD: str = ""
    PORTAL_EMAIL_SMTP_USE_TLS: bool = True
    PORTAL_EMAIL_SMTP_USE_SSL: bool = False
    PORTAL_EMAIL_FROM_EMAIL: str = "portal@fortcordis.local"
    PORTAL_EMAIL_FROM_NAME: str = "Portal Fort Cordis"
    PORTAL_EMAIL_SUBJECT: str = "Seu codigo de acesso - Portal Fort Cordis"
    PORTAL_WHATSAPP_ENABLED: bool = False
    PORTAL_WHATSAPP_WEBHOOK_URL: str = ""
    PORTAL_WHATSAPP_WEBHOOK_METHOD: str = "POST"
    PORTAL_WHATSAPP_WEBHOOK_AUTH_HEADER: str = "Authorization"
    PORTAL_WHATSAPP_WEBHOOK_AUTH_TOKEN: str = ""
    PORTAL_WHATSAPP_WEBHOOK_TIMEOUT_SECONDS: int = 10
    PORTAL_REMOTE_STORAGE_AUTH_HEADER: str = "Authorization"
    PORTAL_REMOTE_STORAGE_AUTH_TOKEN: str = ""
    PORTAL_REMOTE_STORAGE_TIMEOUT_SECONDS: int = 20
    # Hosts (dominio exato, separados por virgula) para os quais
    # PORTAL_REMOTE_STORAGE_AUTH_TOKEN pode ser enviado. Anexos com URL livre
    # (link externo colado pelo usuario) nunca devem receber esse header -
    # so a URL do storage remoto legitimo, configurada aqui, recebe o token.
    PORTAL_REMOTE_STORAGE_TRUSTED_HOSTS: str = ""

    class Config:
        env_file = str(ENV_FILE_PATH)
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
