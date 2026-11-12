"""Script para popular o banco com dados de teste"""
import os
from app.db.database import SessionLocal, engine, Base
from app.models.paciente import Paciente
from app.models.clinica import Clinica
from app.models.servico import Servico
from app.models.tutor import Tutor
from app.models.user import User
from app.models.papel import Papel, usuario_papel
from app.models.agendamento import Agendamento
from datetime import datetime, timedelta
from passlib.context import CryptContext
from sqlalchemy import text

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def seed():
    db = SessionLocal()
    
    try:
        # Criar papéis
        admin_papel = db.query(Papel).filter(Papel.nome == "admin").first()
        if not admin_papel:
            admin_papel = Papel(nome="admin", descricao="Administrador do sistema")
            db.add(admin_papel)
            
        recep_papel = db.query(Papel).filter(Papel.nome == "recepcao").first()
        if not recep_papel:
            recep_papel = Papel(nome="recepcao", descricao="Recepção")
            db.add(recep_papel)
        
        vet_papel = db.query(Papel).filter(Papel.nome == "veterinario").first()
        if not vet_papel:
            vet_papel = Papel(nome="veterinario", descricao="Veterinário")
            db.add(vet_papel)
        
        db.commit()
        
        # Criar usuário admin se não existir
        admin = db.query(User).filter(User.email == "admin@fortcordis.com").first()
        if not admin:
            admin = User(
                email="admin@fortcordis.com",
                nome="Administrador",
                senha_hash=pwd_context.hash(os.environ["SEED_ADMIN_PASSWORD"]),
                ativo=1
            )
            db.add(admin)
            db.commit()
            db.refresh(admin)
        
        # Associar papel admin ao usuário
        result = db.execute(
            text("SELECT 1 FROM usuario_papel WHERE usuario_id = :uid AND papel_id = :pid"),
            {"uid": admin.id, "pid": admin_papel.id}
        ).fetchone()
        if not result:
            db.execute(
                text("INSERT INTO usuario_papel (usuario_id, papel_id) VALUES (:uid, :pid)"),
                {"uid": admin.id, "pid": admin_papel.id}
            )
            db.commit()
        
        # Criar clínicas
        if db.query(Clinica).count() == 0:
            clinicas = [
                Clinica(nome="Clínica Central", cnpj="12345678000190", telefone="(11) 3333-1111", email="central@fortcordis.com", ativo=True),
                Clinica(nome="Clínica Norte", cnpj="12345678000280", telefone="(11) 3333-2222", email="norte@fortcordis.com", ativo=True),
            ]
            db.add_all(clinicas)
            db.commit()
        
        # Criar serviços
        if db.query(Servico).count() == 0:
            servicos = [
                Servico(nome="Consulta", descricao="Consulta veterinária"),
                Servico(nome="Vacinação", descricao="Aplicação de vacinas"),
                Servico(nome="Exame de sangue", descricao="Coleta e análise"),
                Servico(nome="Cirurgia", descricao="Procedimento cirúrgico"),
                Servico(nome="Banho e tosa", descricao="Higiene e estética"),
            ]
            db.add_all(servicos)
            db.commit()
        
        # Criar tutores
        if db.query(Tutor).count() == 0:
            tutores = [
                Tutor(nome="João Silva", telefone="(11) 99999-1111", whatsapp="(11) 99999-1111", email="joao@email.com", ativo=1),
                Tutor(nome="Maria Santos", telefone="(11) 99999-2222", whatsapp="(11) 99999-2222", email="maria@email.com", ativo=1),
                Tutor(nome="Pedro Oliveira", telefone="(11) 99999-3333", whatsapp="(11) 99999-3333", email="pedro@email.com", ativo=1),
            ]
            db.add_all(tutores)
            db.commit()
        
        # Criar pacientes
        if db.query(Paciente).count() == 0:
            tutores = db.query(Tutor).all()
            pacientes = [
                Paciente(nome="Rex", tutor_id=tutores[0].id, especie="Cachorro", raca="Labrador", sexo="M", peso_kg=25.5, ativo=1),
                Paciente(nome="Luna", tutor_id=tutores[1].id, especie="Gato", raca="Siamês", sexo="F", peso_kg=4.2, ativo=1),
                Paciente(nome="Thor", tutor_id=tutores[2].id, especie="Cachorro", raca="Bulldog", sexo="M", peso_kg=18.0, ativo=1),
                Paciente(nome="Nina", tutor_id=tutores[0].id, especie="Gato", raca="Persa", sexo="F", peso_kg=3.8, ativo=1),
            ]
            db.add_all(pacientes)
            db.commit()
        
        # Criar agendamentos de exemplo
        if db.query(Agendamento).count() == 0:
            clinicas = db.query(Clinica).all()
            pacientes = db.query(Paciente).all()
            servicos = db.query(Servico).all()
            
            hoje = datetime.now()
            agendamentos = [
                Agendamento(
                    paciente_id=pacientes[0].id,
                    clinica_id=clinicas[0].id,
                    servico_id=servicos[0].id,
                    inicio=hoje.replace(hour=9, minute=0),
                    fim=hoje.replace(hour=9, minute=30),
                    status="Agendado",
                    criado_por_id=admin.id,
                    criado_por_nome=admin.nome
                ),
                Agendamento(
                    paciente_id=pacientes[1].id,
                    clinica_id=clinicas[0].id,
                    servico_id=servicos[1].id,
                    inicio=hoje.replace(hour=10, minute=0),
                    fim=hoje.replace(hour=10, minute=15),
                    status="Confirmado",
                    criado_por_id=admin.id,
                    criado_por_nome=admin.nome
                ),
                Agendamento(
                    paciente_id=pacientes[2].id,
                    clinica_id=clinicas[1].id,
                    servico_id=servicos[4].id,
                    inicio=hoje.replace(hour=14, minute=0),
                    fim=hoje.replace(hour=15, minute=0),
                    status="Agendado",
                    criado_por_id=admin.id,
                    criado_por_nome=admin.nome
                ),
            ]
            db.add_all(agendamentos)
            db.commit()
        
        print("Dados de teste criados com sucesso!")
        print("")
        print("Usuario: admin@fortcordis.com")
        print("")
        print("Resumo:")
        print(f"   - {db.query(Clinica).count()} clinicas")
        print(f"   - {db.query(Servico).count()} servicos")
        print(f"   - {db.query(Tutor).count()} tutores")
        print(f"   - {db.query(Paciente).count()} pacientes")
        print(f"   - {db.query(Agendamento).count()} agendamentos")
        
    except Exception as e:
        print(f"Erro: {e}")
        db.rollback()
        raise
    finally:
        db.close()

if __name__ == "__main__":
    seed()
