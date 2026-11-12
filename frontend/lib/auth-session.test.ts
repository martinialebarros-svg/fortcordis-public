import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import axios from "axios";
import { refreshBrowserSession, rememberSession, restoreBrowserSession } from "./auth-session";

const session = { user_id: 7, nome: "Synthetic", email: "staff@example.invalid", papeis: ["secretaria"], access_token: "new-access", provider: "supabase" as const, expires_at: 1900000000 };

beforeEach(() => localStorage.clear());
afterEach(() => vi.restoreAllMocks());

describe("browser auth lifecycle", () => {
  it("shares concurrent refresh requests and sends CSRF protection", async () => {
    document.cookie = "fortcordis_csrf=synthetic-csrf";
    const post = vi.spyOn(axios, "post").mockResolvedValue({ data: session });
    const [a, b] = await Promise.all([refreshBrowserSession(), refreshBrowserSession()]);
    expect(a).toEqual(b);
    expect(post).toHaveBeenCalledTimes(1);
    expect(post.mock.calls[0][2]).toMatchObject({ withCredentials: true, headers: { "x-csrf-token": "synthetic-csrf" } });
    expect(localStorage.getItem("token")).toBe("new-access");
    expect(JSON.parse(localStorage.getItem("user")!).id).toBe(7);
    expect(localStorage.getItem("user")).not.toContain("access_token");
  });

  it("restores a refreshed HttpOnly cookie session after a full page load", async () => {
    vi.spyOn(axios, "get").mockResolvedValue({ data: session });
    const post = vi.spyOn(axios, "post");
    expect(await restoreBrowserSession()).toEqual(session);
    expect(post).not.toHaveBeenCalled();
    expect(localStorage.getItem("auth_provider")).toBe("supabase");
  });

  it("refreshes after an expired access token", async () => {
    vi.spyOn(axios, "get").mockRejectedValue({ isAxiosError: true, response: { status: 401 } });
    vi.spyOn(axios, "post").mockResolvedValue({ data: session });
    expect(await restoreBrowserSession()).toEqual(session);
  });

  it("preserves session data on outages and allows a later retry", async () => {
    rememberSession(session);
    const error = { isAxiosError: true, response: { status: 503 } };
    vi.spyOn(axios, "get").mockRejectedValue(error);
    const post = vi.spyOn(axios, "post").mockRejectedValueOnce(error).mockResolvedValueOnce({ data: session });
    await expect(restoreBrowserSession()).rejects.toBe(error);
    expect(post).not.toHaveBeenCalled();
    await expect(refreshBrowserSession()).rejects.toBe(error);
    expect(localStorage.getItem("token")).toBe("new-access");
    expect(await refreshBrowserSession()).toEqual(session);
  });
});
