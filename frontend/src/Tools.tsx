import { useEffect, useRef, useState } from "react";
import { Webhooks } from "./Webhooks";
import { Reminders } from "./Reminders";
import { Icon, PageHeader } from "./ui";
import "./tools.css";

type ToolId = "notifications" | "webhooks" | "reminders";
type Props = {
  apiFetch: (path: string, init?: RequestInit) => Promise<Response>;
  activeTool?: ToolId;
  onSelectTool?: (tool: ToolId) => void;
};
type Settings = { enabled: boolean; channel: "whatsapp"; recipient_id: string | null };
type Configuration = {
  settings: Settings; storage_available: boolean; whatsapp_configured: boolean;
  recipient_available: boolean; available_recipients: string[];
};
type Notification = {
  id: string; source: string; event: string; title: string; message: string;
  received_at: string; whatsapp_status: string; whatsapp_error: string | null;
};
const sourceLabels: Record<string, string> = { manual: "Envíos directos", reminders: "Recordatorios", seerr: "Seerr" };
const statuses: Record<string, string> = {
  pending: "En cola", sending: "Enviando", sent: "Enviado a WhatsApp", retry: "Pendiente de reintento",
  not_requested: "Guardado sin envío",
};

export function Tools({ apiFetch, activeTool, onSelectTool }: Props) {
  const [localTool, setLocalTool] = useState<ToolId>("notifications");
  const selectedTool = activeTool ?? localTool;
  const selectTool = (tool: ToolId) => { setLocalTool(tool); onSelectTool?.(tool); };
  return <>
    <PageHeader eyebrow="PIEZAS QUE TRABAJAN JUNTAS" title="Herramientas" description="Recibe eventos, envía avisos y deja que el tiempo haga su parte."/>
    <section className="panel tools-inventory" aria-label="Herramientas disponibles">
      <button aria-label="Notificaciones" className={selectedTool === "notifications" ? "tool-selected" : ""} aria-pressed={selectedTool === "notifications"} onClick={() => selectTool("notifications")}><span className="tool-card-icon mint"><Icon name="bell"/></span><span className="tool-card-kind">SALIDA</span><strong>Notificaciones</strong><small>Envía avisos desde habilidades, webhooks o directamente</small></button>
      <button aria-label="Webhooks" className={selectedTool === "webhooks" ? "tool-selected" : ""} aria-pressed={selectedTool === "webhooks"} onClick={() => selectTool("webhooks")}><span className="tool-card-icon violet"><Icon name="webhook"/></span><span className="tool-card-kind">ENTRADA</span><strong>Webhooks</strong><small>Recibe eventos y reutiliza Notificaciones para enviar avisos</small></button>
      <button aria-label="Recordatorios" className={selectedTool === "reminders" ? "tool-selected" : ""} aria-pressed={selectedTool === "reminders"} onClick={() => selectTool("reminders")}><span className="tool-card-icon amber"><Icon name="clock"/></span><span className="tool-card-kind">AUTOMATIZACIÓN</span><strong>Recordatorios</strong><small>Un mensaje y un disparador por tiempo o resultado de una herramienta</small></button>
    </section>
    <div hidden={selectedTool !== "notifications"}><NotificationsTool apiFetch={apiFetch} /></div>
    {selectedTool === "reminders" && <Reminders apiFetch={apiFetch} />}
    {selectedTool === "webhooks" && <Webhooks apiFetch={apiFetch} embedded onOpenNotifications={() => selectTool("notifications")} />}
  </>;
}

function NotificationsTool({ apiFetch }: Props) {
  const [configuration, setConfiguration] = useState<Configuration | null>(null);
  const [settings, setSettings] = useState<Settings>({ enabled: true, channel: "whatsapp", recipient_id: null });
  const [knownSources, setKnownSources] = useState(Object.keys(sourceLabels));
  const [source, setSource] = useState("");
  const [history, setHistory] = useState<Notification[]>([]);
  const [title, setTitle] = useState("");
  const [message, setMessage] = useState("");
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [sending, setSending] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [historyError, setHistoryError] = useState("");
  const deliveryId = useRef<string | null>(null);

  useEffect(() => {
    let active = true;
    void apiFetch("/api/v1/tools/notifications/configuration").then(async response => {
      if (!response.ok) throw new Error("load");
      const value = await response.json() as Configuration;
      if (active) { setConfiguration(value); setSettings(value.settings); }
    }).catch(() => { if (active) setError("No se pudo cargar la configuración de Notificaciones."); });
    return () => { active = false; };
  }, [apiFetch]);

  useEffect(() => {
    let active = true;
    setHistoryError("");
    void apiFetch(`/api/v1/tools/notifications/history?limit=50${source ? `&source=${encodeURIComponent(source)}` : ""}`).then(async response => {
      if (!response.ok) throw new Error("history");
      const items = await response.json() as Notification[];
      if (active) {
        setHistory(items);
        setKnownSources(previous => [...new Set([...previous, ...items.map(item => item.source)])]);
      }
    }).catch(() => { if (active) setHistoryError("No se pudo cargar el historial."); });
    return () => { active = false; };
  }, [apiFetch, refresh, source]);

  const save = async () => {
    setSaving(true); setError(""); setStatus("");
    try {
      const response = await apiFetch("/api/v1/tools/notifications/configuration", {
        method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(settings),
      });
      if (!response.ok) throw new Error("save");
      const value = await response.json() as Configuration;
      setConfiguration(value); setSettings(value.settings); setStatus("Configuración guardada.");
    } catch { setError("No se pudo guardar. Elige una conversación registrada y vuelve a intentar."); }
    finally { setSaving(false); }
  };

  const send = async () => {
    setSending(true); setError(""); setStatus("");
    try {
      deliveryId.current ??= crypto.randomUUID?.() ?? crypto.getRandomValues(new Uint32Array(4)).join("-");
      const response = await apiFetch("/api/v1/tools/notifications/send", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: title.trim(), message: message.trim(), event: "notification.manual", event_id: deliveryId.current }),
      });
      if (!response.ok) throw new Error("send");
      setStatus("Aviso en cola. Puedes consultar su estado en el historial.");
      setTitle(""); setMessage(""); deliveryId.current = null;
      setRefresh(value => value + 1);
    } catch { setError("No se pudo confirmar el envío. Puedes reintentar; conservaremos el identificador para evitar duplicados."); }
    finally { setSending(false); }
  };

  const ready = configuration?.storage_available && configuration.whatsapp_configured && configuration.settings.enabled;
  return <>
    <h2 className="tool-heading">Notificaciones</h2>
    <p className="tool-description">Consulta avisos de habilidades, recordatorios, webhooks y envíos directos.</p>
    <div className="notification-grid">
      <section className="panel notification-settings">
        <h3>Configuración</h3>
        <label className="notification-toggle"><input type="checkbox" aria-label="Activar notificaciones" checked={settings.enabled} onChange={event => setSettings(previous => ({ ...previous, enabled: event.target.checked }))} />Activar notificaciones</label>
        <label>Canal<select aria-label="Canal de notificaciones" value={settings.channel} disabled><option value="whatsapp">WhatsApp</option></select></label>
        <label>Destinatario<select aria-label="Destinatario de notificaciones" value={settings.recipient_id ?? ""} onChange={event => setSettings(previous => ({ ...previous, recipient_id: event.target.value || null }))}>
          <option value="">Automático · única conversación registrada</option>
          {(configuration?.available_recipients ?? []).map(recipient => <option value={recipient} key={recipient}>{recipient}</option>)}
        </select></label>
        <p>{!configuration ? "Cargando configuración…" : !configuration.whatsapp_configured ? "Configura WhatsApp en Artemis para enviar avisos." : configuration.recipient_available ? "WhatsApp conectado y destinatario disponible." : "Escribe al agente de WhatsApp para registrar tu conversación o selecciona un destinatario."}</p>
        <button onClick={save} className="primary" disabled={saving || !configuration?.storage_available}>{saving ? "Guardando…" : "Guardar configuración"}</button>
      </section>
      <section className="panel notification-send">
        <h3>Enviar aviso</h3><p>Usa Notificaciones directamente, sin activar una habilidad.</p>
        <label>Título<input aria-label="Título del aviso" maxLength={512} value={title} disabled={sending} onChange={event => { setTitle(event.target.value); deliveryId.current = null; }} /></label>
        <label>Mensaje<textarea aria-label="Mensaje del aviso" maxLength={4096} value={message} disabled={sending} onChange={event => { setMessage(event.target.value); deliveryId.current = null; }} /></label>
        <button className="primary" onClick={send} disabled={sending || !ready || (!title.trim() && !message.trim())}>{sending ? "Enviando…" : "Enviar notificación"}</button>
      </section>
    </div>
    {status && <p role="status">{status}</p>}{error && <p role="alert">{error}</p>}
    <section className="panel notification-history">
      <div className="notification-history-head"><h3>Historial de notificaciones</h3><button onClick={() => setRefresh(value => value + 1)}>Actualizar historial</button></div>
      <label>Origen<select value={source} onChange={event => { setHistory([]); setSource(event.target.value); }}>
        <option value="">Todos los orígenes</option>
        {knownSources.map(id =>
          <option key={id} value={id}>{sourceLabels[id] ?? id}</option>)}
      </select></label>
      {historyError && <p role="alert">{historyError}</p>}
      {!historyError && history.length === 0 && <p>{source ? "No hay avisos de este origen." : "Todavía no hay notificaciones."}</p>}
      {!historyError && history.map(item => <article key={item.id}>
        <div><strong>{item.source === "manual" ? "Envío directo" : sourceLabels[item.source] ?? item.source}</strong><span>{statuses[item.whatsapp_status] ?? item.whatsapp_status}</span><time dateTime={item.received_at}>{new Date(item.received_at).toLocaleString("es-ES")}</time></div>
        {item.title && <h3>{item.title}</h3>}<p>{item.message}</p>{item.whatsapp_error && <p>{item.whatsapp_error}</p>}
      </article>)}
    </section>
  </>;
}
