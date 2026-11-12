self.addEventListener("install", function () {
  self.skipWaiting();
});

self.addEventListener("activate", function (event) {
  event.waitUntil(self.clients.claim());
});

function construirUrlSoneca(targetUrl, notificationData, minutes, notificationTitle, notificationBody) {
  var baseUrl;
  try {
    baseUrl = new URL(String(targetUrl || "/financeiro"), self.location.origin);
  } catch (error) {
    baseUrl = new URL("/financeiro", self.location.origin);
  }

  baseUrl.searchParams.set("push_snooze", "1");
  baseUrl.searchParams.set("push_snooze_minutes", String(minutes));
  baseUrl.searchParams.set("push_snooze_title", String(notificationTitle || ""));
  baseUrl.searchParams.set("push_snooze_body", String(notificationBody || ""));
  baseUrl.searchParams.set("push_snooze_url", String(notificationData.url || "/financeiro"));
  baseUrl.searchParams.set("push_snooze_module", String(notificationData.module || ""));
  baseUrl.searchParams.set("push_snooze_action", String(notificationData.action || ""));
  baseUrl.searchParams.set("push_snooze_priority", String(notificationData.priority || "normal"));
  baseUrl.searchParams.set("push_snooze_notification_id", String(notificationData.notification_id || ""));
  baseUrl.searchParams.set("push_snooze_resource_type", String(notificationData.resource_type || ""));
  baseUrl.searchParams.set(
    "push_snooze_resource_id",
    notificationData.resource_id == null ? "" : String(notificationData.resource_id)
  );

  return baseUrl.pathname + baseUrl.search + baseUrl.hash;
}

self.addEventListener("push", function (event) {
  var payload = {};
  try {
    payload = event.data ? event.data.json() : {};
  } catch (error) {
    payload = {};
  }

  var title = String((payload && payload.title) || "FortCordis");
  var body = String((payload && payload.body) || "Voce recebeu uma nova notificacao.");
  var url = String((payload && payload.url) || "/agenda");
  var baseTag = String((payload && payload.tag) || "fortcordis-push");
  var notificationId = String((payload && payload.notification_id) || "");
  var stackNotifications = Boolean(payload && payload.stack_notifications);
  var requireInteraction = Boolean(payload && payload.require_interaction);
  var allowSnooze = Boolean(payload && payload.allow_snooze);
  var priority = String((payload && payload.priority) || "normal").toLowerCase();
  if (priority !== "high") {
    priority = "normal";
  }

  var payloadData = payload && payload.data && typeof payload.data === "object" ? payload.data : {};
  var moduleName = String(payloadData.module || "");
  var action = String(payloadData.action || "");
  var resourceType = String(payloadData.resource_type || "");
  var resourceId = payloadData.resource_id == null ? null : payloadData.resource_id;

  if (priority === "high" && title.indexOf("[ALTA]") !== 0) {
    title = "[ALTA] " + title;
  }

  var tag = baseTag;
  if (stackNotifications) {
    var uniqueSuffix = notificationId;
    if (!uniqueSuffix) {
      uniqueSuffix = String(Date.now()) + "-" + Math.random().toString(36).slice(2, 8);
    }
    tag = baseTag + "-" + uniqueSuffix;
  }

  var options = {
    body: body,
    icon: "/favicon.ico",
    badge: "/favicon.ico",
    tag: tag,
    renotify: priority === "high",
    requireInteraction: requireInteraction || priority === "high",
    vibrate: priority === "high" ? [250, 120, 250] : undefined,
    actions: allowSnooze
      ? [
          { action: "snooze_15", title: "Adiar 15m" },
          { action: "snooze_30", title: "Adiar 30m" },
          { action: "snooze_60", title: "Adiar 60m" },
        ]
      : [],
    data: {
      url: url,
      notification_id: notificationId,
      stack_notifications: stackNotifications,
      module: moduleName,
      action: action,
      resource_type: resourceType,
      resource_id: resourceId,
      priority: priority,
    },
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", function (event) {
  event.notification.close();
  var notificationData = event.notification && event.notification.data ? event.notification.data : {};
  var targetUrl = String(notificationData.url || "/agenda");
  var clickAction = String(event.action || "");
  var finalUrl = targetUrl;

  if (clickAction.indexOf("snooze_") === 0) {
    var minutesRaw = clickAction.replace("snooze_", "");
    var minutes = parseInt(minutesRaw, 10);
    if (minutes !== 15 && minutes !== 30 && minutes !== 60) {
      minutes = 15;
    }
    finalUrl = construirUrlSoneca(
      targetUrl,
      notificationData,
      minutes,
      event.notification ? event.notification.title : "",
      event.notification ? event.notification.body : ""
    );
  }

  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(function (clientList) {
      for (var i = 0; i < clientList.length; i += 1) {
        var client = clientList[i];
        try {
          var currentUrl = new URL(client.url);
          if (currentUrl.origin === self.location.origin && "focus" in client) {
            if ("navigate" in client) {
              client.navigate(finalUrl);
            }
            return client.focus();
          }
        } catch (error) {
          // ignore malformed client URL
        }
      }
      if (self.clients.openWindow) {
        return self.clients.openWindow(finalUrl);
      }
      return Promise.resolve();
    })
  );
});
