import { Badge, Card, guardrailTone } from "@/components/ui";
import { GUARDRAIL_LABELS, label } from "@/lib/labels";
import type { Guardrail } from "@/lib/types";

const STATE_LABEL: Record<string, string> = { present: "Present", weak: "Weak", missing: "Missing", "n/a": "n/a" };

export function GuardrailPanel({ guardrails }: { guardrails: Guardrail[] }) {
  return (
    <Card className="p-5" aria-label="Guardrail coverage">
      <h2 className="text-[15px] font-semibold">Guardrail coverage</h2>
      <ul className="mt-3 divide-y divide-line">
        {guardrails.map((g) => (
          <li key={g.layer} className="flex items-center justify-between gap-3 py-2.5 text-sm" title={g.detail}>
            <span>{label(GUARDRAIL_LABELS, g.layer)}</span>
            <Badge tone={guardrailTone(g.state)}>{STATE_LABEL[g.state] ?? g.state}</Badge>
          </li>
        ))}
      </ul>
      <p className="mt-3 text-xs text-muted">Present needs a passing live test or code evidence.</p>
    </Card>
  );
}
