import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ChannelConfiguration } from "./ChannelConfiguration";

const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const saved = { configured: true, enabled: true, editable: true, credential_source: "control plane", agent_name: "123", allowed_user_ids: [42] };
afterEach(() => { cleanup(); vi.unstubAllGlobals(); sessionStorage.clear(); });

it("preserves a saved token when applying authorized users and clears newly entered tokens", async () => {
  const requests: RequestInit[] = [];
  vi.stubGlobal("fetch", vi.fn((_path, init?: RequestInit) => {
    if (init?.method === "PUT") requests.push(init);
    return Promise.resolve(response(saved));
  }));
  const applied = vi.fn();
  render(<ChannelConfiguration provider="telegram" onApplied={applied}/>);
  const field = await screen.findByLabelText("Usuarios autorizados de Telegram");
  expect((screen.getByLabelText("Token de Telegram") as HTMLInputElement).value).toBe("");
  fireEvent.change(field, { target: { value: "42, 99" } });
  fireEvent.click(screen.getByRole("button", { name: "Guardar y aplicar" }));
  await screen.findByText("Configuración guardada y aplicada.");
  expect(JSON.parse(String(requests[0].body))).toMatchObject({ token: null, allowed_user_ids: [42, 99] });
  fireEvent.change(screen.getByLabelText("Token de Telegram"), { target: { value: "123:replacement" } });
  fireEvent.click(screen.getByRole("button", { name: "Guardar y aplicar" }));
  await waitFor(() => expect(applied).toHaveBeenCalledTimes(2));
  expect((screen.getByLabelText("Token de Telegram") as HTMLInputElement).value).toBe("");
});

it("rejects invalid IDs and keeps failures visible without claiming success", async () => {
  const mock = vi.fn((_path, init?: RequestInit) => Promise.resolve(response(saved, init?.method === "PUT" ? 503 : 200)));
  vi.stubGlobal("fetch", mock);
  const applied = vi.fn();
  render(<ChannelConfiguration provider="telegram" onApplied={applied}/>);
  const field = await screen.findByLabelText("Usuarios autorizados de Telegram");
  fireEvent.change(field, { target: { value: "@username" } });
  fireEvent.click(screen.getByRole("button", { name: "Guardar y aplicar" }));
  await screen.findByText(/Introduce identificadores numéricos/);
  expect(mock).toHaveBeenCalledTimes(1);
  fireEvent.change(field, { target: { value: "42" } });
  fireEvent.click(screen.getByRole("button", { name: "Guardar y aplicar" }));
  await screen.findByText(/No se pudo aplicar/);
  expect(applied).not.toHaveBeenCalled();
});
