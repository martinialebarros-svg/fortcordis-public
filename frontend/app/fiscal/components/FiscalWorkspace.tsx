"use client";

import { useState } from "react";
import DashboardLayout from "../../layout-dashboard";
import ExportacaoDadosContabeisPage from "./ExportacaoDadosContabeisPage";
import RotinaFiscalPage from "./RotinaFiscalPage";

export default function FiscalWorkspace() {
  const [tab, setTab] = useState<"fechamento" | "avulsa">("fechamento");
  const [preparando, setPreparando] = useState(false);
  return (
    <DashboardLayout>
      <div className="mx-auto flex max-w-[1480px] flex-wrap gap-2 px-4 pt-4 sm:px-5 lg:px-6" role="tablist" aria-label="Fluxo fiscal">
        <button id="fiscal-tab-fechamento" type="button" role="tab" aria-controls="fiscal-tab-content" aria-selected={tab === "fechamento"} disabled={preparando} onClick={() => setTab("fechamento")} className={`rounded-lg border px-4 py-2 text-sm font-semibold ${tab === "fechamento" ? "border-teal-600 bg-teal-50 text-teal-900" : "border-slate-200 bg-white text-slate-600"}`}>Rotina fiscal</button>
        <button id="fiscal-tab-avulsa" type="button" role="tab" aria-controls="fiscal-tab-content" aria-selected={tab === "avulsa"} disabled={preparando} onClick={() => setTab("avulsa")} className={`rounded-lg border px-4 py-2 text-sm font-semibold ${tab === "avulsa" ? "border-teal-600 bg-teal-50 text-teal-900" : "border-slate-200 bg-white text-slate-600"}`}>Cadastro e exportação avulsa</button>
      </div>
      <div id="fiscal-tab-content" role="tabpanel" aria-labelledby={`fiscal-tab-${tab}`}>
        {tab === "fechamento" ? <RotinaFiscalPage onBusyChange={setPreparando} /> : <>
          <p className="mx-4 mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900 sm:mx-5 lg:mx-6">Use este fluxo para conferir o cadastro e consultar exportações antigas. A exportação avulsa mantém o formato anterior; a preparação semanal, por serviço e os andamentos estão na aba Rotina fiscal.</p>
          <ExportacaoDadosContabeisPage embedded />
        </>}
      </div>
    </DashboardLayout>
  );
}
