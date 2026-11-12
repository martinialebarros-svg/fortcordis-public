#!/bin/bash

# =============================================================================
# SCRIPT DE DEPLOY - FortCordis v2
# =============================================================================
# Este script deve estar na VPS em: /var/www/fortcordis-v2/deploy.sh
# Uso: ./deploy.sh [ambiente]
# Exemplo: ./deploy.sh production
# =============================================================================

set -e  # Para execução se houver erro

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configurações
PROJECT_DIR="/var/www/fortcordis-v2"
BACKUP_DIR="$PROJECT_DIR/backups"
ENVIRONMENT="${1:-main}"
LOG_FILE="$PROJECT_DIR/deploy.log"

# Funções de log
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1" | tee -a $LOG_FILE
}

log_success() {
    echo -e "${GREEN}[SUCESSO]${NC} $1" | tee -a $LOG_FILE
}

log_warning() {
    echo -e "${YELLOW}[AVISO]${NC} $1" | tee -a $LOG_FILE
}

log_error() {
    echo -e "${RED}[ERRO]${NC} $1" | tee -a $LOG_FILE
}

# =============================================================================
# INÍCIO DO DEPLOY
# =============================================================================

echo ""
echo "========================================"
echo "   🚀 DEPLOY FORTCORDIS v2"
echo "   Ambiente: $ENVIRONMENT"
echo "   $(date)"
echo "========================================"
echo ""

cd $PROJECT_DIR

# 1. BACKUP
log_info "📦 Criando backup..."
mkdir -p $BACKUP_DIR
BACKUP_NAME="backup_$(date +%Y%m%d_%H%M%S).tar.gz"
tar -czf $BACKUP_DIR/$BACKUP_NAME backend frontend --exclude='backend/venv' --exclude='frontend/node_modules' 2>/dev/null || true
log_success "Backup criado: $BACKUP_NAME"

# 2. ATUALIZAR CÓDIGO
log_info "⬇️  Atualizando código do GitHub..."
git fetch origin
git reset --hard origin/$ENVIRONMENT
git clean -fd
log_success "Código atualizado"

# 3. DEPLOY BACKEND
log_info "🐍 Deploy Backend..."
cd $PROJECT_DIR/backend

# Ativar ambiente virtual ou criar
if [ -d "venv" ]; then
    source venv/bin/activate
else
    log_info "Criando ambiente virtual..."
    python3 -m venv venv
    source venv/bin/activate
fi

# Instalar dependências
log_info "Instalando dependências Python..."
pip install --upgrade pip
pip install -r requirements.txt

# Aplicar migrações (se usar Alembic/SQLAlchemy)
if [ -f "alembic.ini" ]; then
    log_info "Aplicando migrações..."
    alembic upgrade head || log_warning "Migração falhou ou não configurada"
fi

# Restart do serviço
log_info "Reiniciando serviço backend..."
sudo systemctl restart fortcordis-backend 2>/dev/null || log_warning "Serviço 'fortcordis-backend' não encontrado. Reinicie manualmente."

cd $PROJECT_DIR

# 4. DEPLOY FRONTEND
log_info "⚛️  Deploy Frontend..."
cd $PROJECT_DIR/frontend

# Instalar dependências
log_info "Instalando dependências Node..."
npm ci --production=false

# Build
log_info "Compilando frontend..."
npm run build

# Restart do serviço
log_info "Reiniciando serviço frontend..."
sudo systemctl restart fortcordis-frontend 2>/dev/null || log_warning "Serviço 'fortcordis-frontend' não encontrado. Reinicie manualmente."

cd $PROJECT_DIR

# 5. LIMPEZA
log_info "🧹 Limpando arquivos antigos..."
# Manter apenas os 5 backups mais recentes
ls -t $BACKUP_DIR/backup_*.tar.gz 2>/dev/null | tail -n +6 | xargs -r rm --

# =============================================================================
# FIM DO DEPLOY
# =============================================================================

echo ""
echo "========================================"
log_success "✅ DEPLOY CONCLUÍDO COM SUCESSO!"
echo "   $(date)"
echo "========================================"
echo ""

# Verificar status dos serviços
echo "📊 Status dos serviços:"
sudo systemctl status fortcordis-backend --no-pager 2>/dev/null || echo "   Backend: status não disponível"
sudo systemctl status fortcordis-frontend --no-pager 2>/dev/null || echo "   Frontend: status não disponível"
