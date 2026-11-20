import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { ContextMetricCharts } from "./ContextMetricCharts";

afterEach(cleanup);

it("shows the estimated total and uses only paired estimates to calculate savings", () => {
  render(<ContextMetricCharts names={{ history: "Historial" }} samples={[
    { estimated_tokens: 80, baseline_tokens: 150, sections: [{ name: "history", tokens: 50 }] },
    { estimated_tokens: 10, baseline_tokens: null, sections: [{ name: "history", tokens: 5 }] },
    { estimated_tokens: null, baseline_tokens: 100, sections: [] },
  ]}/>);

  expect(screen.getByRole("img", { name: "Reparto de tokens · Sankey" })).toBeTruthy();
  expect(screen.getByText("90")).toBeTruthy();
  expect(screen.getByText("Historial")).toBeTruthy();
  expect(screen.getByText("55")).toBeTruthy();
  expect(screen.getByText("Resto del contexto")).toBeTruthy();
  expect(screen.getByText("35")).toBeTruthy();
  expect(screen.getByText("150 tokens")).toBeTruthy();
  expect(screen.getByText("80 tokens")).toBeTruthy();
  expect(screen.getByText("70 tokens")).toBeTruthy();
});

it("preserves reported section sizes and identifies excess instead of savings", () => {
  render(<ContextMetricCharts names={{}} samples={[
    { estimated_tokens: 120, baseline_tokens: 100, sections: [{ name: "history", tokens: 125 }] },
  ]}/>);

  expect(screen.getByText(/El contexto completo se estimó en 120 tokens/)).toBeTruthy();
  expect(screen.getByText("Exceso estimado")).toBeTruthy();
  expect(screen.getByText("20 tokens")).toBeTruthy();
});
