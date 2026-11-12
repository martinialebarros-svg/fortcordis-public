#!/usr/bin/env python3
"""
Script de diagnóstico para VPS - FortCordis v2
Execute este script no servidor para identificar problemas.
"""
import os
import sys

print("=" * 70)
print("🔍 DIAGNÓSTICO DO SISTEMA - FORTCORDIS v2")
print("=" * 70)

# 1. Verificar variáveis de ambiente
print("\n📋 1. VARIÁVEIS DE AMBIENTE")
print("-" * 40)

required_env = ['DATABASE_URL', 'SECRET_KEY']
for env in required_env:
    value = os.environ.get(env)
    if value:
        # Ocultar senha
        if 'password' in value.lower() or 'secret' in env.lower():
            display = value[:10] + "..." if len(value) > 10 else "***"
        else:
            display = value
        print(f"  ✅ {env}: {display}")
    else:
        print(f"  ❌ {env}: NÃO DEFINIDO")

# 2. Verificar conexão com banco
print("\n🗄️  2. CONEXÃO COM BANCO DE DADOS")
print("-" * 40)

try:
    from app.db.database import engine
    from sqlalchemy import text
    
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1"))
        print("  ✅ Conexão estabelecida")
        
        # Verificar tipo de banco
        db_url = os.environ.get('DATABASE_URL', 'unknown')
        if 'postgresql' in db_url:
            print("  🐘 Tipo: PostgreSQL")
            version = conn.execute(text("SELECT version()")).fetchone()
            print(f"  📌 Versão: {version[0][:50]}...")
        elif 'sqlite' in db_url:
            print("  🪶 Tipo: SQLite")
            version = conn.execute(text("SELECT sqlite_version()")).fetchone()
            print(f"  📌 Versão: {version[0]}")
        else:
            print(f"  ⚠️  Tipo: {db_url.split(':')[0]}")
            
except Exception as e:
    print(f"  ❌ ERRO: {e}")
    print(f"  💡 Verifique se DATABASE_URL está correto")

# 3. Verificar tabelas
print("\n📊 3. TABELAS DO BANCO")
print("-" * 40)

try:
    from app.db.database import engine
    from sqlalchemy import inspect, text
    
    inspector = inspect(engine)
    tabelas_existentes = inspector.get_table_names()
    
    tabelas_esperadas = [
        ("usuarios", True),
        ("papeis", True),
        ("usuario_papel", True),
        ("agendamentos", True),
        ("pacientes", True),
        ("tutores", False),
        ("clinicas", True),
        ("servicos", False),
        ("laudos", True),
        ("exames", False),
        ("frases_qualitativas", True),
        ("referencias_eco", True),
        ("configuracoes", False),
    ]
    
    faltantes = []
    for tabela, obrigatoria in tabelas_esperadas:
        status = "✅" if tabela in tabelas_existentes else "❌"
        obrig = "*" if obrigatoria else " "
        print(f"  {status} [{obrig}] {tabela}")
        if tabela not in tabelas_existentes and obrigatoria:
            faltantes.append(tabela)
    
    if faltantes:
        print(f"\n  ⚠️  TABELAS OBRIGATÓRIAS FALTANDO: {', '.join(faltantes)}")
        print(f"  💡 Execute: python setup_database.py")
    else:
        print(f"\n  ✅ Todas as tabelas obrigatórias existem")
        
    print(f"\n  📈 Total de tabelas: {len(tabelas_existentes)}")
    
except Exception as e:
    print(f"  ❌ ERRO: {e}")

# 4. Verificar dados
print("\n📝 4. DADOS INICIAIS")
print("-" * 40)

try:
    from app.db.database import SessionLocal
    db = SessionLocal()
    
    try:
        from app.models.frase import FraseQualitativa
        count = db.query(FraseQualitativa).count()
        status = "✅" if count > 0 else "❌"
        print(f"  {status} Frases qualitativas: {count}")
        if count == 0:
            print(f"      💡 Execute: python create_frase_tables.py")
    except Exception as e:
        print(f"  ❌ Frases qualitativas: ERRO - {e}")
    
    try:
        from app.models.tabela_preco import TabelaPreco
        count = db.query(TabelaPreco).count()
        status = "✅" if count > 0 else "⚠️"
        print(f"  {status} Tabelas de preço: {count}")
    except Exception as e:
        print(f"  ❌ Tabelas de preço: ERRO - {e}")
    
    try:
        from app.models.user import User
        count = db.query(User).count()
        status = "✅" if count > 0 else "⚠️"
        print(f"  {status} Usuários: {count}")
    except Exception as e:
        print(f"  ❌ Usuários: ERRO - {e}")
    
    try:
        from app.models.referencia_eco import ReferenciaEco
        count = db.query(ReferenciaEco).count()
        status = "✅" if count > 0 else "⚠️"
        print(f"  {status} Referências eco: {count}")
    except Exception as e:
        print(f"  ❌ Referências eco: ERRO - {e}")
    
    db.close()
    
except Exception as e:
    print(f"  ❌ ERRO: {e}")

# 5. Verificar arquivos
print("\n📁 5. ARQUIVOS E DIRETÓRIOS")
print("-" * 40)

checks = [
    ("backend/app", "Diretório da aplicação"),
    ("backend/venv", "Ambiente virtual"),
    ("backend/.env", "Arquivo de configuração"),
]

for path, desc in checks:
    exists = os.path.exists(path)
    status = "✅" if exists else "❌"
    print(f"  {status} {desc}: {path}")

# 6. Verificar permissões
print("\n🔐 6. PERMISSÕES")
print("-" * 40)

upload_dir = os.environ.get('UPLOAD_DIR', '/opt/fortcordis/uploads')
if os.path.exists(upload_dir):
    print(f"  ✅ Diretório de uploads existe: {upload_dir}")
    if os.access(upload_dir, os.W_OK):
        print(f"  ✅ Diretório tem permissão de escrita")
    else:
        print(f"  ❌ Diretório SEM permissão de escrita")
        print(f"  💡 Execute: sudo chown -R www-data:www-data {upload_dir}")
else:
    print(f"  ⚠️  Diretório de uploads NÃO existe: {upload_dir}")
    print(f"  💡 Execute: sudo mkdir -p {upload_dir}")
    print(f"      sudo chown -R www-data:www-data {upload_dir}")

# 7. Resumo
print("\n" + "=" * 70)
print("📋 RESUMO")
print("=" * 70)

problemas = []

if not os.environ.get('DATABASE_URL'):
    problemas.append("DATABASE_URL não definido")

if not os.environ.get('SECRET_KEY'):
    problemas.append("SECRET_KEY não definido")

if problemas:
    print("❌ PROBLEMAS ENCONTRADOS:")
    for p in problemas:
        print(f"   - {p}")
    print("\n💡 SOLUÇÃO:")
    print("   1. Configure as variáveis de ambiente no arquivo .env")
    print("   2. Ou defina no sistema: export DATABASE_URL=...")
    sys.exit(1)
else:
    print("✅ Configuração básica OK")
    print("\n🚀 Próximos passos:")
    print("   - Se houver tabelas faltando: python setup_database.py")
    print("   - Reiniciar o serviço: sudo systemctl restart fortcordis-backend")
