#!/bin/bash
# =============================================================================
# SCRIPT DE CORREÇÃO PARA VPS - FortCordis v2
# Execute na VPS para corrigir problemas após deploy
# =============================================================================

set -e

echo "=========================================="
echo "🔧 CORREÇÃO DO SISTEMA - FORTCORDIS v2"
echo "=========================================="
echo ""

# Cores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

PROJECT_DIR="/var/www/fortcordis-v2"
BACKEND_DIR="$PROJECT_DIR/backend"

# Verificar se está no diretório correto
if [ ! -d "$BACKEND_DIR" ]; then
    echo -e "${RED}❌ Diretório do projeto não encontrado: $BACKEND_DIR${NC}"
    echo "Execute este script da raiz do projeto"
    exit 1
fi

cd $BACKEND_DIR

echo "📂 Diretório do projeto: $BACKEND_DIR"
echo ""

# 1. Verificar/criar ambiente virtual
echo "🐍 1. Verificando ambiente virtual..."
if [ -d "venv" ]; then
    echo "   ✅ Ambiente virtual existe"
    source venv/bin/activate
else
    echo "   ⚠️  Criando ambiente virtual..."
    python3 -m venv venv
    source venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
fi
echo ""

# 2. Verificar arquivo .env
echo "⚙️  2. Verificando arquivo .env..."
if [ -f ".env" ]; then
    echo "   ✅ Arquivo .env existe"
    # Mostrar DATABASE_URL (ocultando senha)
    DB_URL=$(grep DATABASE_URL .env | cut -d= -f2-)
    if [[ $DB_URL == *"postgresql"* ]]; then
        echo "   🐘 Banco: PostgreSQL"
    elif [[ $DB_URL == *"sqlite"* ]]; then
        echo "   🪶 Banco: SQLite"
    fi
else
    echo -e "${RED}   ❌ Arquivo .env NÃO encontrado!${NC}"
    echo "   Crie o arquivo .env com as configurações do banco"
    exit 1
fi
echo ""

# 3. Executar diagnóstico
echo "🔍 3. Executando diagnóstico..."
python3 diagnostico_vps.py || true
echo ""

# 4. Criar tabelas faltantes
echo "📊 4. Criando tabelas do banco..."
python3 setup_database.py || {
    echo -e "${RED}   ❌ Erro ao criar tabelas${NC}"
    exit 1
}
echo ""

# 5. Verificar diretório de uploads
echo "📁 5. Verificando diretório de uploads..."
UPLOAD_DIR="/opt/fortcordis/uploads"
if [ ! -d "$UPLOAD_DIR" ]; then
    echo "   📂 Criando diretório de uploads..."
    sudo mkdir -p $UPLOAD_DIR
    sudo chown -R www-data:www-data $UPLOAD_DIR
    sudo chmod 755 $UPLOAD_DIR
    echo "   ✅ Diretório criado"
else
    echo "   ✅ Diretório de uploads existe"
fi
echo ""

# 6. Reiniciar serviço
echo "🔄 6. Reiniciando serviço..."
if systemctl is-active --quiet fortcordis-backend; then
    sudo systemctl restart fortcordis-backend
    echo "   ✅ Serviço reiniciado"
else
    echo -e "${YELLOW}   ⚠️  Serviço fortcordis-backend não está rodando${NC}"
    echo "   Inicie manualmente com: sudo systemctl start fortcordis-backend"
fi
echo ""

# 7. Verificar status
echo "📋 7. Status do serviço..."
sleep 2
if systemctl is-active --quiet fortcordis-backend; then
    echo -e "   ${GREEN}✅ Serviço está rodando${NC}"
else
    echo -e "   ${RED}❌ Serviço NÃO está rodando${NC}"
    echo "   Verifique os logs: sudo journalctl -u fortcordis-backend -n 50"
fi
echo ""

echo "=========================================="
echo -e "${GREEN}✅ CORREÇÃO CONCLUÍDA!${NC}"
echo "=========================================="
echo ""
echo "🧪 Teste os endpoints:"
echo "   curl http://localhost:8000/health"
echo "   curl http://localhost:8000/api/v1/clinicas"
echo ""
