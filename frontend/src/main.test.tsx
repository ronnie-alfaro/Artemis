import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { App } from "./main";

describe("Artemis shell", () => {
  it("renders the SaaS control-plane navigation", () => {
    render(<App />);
    expect(screen.getByText("Flows")).toBeDefined();
    expect(screen.getByText("Channels")).toBeDefined();
  });
});
