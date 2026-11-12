import Image from "next/image";
import Link from "next/link";
import type { ReactNode } from "react";

type LegalDocumentPageProps = {
  eyebrow: string;
  title: string;
  description: string;
  children: ReactNode;
};

export function LegalDocumentPage({
  eyebrow,
  title,
  description,
  children,
}: LegalDocumentPageProps) {
  return (
    <main className="min-h-screen bg-slate-50 text-slate-900">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex w-full max-w-4xl items-center justify-between px-5 py-5 sm:px-8">
          <Link href="/" className="flex items-center gap-3" aria-label="Voltar ao início da Fort Cordis">
            <Image
              src="/brand/fortcordis-logo-oficial.png"
              alt="Fort Cordis"
              width={52}
              height={52}
              className="h-11 w-11 rounded-lg border border-slate-200 bg-white object-contain p-1"
            />
            <span>
              <strong className="block text-base leading-tight text-slate-950">Fort Cordis</strong>
              <small className="text-xs font-medium uppercase tracking-[0.16em] text-slate-500">
                Cardiologia Veterinária
              </small>
            </span>
          </Link>
          <Link
            href="/"
            className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-100"
          >
            Início
          </Link>
        </div>
      </header>

      <article className="mx-auto w-full max-w-4xl px-5 py-10 sm:px-8 sm:py-14">
        <p className="text-sm font-bold uppercase tracking-[0.16em] text-teal-700">{eyebrow}</p>
        <h1 className="mt-3 text-3xl font-bold tracking-tight text-slate-950 sm:text-4xl">{title}</h1>
        <p className="mt-4 max-w-3xl text-base leading-7 text-slate-600">{description}</p>
        <p className="mt-4 text-sm text-slate-500">Atualizado em 12 de agosto de 2026.</p>

        <div className="mt-10 space-y-8 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-9 [&_a]:font-semibold [&_a]:text-teal-700 [&_a]:underline [&_a]:underline-offset-4 [&_h2]:text-xl [&_h2]:font-bold [&_h2]:text-slate-950 [&_li]:leading-7 [&_p]:leading-7 [&_p]:text-slate-700 [&_ul]:list-disc [&_ul]:space-y-2 [&_ul]:pl-6">
          {children}
        </div>
      </article>
    </main>
  );
}
