import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { CodexConfiguration } from "./CodexConfiguration";
afterEach(cleanup);
it("shows worker connection and queued work, and handles an unavailable patch", async () => {
  const apiFetch = vi.fn((path: string) => Promise.resolve(new Response(JSON.stringify(
    path.endsWith("/configuration") ? { connected: true } : path.endsWith("/patch") ? {} : [{ id: "test-job", status: "completed", mode: "tool", prompt: "Crear herramienta de estado", answer: "Código preparado", has_patch: true, created_at: 1 }]
  ), { status: path.endsWith("/patch") ? 404 : 200 })));
  render(<CodexConfiguration apiFetch={apiFetch}/>);
  expect(await screen.findByText("Conectado")).toBeDefined();
  expect(await screen.findByText("Crear herramienta de estado")).toBeDefined();
  fireEvent.click(screen.getByText("Ver respuesta"));
  expect(screen.getByText("Código preparado")).toBeDefined();
  fireEvent.click(screen.getByRole("button", { name: "Descargar parche" }));
  expect(await screen.findByRole("alert")).toHaveProperty("textContent", "No se pudo descargar el parche.");
  expect(apiFetch.mock.calls.some(([path]) => path.endsWith("test-job/patch"))).toBe(true);
});
it("shows connection failures without presenting a successful state", async () => {
  const apiFetch = vi.fn(() => Promise.reject(new Error("offline")));
  render(<CodexConfiguration apiFetch={apiFetch}/>);
  expect(await screen.findByRole("alert")).toHaveProperty("textContent", "No se pudo consultar Codex. Inténtalo de nuevo.");
  expect(screen.queryByText("Conectado")).toBeNull();
});
