import os

# Usar variáveis de ambiente ou .env; fallback para SQLite apenas em desenvolvimento local
if not os.environ.get('DATABASE_URL'):
    # Tentar carregar do .env
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_path):
        from dotenv import load_dotenv
        load_dotenv(env_path)
    else:
        # Fallback para SQLite local apenas se não houver .env
        os.environ['DATABASE_URL'] = 'sqlite:///./fortcordis.db'

if not os.environ.get('SECRET_KEY'):
    app_env = (
        os.environ.get("APP_ENV")
        or os.environ.get("ENVIRONMENT")
        or os.environ.get("ENV")
        or "development"
    ).strip().lower()
    if app_env in {"prod", "production"}:
        raise RuntimeError(
            "SECRET_KEY ausente em ambiente de producao. "
            "Defina uma chave forte via variavel de ambiente."
        )
    os.environ['SECRET_KEY'] = 'dev-only-insecure-secret-change-me'

from app.main import app
import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 8001))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
