import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./main";

describe("Artemis shell", () => {
  afterEach(() => vi.unstubAllGlobals());
  it("renders the SaaS control-plane navigation", () => {
    render(<App />);
    expect(screen.queryByText("Flows")).toBeNull();
    expect(screen.getByText("Channels")).toBeDefined();
  });

  it("shows typed Seerr capabilities in the Skills inspector", () => {
    render(<App />);
    const skillButtons = screen.getAllByRole("button", { name: "Skills" });
    fireEvent.click(skillButtons[skillButtons.length - 1]);
    expect(screen.getByText("search_media")).toBeDefined();
    expect(screen.getByText("create_request")).toBeDefined();
    expect(screen.getByText("WRITE")).toBeDefined();
  });

  it("shows the configured WhatsApp runtime in Agents", async () => {
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ authentication_required: false }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ configured: true, agent_name: "primary", running: true, last_error: null }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ capabilities: ["assistant.status"], available_capabilities: ["seerr.media"] }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ greeting: "Hola, soy tu asistente de WhatsApp." }),
      }));
    render(<App />);
    const agentButtons = screen.getAllByRole("button", { name: "Agents" });
    fireEvent.click(agentButtons[agentButtons.length - 1]);
    expect((await screen.findAllByText("WhatsApp Agent · primary")).length).toBe(2);
    expect(screen.getByText("healthy · whatsapp")).toBeDefined();
    expect(screen.getByLabelText("Status response")).toBeDefined();
  });
});
