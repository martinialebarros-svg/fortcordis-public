from app.models.user import User
from app.models.papel import Papel
from app.models.agendamento import Agendamento
from app.models.whatsapp_agenda_resposta import WhatsappAgendaResposta
from app.models.paciente import Paciente
from app.models.paciente_mesclagem import PacienteMesclagem
from app.models.tutor import Tutor
from app.models.tutor_mesclagem import TutorMesclagem
from app.models.tutor_mesclagem_reversao import TutorMesclagemReversao
from app.models.tutor_rotina import TutorContato, TutorOrigem, TutorIdentificacaoEvento, TutorDuplicidadeDescarte, TutorOperacao
from app.models.clinica import Clinica
from app.models.servico import Servico
from app.models.laudo import Laudo, Exame
from app.models.laudo_editor_draft import LaudoEditorDraft, LaudoEditorDraftRequest
from app.models.catalogo_exame import CatalogoExame, PainelExame, PainelExameItem
from app.models.financeiro import (
    Transacao,
    BandeiraCartao,
    FormaPagamentoConfiguracao,
    OrdemServicoPagamento,
    CreditoFinanceiro,
    ContaPagar,
    ContaReceber,
    CustoFrota,
    VeiculoFrota,
    TelemetriaFrotaMensal,
    ConfigRateioFrota,
)
from app.models.frase import FraseQualitativa, FraseQualitativaHistorico
from app.models.imagem_laudo import ImagemLaudo, ImagemTemporaria
from app.models.laudo_pdf_job import LaudoPdfJob
from app.models.xml_import_job import XmlImportJob
from app.models.eco_study_import_job import EcoStudyImportJob
from app.models.tabela_preco import TabelaPreco, PrecoServico, PrecoServicoClinica
from app.models.ordem_servico import OrdemServico
from app.models.referencia_eco import ReferenciaEco
from app.models.papel_permissao import PapelPermissao
from app.models.atendimento_clinico import (
    AnexoAtendimento,
    AlertaClinico,
    AtendimentoClinico,
    DocumentoAtendimento,
    DocumentoAtendimentoTemplate,
    EvolucaoClinica,
    Medicamento,
    PrescricaoClinica,
    PrescricaoItem,
    PrescricaoItemAjuste,
    UploadDedupeCleanupRun,
    UploadDedupeMetrica,
)
from app.models.auditoria_evento import AuditoriaEvento
from app.models.clinica_deslocamento import ClinicaDeslocamento
from app.models.cep_bairro_override import CepBairroOverride
from app.models.frase_atendimento_clinico import FraseAtendimentoClinico
from app.models.push_subscription import PushSubscription
from app.models.push_scheduled_notification import PushScheduledNotification
from app.models.google_maps_usage_metrica import GoogleMapsUsageMetrica
from app.models.google_maps_cost_control import GoogleMapsCostConfig, GoogleMapsCostAction, GoogleMapsCostEvent
from app.models.runtime_frontend_performance_metric import RuntimeFrontendPerformanceMetric
from app.models.runtime_http_latency_metric import RuntimeHttpLatencyMetric
from app.models.portal_access import PortalAccessChallenge
from app.models.portal_clinic_exam_link import PortalClinicExamLink
from app.models.portal_clinic_trusted_device import PortalClinicTrustedDevice
from app.models.portal_clinic_auth import (
    PortalAuthChallenge,
    PortalClinicAccount,
    PortalClinicInvite,
    PortalClinicSession,
    PortalPasswordResetToken,
)
from app.models.portal_partner import PortalPartnerProfile, PortalPartnerReleaseTarget
from app.models.portal_partner_auth import (
    PortalPartnerAccount,
    PortalPartnerAuthChallenge,
    PortalPartnerInvite,
    PortalPartnerPasswordResetToken,
    PortalPartnerSession,
)
from app.models.assistente_ia import (
    AssistenteIAAcaoPendente,
    AssistenteIAAprendizado,
    AssistenteIAConhecimentoDocumento,
    AssistenteIAConhecimentoTrecho,
    AssistenteIAConversa,
    AssistenteIAExecucao,
    AssistenteIAFeedback,
    AssistenteIAMemoria,
    AssistenteIAMemoriaVersao,
    AssistenteIAMensagem,
    AssistenteIAMissao,
    AssistenteIARegressaoCaso,
    AssistenteIARascunhoClinico,
)
from app.models.agenda_bloqueio import AgendaBloqueio
from app.models.ai_echo import (
    AIEchoApplication,
    AIEchoAudioAsset,
    AIEchoClinicalWarning,
    AIEchoFeedback,
    AIEchoFieldSuggestion,
    AIEchoMeasurement,
    AIEchoPhrasePreference,
    AIEchoSession,
    AIEchoTranscript,
    AIEchoVocabulary,
)
from app.models.atendimento_assistente_lote import AtendimentoAssistenteLote, AtendimentoAssistenteLoteArquivo
