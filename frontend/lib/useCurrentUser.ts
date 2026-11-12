"use client";

import { useState } from "react";

export interface CurrentUser {
  id: number;
  email: string;
  nome: string;
  ativo: number;
  papeis: unknown[];
}

export function useCurrentUser(): CurrentUser | null {
  const [currentUser] = useState<CurrentUser | null>(() => {
    if (typeof window === "undefined") return null;
    const userData = window.localStorage.getItem("user");
    if (!userData) return null;
    try {
      const parsed = JSON.parse(userData);
      return parsed && typeof parsed.email === "string" ? (parsed as CurrentUser) : null;
    } catch {
      return null;
    }
  });

  return currentUser;
}
