"use client";

import { useSyncExternalStore } from "react";

// The admin token is printed by `evalpilot serve --admin` and lives only for this browser tab (sessionStorage).
const KEY = "evalpilot.admin-token";
const EVENT = "evalpilot:admin";

export function getAdminToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.sessionStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function setAdminToken(token: string | null): void {
  if (typeof window === "undefined") return;
  if (token) window.sessionStorage.setItem(KEY, token);
  else window.sessionStorage.removeItem(KEY);
  window.dispatchEvent(new Event(EVENT));
}

function subscribe(cb: () => void): () => void {
  window.addEventListener(EVENT, cb);
  window.addEventListener("storage", cb);
  return () => {
    window.removeEventListener(EVENT, cb);
    window.removeEventListener("storage", cb);
  };
}

export function useAdminToken(): string | null {
  return useSyncExternalStore(subscribe, getAdminToken, () => null);
}
