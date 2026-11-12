"""
Script de migração para adicionar novas colunas à tabela laudos
"""
import sqlite3
import os

# Caminho do banco de dados
DB_PATH = os.path.join(os.path.dirname(__file__), "fortcordis.db")

def migrar():
    print(f"Migrando banco de dados: {DB_PATH}")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Verificar colunas existentes na tabela laudos
    cursor.execute("PRAGMA table_info(laudos)")
    colunas = {col[1] for col in cursor.fetchall()}
    
    print(f"Colunas existentes: {colunas}")
    
    # Adicionar clinic_id se não existir
    if "clinic_id" not in colunas:
        print("Adicionando coluna clinic_id...")
        cursor.execute("ALTER TABLE laudos ADD COLUMN clinic_id INTEGER")
        print("OK Coluna clinic_id adicionada")
    else:
        print("OK Coluna clinic_id já existe")
    
    # Adicionar data_exame se não existir
    if "data_exame" not in colunas:
        print("Adicionando coluna data_exame...")
        cursor.execute("ALTER TABLE laudos ADD COLUMN data_exame TIMESTAMP")
        print("OK Coluna data_exame adicionada")
    else:
        print("OK Coluna data_exame já existe")
    
    # Adicionar medico_solicitante se não existir
    if "medico_solicitante" not in colunas:
        print("Adicionando coluna medico_solicitante...")
        cursor.execute("ALTER TABLE laudos ADD COLUMN medico_solicitante TEXT")
        print("OK Coluna medico_solicitante adicionada")
    else:
        print("OK Coluna medico_solicitante já existe")
    
    conn.commit()
    conn.close()
    
    print("\nMigração concluída com sucesso!")

if __name__ == "__main__":
    migrar()
