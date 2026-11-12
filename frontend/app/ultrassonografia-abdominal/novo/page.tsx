"use client";

import DashboardLayout from "@/app/layout-dashboard";
import UltrassonografiaAbdominalForm from "../components/UltrassonografiaAbdominalForm";

export default function NovaUltrassonografiaAbdominalPage() {
  return (
    <DashboardLayout>
      <UltrassonografiaAbdominalForm mode="create" />
    </DashboardLayout>
  );
}
