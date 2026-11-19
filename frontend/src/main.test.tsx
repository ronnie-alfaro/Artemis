import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./main";

const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
let saved: string[];
let greeting: string;
let persona: string;
let requireAuth: boolean;
let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  sessionStorage.clear(); localStorage.clear(); window.history.replaceState(null, "", "/");
  saved = ["assistant.status"]; greeting = "Hola, soy Artemis."; persona = "Eres Artemis, cercano y claro."; requireAuth = false;
  fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (path === "/api/v1/auth/status") return Promise.resolve(response({ authentication_required: requireAuth }));
    if (path === "/api/v1/health") return Promise.resolve(response({ status: "ok" }));
    if (requireAuth && !new Headers(init?.headers).get("Authorization")?.includes("correct-token")) return Promise.resolve(response({}, 401));
    if (path === "/api/v1/channels/telegram") return Promise.resolve(response({ configured: false, running: false, agent_name: null, last_error: null }));
    if (path === "/api/v1/channels/whatsapp") return Promise.resolve(response({ configured: true, running: true, agent_name: "primary", last_error: null }));
    if (path.endsWith("/profile")) { if (init?.method === "PUT") { const body = JSON.parse(String(init.body)); if (body.greeting !== undefined) greeting = body.greeting; if (body.persona !== undefined) persona = body.persona; } return Promise.resolve(response({ greeting, persona })); }
    if (path.endsWith("/skills") && path.includes("/agents/")) {
      if (init?.method === "PUT") saved = ["assistant.status", ...JSON.parse(String(init.body)).capabilities];
      return Promise.resolve(response({ capabilities: saved, available_capabilities: ["seerr.media", "karakeep.bookmarks", "usenet.downloads"] }));
    }
    if (path.endsWith("/skills/presentations")) return Promise.resolve(response({ seerr: { name: "Seerr", description: "Películas y series" }, karakeep: { name: "Karakeep", description: "Marcadores" }, usenet: { name: "Usenet", description: "Descargas" } }));
    if (path.includes("/skills/") && path.endsWith("/configuration")) return Promise.resolve(response({ configured: false, base_url: null, credential_source: null, last_test: null }));
    if (path === "/api/v1/tools/notifications/configuration") return Promise.resolve(response({ settings: { enabled: true, channel: "whatsapp", recipient_id: null }, storage_available: true, whatsapp_configured: true, recipient_available: true, available_recipients: [] }));
    if (path === "/api/v1/webhooks/configuration") return Promise.resolve(response({ configured: true, storage_available: true, whatsapp_enabled: true, whatsapp_recipient_available: true, docker_url: "http://artemis-api:8000/api/v1/webhooks/{source}" }));
    if (path.startsWith("/api/v1/tools/") || path.startsWith("/api/v1/webhooks/events")) return Promise.resolve(response([]));
    return Promise.resolve(response({}, 404));
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("Artemis en español", () => {
  it("shows Spanish navigation and removes executions and approval pages", async () => {
    render(<App/>);
    const nav = await screen.findByRole("navigation", { name: "Navegación principal" });
    expect(within(nav).getAllByRole("button").map(item => item.getAttribute("aria-label"))).toEqual(["Inicio", "Agentes", "Habilidades", "Herramientas", "Cerebro", "Context Builder", "Canales", "Ajustes"]);
    expect(screen.queryByText("Runs")).toBeNull(); expect(screen.queryByText("Approvals")).toBeNull();
    expect(screen.queryByRole("button", { name: "Webhooks" })).toBeNull();
    expect(await screen.findByRole("heading", { name: "Consola de administración", level: 1 })).toBeDefined();
  });

  it("shows only the existing Artemis logo followed by the console title", async () => {
    const { container } = render(<App/>);
    const title = await screen.findByRole("heading", { name: "Consola de administración", level: 1 });
    const heading = title.parentElement!;
    const logo = within(heading).getByRole("img", { name: "Artemis" });
    expect(logo.getAttribute("src")).toBe("/images/arty_final.png");
    expect([...heading.children]).toEqual([logo, title]);
    expect(container.querySelectorAll(".artemis-mascot canvas")).toHaveLength(2);
  });

  it("places WhatsApp Curiosidad under Meta Habilidades", async () => {
    window.location.hash = "#/curiosidad";
    render(<App/>);
    expect(await screen.findByRole("heading", { name: "Meta Habilidades" })).toBeDefined();
    expect(screen.getByRole("heading", { name: "Curiosidad" })).toBeDefined();
    expect(screen.getByText("Aprende esta API URL_OPENAPI_JSON")).toBeDefined();
  });

  it("shows learning and finished jobs alongside notifications on Inicio", async () => {
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/api/v1/activity/memories") return Promise.resolve(response([
        { id: "learn", text: "Aprendí a usar Curiosidad.", metadata: { kind: "learning", created_at: "2026-01-01T00:00:00Z" } },
      ]));
      if (path === "/api/v1/skills/codex/jobs") return Promise.resolve(response([
        { id: "job", status: "completed", created_at: 1767225600 },
      ]));
      if (path.includes("/notifications/history")) return Promise.resolve(response([
        { id: "notice", title: "Película disponible", source: "seerr", whatsapp_status: "sent", received_at: "2026-01-01T00:00:00Z" },
      ]));
      if (path.endsWith("/jobs") || path.endsWith("/reminders")) return Promise.resolve(response([]));
      return Promise.resolve(response({}));
    });
    render(<App/>);
    expect(await screen.findByText("Aprendí a usar Curiosidad.")).toBeDefined();
    expect(screen.getByText("Artemis completó una tarea")).toBeDefined();
    expect(screen.getByText("Película disponible")).toBeDefined();
    expect(screen.queryByText(/Cualquier forma, sensación/)).toBeNull();
  });

  it("shows Telegram in Channels before the bot is configured", async () => {
    render(<App/>);
    fireEvent.click(await screen.findByRole("button", { name: "Canales" }));
    expect(await screen.findByRole("heading", { name: "Telegram" })).toBeDefined();
    expect(await screen.findByText("Conexión de Telegram")).toBeDefined();
    expect(screen.getByRole("heading", { name: "WhatsApp" })).toBeDefined();
  });

  it("opens the matching agent from Channels and keeps drafts while switching agents", async () => {
    render(<App/>);
    fireEvent.click(await screen.findByRole("button", { name: "Canales" }));
    fireEvent.click(await screen.findByRole("button", { name: "Configurar agente de Telegram" }));
    const switcher = within(await screen.findByRole("group", { name: "Canal del agente" }));
    expect(window.location.hash).toBe("#/agentes/telegram");
    expect(switcher.getByRole("button", { name: "Telegram" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.queryByRole("region", { name: "Agente de WhatsApp" })).toBeNull();

    fireEvent.click(switcher.getByRole("button", { name: "WhatsApp" }));
    const field = await screen.findByRole("textbox", { name: "PERSONA de WhatsApp" });
    await waitFor(() => expect(field).toHaveProperty("value", persona));
    fireEvent.change(field, { target: { value: "Borrador del agente" } });
    fireEvent.click(switcher.getByRole("button", { name: "Telegram" }));
    fireEvent.click(switcher.getByRole("button", { name: "WhatsApp" }));
    expect(screen.getByRole("textbox", { name: "PERSONA de WhatsApp" })).toHaveProperty("value", "Borrador del agente");
  });

  it("keeps translated skill connections and operations available", async () => {
    render(<App/>);
    fireEvent.click(await screen.findByRole("button", { name: "Habilidades" }));
    expect(await screen.findByLabelText("URL de Seerr")).toBeDefined();
    fireEvent.click(screen.getByText(/Ver operaciones disponibles/));
    expect(screen.getByText("Buscar títulos")).toBeDefined();
    expect(screen.getByText("Solicitar título")).toBeDefined();
    expect(screen.getByText("Ver pendientes")).toBeDefined();
    expect(screen.getByText("API de Seerr")).toBeDefined();
    expect(screen.getAllByText("Modifica datos").length).toBeGreaterThan(0);
  });

  it("preserves skill binding by drag and drop and only persists optional capabilities", async () => {
    render(<App/>);
    fireEvent.click(await screen.findByRole("button", { name: "Agentes" }));
    expect(await screen.findByLabelText("PERSONA de WhatsApp")).toBeDefined();
    const button = screen.getByRole("button", { name: "Guardar habilidades asignadas" });
    expect(button).toHaveProperty("disabled", true);
    const zone = screen.getByText("Asignadas al agente").parentElement!;
    fireEvent.drop(zone, { dataTransfer: { getData: () => "karakeep.bookmarks" } });
    fireEvent.click(button);
    await screen.findByText("Habilidades asignadas guardadas.");
    expect(saved).toEqual(["assistant.status", "karakeep.bookmarks"]);
    const put = fetchMock.mock.calls.find(([path, init]) => String(path).endsWith("/skills") && init?.method === "PUT");
    expect(JSON.parse(String(put?.[1].body))).toEqual({ capabilities: ["karakeep.bookmarks"] });
  });

  it("supports keyboard-friendly assignment of skills", async () => {
    render(<App/>);
    fireEvent.click(await screen.findByRole("button", { name: "Agentes" }));
    await screen.findByLabelText("PERSONA de WhatsApp");
    fireEvent.click(screen.getByRole("button", { name: "Buscar y guardar enlaces · Karakeep" }));
    expect(screen.getByRole("button", { name: "Guardar habilidades asignadas" })).toHaveProperty("disabled", false);
  });

  it("saves the bot PERSONA for natural conversation", async () => {
    render(<App/>);
    fireEvent.click(await screen.findByRole("button", { name: "Agentes" }));
    const field = await screen.findByLabelText("PERSONA de WhatsApp");
    fireEvent.change(field, { target: { value: "Hablas como un pirata amable." } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar PERSONA" }));
    await screen.findByText("PERSONA guardada. Se aplicará al próximo mensaje.");
    expect(persona).toBe("Hablas como un pirata amable.");
    expect(screen.queryByText(/Usa «utiliza HABILIDAD»/)).toBeNull();
  });

  it("opens reminders directly from the command palette", async () => {
    render(<App/>);
    await screen.findByRole("navigation");
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const dialog = await screen.findByRole("dialog", { name: "Buscar en Artemis" });
    const field = within(dialog).getByLabelText("Buscar sección o herramienta");
    fireEvent.change(field, { target: { value: "recordatorios" } });
    fireEvent.keyDown(field, { key: "Enter" });
    expect(await screen.findByLabelText("Mensaje del recordatorio")).toBeDefined();
    expect(window.location.hash).toBe("#/herramientas/reminders");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(fetchMock.mock.calls.every(([, init]) => !init?.method)).toBe(true);
  });

  it("persists theme and reduced-motion settings", async () => {
    render(<App/>);
    fireEvent.click(await screen.findByRole("button", { name: "Ajustes" }));
    fireEvent.click(screen.getByRole("button", { name: "Tema oscuro" }));
    fireEvent.click(screen.getByRole("button", { name: "Menos movimiento" }));
    await waitFor(() => expect(document.documentElement.dataset.theme).toBe("dark"));
    expect(document.documentElement.dataset.motion).toBe("reduced");
    expect(JSON.parse(localStorage.getItem("artemis_preferences")!)).toMatchObject({ theme: "dark", motion: "reduced" });
  });

  it("requires a valid token before opening an authenticated workspace", async () => {
    requireAuth = true;
    render(<App/>);
    const token = await screen.findByLabelText("Clave de acceso");
    fireEvent.change(token, { target: { value: "wrong" } });
    fireEvent.click(screen.getByRole("button", { name: "Entrar a Artemis" }));
    await screen.findByRole("alert");
    expect(sessionStorage.getItem("artemis_admin_token")).toBeNull();
    fireEvent.change(token, { target: { value: "correct-token" } });
    fireEvent.click(screen.getByRole("button", { name: "Entrar a Artemis" }));
    await screen.findByRole("navigation");
    expect(sessionStorage.getItem("artemis_admin_token")).toBe("correct-token");
  });
});
