import { vi } from "vitest";

// What the mocked next/navigation hooks return; tests set it before rendering a page.
export const nav = {
  pathname: "/",
  params: new URLSearchParams(),
  push: vi.fn(),
};

export function setRoute(pathname: string, query = ""): void {
  nav.pathname = pathname;
  nav.params = new URLSearchParams(query);
  nav.push = vi.fn();
}
