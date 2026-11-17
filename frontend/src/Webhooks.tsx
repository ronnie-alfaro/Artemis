import { useEffect, useState } from "react";
import "./webhooks.css";

type Props = {
  apiFetch: (path: string, init?: RequestInit) => Promise<Response>;
  embedded?: boolean;
  onOpenNotifications?: () => void;
};
type Configuration = { configured: boolean; storage_available: boolean; docker_url: string; whatsapp_enabled: boolean; whatsapp_recipient_available: boolean };
type Event = {
  id: string; source: string; event: string; title: string; message: string; received_at: string; whatsapp_status: string; whatsapp_error: string | null;
};

export function Webhooks({ apiFetch, embedded = false, onOpenNotifications }: Props) {
  const [configuration, setConfiguration] = useState<Configuration | null>(null);
  const [events, setEvents] = useState<Event[]>([]);
  const [source, setSource] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    setLoading(true); setError("");
    const query = new URLSearchParams({ limit: "50" });
    if (source.trim()) query.set("source", source.trim());
    void Promise.all([
      apiFetch("/api/v1/webhooks/configuration"),
      apiFetch(`/api/v1/webhooks/events?${query}`),
    ]).then(async ([configResponse, eventsResponse]) => {
      if (!configResponse.ok || !eventsResponse.ok) throw new Error("load");
      const config = await configResponse.json() as Configuration;
      const items = await eventsResponse.json() as Event[];
      if (active) { setConfiguration(config); setEvents(items); }
    }).catch(() => {
      if (active) setError("No se pudieron cargar los eventos. Revisa la conexión y PostgreSQL.");
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [apiFetch, source, refresh]);

  return <>
    {embedded ? <h2>Webhooks</h2> : <header><p>EVENTOS DE TUS APLICACIONES</p><div className="head"><h1>Webhooks</h1></div></header>}
    <section className="panel webhook-setup">
      <h3>Recibir eventos</h3>
      <p>Webhooks recibe los eventos de tus aplicaciones y reutiliza la herramienta Notificaciones para enviarlos al destino configurado.</p>
      {onOpenNotifications && <button onClick={onOpenNotifications}>Configurar Notificaciones</button>}
      <p>{!configuration ? "Consultando configuración…" : configuration.configured && configuration.storage_available
        ? "Receptor activo. Los eventos se guardan en Artemis."
        : "Configura ARTEMIS_WEBHOOK_TOKEN en el despliegue y reinicia la API para activar el receptor."}</p>
      {configuration && <p>{configuration.whatsapp_enabled
        ? configuration.whatsapp_recipient_available
          ? "Avisos por WhatsApp activos para tu conversación."
          : "Los avisos esperan un destino de WhatsApp. Escribe al agente; si hay varias conversaciones, configura el destinatario."
        : "Activa Notificaciones y configura WhatsApp para enviar avisos."}</p>}
      <p>Las aplicaciones deben compartir una red Docker con Artemis. En Seerr, abre Ajustes → Notificaciones → Webhook.</p>
      <label>URL para Seerr<code>{configuration?.docker_url.replace("{source}", "seerr") ?? "http://artemis-api:8000/api/v1/webhooks/seerr"}</code></label>
      <label>Autorización<code>Bearer TU_TOKEN_DE_WEBHOOK</code></label>
      <label>Plantilla JSON para Seerr<pre>{JSON.stringify({ notification_type: "{{notification_type}}", subject: "{{subject}}", message: "{{message}}" }, null, 2)}</pre></label>
      <p>Para otra app, cambia «seerr» por su nombre en la URL y envía un JSON con «event», «title» y «message». Añade un «event_id» único para evitar duplicados al reintentar.</p>
    </section>
    <section className="panel webhook-feed">
      <div className="webhook-toolbar"><h3>Últimos eventos</h3>
        <label>Filtrar por app<input aria-label="Filtrar eventos por app" value={source} placeholder="Todas · seerr, backups…" onChange={event => setSource(event.target.value)} /></label>
        <button onClick={() => setRefresh(value => value + 1)} disabled={loading}>Actualizar</button>
      </div>
      {loading && <p role="status">Cargando eventos…</p>}
      {error && <p role="alert">{error}</p>}
      {!loading && !error && events.length === 0 && <p>Todavía no hay eventos para esta selección.</p>}
      {!error && events.map(event => <article className="webhook-event" key={event.id}>
        <div><strong>{event.source} · {event.event}</strong><time dateTime={event.received_at}>{new Date(event.received_at).toLocaleString("es-ES")}</time></div>
        <small>{({ pending: "En cola para WhatsApp", sending: "Enviando a WhatsApp", sent: "Enviado a WhatsApp", retry: "Pendiente de reintento en WhatsApp", not_requested: "Guardado en Artemis" } as Record<string, string>)[event.whatsapp_status] ?? "Guardado en Artemis"}</small>
        {event.whatsapp_error && <p>{event.whatsapp_error}</p>}
        {event.title && <h3>{event.title}</h3>}<p>{event.message}</p>
      </article>)}
    </section>
  </>;
}
