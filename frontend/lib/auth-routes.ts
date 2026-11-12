import { usesDashboardShell } from "./dashboard-shell-routes";

export function requiresLogin(pathname: string): boolean {
  return usesDashboardShell(pathname);
}

export function safeLoginDestination(value: string | null | undefined): string {
  if (!value?.startsWith("/") || value.startsWith("//") || /[\\\r\n]/.test(value)) return "/dashboard";
  const url = new URL(value, "https://fortcordis.invalid");
  return url.origin === "https://fortcordis.invalid" && requiresLogin(url.pathname)
    ? `${url.pathname}${url.search}` : "/dashboard";
}
