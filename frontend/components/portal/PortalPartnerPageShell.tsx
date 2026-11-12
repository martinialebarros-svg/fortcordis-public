"use client";

import Image from "next/image";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import {
  ArrowLeft,
  BadgeCheck,
  ClipboardList,
  Download,
  FileCheck2,
  HousePlus,
  ShieldCheck,
} from "lucide-react";

import PortalPartnerWorkspace from "@/components/portal/PortalPartnerWorkspace";
import {
  clearPortalSession,
  loadPortalSession,
  refreshPartnerPortalSession,
  savePortalSession,
  type PortalPartnerAuthResponse,
  type PortalSessionResponse,
} from "@/lib/portal-api";

const partnerBenefits = [
  {
    title: "Atuação volante sem perder contexto",
    description:
      "O parceiro acessa os casos liberados pela Fort Cordis mesmo quando atende de forma domiciliar, volante ou por telemedicina.",
    icon: HousePlus,
  },
  {
    title: "Casos organizados por paciente",
    description:
      "Exames, anexos e dados principais ficam reunidos para consulta rápida, sem depender de encaminhamento manual a cada liberação.",
    icon: ClipboardList,
  },
  {
    title: "Busca prática no dia a dia",
    description:
      "Filtros por pet, tutor, espécie, tipo de exame e período ajudam a localizar rapidamente o que precisa ser revisto.",
    icon: Download,
  },
  {
    title: "Acesso protegido e escopado",
    description:
      "Cada parceiro vê somente os casos liberados para o seu perfil, com proteção adequada para dados clínicos sensíveis.",
    icon: ShieldCheck,
  },
] as const;

function normalizePartnerSession(payload: PortalPartnerAuthResponse): PortalSessionResponse {
  if (!payload.access_token || !payload.expires_at || payload.actor_type !== "parceiro" || !payload.actor_id) {
    throw new Error("Sessão do parceiro retornou incompleta.");
  }

  return {
    access_token: payload.access_token,
    token_type: payload.token_type || "bearer",
    expires_at: payload.expires_at,
    actor_type: "parceiro",
    actor_id: payload.actor_id,
    clinica_id: payload.clinica_id ?? null,
    partner_id: payload.partner_id ?? payload.actor_id,
    partner_nome: payload.partner_nome ?? null,
    partner_tipo: payload.partner_tipo ?? null,
    partner_tipo_label: payload.partner_tipo_label ?? null,
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
            Validando o acesso do parceiro neste dispositivo...
          </div>
        </div>
      </section>
    </main>
  );
}

function PublicLanding({ onSessionChange }: { onSessionChange: (session: PortalSessionResponse | null) => void }) {
  return (
    <main className="fc-public-portal fc-public-portal-clinic">
      <section className="fc-public-portal-hero">
        <div className="fc-public-portal-inner">
          <Link href="/" className="fc-public-portal-back">
            <ArrowLeft className="h-4 w-4" />
            Portal Fort Cordis
          </Link>

          <div className="fc-public-portal-hero-grid">
            <div className="fc-public-portal-copy">
              <div className="fc-public-portal-brand">
                <Image src="/brand/fortcordis-logo-oficial.png" alt="Fort Cordis" width={52} height={52} priority />
                <span>
                  <strong>FORT CORDIS</strong>
                  <small>Cardiologia Veterinária</small>
                </span>
              </div>
              <p className="fc-public-portal-kicker">Veterinários parceiros</p>
              <h1>Acesso organizado para quem acompanha o paciente além da clínica fixa.</h1>
              <p className="fc-public-portal-lead">
                Este portal foi pensado para parceiros que atendem de forma volante, domiciliar ou por telemedicina.
                Aqui, os exames liberados pela Fort Cordis ficam reunidos com segurança para a continuidade do cuidado.
              </p>
              <div className="fc-public-portal-actions">
                <a href="#parceria" className="fc-public-portal-primary">
                  <HousePlus className="h-5 w-5" />
                  Como funciona
                </a>
                <a href="#resultados" className="fc-public-portal-secondary">
                  <Download className="h-5 w-5" />
                  Consultar resultados
                </a>
              </div>
            </div>

            <PortalPartnerWorkspace mode="embedded" onSessionChange={onSessionChange} />
          </div>
        </div>
      </section>

      <section id="parceria" className="fc-public-portal-section fc-scroll-section">
        <div className="fc-public-portal-inner">
          <div className="fc-public-portal-section-heading">
            <p className="fc-public-portal-eyebrow">Experiência do parceiro</p>
            <h2>Informação organizada para quem precisa responder com agilidade.</h2>
            <p className="mt-4 text-sm leading-6 text-slate-600">
              O portal reduz a dependência de encaminhamentos manuais, mantém o contexto do paciente e ajuda o parceiro
              a consultar laudos e exames liberados com mais previsibilidade.
            </p>
          </div>

          <div className="fc-public-portal-feature-grid fc-public-portal-feature-grid-four">
            {partnerBenefits.map(({ title, description, icon: Icon }) => (
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
            <p className="fc-public-portal-eyebrow">Resultados e documentos</p>
            <h2 className="mt-3 text-3xl font-bold text-slate-950 sm:text-4xl">
              O que precisa ser revisto, em um ambiente só seu.
            </h2>
            <p className="mt-4 text-sm leading-6 text-slate-600">
              O parceiro encontra os exames liberados no seu escopo, consulta anexos e acompanha rapidamente os dados
              essenciais para seguir a orientação clínica do caso.
            </p>
          </div>

          <div className="space-y-3">
            {[
              "Busca por pet, tutor ou exame apenas dentro do escopo autorizado.",
              "Filtros por espécie, tipo de exame e período para localizar casos com rapidez.",
              "Downloads protegidos de PDFs e anexos liberados pela Fort Cordis.",
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
          <h2 className="mt-5 text-2xl font-bold text-slate-950">Quando o histórico acompanha o profissional, a decisão fica mais segura.</h2>
          <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-600">
            O portal do parceiro foi desenhado para apoiar a continuidade do cuidado sem abrir acesso amplo demais.
            Cada profissional consulta somente os casos liberados para sua atuação.
          </p>
        </div>
      </section>
    </main>
  );
}

export default function PortalPartnerPageShell() {
  const [bootstrapping, setBootstrapping] = useState(true);
  const [session, setSession] = useState<PortalSessionResponse | null>(null);

  const handleSessionChange = useCallback((nextSession: PortalSessionResponse | null) => {
    setSession(nextSession);
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function hydrate() {
      const storedSession = loadPortalSession("parceiro");
      if (storedSession) {
        if (!cancelled) {
          setSession(storedSession);
          setBootstrapping(false);
        }
        return;
      }

      try {
        const refreshed = normalizePartnerSession(await refreshPartnerPortalSession());
        savePortalSession(refreshed);
        if (!cancelled) {
          setSession(refreshed);
        }
      } catch {
        clearPortalSession("parceiro");
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
    return <PortalPartnerWorkspace mode="standalone" initialSession={session} onSessionChange={handleSessionChange} />;
  }

  return <PublicLanding onSessionChange={handleSessionChange} />;
}
