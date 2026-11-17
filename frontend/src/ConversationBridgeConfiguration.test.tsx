import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { ConversationBridgeConfiguration } from "./ConversationBridgeConfiguration";

it("lets the operator choose a primary LLM and retains the prior one as fallback", async () => {
  const apiFetch = vi.fn(async (path: string, init?: RequestInit) => {
    if (init?.method === "PUT") return Response.json({ providers: ["agy", "codex"] });
    if (path.endsWith("/providers")) return Response.json({
      providers: [
        { id: "codex", label: "Codex", status: "untested" },
        { id: "agy", label: "Antigravity", status: "ready" },
      ],
      discoverable: [],
    });
    return Response.json({ providers: ["codex", "agy"], last_provider: null });
  });
  render(<ConversationBridgeConfiguration apiFetch={apiFetch} channel="whatsapp"/>);
  const primary = await screen.findByLabelText<HTMLSelectElement>("LLM principal");
  expect(primary.value).toBe("codex");
  fireEvent.change(primary, { target: { value: "agy" } });
  fireEvent.click(screen.getByRole("button", { name: "Guardar selección" }));
  await waitFor(() => expect(apiFetch).toHaveBeenCalledWith(
    "/api/v1/conversation-bridge/routing/whatsapp",
    expect.objectContaining({ method: "PUT", body: JSON.stringify({ providers: ["agy", "codex"] }) }),
  ));
  await screen.findByText("Orden de proveedores guardado.");
});
