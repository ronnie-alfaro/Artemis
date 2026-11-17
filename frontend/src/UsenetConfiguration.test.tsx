import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { UsenetConfiguration } from "./UsenetConfiguration";

const configured = {
  configured: true, provider_url: "https://provider.example/api",
  nzbget_url: "https://downloads.example/xmlrpc", nzbget_username: "operator",
  provider_test: null, downloader_test: null, last_test: null,
};
afterEach(cleanup);

it("loads both connections without filling secret fields and preserves stored secrets on save", async () => {
  const apiFetch = vi.fn().mockResolvedValue({ ok: true, json: async () => configured });
  render(<UsenetConfiguration apiFetch={apiFetch}/>);
  await waitFor(() => expect(screen.getByLabelText("URL de NZBPlanet")).toHaveProperty("value", configured.provider_url));
  expect(screen.getByLabelText("Clave de API de NZBPlanet")).toHaveProperty("value", "");
  expect(screen.getByLabelText("Contraseña de NZBGet")).toHaveProperty("value", "");
  fireEvent.change(screen.getByLabelText("Usuario de NZBGet"), { target: { value: "new-user" } });
  expect(screen.getByRole("button", { name: "Probar conexiones" })).toHaveProperty("disabled", true);
  fireEvent.click(screen.getByRole("button", { name: "Guardar conexiones" }));
  await screen.findByText("Conexiones guardadas.");
  const request = apiFetch.mock.calls.find(([, init]) => init?.method === "PUT");
  expect(JSON.parse(request![1].body)).toEqual({
    provider_url: configured.provider_url, provider_api_key: null,
    nzbget_url: configured.nzbget_url, nzbget_username: "new-user", nzbget_password: null,
  });
});

it("requires both secrets on first save and displays each connection's test result", async () => {
  const apiFetch = vi.fn((path: string, init?: RequestInit) => {
    const data = init?.method === "PUT" ? configured : path.endsWith("/test")
      ? { ...configured, provider_test: "Credenciales rechazadas", downloader_test: "Conexión verificada", last_test: "Revisa el resultado de cada conexión." }
      : { ...configured, configured: false, provider_url: null, nzbget_username: null };
    return Promise.resolve({ ok: true, json: async () => data } as Response);
  });
  render(<UsenetConfiguration apiFetch={apiFetch}/>);
  await screen.findByText("Configura las dos conexiones");
  fireEvent.change(screen.getByLabelText("URL de NZBPlanet"), { target: { value: configured.provider_url } });
  fireEvent.change(screen.getByLabelText("Usuario de NZBGet"), { target: { value: "operator" } });
  expect(screen.getByRole("button", { name: "Guardar conexiones" })).toHaveProperty("disabled", true);
  fireEvent.change(screen.getByLabelText("Clave de API de NZBPlanet"), { target: { value: "provider-secret" } });
  fireEvent.change(screen.getByLabelText("Contraseña de NZBGet"), { target: { value: "download-secret" } });
  fireEvent.click(screen.getByRole("button", { name: "Guardar conexiones" }));
  await screen.findByText("Conexiones guardadas.");
  expect(screen.getByLabelText("Contraseña de NZBGet")).toHaveProperty("value", "");
  fireEvent.click(screen.getByRole("button", { name: "Probar conexiones" }));
  await screen.findByText("Buscador: Credenciales rechazadas");
  expect(screen.getByText("Gestor de descargas: Conexión verificada")).toBeDefined();
});
