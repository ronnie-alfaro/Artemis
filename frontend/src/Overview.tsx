import { useEffect, useState } from "react";
import { apiFetch, dateTime } from "./api";
import { Icon, StatusTag } from "./ui";
import { PixelScene } from "./pixel/PixelScene";

type Navigate = (view: "Overview" | "Agents" | "Skills" | "Tools" | "Channels" | "Settings", tool?: "notifications" | "webhooks" | "reminders") => void;
type Event = { id: string; title: string; message: string; source: string; whatsapp_status: string; received_at: string };
type Reminder = { id: string; message: string; status: string; next_check_at: string | null };
type Channel = { configured: boolean; running: boolean; last_error: string | null };
type Snapshot = { events: Event[] | null; reminders: Reminder[] | null; channel: Channel | null; services: Record<string, boolean | null>; refreshed: Date | null };
const initial: Snapshot = { events: null, reminders: null, channel: null, services: { seerr: null, karakeep: null, usenet: null, codex: null, antigravity: null }, refreshed: null };
const eventLabels: Record<string, string> = { sent: "Enviado", pending: "En cola", sending: "Enviando", retry: "Reintentando", not_requested: "Registrado" };
const origins: Record<string, string> = { reminders: "Recordatorios", manual: "Envío directo" };

export function Overview({ navigate, light }: {
  navigate: Navigate; light: boolean;
}) {
  const [snapshot, setSnapshot] = useState<Snapshot>(initial);
  const [refresh, setRefresh] = useState(0);
  const [refreshing, setRefreshing] = useState(true);
  useEffect(() => {
    let active = true;
    const load = async () => {
      setRefreshing(true);
      const paths = ["/api/v1/tools/notifications/history?limit=50", "/api/v1/tools/reminders", "/api/v1/channels/whatsapp", ...["seerr", "karakeep", "usenet", "codex", "antigravity"].map(id => `/api/v1/skills/${id}/configuration`)];
      const results = await Promise.allSettled(paths.map(async path => {
        const response = await apiFetch(path);
        if (!response.ok) throw new Error("unavailable");
        return response.json();
      }));
      if (!active) return;
      const data = results.map(result => result.status === "fulfilled" ? result.value : null);
      setSnapshot({ events: data[0], reminders: data[1], channel: data[2], services: Object.fromEntries(["seerr", "karakeep", "usenet", "codex", "antigravity"].map((id, index) => [id, data[index + 3]?.configured ?? null])), refreshed: new Date() });
      setRefreshing(false);
    };
    void load();
    const timer = window.setInterval(() => { void load(); }, 30000);
    return () => { active = false; window.clearInterval(timer); };
  }, [refresh]);
  const configured = Object.values(snapshot.services).filter(value => value === true).length;
  const serviceCount = Object.keys(snapshot.services).length;
  const verified = Object.values(snapshot.services).filter(value => value !== null).length;
  const activeReminders = snapshot.reminders?.filter(item => item.status === "active") ?? [];
  const upcoming = activeReminders.filter(item => item.next_check_at).sort((a, b) => Date.parse(a.next_check_at!) - Date.parse(b.next_check_at!)).slice(0, 3);
  const pending = snapshot.events?.filter(event => ["pending", "sending", "retry"].includes(event.whatsapp_status)).length;
  const channelLive = snapshot.channel?.configured && snapshot.channel.running;
  const metrics = [
    { icon: "skills" as const, label: "Habilidades configuradas", value: verified ? `${configured} / ${serviceCount}` : "—", note: verified < serviceCount ? "Verificación parcial" : "Tus servicios personales", view: "Skills" as const, tone: "violet" },
    { icon: "clock" as const, label: "Recordatorios activos", value: snapshot.reminders ? String(activeReminders.length) : "—", note: "El tiempo también trabaja para ti", view: "Tools" as const, tool: "reminders" as const, tone: "mint" },
    { icon: "bell" as const, label: "Avisos pendientes", value: pending === undefined ? "—" : String(pending), note: "En las últimas 50 notificaciones", view: "Tools" as const, tool: "notifications" as const, tone: "amber" },
  ];
  return <div className="overview">
    <div className="overview-intro"><div><p className="eyebrow"><span/>Acceso Omega</p><h1>Consola de Administracion</h1><p>Menos pestañas. Más cosas pasando por ti.</p></div><button className="subtle-button" disabled={refreshing} onClick={() => setRefresh(value => value + 1)}><Icon name="bolt" size={16}/>{refreshing ? "Sincronizando…" : "Sincronizar"}</button></div>
    <section className="command-hero">
      <div className="hero-copy"><StatusTag tone={channelLive ? "good" : "neutral"}>{channelLive ? "WhatsApp en marcha" : snapshot.channel?.configured ? "WhatsApp iniciando" : "Artemis platform - Admin Console"}</StatusTag><p className="hero-kicker">ARTEMIS / EN TU FRECUENCIA</p><h2 className="hero-quote">«Cualquier forma, sensación, percepción, formación mental o conciencia —pasada, futura o presente, interna o externa, burda o sutil— debe ser vista como realmente es con sabiduría correcta: "Esto no es mío, esto no soy yo, esto no es mi ser"»</h2><p>Conecta tus servicios, programa lo importante y deja que los avisos te encuentren.</p><div className="hero-actions"><button className="primary" onClick={() => navigate("Tools", "reminders")}><Icon name="clock" size={18}/>Crear recordatorio<Icon name="arrow" size={18}/></button><button className="hero-link" onClick={() => navigate("Skills")}>Ver habilidades<Icon name="arrow" size={16}/></button></div><div className="hero-meta"><span className="signal-bars"><i/><i/><i/><i/></span>UN PANEL. TUS REGLAS.</div></div>
      <PixelScene light={light}/>
    </section>
    <section className="metric-grid" aria-label="Resumen del sistema">{metrics.map(metric => <button key={metric.label} className={`metric-card ${metric.tone}`} onClick={() => navigate(metric.view, metric.tool)}><div className="metric-top"><span className="metric-icon"><Icon name={metric.icon}/></span><Icon name="arrow" size={16}/></div><strong>{metric.value}</strong><span className="metric-label">{metric.label}</span><small>{metric.note}</small></button>)}</section>
    <div className="dashboard-columns">
      <section className="panel activity-panel"><div className="section-heading"><div><p className="eyebrow">LO QUE ESTÁ PASANDO</p><h3>Señales recientes</h3></div><button className="text-button" onClick={() => navigate("Tools", "notifications")}>Ver todas<Icon name="arrow" size={15}/></button></div>
        {snapshot.events === null ? <div className="empty-inline"><Icon name="bell"/><p>No se pudo consultar la actividad. Vuelve a sincronizar.</p></div> : snapshot.events.length === 0 ? <div className="empty-inline"><Icon name="bell"/><p>Todo en calma. Tus próximos avisos aparecerán aquí.</p></div> : <div className="activity-stream">{snapshot.events.slice(0, 5).map(event => <article key={event.id}><span className={`activity-dot ${event.whatsapp_status === "retry" ? "warn" : ""}`}/><div className="activity-copy"><strong>{event.title || event.message.slice(0, 70)}</strong><p>{origins[event.source] ?? event.source}<span>·</span>{dateTime(event.received_at)}</p></div><span className={`event-pill ${event.whatsapp_status}`}>{eventLabels[event.whatsapp_status] ?? "Registrado"}</span></article>)}</div>}
      </section>
      <section className="panel next-panel"><div className="section-heading"><div><p className="eyebrow">EN EL RADAR</p><h3>Próximos disparadores</h3></div><span className="section-icon"><Icon name="clock"/></span></div>{upcoming.length ? upcoming.map(item => <article className="upcoming-item" key={item.id}><div className="upcoming-time"><Icon name="clock" size={15}/>{dateTime(item.next_check_at!)}</div><p>{item.message}</p></article>) : <div className="empty-inline"><Icon name="clock"/><p>{snapshot.reminders === null ? "No se pudieron consultar los recordatorios." : "Sin pendientes en el horizonte."}</p></div>}<button className="dashed-action" onClick={() => navigate("Tools", "reminders")}>＋ Programar algo importante</button></section>
    </div>
    <section className="connections-strip"><div><span className="mini-orbit"/><span>Tus conexiones</span></div>{Object.entries(snapshot.services).map(([id, ready]) => <button key={id} onClick={() => navigate("Skills")}><i className={ready ? "good" : "neutral"}/>{({ seerr: "Seerr", karakeep: "Karakeep", usenet: "Usenet", codex: "Codex", antigravity: "Antigravity" } as Record<string, string>)[id]}<small>{ready === null ? "Sin verificar" : ready ? "Configurado" : "Sin configurar"}</small></button>)}<span className="last-sync">{snapshot.refreshed ? `Actualizado ${snapshot.refreshed.toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" })}` : "Esperando datos"}</span></section>
  </div>;
}
