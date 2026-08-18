import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { EvidenceTable, MetricCard, formatValue } from "./reporting-ui";

afterEach(cleanup);

describe("benchmark reporting presentation", () => {
  it("distinguishes unavailable evidence from measured zero", () => {
    expect(formatValue(null)).toBe("Unavailable");
    expect(formatValue(0)).toBe("0");
    expect(formatValue(0, "percent")).toBe("0.0%");
  });

  it("formats percentages and latency with visible units", () => {
    expect(formatValue("0.875", "percent")).toBe("87.5%");
    expect(formatValue(1234.56, "latency")).toContain("ms");
  });

  it("renders a labelled metric card", () => {
    render(<MetricCard label="Pass rate" value="0.5" kind="percent" />);
    expect(screen.getByText("Pass rate")).toBeTruthy();
    expect(screen.getByText("50.0%")).toBeTruthy();
  });

  it("renders an explicit empty evidence state", () => {
    render(<EvidenceTable rows={[]} />);
    expect(screen.getByText(/No measured evidence/)).toBeTruthy();
  });

  it("retains measured zero in a table", () => {
    render(<EvidenceTable rows={[{ metric: "hallucinations", value: 0 }]} />);
    expect(screen.getByText("hallucinations")).toBeTruthy();
    expect(screen.getByText("0")).toBeTruthy();
  });
});
