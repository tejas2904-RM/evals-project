import { render, screen, waitFor, within } from "@testing-library/react";
import HomePage from "@/app/page";
import DashboardPage from "@/app/dashboard/page";
import AuditViewPage from "@/app/audits/view/page";
import NewAuditPage from "@/app/audits/new/page";
import CasesPage from "@/app/cases/page";
import PlaygroundPage from "@/app/playground/page";
import { Nav } from "@/components/Nav";
import { setAdminToken } from "@/lib/admin";
import type { CasePage } from "@/lib/types";
import { fakeApi, meta, response, vulnerableAudit } from "./fixtures";
import { setRoute } from "./nav";

const XSS = '<img src=x onerror="window.__pwned=1">';
const casesPath = (v: string) => `/api/runs/${meta().runs[0]}/cases?case_version=${v}&limit=100`;

function adminMeta() {
  return { ...meta(), mode: "admin", admin: true, jobs_enabled: true };
}

describe("Home", () => {
  it("offers three inputs and explains that the public site is read-only", async () => {
    fakeApi();
    setRoute("/");
    render(<HomePage />);
    expect(screen.getAllByRole("radio")).toHaveLength(3);
    expect(screen.getByRole("radio", { name: /Bot URL/ })).toHaveAttribute("aria-checked", "true");
    expect(await screen.findByText(/public site is read-only/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start audit" })).toBeDisabled();
    expect(screen.getByLabelText("Your bot's chat endpoint")).toBeDisabled();
  });
});

describe("Dashboard", () => {
  it("shows three version cards and all eight checks", async () => {
    fakeApi();
    setRoute("/dashboard/");
    render(<DashboardPage />);
    expect(await screen.findByText("v1 · first demo")).toBeInTheDocument();
    expect(screen.getByText("v2 · guardrails")).toBeInTheDocument();
    expect(screen.getByText("v3 · entity filter")).toBeInTheDocument();
    const summaries = response<{ version_summaries: Record<string, { cases_passed: number; cases_total: number }> }>(
      `/api/runs/${meta().runs[0]}?version=v3`,
    ).version_summaries;
    for (const s of Object.values(summaries)) expect(screen.getAllByText(`${s.cases_passed} / ${s.cases_total}`).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("img", { name: /^v1 / })).toHaveLength(8);
    expect(screen.getAllByRole("img", { name: /^v3 / })).toHaveLength(8);
  });
});

describe("Audit report", () => {
  it("has six tabs, a risk register and no admin actions in public mode", async () => {
    fakeApi();
    const audit = vulnerableAudit();
    setRoute("/audits/view/", `id=${audit.audit_id}`);
    render(<AuditViewPage />);
    expect(await screen.findByRole("heading", { level: 1, name: audit.headline })).toBeInTheDocument();
    expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual(["Overview", "Evals", "Security", "Code", "Risks", "Guardrails"]);
    expect(screen.getByRole("list", { name: "Risks" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Re-run audit" })).not.toBeInTheDocument();
  });

  it("shows an error, not stale data, for an unknown audit id", async () => {
    fakeApi();
    setRoute("/audits/view/", "id=does-not-exist");
    render(<AuditViewPage />);
    expect(await screen.findByText(/not found/i)).toBeInTheDocument();
  });
});

describe("New audit wizard", () => {
  it("has five steps and blocks submission in public mode", async () => {
    fakeApi();
    setRoute("/audits/new/", "step=1");
    render(<NewAuditPage />);
    const steps = await screen.findByRole("list", { name: "Steps" });
    expect(within(steps).getAllByRole("listitem")).toHaveLength(5);
    expect(await screen.findByText(/public site is read-only, so nothing can be submitted/)).toBeInTheDocument();
  });
});

describe("Case explorer", () => {
  it("has four filter chips whose counts match the cases", async () => {
    fakeApi();
    setRoute("/cases/", "version=v3");
    render(<CasesPage />);
    const page = response<CasePage>(casesPath("v3"));
    const failed = page.items.filter((c) => !c.versions.v3?.status?.passed).length;
    const group = await screen.findByRole("group", { name: "Filter cases" });
    await waitFor(() => expect(within(group).getByRole("button", { name: `All (${page.total})` })).toBeInTheDocument());
    expect(within(group).getAllByRole("button")).toHaveLength(4);
    expect(within(group).getByRole("button", { name: `Failed (${failed})` })).toBeInTheDocument();
    expect(within(group).getByRole("button", { name: `Passed (${page.total - failed})` })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Label this answer" })).not.toBeInTheDocument();
  });

  it("renders a hostile bot answer as text", async () => {
    const page = response<CasePage>(casesPath("v2"));
    const first = page.items[0];
    if (!first?.versions.v2) throw new Error("fixture");
    first.versions.v2.answer = XSS;
    first.query = `<script>window.__pwned=1</script>`;
    fakeApi({ [casesPath("v2")]: page });
    setRoute("/cases/", "");
    const { container } = render(<CasesPage />);
    expect(await screen.findByText(XSS)).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
    expect((window as unknown as { __pwned?: number }).__pwned).toBeUndefined();
  });

  it("lets a signed-in admin label an answer", async () => {
    fakeApi({ "/api/meta": adminMeta() });
    setAdminToken("t0ken");
    setRoute("/cases/", "version=v3");
    render(<CasesPage />);
    expect(await screen.findByRole("button", { name: "Label this answer" })).toBeInTheDocument();
  });
});

describe("Playground", () => {
  it("keeps free-text questions for admin mode", async () => {
    fakeApi();
    setRoute("/playground/", "");
    render(<PlaygroundPage />);
    expect(await screen.findByText(/only work in admin mode/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Ask/ })).not.toBeInTheDocument();
  });
});

describe("Nav", () => {
  it("shows Admin sign in publicly and Admin once signed in", async () => {
    fakeApi();
    setRoute("/dashboard/");
    const { unmount } = render(<Nav />);
    expect(await screen.findByRole("link", { name: "Admin sign in" })).toBeInTheDocument();
    unmount();

    fakeApi({ "/api/meta": adminMeta() });
    setAdminToken("t0ken");
    render(<Nav />);
    expect(await screen.findByRole("link", { name: "Admin" })).toBeInTheDocument();
  });

  it("marks the current page", async () => {
    fakeApi();
    setRoute("/cases/");
    render(<Nav />);
    const links = screen.getAllByRole("link", { name: "Cases" });
    expect(links.some((l) => l.getAttribute("aria-current") === "page")).toBe(true);
  });
});
