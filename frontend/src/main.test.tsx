import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./main";

describe("Artemis shell", () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
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
    expect(screen.getByRole("button", { name: "Save assigned skills" })).toHaveProperty("disabled", true);
  });

  it("saves only optional skills and confirms the persisted binding", async () => {
    let saved: string[] = ["assistant.status"];
    const fetchMock = vi.fn((path: string, init?: RequestInit) => {
      if (path === "/api/v1/auth/status") return Promise.resolve({ ok: true, json: async () => ({ authentication_required: false }) });
      if (path === "/api/v1/channels/whatsapp") return Promise.resolve({ ok: true, json: async () => ({ configured: true, agent_name: "primary", running: true, last_error: null }) });
      if (path.endsWith("/profile")) return Promise.resolve({ ok: true, json: async () => ({ greeting: "Hola" }) });
      if (path.endsWith("/skills") && init?.method === "PUT") {
        const payload = JSON.parse(String(init.body)) as { capabilities: string[] };
        saved = ["assistant.status", ...payload.capabilities];
        return Promise.resolve({ ok: true, json: async () => ({ capabilities: saved, available_capabilities: ["karakeep.bookmarks"] }) });
      }
      if (path.endsWith("/skills")) return Promise.resolve({ ok: true, json: async () => ({ capabilities: saved, available_capabilities: ["karakeep.bookmarks"] }) });
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);
    fireEvent.click(screen.getAllByRole("button", { name: "Agents" }).at(-1)!);
    const dropZone = (await screen.findByText("Assigned to this agent")).parentElement!;
    fireEvent.drop(dropZone, { dataTransfer: { getData: () => "karakeep.bookmarks" } });
    fireEvent.click(screen.getByRole("button", { name: "Save assigned skills" }));
    await waitFor(() => expect(screen.getByText("Assigned skills saved.")).toBeDefined());
    expect(saved).toEqual(["assistant.status", "karakeep.bookmarks"]);
    const put = fetchMock.mock.calls.find(([path, init]) => path.endsWith("/skills") && init?.method === "PUT");
    expect(JSON.parse(String(put?.[1]?.body))).toEqual({ capabilities: ["karakeep.bookmarks"] });
  });
});
