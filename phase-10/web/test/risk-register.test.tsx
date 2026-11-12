import { fireEvent, render, screen, within } from "@testing-library/react";
import { RiskRegister } from "@/components/RiskRegister";
import type { Risk } from "@/lib/types";

function risk(id: string, level: string, severity: number, owasp: string | null, title = `risk ${id}`): Risk {
  return {
    risk_id: id,
    owasp,
    title,
    findings: [],
    check_ids: ["X-01"],
    evidence: [{ kind: "code", location: "app.py:1", excerpt: "eval(x)" }],
    likelihood: 1,
    impact: severity,
    severity,
    level,
    fix: "fix it",
    status: "open",
    acceptance: null,
    capped_from: null,
    found_by: ["Code rule"],
  };
}

const RISKS = [risk("a", "medium", 9, "LLM06"), risk("b", "critical", 25, "LLM10"), risk("c", "high", 16, "LLM10"), risk("d", "low", 2, null)];

const titles = () =>
  within(screen.getByRole("list", { name: "Risks" }))
    .getAllByRole("button")
    .map((b) => b.textContent ?? "");

describe("RiskRegister", () => {
  it("sorts by severity and opens the worst risk", () => {
    render(<RiskRegister risks={RISKS} />);
    expect(titles().map((t) => t.match(/risk (\w)/)?.[1])).toEqual(["b", "c", "a", "d"]);
    expect(screen.getByRole("button", { name: /risk b/ })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Likelihood 1 × impact 25 = 25")).toBeInTheDocument();
  });

  it("filters by severity and OWASP category", () => {
    render(<RiskRegister risks={RISKS} />);
    fireEvent.change(screen.getByLabelText("Severity"), { target: { value: "high" } });
    expect(titles()).toHaveLength(1);
    fireEvent.change(screen.getByLabelText("Severity"), { target: { value: "all" } });
    fireEvent.change(screen.getByLabelText("OWASP"), { target: { value: "LLM10" } });
    expect(titles().map((t) => t.match(/risk (\w)/)?.[1])).toEqual(["b", "c"]);
    fireEvent.change(screen.getByLabelText("Severity"), { target: { value: "low" } });
    expect(screen.getByText("No risks found.")).toBeInTheDocument();
  });

  it("renders titles and evidence as text", () => {
    const evil = risk("e", "critical", 25, "LLM10", '<img src=x onerror="window.__pwned=1">');
    evil.evidence = [{ kind: "code", location: "<b>x</b>", excerpt: "<script>window.__pwned=1</script>" }];
    const { container } = render(<RiskRegister risks={[evil]} />);
    expect(screen.getByText('<img src=x onerror="window.__pwned=1">')).toBeInTheDocument();
    expect(screen.getByText("<script>window.__pwned=1</script>")).toBeInTheDocument();
    expect(container.querySelector("img, script, b")).toBeNull();
  });
});
