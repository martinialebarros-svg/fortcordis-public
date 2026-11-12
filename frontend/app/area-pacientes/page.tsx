import Link from "next/link";
import Image from "next/image";
import {
  ArrowLeft,
  CalendarHeart,
  Download,
  FileHeart,
  HeartPulse,
  MessageCircle,
} from "lucide-react";
import PortalTutorWorkspace from "@/components/portal/PortalTutorWorkspace";

const tutorExperience = [
  {
    title: "Orientação desde o início",
    description:
      "Informações práticas ajudam o tutor a se preparar para o exame e a compartilhar mudanças importantes na saúde do pet.",
    icon: CalendarHeart,
  },
  {
    title: "Histórico bem organizado",
    description:
      "Orientações, atendimentos e documentos ficam reunidos para facilitar o acompanhamento cardiológico ao longo do tempo.",
    icon: FileHeart,
  },
  {
    title: "Resultados ao alcance",
    description:
      "Laudos e exames liberados pela Fort Cordis podem ser consultados no portal de forma simples e confiável.",
    icon: Download,
  },
] as const;

const healthNotes = [
  "Tenha em mãos receitas, exames antigos e a lista de medicamentos em uso.",
  "Avise a equipe se houve tosse, cansaço, desmaio, apetite reduzido ou mudança na respiração.",
  "Depois do exame, acompanhe orientações e retornos pelo histórico do pet.",
] as const;

export default function AreaPacientesPage() {
  return (
    <main className="fc-public-portal fc-public-portal-tutor">
      <section className="fc-public-portal-hero">
        <div className="fc-public-portal-inner">
          <Link
            href="/"
            className="fc-public-portal-back"
          >
            <ArrowLeft className="h-4 w-4" />
            Portal Fort Cordis
          </Link>

          <div className="fc-public-portal-hero-grid">
            <div className="fc-public-portal-copy">
              <div className="fc-public-portal-brand">
                <Image src="/brand/fortcordis-logo-oficial.png" alt="Fort Cordis" width={52} height={52} priority />
                <span><strong>FORT CORDIS</strong><small>Cardiologia Veterinária</small></span>
              </div>
              <p className="fc-public-portal-kicker">
                Área do tutor
              </p>
              <h1>
                Mais clareza para acompanhar o cuidado cardiológico do seu pet.
              </h1>
              <p className="fc-public-portal-lead">
                O portal do tutor reúne orientações do atendimento, histórico cardiológico e
                documentos liberados pela Fort Cordis para você participar de cada etapa com mais
                tranquilidade e segurança.
              </p>
              <div className="fc-public-portal-actions">
                <a
                  href="#acompanhamento"
                  className="fc-public-portal-primary"
                >
                  <HeartPulse className="h-5 w-5" />
                  Como acompanhamos
                </a>
                <a
                  href="#saude-pet"
                  className="fc-public-portal-secondary"
                >
                  <HeartPulse className="h-5 w-5" />
                  Dicas ao tutor
                </a>
              </div>
            </div>

            <PortalTutorWorkspace />
          </div>
        </div>
      </section>

      <section id="acompanhamento" className="fc-public-portal-section fc-scroll-section">
        <div className="fc-public-portal-inner">
          <div className="fc-public-portal-section-heading">
            <p className="fc-public-portal-eyebrow">
              Experiência do tutor
            </p>
            <h2>
              Informação organizada para cuidar com mais confiança.
            </h2>
          </div>
          <div className="fc-public-portal-feature-grid fc-public-portal-feature-grid-three">
            {tutorExperience.map(({ title, description, icon: Icon }) => (
              <article key={title} className="fc-public-portal-feature">
                <Icon className="h-7 w-7 text-teal-700" />
                <h3 className="mt-5 text-lg font-bold text-slate-950">{title}</h3>
                <p className="mt-3 text-sm leading-6 text-slate-600">{description}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section id="saude-pet" className="fc-public-portal-band fc-scroll-section">
        <div className="fc-public-portal-band-grid">
          <div>
            <p className="fc-public-portal-eyebrow">
              Saúde pet
            </p>
            <h2 className="mt-3 text-3xl font-bold sm:text-4xl">
              Pequenos registros melhoram a consulta cardiológica.
            </h2>
          </div>
          <div className="space-y-3">
            {healthNotes.map((note) => (
              <div key={note} className="flex gap-3 rounded-lg border border-white/15 bg-white/[0.06] p-4">
                <CalendarHeart className="mt-0.5 h-5 w-5 shrink-0 text-teal-200" />
                <p className="text-sm leading-6 text-slate-200">{note}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="fc-public-portal-section fc-public-portal-final fc-scroll-section">
        <div className="fc-public-portal-callout">
          <MessageCircle className="h-8 w-8 text-rose-700" />
          <h2 className="mt-5 text-2xl font-bold text-slate-950">
            O cuidado de qualidade continua depois do exame.
          </h2>
          <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-600">
            Acompanhar orientações, manter o histórico por perto e chegar preparado aos retornos
            faz diferença. O portal facilita essa rotina e mantém os dados clínicos protegidos no
            sistema Fort Cordis.
          </p>
        </div>
      </section>
    </main>
  );
}
