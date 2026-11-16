"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import DashboardLayout from "../../layout-dashboard";
import RevisaoPacientes from "./RevisaoPacientes";

function codigoValido(value: string | null) {
  return value && /^\d+$/.test(value) && Number.isSafeInteger(Number(value)) && Number(value) > 0
    ? String(Number(value)) : "";
}

export default function MesclagensPacientesPage() {
  const [codigos, setCodigos] = useState<{ principal: string; secundario: string } | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    setCodigos({
      principal: codigoValido(params.get("paciente")),
      secundario: codigoValido(params.get("duplicado")),
    });
  }, []);

  return (
    <DashboardLayout>
      <main className="mx-auto max-w-5xl space-y-5 px-4 py-6 text-slate-900">
        <header>
          <Link href="/pacientes" className="text-sm text-blue-800 underline">Voltar para Pacientes</Link>
          <h1 className="mt-2 text-2xl font-bold">Revisão de duplicidade de pacientes</h1>
          <p className="mt-1 text-slate-600">Escolha os dois cadastros do mesmo animal. Você pode guardar a revisão e retomá-la depois.</p>
        </header>
        {codigos && <RevisaoPacientes principalInicial={codigos.principal} secundarioInicial={codigos.secundario} />}
      </main>
    </DashboardLayout>
  );
}
