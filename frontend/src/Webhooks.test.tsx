import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Webhooks } from "./Webhooks";

const config = { whatsapp_enabled: true, whatsapp_recipient_available: true, configured: true, storage_available: true, docker_url: "http://artemis-api:8000/api/v1/webhooks/{source}" };
const event = { id: "event-1", whatsapp_status: "sent", whatsapp_error: null, source: "seerr", event: "MEDIA_AVAILABLE", title: "Dune", message: "Ya disponible", received_at: "2026-11-04T12:00:00Z" };
const response = (body: unknown) => ({ ok: true, json: async () => body }) as Response;

describe("Webhook events", () => {
  afterEach(cleanup);

  it("shows received events and Docker setup instructions", async () => {
    const apiFetch = vi.fn(async (path: string) => response(path.endsWith("configuration") ? config : [event]));
    render(<Webhooks apiFetch={apiFetch} />);
    expect(await screen.findByText("Dune")).toBeDefined();
    expect(screen.getByText("Ya disponible")).toBeDefined();
    expect(screen.getByText("Enviado a WhatsApp")).toBeDefined();
    expect(screen.getByText("Avisos por WhatsApp activos para tu conversación.")).toBeDefined();
    expect(screen.getByText("seerr · MEDIA_AVAILABLE")).toBeDefined();
    expect(screen.getByText("http://artemis-api:8000/api/v1/webhooks/seerr")).toBeDefined();
    expect(screen.getByText("Receptor activo. Los eventos se guardan en Artemis.")).toBeDefined();
    fireEvent.change(screen.getByLabelText("Filtrar eventos por app"), { target: { value: "backups" } });
    await waitFor(() => expect(apiFetch.mock.calls.some(([path]) => path.includes("source=backups"))).toBe(true));
  });

  it("shows a load failure instead of claiming the inbox is empty", async () => {
    const apiFetch = vi.fn(async () => ({ ok: false }) as Response);
    render(<Webhooks apiFetch={apiFetch} />);
    expect(await screen.findByRole("alert")).toBeDefined();
    expect(screen.queryByText("Todavía no hay eventos para esta selección.")).toBeNull();
  });

  it("explains disabled ingestion and allows refreshing an empty inbox", async () => {
    const apiFetch = vi.fn(async (path: string) => response(path.endsWith("configuration") ? { ...config, configured: false } : []));
    render(<Webhooks apiFetch={apiFetch} />);
    expect(await screen.findByText("Todavía no hay eventos para esta selección.")).toBeDefined();
    expect(screen.getByText(/Configura ARTEMIS_WEBHOOK_TOKEN/)).toBeDefined();
    fireEvent.click(screen.getByRole("button", { name: "Actualizar" }));
    await waitFor(() => expect(apiFetch).toHaveBeenCalledTimes(4));
  });
});
