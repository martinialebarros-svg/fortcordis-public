import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";
import { requiresLogin } from "@/lib/auth-routes";
import { protectRoute } from "@/lib/server-route-auth";
import {
  isAppRoutePath,
  isInstitutionalHost,
  resolveAppHostForInstitutionalHost,
  resolveRequestHost,
} from "@/lib/host-routing";

function resolveProtocol(request: NextRequest): string {
  const forwardedProto = request.headers.get("x-forwarded-proto");
  if (forwardedProto) {
    return forwardedProto.split(",")[0]?.trim() || "https";
  }
  return request.nextUrl.protocol.replace(":", "");
}

export async function middleware(request: NextRequest) {
  const host = resolveRequestHost({
    host: request.headers.get("host"),
    forwardedHost: request.headers.get("x-forwarded-host"),
    originalHost: request.headers.get("x-original-host"),
  });

  if (!isInstitutionalHost(host)) {
    return requiresLogin(request.nextUrl.pathname) ? protectRoute(request) : NextResponse.next();
  }

  if (!isAppRoutePath(request.nextUrl.pathname)) {
    return NextResponse.next();
  }

  const appHost = resolveAppHostForInstitutionalHost(host);
  if (!appHost) {
    return NextResponse.next();
  }

  const redirectUrl = request.nextUrl.clone();
  redirectUrl.protocol = `${resolveProtocol(request)}:`;
  redirectUrl.hostname = appHost;
  redirectUrl.port = "";

  return NextResponse.redirect(redirectUrl);
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|robots.txt|sitemap.xml).*)"],
};
