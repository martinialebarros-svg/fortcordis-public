import Image from "next/image";
import Link from "next/link";
import type { ReactNode } from "react";

type FortCordisStateShellProps = {
  children?: ReactNode;
  description: string;
  eyebrow: string;
  icon: ReactNode;
  title: string;
};

export default function FortCordisStateShell({
  children,
  description,
  eyebrow,
  icon,
  title,
}: FortCordisStateShellProps) {
  return (
    <main className="fc-system-state-page">
      <Image
        src="/brand/fortcordis-portal-hero.jpg"
        alt=""
        fill
        priority
        sizes="100vw"
        className="fc-system-state-background"
      />
      <div className="fc-system-state-overlay" />

      <div className="fc-system-state-shell">
        <Link href="/" className="fc-system-state-brand">
          <Image src="/brand/fortcordis-logo-oficial.png" alt="Fort Cordis" width={50} height={50} />
          <span><strong>FORT CORDIS</strong><small>Cardiologia Veterinária</small></span>
        </Link>

        <section className="fc-system-state-panel">
          <span className="fc-system-state-icon">{icon}</span>
          <p>{eyebrow}</p>
          <h1>{title}</h1>
          <div className="fc-system-state-description">{description}</div>
          {children ? <div className="fc-system-state-actions">{children}</div> : null}
        </section>
      </div>
    </main>
  );
}
