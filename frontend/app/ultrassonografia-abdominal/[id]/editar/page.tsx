"use client";

import DashboardLayout from "@/app/layout-dashboard";
import { useParams } from "next/navigation";
import UltrassonografiaAbdominalForm from "../../components/UltrassonografiaAbdominalForm";

export default function EditarUltrassonografiaAbdominalPage() {
  const routeParams = useParams<{ id?: string | string[] }>();
  const laudoId = Array.isArray(routeParams.id) ? routeParams.id[0] : routeParams.id;
  return (
    <DashboardLayout>
      <UltrassonografiaAbdominalForm mode="edit" laudoId={laudoId || ""} />
    </DashboardLayout>
  );
}
