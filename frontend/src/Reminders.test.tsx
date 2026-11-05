import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Reminders } from "./Reminders";

const tools = [{ name: "usenet.history", description: "Consultar historial", input_example: {} }];
const response = (value: unknown, ok = true) => ({ ok, json: async () => value }) as Response;

describe("Recordatorios", () => {
  afterEach(cleanup);

  it("creates a time reminder using the local date converted to UTC", async () => {
    const apiFetch = vi.fn(async (path: string, init?: RequestInit) => {
      if (path.endsWith("catalog")) return response(tools);
      if (init?.method === "POST") return response({ id: "1" });
      return response([]);
    });
    render(<Reminders apiFetch={apiFetch} />);
    await screen.findByText("Todavía no hay recordatorios.");
    fireEvent.change(screen.getByLabelText("Mensaje del recordatorio"), { target: { value: "Renovar dominio" } });
    fireEvent.change(screen.getByLabelText("Fecha y hora del recordatorio"), { target: { value: "2099-04-12T14:30" } });
    fireEvent.click(screen.getByRole("button", { name: "Crear recordatorio" }));
    await screen.findByText(/Recordatorio creado/);
    const send = apiFetch.mock.calls.find(([, init]) => init?.method === "POST");
    expect(JSON.parse(String(send?.[1]?.body))).toMatchObject({
      message: "Renovar dominio", trigger: { kind: "time", at: new Date("2099-04-12T14:30").toISOString() },
      request_id: expect.any(String),
    });
    expect(screen.queryByLabelText("Frecuencia de revisión")).toBeNull();
  });

  it("previews a tool condition and saves its frequency and selected field", async () => {
    const apiFetch = vi.fn(async (path: string, init?: RequestInit) => {
      if (path.endsWith("catalog")) return response(tools);
      if (path.endsWith("preview")) return response({ matched: true, values: ["SUCCESS/ALL"], output: { items: [{ id: 42, status: "SUCCESS/ALL" }] } });
      if (init?.method === "POST") return response({ id: "2" });
      return response([]);
    });
    render(<Reminders apiFetch={apiFetch} />);
    await screen.findByText("Todavía no hay recordatorios.");
    fireEvent.change(screen.getByLabelText("Mensaje del recordatorio"), { target: { value: "Terminó la descarga" } });
    fireEvent.change(screen.getByLabelText("Disparador del recordatorio"), { target: { value: "tool" } });
    fireEvent.change(screen.getByLabelText("Campo del resultado"), { target: { value: "items[id=42].status" } });
    fireEvent.change(screen.getByLabelText("Condición del resultado"), { target: { value: "contains" } });
    fireEvent.change(screen.getByLabelText("Valor esperado"), { target: { value: "SUCCESS" } });
    fireEvent.change(screen.getByLabelText("Frecuencia de revisión"), { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: "Probar condición" }));
    await screen.findByText("La condición se cumple ahora.");
    fireEvent.click(screen.getByRole("button", { name: "Crear recordatorio" }));
    await screen.findByText(/Recordatorio creado/);
    const send = apiFetch.mock.calls.find(([path, init]) => path.endsWith("/reminders") && init?.method === "POST");
    expect(JSON.parse(String(send?.[1]?.body)).trigger).toEqual({
      kind: "tool", tool_name: "usenet.history", input: {}, interval_seconds: 180,
      condition: { path: "items[id=42].status", operator: "contains", value: "SUCCESS" },
    });
  });

  it("pauses and cancels a saved reminder", async () => {
    const item = { id: "saved-1", message: "Pendiente", trigger: { kind: "time", at: "2099-01-01T10:00:00Z" }, status: "active", next_check_at: null, last_checked_at: null, last_value: null, last_error: null };
    const apiFetch = vi.fn(async (path: string, init?: RequestInit) => {
      if (path.endsWith("catalog")) return response(tools);
      if (init?.method === "PATCH") { item.status = "paused"; return response(item); }
      if (init?.method === "DELETE") return response(null);
      return response([{ ...item }]);
    });
    render(<Reminders apiFetch={apiFetch} />);
    fireEvent.click(await screen.findByRole("button", { name: "Pausar" }));
    await screen.findByRole("button", { name: "Reanudar" });
    fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));
    await waitFor(() => expect(apiFetch.mock.calls.some(([, init]) => init?.method === "DELETE")).toBe(true));
    const patch = apiFetch.mock.calls.find(([, init]) => init?.method === "PATCH");
    expect(JSON.parse(String(patch?.[1]?.body))).toEqual({ status: "paused" });
  });
});
