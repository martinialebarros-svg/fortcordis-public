"use client";

import { useCallback, useEffect, useRef } from "react";

import api from "@/lib/axios";

const PUSH_SYNC_EVENT = "fortcordis:push-sync";
const SERVICE_WORKER_PATH = "/sw.js";

interface PushSyncEventDetail {
  allowPermissionPrompt?: boolean;
}

interface UserConfigResponse {
  notificacoes_push?: boolean;
}

interface PushPublicKeyResponse {
  enabled?: boolean;
  public_key?: string | null;
}

function supportsWebPush(): boolean {
  if (typeof window === "undefined") return false;
  if (!window.isSecureContext) return false;
  return "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
}

function urlBase64ToUint8Array(base64String: string): Uint8Array {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = window.atob(base64);
  const outputArray = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; i += 1) {
    outputArray[i] = rawData.charCodeAt(i);
  }
  return outputArray;
}

async function unsubscribeRemote(endpoint: string): Promise<void> {
  if (!endpoint) return;
  try {
    await api.post("/configuracoes/usuario/push/unsubscribe", { endpoint });
  } catch {
    // best effort
  }
}

async function removeSubscription(
  registration: ServiceWorkerRegistration,
  existing?: PushSubscription | null
): Promise<void> {
  const subscription = existing ?? (await registration.pushManager.getSubscription());
  if (!subscription) return;

  await unsubscribeRemote(subscription.endpoint);
  try {
    await subscription.unsubscribe();
  } catch {
    // best effort
  }
}

export async function removePushSubscriptionForCurrentDevice(): Promise<void> {
  if (typeof window === "undefined") return;
  if (!("serviceWorker" in navigator)) return;

  const registration = await navigator.serviceWorker.getRegistration(SERVICE_WORKER_PATH);
  if (!registration) return;
  await removeSubscription(registration);
}

async function syncPushSubscription(allowPermissionPrompt: boolean): Promise<void> {
  if (typeof window === "undefined") return;

  const token = localStorage.getItem("token");
  if (!token) return;
  if (!supportsWebPush()) return;

  const [configResponse, pushPublicKeyResponse] = await Promise.all([
    api.get<UserConfigResponse>("/configuracoes/usuario"),
    api.get<PushPublicKeyResponse>("/configuracoes/usuario/push/public-key"),
  ]);

  const pushEnabledByUser = configResponse.data?.notificacoes_push !== false;
  const pushPublicKey = String(pushPublicKeyResponse.data?.public_key || "").trim();
  const pushEnabledByServer = Boolean(pushPublicKeyResponse.data?.enabled && pushPublicKey);

  const registration = await navigator.serviceWorker.register(SERVICE_WORKER_PATH);
  const existingSubscription = await registration.pushManager.getSubscription();

  if (!pushEnabledByUser || !pushEnabledByServer) {
    await removeSubscription(registration, existingSubscription);
    return;
  }

  let permission = Notification.permission;
  if (permission === "default" && allowPermissionPrompt) {
    permission = await Notification.requestPermission();
  }

  if (permission !== "granted") {
    if (permission === "denied") {
      await removeSubscription(registration, existingSubscription);
    }
    return;
  }

  let subscription = existingSubscription;
  if (!subscription) {
    subscription = await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(pushPublicKey) as BufferSource,
    });
  }

  await api.post("/configuracoes/usuario/push/subscribe", {
    subscription: subscription.toJSON(),
  });
}

export async function syncPushNotificationsNow(allowPermissionPrompt = false): Promise<void> {
  await syncPushSubscription(allowPermissionPrompt);
}

export function requestPushSync(allowPermissionPrompt = false): void {
  if (typeof window === "undefined") return;
  const event = new CustomEvent<PushSyncEventDetail>(PUSH_SYNC_EVENT, {
    detail: { allowPermissionPrompt },
  });
  window.dispatchEvent(event);
}

export function usePushNotifications(enabled: boolean): void {
  const syncInProgressRef = useRef(false);

  const runSync = useCallback(async (allowPermissionPrompt: boolean) => {
    if (!enabled) return;
    if (syncInProgressRef.current) return;
    syncInProgressRef.current = true;
    try {
      await syncPushSubscription(allowPermissionPrompt);
    } catch (error) {
      console.error("Falha ao sincronizar inscricao push:", error);
    } finally {
      syncInProgressRef.current = false;
    }
  }, [enabled]);

  useEffect(() => {
    if (!enabled) return;

    void runSync(false);

    const handleFocus = () => {
      void runSync(false);
    };

    const handleSyncEvent = (event: Event) => {
      const customEvent = event as CustomEvent<PushSyncEventDetail>;
      const allowPermissionPrompt = customEvent?.detail?.allowPermissionPrompt === true;
      void runSync(allowPermissionPrompt);
    };

    window.addEventListener("focus", handleFocus);
    window.addEventListener(PUSH_SYNC_EVENT, handleSyncEvent as EventListener);

    return () => {
      window.removeEventListener("focus", handleFocus);
      window.removeEventListener(PUSH_SYNC_EVENT, handleSyncEvent as EventListener);
    };
  }, [enabled, runSync]);
}
