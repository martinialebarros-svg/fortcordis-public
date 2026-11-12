"""
Script completo de setup do banco de dados para FortCordis v2.
Cria todas as tabelas e executa os seeds necessários.
"""
import os
import sys

# Verificar se DATABASE_URL está definido
if not os.environ.get("DATABASE_URL"):
    print("⚠️  ATENÇÃO: DATABASE_URL não está definido!")
    print("Usando SQLite local como fallback: sqlite:///./fortcordis.db")
    os.environ["DATABASE_URL"] = "sqlite:///./fortcordis.db"

from app.db.database import engine, Base, SessionLocal
from app.models import (
    user, papel, agendamento, paciente, tutor, clinica, servico,
    laudo, financeiro, frase, imagem_laudo, tabela_preco, 
    ordem_servico, referencia_eco, configuracao, auditoria_evento,
    clinica_deslocamento, cep_bairro_override, push_subscription, push_scheduled_notification,
    google_maps_usage_metrica, portal_access, portal_partner, portal_partner_auth
)
from app.utils.frases_seed import seed_frases
from migrations.runner import get_deferred_migrations, run_migrations

# Importar todos os modelos para o Base.metadata
MODELS = [
    user.User,
    papel.Papel,
    agendamento.Agendamento,
    paciente.Paciente,
    tutor.Tutor,
    clinica.Clinica,
    servico.Servico,
    laudo.Laudo,
    laudo.Exame,
    financeiro.Transacao,
    financeiro.ContaPagar,
    financeiro.ContaReceber,
    frase.FraseQualitativa,
    frase.FraseQualitativaHistorico,
    imagem_laudo.ImagemLaudo,
    imagem_laudo.ImagemTemporaria,
    tabela_preco.TabelaPreco,
    tabela_preco.PrecoServico,
    ordem_servico.OrdemServico,
    referencia_eco.ReferenciaEco,
    configuracao.Configuracao,
    configuracao.ConfiguracaoUsuario,
    push_subscription.PushSubscription,
    push_scheduled_notification.PushScheduledNotification,
    auditoria_evento.AuditoriaEvento,
    clinica_deslocamento.ClinicaDeslocamento,
    cep_bairro_override.CepBairroOverride,
    google_maps_usage_metrica.GoogleMapsUsageMetrica,
    portal_access.PortalAccessChallenge,
    portal_partner.PortalPartnerProfile,
    portal_partner.PortalPartnerReleaseTarget,
    portal_partner_auth.PortalPartnerInvite,
    portal_partner_auth.PortalPartnerAccount,
    portal_partner_auth.PortalPartnerSession,
    portal_partner_auth.PortalPartnerPasswordResetToken,
    portal_partner_auth.PortalPartnerAuthChallenge,
]

def criar_tabelas():
    """Cria todas as tabelas no banco de dados."""
    print("\n🔧 Criando tabelas...")
    try:
        Base.metadata.create_all(bind=engine)
        print("✅ Tabelas criadas com sucesso!")
        return True
    except Exception as e:
        print(f"❌ Erro ao criar tabelas: {e}")
        return False

def executar_migracoes():
    """Executa migracoes versionadas para corrigir drift de schema.

    Migracoes adiadas por pendencia de conciliacao de dados nao interrompem o
    deploy: o runner segue aplicando as demais e a versao adiada volta a ser
    tentada no proximo deploy. Elas continuam aparecendo como pendentes em
    `get_migration_status()`, que alimenta o aviso de runtime.
    """
    print("\n🧱 Executando migracoes versionadas...")
    try:
        run_migrations()
    except Exception as e:
        print(f"❌ Erro ao executar migracoes: {e}")
        return False

    deferred = get_deferred_migrations()
    if deferred:
        print("⚠️  Migracoes adiadas por pendencia de dados (schema segue incompleto):")
        for version, motivo in deferred:
            print(f"    - {version}: {motivo}")
        print("    Concilie os registros citados e rode o deploy novamente.")
        return True

    print("✅ Migracoes executadas com sucesso!")
    return True

def criar_tabelas_preco():
    """Cria as tabelas de preço padrão."""
    from app.models.tabela_preco import TabelaPreco
    
    db = SessionLocal()
    try:
        print("\n💰 Configurando tabelas de preço...")
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
                print(f"  ✅ Tabela '{tabela_data['nome']}' criada")
            else:
                print(f"  ⏭️  Tabela '{tabela_data['nome']}' já existe")
        
        db.commit()
        print("✅ Tabelas de preço configuradas!")
    except Exception as e:
        print(f"❌ Erro ao criar tabelas de preço: {e}")
        db.rollback()
    finally:
        db.close()

def seed_frases_qualitativas():
    """Executa o seed de frases qualitativas."""
    db = SessionLocal()
    try:
        print("\n📝 Adicionando frases qualitativas...")
        seed_frases(db)
        print("✅ Frases qualitativas configuradas!")
    except Exception as e:
        print(f"❌ Erro ao adicionar frases: {e}")
        db.rollback()
    finally:
        db.close()

def verificar_tabelas():
    """Verifica se todas as tabelas existem."""
    from sqlalchemy import inspect
    
    print("\n🔍 Verificando tabelas...")
    inspector = inspect(engine)
    tabelas_existentes = inspector.get_table_names()
    
    tabelas_esperadas = [
        "usuarios", "papeis", "usuario_papel",
        "agendamentos", "pacientes", "tutores", "clinicas", "servicos",
        "laudos", "exames", "transacoes", "contas_pagar", "contas_receber",
        "frases_qualitativas", "frases_qualitativas_historico",
        "imagens_laudo", "imagens_temporarias",
        "tabelas_preco", "precos_servicos", "ordens_servico",
        "referencias_eco", "configuracoes", "configuracoes_usuario"
        , "auditoria_eventos", "clinica_deslocamentos", "cep_bairro_overrides",
        "push_subscriptions", "push_scheduled_notifications", "google_maps_usage_metricas"
        , "portal_access_challenges", "portal_partner_profiles", "portal_partner_release_targets"
        , "portal_partner_invites", "portal_partner_accounts", "portal_partner_sessions"
        , "portal_partner_password_reset_tokens", "portal_partner_auth_challenges"
    ]
    
    todas_ok = True
    for tabela in tabelas_esperadas:
        if tabela in tabelas_existentes:
            print(f"  ✅ {tabela}")
        else:
            print(f"  ❌ {tabela} - NÃO ENCONTRADA")
            todas_ok = False
    
    return todas_ok

def verificar_dados():
    """Verifica se há dados básicos nas tabelas."""
    db = SessionLocal()
    try:
        print("\n📊 Verificando dados...")
        
        # Contar registros em tabelas importantes
        from app.models.frase import FraseQualitativa
        from app.models.tabela_preco import TabelaPreco
        from app.models.clinica import Clinica
        
        frases_count = db.query(FraseQualitativa).count()
        tabelas_count = db.query(TabelaPreco).count()
        clinicas_count = db.query(Clinica).count()
        
        print(f"  Frases qualitativas: {frases_count}")
        print(f"  Tabelas de preço: {tabelas_count}")
        print(f"  Clínicas: {clinicas_count}")
        
        if frases_count == 0:
            print("  ⚠️  Nenhuma frase qualitativa encontrada!")
        if tabelas_count == 0:
            print("  ⚠️  Nenhuma tabela de preço encontrada!")
            
    except Exception as e:
        print(f"❌ Erro ao verificar dados: {e}")
    finally:
        db.close()

def main():
    """Função principal de setup."""
    print("=" * 60)
    print("🚀 SETUP DO BANCO DE DADOS - FORTCORDIS v2")
    print("=" * 60)
    print(f"\n📡 Database URL: {os.environ.get('DATABASE_URL', 'Não definido')}")
    
    # 1. Criar tabelas
    if not criar_tabelas():
        print("\n❌ Falha ao criar tabelas. Abortando.")
        sys.exit(1)
    
    # 1.1 Executar migracoes versionadas
    if not executar_migracoes():
        print("\n❌ Falha ao executar migracoes. Abortando.")
        sys.exit(1)
    
    # 2. Verificar tabelas
    if not verificar_tabelas():
        print("\n⚠️  Algumas tabelas não foram criadas corretamente.")
    
    # 3. Criar dados iniciais
    criar_tabelas_preco()
    seed_frases_qualitativas()
    
    # 4. Verificar dados
    verificar_dados()
    
    print("\n" + "=" * 60)
    print("✅ SETUP CONCLUÍDO!")
    print("=" * 60)

if __name__ == "__main__":
    main()
