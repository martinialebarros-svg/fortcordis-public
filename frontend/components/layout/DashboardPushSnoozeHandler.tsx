"use client";

import { useEffect, useRef } from "react";
import { usePathname, useRouter } from "next/navigation";

import api from "@/lib/axios";

interface DashboardPushSnoozeHandlerProps {
  enabled: boolean;
}

export default function DashboardPushSnoozeHandler({
  enabled,
}: DashboardPushSnoozeHandlerProps) {
  const pathname = usePathname();
  const router = useRouter();
  const handledSnoozeRef = useRef<string>("");

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (!enabled) return;

    const searchParams = new URLSearchParams(window.location.search);
    const shouldSnooze = searchParams.get("push_snooze");
    if (shouldSnooze !== "1") return;

    const minutes = Number(searchParams.get("push_snooze_minutes") || "15");
    const safeMinutes = minutes === 30 || minutes === 60 ? minutes : 15;
    const notificationId = String(searchParams.get("push_snooze_notification_id") || "");
    const dedupeKey = `${notificationId}:${safeMinutes}:${pathname}`;
    if (handledSnoozeRef.current === dedupeKey) return;
    handledSnoozeRef.current = dedupeKey;

    const payload: Record<string, any> = {
      minutes: safeMinutes,
      title: String(searchParams.get("push_snooze_title") || ""),
      body: String(searchParams.get("push_snooze_body") || ""),
      url: String(searchParams.get("push_snooze_url") || "/financeiro"),
      module: String(searchParams.get("push_snooze_module") || "financeiro"),
      action: String(searchParams.get("push_snooze_action") || "payment_pending"),
      priority: String(searchParams.get("push_snooze_priority") || "normal"),
      notification_id: notificationId,
      resource_type: String(searchParams.get("push_snooze_resource_type") || ""),
    };
    const resourceIdRaw = searchParams.get("push_snooze_resource_id");
    if (resourceIdRaw && String(resourceIdRaw).trim() !== "") {
      const parsed = Number(resourceIdRaw);
      if (Number.isFinite(parsed) && parsed > 0) {
        payload.resource_id = parsed;
      }
    }

    const limparQuerySoneca = () => {
      const params = new URLSearchParams(window.location.search);
      [
        "push_snooze",
        "push_snooze_minutes",
        "push_snooze_title",
        "push_snooze_body",
        "push_snooze_url",
        "push_snooze_module",
        "push_snooze_action",
        "push_snooze_priority",
        "push_snooze_notification_id",
        "push_snooze_resource_type",
        "push_snooze_resource_id",
      ].forEach((key) => params.delete(key));
      const query = params.toString();
      router.replace(query ? `${pathname}?${query}` : pathname);
    };

    void (async () => {
      try {
        await api.post("/configuracoes/usuario/push/snooze", payload);
        alert(`Notificacao adiada por ${safeMinutes} minuto(s).`);
      } catch (error) {
        console.error("Erro ao agendar soneca da notificacao push:", error);
        alert("Nao foi possivel adiar a notificacao.");
      } finally {
        limparQuerySoneca();
      }
    })();
  }, [enabled, pathname, router]);

  return null;
}
