"""Script para criar tabelas de negócio (tabelas de preço e ordens de serviço)"""
from app.db.database import engine
from app.models.tabela_preco import TabelaPreco, PrecoServico
from app.models.ordem_servico import OrdemServico

print("Criando tabelas de negócio...")

# Criar tabelas
TabelaPreco.__table__.create(engine, checkfirst=True)
PrecoServico.__table__.create(engine, checkfirst=True)
OrdemServico.__table__.create(engine, checkfirst=True)

print("[OK] Tabelas criadas!")
print("- tabelas_preco")
print("- precos_servicos")
print("- ordens_servico")

# Criar tabelas de preço padrão
from app.db.database import SessionLocal

db = SessionLocal()

tabelas_padrao = [
    {"id": 1, "nome": "Clínicas Fortaleza", "descricao": "Tabela para clínicas na cidade de Fortaleza"},
    {"id": 2, "nome": "Região Metropolitana", "descricao": "Tabela para clínicas na região metropolitana de Fortaleza"},
    {"id": 3, "nome": "Atendimento Domiciliar", "descricao": "Tabela para atendimentos domiciliares"},
]

for tabela_data in tabelas_padrao:
    existing = db.query(TabelaPreco).filter(TabelaPreco.id == tabela_data["id"]).first()
    if not existing:
        tabela = TabelaPreco(**tabela_data, ativo=1)
        db.add(tabela)
        print(f"[OK] Tabela '{tabela_data['nome']}' criada")
    else:
        print(f"[SKIP] Tabela '{tabela_data['nome']}' já existe")

db.commit()
db.close()

print("\n[OK] Setup completo!")
