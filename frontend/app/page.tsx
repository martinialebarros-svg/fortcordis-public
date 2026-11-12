import Link from "next/link";
import Image from "next/image";
import { headers } from "next/headers";
import localFont from "next/font/local";
import {
  ArrowRight,
  BadgeCheck,
  Building2,
  CalendarHeart,
  ClipboardCheck,
  Download,
  FileHeart,
  HeartPulse,
  ShieldCheck,
  Smartphone,
  Stethoscope,
  UserRound,
} from "lucide-react";
import LoginPageClient from "./page-client";
import {
  isInstitutionalHost,
  resolveAppHostForInstitutionalHost,
  resolveRequestHost,
} from "@/lib/host-routing";

const displayFont = localFont({
  src: "../node_modules/@fontsource-variable/fraunces/files/fraunces-latin-wght-normal.woff2",
  variable: "--font-display",
  weight: "100 900",
  display: "swap",
});

const textFont = localFont({
  src: "../node_modules/@fontsource-variable/manrope/files/manrope-latin-wght-normal.woff2",
  variable: "--font-manrope",
  weight: "200 800",
  display: "swap",
});

function getAppHost(host: string) {
  return resolveAppHostForInstitutionalHost(host) ?? "app.fortcordis.com.br";
}

function getPortalLinks(host: string) {
  const appHost = getAppHost(host);

  return [
    {
      title: "Portal do tutor",
      eyebrow: "Cuidado que continua",
      description:
        "Orientações, histórico e resultados reunidos para acompanhar a saúde cardiológica do pet com mais clareza.",
      href: "/area-pacientes",
      action: "Acessar como tutor",
      icon: UserRound,
      accent: "border-teal-200 bg-teal-50 text-teal-800",
    },
    {
      title: "Clínica parceira",
      eyebrow: "Cuidado em parceria",
      description:
        "Exames e informações organizados para apoiar a rotina da unidade e a continuidade de cada atendimento.",
      href: "/clinica-parceira",
      action: "Acessar como clínica",
      icon: Building2,
      accent: "border-rose-200 bg-rose-50 text-rose-800",
    },
    {
      title: "Sistema Fort Cordis",
      eyebrow: "Operação integrada",
      description:
        "Agenda, atendimento, laudos e gestão conectados para a equipe dedicar mais atenção ao cuidado.",
      href: `https://${appHost}/`,
      action: "Abrir sistema",
      icon: ShieldCheck,
      accent: "border-amber-200 bg-amber-50 text-amber-900",
    },
  ] as const;
}

const trustItems = [
  {
    value: "Clareza",
    label: "orientações e resultados fáceis de acompanhar",
  },
  {
    value: "Integração",
    label: "tutores, clínicas e equipe conectados",
  },
  {
    value: "Continuidade",
    label: "informação que acompanha cada caso",
  },
] as const;

const tutorTips = [
  {
    title: "Antes do eco",
    description:
      "Leve receitas em uso, exames anteriores e relate mudanças de respiração, apetite ou disposição.",
    icon: ClipboardCheck,
  },
  {
    title: "Sinais de alerta",
    description:
      "Cansaço incomum, tosse persistente, desmaios ou respiração ofegante merecem contato com o veterinário.",
    icon: HeartPulse,
  },
  {
    title: "Rotina em casa",
    description:
      "Mantenha horários dos medicamentos e anote reações para facilitar a revisão do cardiologista.",
    icon: CalendarHeart,
  },
  {
    title: "Resultados",
    description:
      "Consulte laudos e orientações no portal e mantenha o histórico do pet disponível para os próximos cuidados.",
    icon: Download,
  },
] as const;

const careJourneys = [
  {
    title: "Tutores",
    description:
      "Mais clareza para entender cada etapa e participar ativamente do cuidado com o pet.",
    icon: Smartphone,
    steps: [
      "Orientações para chegar mais preparado ao atendimento.",
      "Histórico, resultados e recomendações reunidos em um só lugar.",
      "Acompanhamento mais simples entre exames e retornos.",
    ],
  },
  {
    title: "Clínicas parceiras",
    description:
      "Uma parceria mais fluida para consultar casos e dar sequência ao atendimento na unidade.",
    icon: BadgeCheck,
    steps: [
      "Casos e documentos organizados por unidade e paciente.",
      "Busca prática de exames e informações relevantes para a equipe.",
      "Continuidade do cuidado com acesso confiável e permissões adequadas.",
    ],
  },
] as const;

const servicePrinciples = [
  {
    title: "Atenção em cada etapa",
    description:
      "Orientações antes, durante e depois do exame ajudam tutores e clínicas a se sentirem bem acompanhados.",
    icon: HeartPulse,
  },
  {
    title: "Informação clara",
    description:
      "Resultados e recomendações são apresentados de forma organizada para facilitar os próximos passos do cuidado.",
    icon: FileHeart,
  },
  {
    title: "Continuidade do cuidado",
    description:
      "Tutores, clínicas parceiras e equipe Fort Cordis compartilham o contexto necessário para acompanhar cada caso.",
    icon: BadgeCheck,
  },
] as const;

export const dynamic = "force-dynamic";
export const revalidate = 0;

function InstitutionalLanding({ host }: { host: string }) {
  const portalLinks = getPortalLinks(host);

  return (
    <main
      className={`${displayFont.variable} ${textFont.variable} bg-white font-[family-name:var(--font-manrope)] text-slate-950`}
    >
      <section className="relative isolate flex min-h-[82svh] flex-col overflow-hidden bg-slate-950 text-white sm:min-h-[88svh]">
        <Image
          src="/brand/fortcordis-portal-hero.jpg"
          alt=""
          fill
          priority
          sizes="100vw"
          className="-z-20 object-cover object-center"
        />
        <div className="absolute inset-0 -z-10 bg-[linear-gradient(90deg,rgba(2,6,23,0.94)_0%,rgba(15,23,42,0.78)_42%,rgba(15,23,42,0.18)_78%)]" />

        <header className="mx-auto flex w-full max-w-7xl flex-col gap-5 px-5 py-5 sm:px-8 lg:flex-row lg:items-center lg:justify-between">
          <Link href="/" className="flex items-center gap-3">
            <Image
              src="/brand/fortcordis-logo-oficial.png"
              alt="Fort Cordis"
              width={72}
              height={72}
              className="h-12 w-12 rounded-lg bg-white p-1 shadow-sm"
            />
            <div>
              <p className="font-[family-name:var(--font-display)] text-xl font-semibold leading-none">
                Fort Cordis
              </p>
              <p className="mt-1 text-xs font-semibold uppercase tracking-[0.18em] text-teal-100">
                cardiologia veterinária
              </p>
            </div>
          </Link>

          <nav className="flex flex-wrap gap-2 text-sm font-semibold text-slate-100">
            <Link className="rounded-lg px-3 py-2 transition hover:bg-white/10" href="#portais">
              Portais
            </Link>
            <Link className="rounded-lg px-3 py-2 transition hover:bg-white/10" href="#dicas">
              Saúde pet
            </Link>
            <Link className="rounded-lg px-3 py-2 transition hover:bg-white/10" href="#qualidade">
              Nossa qualidade
            </Link>
          </nav>
        </header>

        <div className="mx-auto flex w-full max-w-7xl flex-1 items-center px-5 pb-10 pt-6 sm:px-8 sm:pb-16 sm:pt-10 lg:pb-20">
          <div className="max-w-3xl">
            <p className="mb-4 inline-flex items-center gap-2 rounded-lg border border-white/20 bg-white/10 px-3 py-2 text-sm font-semibold text-teal-50 backdrop-blur">
              <Stethoscope className="h-4 w-4" />
              Portal integrado ao sistema Fort Cordis
            </p>
            <h1 className="font-[family-name:var(--font-display)] text-5xl font-semibold leading-[0.95] text-white sm:text-6xl lg:text-7xl">
              Fort Cordis
            </h1>
            <p className="mt-6 max-w-2xl text-lg leading-8 text-slate-100 sm:text-xl">
              Cuidado cardiológico veterinário com atenção em cada etapa, informação clara para
              tutores e uma parceria próxima com as clínicas que acompanham cada pet.
            </p>
            <div className="mt-8 flex flex-col gap-3 sm:flex-row">
              <Link
                href="/area-pacientes"
                className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-teal-500 px-5 py-3 text-sm font-bold text-slate-950 shadow-lg shadow-slate-950/20 transition hover:bg-teal-300 sm:w-auto"
              >
                <UserRound className="h-5 w-5" />
                Portal do tutor
              </Link>
              <Link
                href="/clinica-parceira"
                className="inline-flex w-full items-center justify-center gap-2 rounded-lg border border-white/25 bg-white/10 px-5 py-3 text-sm font-bold text-white backdrop-blur transition hover:bg-white/18 sm:w-auto"
              >
                <Building2 className="h-5 w-5" />
                Clínica parceira
              </Link>
            </div>
            <dl className="mt-10 hidden max-w-2xl gap-3 sm:grid sm:grid-cols-3">
              {trustItems.map((item) => (
                <div key={item.value} className="border-l-2 border-teal-300 pl-4">
                  <dt className="font-[family-name:var(--font-display)] text-2xl font-semibold text-white">
                    {item.value}
                  </dt>
                  <dd className="mt-1 text-sm leading-5 text-slate-200">{item.label}</dd>
                </div>
              ))}
            </dl>
          </div>
        </div>
      </section>

      <section id="portais" className="fc-scroll-section bg-white px-5 py-16 sm:px-8 lg:py-20">
        <div className="mx-auto max-w-7xl">
          <div className="max-w-3xl">
            <p className="text-sm font-bold uppercase tracking-[0.18em] text-teal-700">Portais</p>
            <h2 className="mt-3 font-[family-name:var(--font-display)] text-4xl font-semibold tracking-normal text-slate-950 sm:text-5xl">
              Um ponto de entrada para cada relação de cuidado.
            </h2>
            <p className="mt-4 text-base leading-7 text-slate-600">
              Tutores acompanham seus pets, clínicas parceiras consultam casos da própria
              unidade e a equipe interna segue operando no sistema Fort Cordis.
            </p>
          </div>

          <div className="mt-10 grid gap-5 lg:grid-cols-3">
            {portalLinks.map(({ title, eyebrow, description, href, action, icon: Icon, accent }) => (
              <Link
                key={title}
                href={href}
                className="group flex min-h-80 flex-col justify-between rounded-lg border border-slate-200 bg-white p-6 shadow-sm transition hover:-translate-y-1 hover:border-slate-300 hover:shadow-xl"
              >
                <div>
                  <div className={`mb-6 inline-flex rounded-lg border p-3 ${accent}`}>
                    <Icon className="h-7 w-7" />
                  </div>
                  <p className="text-xs font-bold uppercase tracking-[0.16em] text-slate-500">
                    {eyebrow}
                  </p>
                  <h3 className="mt-3 font-[family-name:var(--font-display)] text-3xl font-semibold text-slate-950">
                    {title}
                  </h3>
                  <p className="mt-4 text-sm leading-6 text-slate-600">{description}</p>
                </div>
                <span className="mt-8 inline-flex items-center gap-2 text-sm font-bold text-teal-800">
                  {action}
                  <ArrowRight className="h-4 w-4 transition group-hover:translate-x-1" />
                </span>
              </Link>
            ))}
          </div>
        </div>
      </section>

      <section id="qualidade" className="fc-scroll-section bg-slate-950 px-5 py-16 text-white sm:px-8 lg:py-20">
        <div className="mx-auto grid max-w-7xl gap-10 lg:grid-cols-[0.9fr_1.1fr] lg:items-start">
          <div>
            <p className="text-sm font-bold uppercase tracking-[0.18em] text-teal-200">
              Qualidade no atendimento
            </p>
            <h2 className="mt-3 font-[family-name:var(--font-display)] text-4xl font-semibold tracking-normal sm:text-5xl">
              Um cuidado bem conduzido antes, durante e depois do exame.
            </h2>
            <p className="mt-5 text-base leading-7 text-slate-300">
              A qualidade do serviço também está na experiência: orientar com clareza, organizar
              as informações do caso e facilitar a continuidade do atendimento. Tudo isso em um
              ambiente confiável, com acessos adequados para tutores e clínicas parceiras.
            </p>
          </div>

          <div className="grid gap-5 md:grid-cols-2">
            {careJourneys.map(({ title, description, icon: Icon, steps }) => (
              <article key={title} className="rounded-lg border border-white/15 bg-white/[0.06] p-6">
                <Icon className="h-8 w-8 text-teal-200" />
                <h3 className="mt-5 font-[family-name:var(--font-display)] text-3xl font-semibold">
                  {title}
                </h3>
                <p className="mt-3 text-sm leading-6 text-slate-300">{description}</p>
                <ol className="mt-6 space-y-4">
                  {steps.map((step, index) => (
                    <li key={step} className="flex gap-3 text-sm leading-6 text-slate-200">
                      <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-teal-300 text-xs font-bold text-slate-950">
                        {index + 1}
                      </span>
                      <span>{step}</span>
                    </li>
                  ))}
                </ol>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section id="dicas" className="fc-scroll-section bg-[#f8fbfc] px-5 py-16 sm:px-8 lg:py-20">
        <div className="mx-auto max-w-7xl">
          <div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
            <div className="max-w-3xl">
              <p className="text-sm font-bold uppercase tracking-[0.18em] text-rose-700">
                Saúde pet
              </p>
              <h2 className="mt-3 font-[family-name:var(--font-display)] text-4xl font-semibold tracking-normal text-slate-950 sm:text-5xl">
                Dicas para tutores acompanharem melhor o cuidado cardiológico.
              </h2>
            </div>
            <p className="max-w-md text-sm leading-6 text-slate-600">
              Conteúdos objetivos ajudam o tutor a chegar mais preparado ao atendimento e a
              manter o tratamento com menos dúvidas no dia a dia.
            </p>
          </div>

          <div className="mt-10 grid gap-5 md:grid-cols-2 lg:grid-cols-4">
            {tutorTips.map(({ title, description, icon: Icon }) => (
              <article key={title} className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
                <Icon className="h-7 w-7 text-rose-700" />
                <h3 className="mt-5 text-lg font-bold text-slate-950">{title}</h3>
                <p className="mt-3 text-sm leading-6 text-slate-600">{description}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="fc-scroll-section bg-white px-5 py-16 sm:px-8 lg:py-20">
        <div className="mx-auto grid max-w-7xl gap-10 lg:grid-cols-[1fr_1fr] lg:items-center">
          <div>
            <p className="text-sm font-bold uppercase tracking-[0.18em] text-amber-700">
              Experiência Fort Cordis
            </p>
            <h2 className="mt-3 font-[family-name:var(--font-display)] text-4xl font-semibold tracking-normal text-slate-950 sm:text-5xl">
              Tecnologia a serviço de um atendimento bem acompanhado.
            </h2>
            <p className="mt-5 text-base leading-7 text-slate-600">
              O portal aproxima tutores, clínicas parceiras e a equipe Fort Cordis. Ele organiza
              orientações, laudos e o histórico de cada caso para que a informação certa esteja
              disponível no momento certo, com a proteção que dados clínicos exigem.
            </p>
          </div>
          <div className="grid gap-4">
            {servicePrinciples.map(({ title, description, icon: Icon }) => (
              <article key={title} className="flex gap-4 rounded-lg border border-slate-200 p-5">
                <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-amber-50 text-amber-800">
                  <Icon className="h-6 w-6" />
                </span>
                <div>
                  <h3 className="font-bold text-slate-950">{title}</h3>
                  <p className="mt-2 text-sm leading-6 text-slate-600">{description}</p>
                </div>
              </article>
            ))}
          </div>
        </div>
      </section>

      <footer className="border-t border-slate-200 bg-white px-5 py-8 sm:px-8">
        <div className="mx-auto flex max-w-7xl flex-col gap-4 text-sm text-slate-600 sm:flex-row sm:items-center sm:justify-between">
          <p className="font-semibold text-slate-950">Fort Cordis</p>
          <p>Cardiologia veterinária com clareza, proximidade e continuidade do cuidado.</p>
        </div>
      </footer>
    </main>
  );
}

export default async function HomePage() {
  const headersList = await headers();
  const host = resolveRequestHost({
    host: headersList.get("host"),
    forwardedHost: headersList.get("x-forwarded-host"),
    originalHost: headersList.get("x-original-host"),
  });

  if (isInstitutionalHost(host)) {
    return <InstitutionalLanding host={host} />;
  }

  return <LoginPageClient />;
}
