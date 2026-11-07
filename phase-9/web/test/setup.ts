import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";
import { nav } from "./nav";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: nav.push, replace: nav.push, back: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => nav.params,
  usePathname: () => nav.pathname,
}));

afterEach(() => {
  cleanup();
  window.sessionStorage.clear();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});
