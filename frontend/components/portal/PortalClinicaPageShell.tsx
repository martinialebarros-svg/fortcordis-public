"use client";

import Image from "next/image";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  BadgeCheck,
  Building2,
  ClipboardList,
  Download,
  FileCheck2,
  UserCheck,
} from "lucide-react";

import PortalClinicaWorkspace from "@/components/portal/PortalClinicaWorkspace";
import {
  clearPortalSession,
  loadPortalSession,
  portalSessionIsDeviceTrust,
  PortalRequestError,
  refreshClinicPortalSession,
  resumePortalDeviceSession,
  savePortalSession,
  type PortalClinicAuthResponse,
  type PortalSessionResponse,
} from "@/lib/portal-api";

const partnershipBenefits = [
  {
    title: "Parceria que aproxima",
    description:
      "A unidade parceira mantém acesso direto às informações dos pets atendidos em conjunto com a Fort Cordis.",
    icon: UserCheck,
  },
  {
    title: "Casos bem organizados",
    description:
      "Resultados e documentos ficam reunidos por unidade, paciente e atendimento para facilitar a rotina da equipe.",
    icon: Building2,
  },
  {
    title: "Consulta mais prática",
    description:
      "Filtros e buscas ajudam a localizar exames com agilidade e a dar sequência ao cuidado na clínica.",
    icon: ClipboardList,
  },
  {
    title: "Acesso confiável",
    description:
      "Cada profissional consulta apenas os casos da unidade autorizada, com proteção adequada para dados clínicos.",
    icon: FileCheck2,
  },
] as const;

function normalizeClinicSession(payload: PortalClinicAuthResponse): PortalSessionResponse {
  if (!payload.access_token || !payload.expires_at || payload.actor_type !== "clinica" || !payload.actor_id) {
    throw new Error("Sessão da clínica retornou incompleta.");
  }

  return {
    access_token: payload.access_token,
    token_type: payload.token_type || "bearer",
    expires_at: payload.expires_at,
    actor_type: "clinica",
    actor_id: payload.actor_id,
    clinica_id: payload.clinica_id ?? payload.actor_id,
    paciente_id: null,
    account_id: payload.account_id ?? null,
    auth_method: payload.auth_method ?? null,
    trusted_session_expires_at: payload.trusted_session_expires_at ?? null,
    scope: payload.scope || [],
    message: payload.message ?? null,
  };
}

function LoadingState() {
  return (
    <main className="fc-public-portal fc-public-portal-clinic">
      <section className="fc-public-portal-hero">
        <div className="fc-public-portal-inner">
          <div className="flex min-h-[360px] items-center justify-center rounded-lg border border-white/10 bg-white/5 px-6 text-center text-sm font-semibold text-white/80 backdrop-blur-sm">
            Validando o acesso da clínica neste dispositivo...
          </div>
        </div>
      </section>
    </main>
  );
}

function PublicLanding({
  onSessionChange,
  onVoltarParaLaudos,
}: {
  onSessionChange: (session: PortalSessionResponse | null) => void;
  onVoltarParaLaudos?: () => void;
}) {
  return (
    <main className="fc-public-portal fc-public-portal-clinic">
      <section className="fc-public-portal-hero">
        <div className="fc-public-portal-inner">
          <Link
            href="/"
            className="fc-public-portal-back"
          >
            <ArrowLeft className="h-4 w-4" />
            Portal Fort Cordis
          </Link>

          {/* So aparece quando o gestor veio do modo laudos: a confianca do
              computador continua de pe, entao da para desistir do login sem que a
              recepcao perca o acesso. */}
          {onVoltarParaLaudos ? (
            <button type="button" onClick={onVoltarParaLaudos} className="fc-public-portal-back">
              <ArrowLeft className="h-4 w-4" />
              Voltar para os laudos da unidade
            </button>
          ) : null}

          <div className="fc-public-portal-hero-grid">
            <div className="fc-public-portal-copy">
              <div className="fc-public-portal-brand">
                <Image src="/brand/fortcordis-logo-oficial.png" alt="Fort Cordis" width={52} height={52} priority />
                <span><strong>FORT CORDIS</strong><small>Cardiologia Veterinária</small></span>
              </div>
              <p className="fc-public-portal-kicker">
                Clínicas parceiras
              </p>
              <h1>
                Uma parceria que dá continuidade ao cuidado de cada pet.
              </h1>
              <p className="fc-public-portal-lead">
                O portal aproxima a clínica parceira da Fort Cordis, reúne exames e informações
                dos pets atendidos na unidade e torna a rotina da equipe mais ágil, organizada e
                bem acompanhada.
              </p>
              <div className="fc-public-portal-actions">
                <a
                  href="#parceria"
                  className="fc-public-portal-primary"
                >
                  <Building2 className="h-5 w-5" />
                  Como funciona
                </a>
                <a
                  href="#resultados"
                  className="fc-public-portal-secondary"
                >
                  <Download className="h-5 w-5" />
                  Consultar resultados
                </a>
              </div>
            </div>

            <PortalClinicaWorkspace mode="embedded" onSessionChange={onSessionChange} />
          </div>
        </div>
      </section>

      <section id="parceria" className="fc-public-portal-section fc-scroll-section">
        <div className="fc-public-portal-inner">
          <div className="fc-public-portal-section-heading">
            <p className="fc-public-portal-eyebrow">
              Experiência da clínica parceira
            </p>
            <h2>
              Informação que flui para o atendimento continuar.
            </h2>
            <p className="mt-4 text-sm leading-6 text-slate-600">
              O portal organiza a troca de informações entre a Fort Cordis e a unidade parceira,
              reduz etapas na consulta de exames e preserva o contexto de cada caso.
            </p>
          </div>

          <div className="fc-public-portal-feature-grid fc-public-portal-feature-grid-four">
            {partnershipBenefits.map(({ title, description, icon: Icon }) => (
              <article key={title} className="fc-public-portal-feature">
                <Icon className="h-7 w-7 text-rose-700" />
                <h3 className="mt-5 text-lg font-bold text-slate-950">{title}</h3>
                <p className="mt-3 text-sm leading-6 text-slate-600">{description}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section id="resultados" className="fc-public-portal-band fc-public-portal-band-light fc-scroll-section">
        <div className="fc-public-portal-band-grid">
          <div>
            <p className="fc-public-portal-eyebrow">
              Resultados e documentos
            </p>
            <h2 className="mt-3 text-3xl font-bold text-slate-950 sm:text-4xl">
              O que a equipe precisa, organizado em um só lugar.
            </h2>
            <p className="mt-4 text-sm leading-6 text-slate-600">
              A clínica encontra os exames dos pets atendidos na unidade, consulta documentos e
              mantém as informações importantes disponíveis para conduzir os próximos passos.
            </p>
          </div>

          <div className="space-y-3">
            {[
              "Busca por protocolo, pet ou tutor somente dentro da unidade autorizada.",
              "Visão panorâmica com filtros por pet, tutor, espécie, tipo de exame e período.",
              "Laudos e documentos disponíveis no portal, com acesso protegido para a equipe responsável.",
            ].map((item) => (
              <div key={item} className="flex gap-3 rounded-lg border border-slate-200 bg-white p-4">
                <FileCheck2 className="mt-0.5 h-5 w-5 shrink-0 text-teal-700" />
                <p className="text-sm leading-6 text-slate-600">{item}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="fc-public-portal-section fc-public-portal-final fc-scroll-section">
        <div className="fc-public-portal-callout">
          <BadgeCheck className="h-8 w-8 text-amber-700" />
          <h2 className="mt-5 text-2xl font-bold text-slate-950">
            Quando a informação flui, o cuidado continua.
          </h2>
          <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-600">
            A integração reduz a busca por documentos, aproxima as equipes e ajuda a clínica
            parceira a orientar o tutor com mais contexto. Cada unidade acessa somente os casos sob
            sua responsabilidade.
          </p>
        </div>
      </section>
    </main>
  );
}

export default function PortalClinicaPageShell() {
  const [bootstrapping, setBootstrapping] = useState(true);
  const [session, setSession] = useState<PortalSessionResponse | null>(null);
  const [pedindoSenha, setPedindoSenha] = useState(false);

  // Lidos dentro de `handleSessionChange`, que precisa ficar com identidade
  // estavel: o workspace guarda esse callback nas dependencias de um efeito, e
  // trocar a funcao a cada render o faria reemitir a sessao sem necessidade.
  const sessionRef = useRef<PortalSessionResponse | null>(null);
  const pedindoSenhaRef = useRef(false);

  useEffect(() => {
    sessionRef.current = session;
  }, [session]);

  useEffect(() => {
    pedindoSenhaRef.current = pedindoSenha;
  }, [pedindoSenha]);

  const retomarDispositivo = useCallback(async () => {
    try {
      const dispositivo = await resumePortalDeviceSession();
      savePortalSession(dispositivo);
      setSession(dispositivo);
      return true;
    } catch {
      clearPortalSession("clinica");
      return false;
    }
  }, []);

  const handleSessionChange = useCallback(
    (nextSession: PortalSessionResponse | null) => {
      if (nextSession) {
        setSession(nextSession);
        setPedindoSenha(false);
        return;
      }

      setSession(null);

      // Uma sessao acabou de terminar (logout do gestor). Antes de mandar a
      // recepcao para a pagina publica, ve se o computador continua confiavel:
      // senao a secretaria encontra a maquina pedindo uma senha que ela nao tem
      // - o problema que esta entrega existe para evitar - e so um F5 desfaria.
      //
      // Duas guardas. Se o gestor PEDIU o formulario (RF-019), a volta e decisao
      // dele, pelo "Voltar para os laudos da unidade". E se nao havia sessao, o
      // null veio do cartao de login da pagina publica terminando o proprio
      // bootstrap - nao ha logout nenhum para reagir.
      if (pedindoSenhaRef.current || !sessionRef.current) {
        return;
      }

      void retomarDispositivo();
    },
    [retomarDispositivo],
  );

  /**
   * Abre o formulario de senha sem encerrar a confianca do computador (RF-019).
   *
   * So limpa a sessao guardada: o cookie do dispositivo continua no navegador.
   * Por isso o gestor pode desistir - por "Voltar para os laudos da unidade" ou
   * simplesmente recarregando - que a recepcao volta sozinha. Antes disso a unica
   * saida do modo laudos era "Sair deste computador", que revoga a confianca e
   * obrigava a reconectar pelo link seguinte.
   */
  const pedirLoginPorSenha = useCallback(() => {
    clearPortalSession("clinica");
    setSession(null);
    setPedindoSenha(true);
  }, []);

  const voltarParaOsLaudos = useCallback(async () => {
    // Confianca pode ter caido nesse meio tempo; ai fica no formulario de senha,
    // que e a unica porta que sobrou.
    await retomarDispositivo();
    setPedindoSenha(false);
  }, [retomarDispositivo]);

  useEffect(() => {
    let cancelled = false;

    function aplicar(nextSession: PortalSessionResponse | null) {
      if (cancelled) {
        return;
      }
      setSession(nextSession);
      setBootstrapping(false);
    }

    async function hydrate() {
      const storedSession = loadPortalSession("clinica");
      let dispositivoRecusado = false;

      if (storedSession) {
        if (!portalSessionIsDeviceTrust(storedSession)) {
          aplicar(storedSession);
          return;
        }

        // Modo laudos: o token guardado sozinho não prova mais nada. Ele vive até
        // meia hora no armazenamento do navegador, então confiar nele faria a
        // revogação só valer quando o token expirasse — e revogar existe
        // justamente para máquina trocada, vendida ou roubada, onde meia hora é
        // tempo demais. Reconfere com o servidor antes de mostrar qualquer laudo.
        try {
          const revalidada = await resumePortalDeviceSession();
          savePortalSession(revalidada);
          aplicar(revalidada);
          return;
        } catch (erro) {
          if (!(erro instanceof PortalRequestError)) {
            // Sem resposta do servidor (rede fora, por exemplo) não é recusa.
            // Derrubar a recepção por causa de uma oscilação seria pior do que o
            // risco que esta revalidação fecha, e a sessão guardada continua
            // dentro do próprio prazo.
            aplicar(storedSession);
            return;
          }
          clearPortalSession("clinica");
          dispositivoRecusado = true;
        }
      }

      try {
        const refreshed = normalizeClinicSession(await refreshClinicPortalSession());
        savePortalSession(refreshed);
        if (!cancelled) {
          setSession(refreshed);
        }
      } catch {
        clearPortalSession("clinica");
        // Sem sessão de senha, tenta o computador confiável da recepção. A ordem
        // importa: o gerente logado na mesma máquina tem precedência, e o modo
        // laudos é o que sobra para quem não tem senha (CB-001).
        if (!dispositivoRecusado) {
          try {
            const dispositivo = await resumePortalDeviceSession();
            savePortalSession(dispositivo);
            if (!cancelled) {
              setSession(dispositivo);
            }
          } catch {
            clearPortalSession("clinica");
          }
        }
      } finally {
        if (!cancelled) {
          setBootstrapping(false);
        }
      }
    }

    void hydrate();

    return () => {
      cancelled = true;
    };
  }, []);

  if (bootstrapping) {
    return <LoadingState />;
  }

  if (session) {
    return (
      <PortalClinicaWorkspace
        mode="standalone"
        initialSession={session}
        onSessionChange={handleSessionChange}
        onPedirLoginPorSenha={pedirLoginPorSenha}
      />
    );
  }

  return (
    <PublicLanding
      onSessionChange={handleSessionChange}
      onVoltarParaLaudos={pedindoSenha ? voltarParaOsLaudos : undefined}
    />
  );
}
