import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { Brain } from "./Brain";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
it("explores memory, filters agents and shows vectors and recent architecture", async () => {
  const fetch = vi.fn(async (path: string) => ({ ok: true, json: async () => path.includes("/minions") ? [{ id: "j1", name: "Atenea", mythology: "Griega", state: "running", task: "Consultar", target: "local" }] : path.includes("/contracts") ? [{ name: "memory.search", capability: "memory.search", parameters: { type: "object" } }] : { total: 21, items: [{ id: "m1", text: "Prefiere español", metadata: { agent: "alice" }, embedding: [0.2, -0.1] }] } }));
  vi.stubGlobal("fetch", fetch);
  render(<Brain/>);
  fireEvent.click(screen.getByRole("button", { name: "Lista" }));
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
it("opens the memory map and scopes semantic search to the visible dates", async () => {
  const fetch = vi.fn(async (path: string, init?: RequestInit) => {
    if (path.endsWith("/explore")) {
      const body = JSON.parse(String(init?.body));
      return { ok: true, json: async () => body.text
        ? [{ id: "m1", text: "Prefiere español", distance: 0.1 }] : [] };
    }
    return { ok: true, json: async () => ({ total: 2, items: [
      { id: "m1", text: "Prefiere español", metadata: { agent: "alice", created_at: "2026-11-16T12:00:00Z" }, embedding: [0.2, -0.1] },
      { id: "m2", text: "Un recuerdo antiguo", metadata: { agent: "bob" }, embedding: [-0.2, 0.1] },
    ] }) };
  });
  vi.stubGlobal("fetch", fetch);
  render(<Brain/>);
  const point = await screen.findByRole("button", { name: "alice · Prefiere español" });
  expect(fetch.mock.calls[0][0]).toContain("/agent_memory/map");
  fireEvent.change(screen.getByLabelText("Desde"), { target: { value: "2026-11-16" } });
  expect(screen.queryByRole("button", { name: /Un recuerdo antiguo/ })).toBeNull();
  fireEvent.change(screen.getByLabelText("Buscar por significado"), { target: { value: "idioma" } });
  fireEvent.click(screen.getByRole("button", { name: "Buscar" }));
  expect(await screen.findByText("Distancia 0.100 · En el mapa")).toBeDefined();
  expect(JSON.parse(String(fetch.mock.lastCall?.[1]?.body))).toEqual({ text: "idioma", ids: ["m1"] });
  fireEvent.keyDown(point, { key: "Enter" });
  expect(await screen.findByText("No se encontraron coincidencias.")).toBeDefined();
  expect(screen.getByRole("heading", { name: "Recuerdo seleccionado" })).toBeDefined();
  expect(JSON.parse(String(fetch.mock.lastCall?.[1]?.body))).toEqual({ memory_id: "m1", ids: ["m1"] });
});
it("reports unavailable memory and allows retry", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce({ ok: false }).mockResolvedValue({ ok: true, json: async () => ({ total: 0, items: [] }) }));
  render(<Brain/>);
  expect(await screen.findByRole("alert")).toBeDefined();
  fireEvent.click(screen.getByText("Actualizar"));
  expect(await screen.findByText(/No hay recuerdos/)).toBeDefined();
});
