import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { Brain } from "./Brain";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
it("explores memory, filters agents and shows vectors and recent architecture", async () => {
  const fetch = vi.fn(async (path: string) => ({ ok: true, json: async () => path.includes("/minions") ? [{ id: "j1", name: "Atenea", mythology: "Griega", state: "running", task: "Consultar", target: "local" }] : path.includes("/contracts") ? [{ name: "memory.search", capability: "memory.search", parameters: { type: "object" } }] : { total: 21, items: [{ id: "m1", text: "Prefiere español", metadata: { agent: "alice" }, embedding: [0.2, -0.1] }] } }));
  vi.stubGlobal("fetch", fetch);
  render(<Brain/>);
  expect(await screen.findByText("Prefiere español")).toBeDefined();
  fireEvent.click(screen.getByText("Datos y embedding"));
  expect(screen.getByRole("img", { name: /Vector de 2/ })).toBeDefined();
  fireEvent.change(screen.getByLabelText("Agente"), { target: { value: "alice" } });
  fireEvent.click(screen.getByText("Filtrar"));
  await waitFor(() => expect(fetch.mock.calls.some(([path]) => path.includes("agent=alice"))).toBe(true));
  await screen.findByText("Prefiere español");
  fireEvent.click(screen.getByText("Siguiente"));
  await waitFor(() => expect(fetch.mock.calls.some(([path]) => path.includes("offset=20"))).toBe(true));
  fireEvent.click(screen.getByText("Herramientas nativas"));
  expect(await screen.findByText("memory.search")).toBeDefined();
  fireEvent.click(screen.getByText("Minions"));
  expect(await screen.findByText("Atenea")).toBeDefined();
  expect(screen.getByText("En marcha")).toBeDefined();
});
it("reports unavailable memory and allows retry", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce({ ok: false }).mockResolvedValue({ ok: true, json: async () => ({ total: 0, items: [] }) }));
  render(<Brain/>);
  expect(await screen.findByRole("alert")).toBeDefined();
  fireEvent.click(screen.getByText("Actualizar"));
  expect(await screen.findByText(/No hay recuerdos/)).toBeDefined();
});
