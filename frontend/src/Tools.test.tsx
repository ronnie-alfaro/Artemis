import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Tools } from "./Tools";

const config = {
  settings: { enabled: true, channel: "whatsapp", recipient_id: null },
  storage_available: true, whatsapp_configured: true, recipient_available: true,
  available_recipients: ["user:owner"],
};
const response = (body: unknown, ok = true) => ({ ok, json: async () => body }) as Response;

describe("Tools · Notificaciones", () => {
  afterEach(cleanup);

  it("loads shared configuration, saves a destination and sends directly", async () => {
    const apiFetch = vi.fn(async (path: string, init?: RequestInit) => {
      if (path.endsWith("/send")) return response({ id: "1", whatsapp_status: "pending" });
      if (path.includes("/history")) return response([]);
      if (init?.method === "PUT") return response({ ...config, settings: JSON.parse(String(init.body)) });
      return response(config);
    });
    render(<Tools apiFetch={apiFetch} />);
    expect(await screen.findByText("WhatsApp conectado y destinatario disponible.")).toBeDefined();
    fireEvent.change(screen.getByLabelText("Destinatario de notificaciones"), { target: { value: "user:owner" } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar configuración" }));
    expect(await screen.findByText("Configuración guardada.")).toBeDefined();
    fireEvent.change(screen.getByLabelText("Título del aviso"), { target: { value: "Prueba" } });
    fireEvent.change(screen.getByLabelText("Mensaje del aviso"), { target: { value: "Hola desde Tools" } });
    fireEvent.click(screen.getByRole("button", { name: "Enviar notificación" }));
    expect(await screen.findByText(/Aviso en cola/)).toBeDefined();
    const send = apiFetch.mock.calls.find(([path]) => path.endsWith("/send"));
    expect(JSON.parse(String(send?.[1]?.body))).toMatchObject({ title: "Prueba", message: "Hola desde Tools", event_id: expect.any(String) });
    const save = apiFetch.mock.calls.find(([, init]) => init?.method === "PUT");
    expect(JSON.parse(String(save?.[1]?.body))).toMatchObject({ recipient_id: "user:owner" });
  });

  it("preserves delivery ID when a send fails and is retried", async () => {
    const apiFetch = vi.fn(async (path: string, init?: RequestInit) => {
      if (init?.method === "POST") return response({}, false);
      return path.includes("/history") ? response([]) : response(config);
    });
    render(<Tools apiFetch={apiFetch} />);
    await screen.findByText("WhatsApp conectado y destinatario disponible.");
    fireEvent.change(screen.getByLabelText("Mensaje del aviso"), { target: { value: "Hola" } });
    fireEvent.click(screen.getByRole("button", { name: "Enviar notificación" }));
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "Enviar notificación" }));
    await waitFor(() => expect(apiFetch.mock.calls.filter(([path]) => path.endsWith("/send"))).toHaveLength(2));
    const sends = apiFetch.mock.calls.filter(([path]) => path.endsWith("/send"));
    expect(sends[0][1]?.body).toBe(sends[1][1]?.body);
    expect(screen.queryByText(/Aviso en cola/)).toBeNull();
  });
});

describe("Tools · Webhooks", () => {
  afterEach(cleanup);

  it("opens Webhooks within Tools and returns to the shared notifications configuration", async () => {
    const apiFetch = vi.fn(async (path: string, init?: RequestInit) => {
      if (init?.method) throw new Error("Navigation must not send notifications");
      if (path === "/api/v1/webhooks/configuration") return response({
        configured: true, storage_available: true, whatsapp_enabled: true,
        whatsapp_recipient_available: true,
        docker_url: "http://artemis-api:8000/api/v1/webhooks/{source}",
      });
      if (path.includes("/history") || path.includes("/events?")) return response([]);
      return response(config);
    });
    render(<Tools apiFetch={apiFetch} />);
    await screen.findByText("WhatsApp conectado y destinatario disponible.");
    fireEvent.change(screen.getByLabelText("Mensaje del aviso"), { target: { value: "Borrador conservado" } });
    fireEvent.click(screen.getByRole("button", { name: /^Webhooks/ }));
    expect(await screen.findByText("Receptor activo. Los eventos se guardan en Artemis.")).toBeDefined();
    expect(screen.getByRole("heading", { name: "Herramientas", level: 1 })).toBeDefined();
    expect(screen.getByRole("heading", { name: "Webhooks", level: 2 })).toBeDefined();
    expect(screen.getByText("http://artemis-api:8000/api/v1/webhooks/seerr")).toBeDefined();
    fireEvent.click(screen.getByRole("button", { name: "Configurar Notificaciones" }));
    expect(screen.getByLabelText("Mensaje del aviso")).toHaveProperty("value", "Borrador conservado");
    expect(screen.queryByRole("heading", { name: "Webhooks" })).toBeNull();
    expect(apiFetch.mock.calls.every(([, init]) => !init?.method)).toBe(true);
  });
});
