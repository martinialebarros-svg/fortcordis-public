"use client";

import { usePushNotifications } from "@/lib/usePushNotifications";

interface PushNotificationsBootstrapProps {
  enabled: boolean;
}

export default function PushNotificationsBootstrap({
  enabled,
}: PushNotificationsBootstrapProps) {
  usePushNotifications(enabled);
  return null;
}
