import { useEffect, useState } from "react";
import { apiFetch, dateTime } from "./api";
import { Icon, StatusTag } from "./ui";
import { PixelScene } from "./pixel/PixelScene";

type Navigate = (view: "Overview" | "Agents" | "Skills" | "Tools" | "Channels" | "Settings", tool?: "notifications" | "webhooks" | "reminders") => void;
type Event = { id: string; title: string; message: string; source: string; whatsapp_status: string; received_at: string };
type Reminder = { id: string; message: string; status: string; next_check_at: string | null };
type Channel = { configured: boolean; running: boolean; last_error: string | null };
type Job = { id: string; status: string; created_at: number; prompt?: string };
type MemoryNote = { id: string; text: string; metadata: { created_at: number | string; kind?: string } };
type Activity = { id: string; title: string; source: string; status: string; label: string; at: number };
type Snapshot = { activity: Activity[] | null; events: Event[] | null; reminders: Reminder[] | null; channel: Channel | null; services: Record<string, boolean | null>; refreshed: Date | null };
const initial: Snapshot = { activity: null, events: null, reminders: null, channel: null, services: { seerr: null, karakeep: null, usenet: null, codex: null, antigravity: null }, refreshed: null };
const eventLabels: Record<string, string> = { sent: "Enviado", pending: "En cola", sending: "Enviando", retry: "Reintentando", not_requested: "Registrado" };
const origins: Record<string, string> = { reminders: "Recordatorios", manual: "Envío directo", seerr: "Seerr" };
const services = ["seerr", "karakeep", "usenet", "codex", "antigravity"];
const workers = ["Codex", "Antigravity"];
const memoryLabels: Record<string, string> = { learning: "Aprendizaje", feedback: "Reconocimiento", requested: "Recuerdo solicitado" };

function recentActivity(events: Event[] | null, memories: MemoryNote[] | null, jobs: (Job[] | null)[]) {
  if (!events && !memories && jobs.every(items => !items)) return null;
  const activity: Activity[] = [];
  for (const event of events ?? []) {
    activity.push({ id: `notice-${event.id}`, title: event.title || event.message.slice(0, 100),
      source: origins[event.source] ?? event.source, at: Date.parse(event.received_at),
      status: event.whatsapp_status, label: eventLabels[event.whatsapp_status] ?? "Registrado" });
  }
  jobs.forEach((items, index) => {
    for (const job of items ?? []) {
      if (job.status !== "completed" && job.status !== "failed") continue;
      const title = job.prompt?.trim().split("\n")[0].slice(0, 100) ||
        (job.status === "completed" ? "Artemis completó una tarea" : "Una tarea de Artemis falló");
      activity.push({ id: `job-${job.id}`, title,
        source: workers[index], at: job.created_at * 1000,
        status: job.status === "completed" ? "sent" : "retry",
        label: job.status === "completed" ? "Completada" : "Fallida" });
    }
  });
  for (const memory of memories ?? []) {
    const { created_at, kind } = memory.metadata;
    const at = typeof created_at === "number" ? created_at * 1000 : Date.parse(created_at);
    activity.push({ id: `memory-${memory.id}`, title: memory.text.slice(0, 120),
      source: "Memoria de Artemis", at, status: "sent", label: memoryLabels[kind ?? ""] ?? "Recuerdo" });
  }
  // Give each source a place in the summary even when one integration sends many events.
  const ordered = activity.filter(item => Number.isFinite(item.at)).sort((a, b) => b.at - a.at);
  const sources = new Set<string>();
  const highlights = ordered.filter(item => {
    if (sources.has(item.source)) return false;
    sources.add(item.source);
    return true;
  }).slice(0, 5);
  return [...highlights, ...ordered.filter(item => !highlights.includes(item)).slice(0, 5 - highlights.length)]
    .sort((a, b) => b.at - a.at);
}

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
      const paths = ["/api/v1/tools/notifications/history?limit=50", "/api/v1/tools/reminders", "/api/v1/channels/whatsapp", "/api/v1/activity/memories", ...workers.map(worker => `/api/v1/skills/${worker.toLowerCase()}/jobs`), ...services.map(id => `/api/v1/skills/${id}/configuration`)];
      const results = await Promise.allSettled(paths.map(async path => {
        const response = await apiFetch(path);
        if (!response.ok) throw new Error("unavailable");
        return response.json();
      }));
      if (!active) return;
      const data = results.map(result => result.status === "fulfilled" ? result.value : null);
      setSnapshot({ events: data[0], reminders: data[1], channel: data[2], activity: recentActivity(data[0], data[3], data.slice(4, 6)), services: Object.fromEntries(services.map((id, index) => [id, data[index + 6]?.configured ?? null])), refreshed: new Date() });
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
    <div className="overview-intro"><div><h1>Consola de administración</h1></div><button className="subtle-button" disabled={refreshing} onClick={() => setRefresh(value => value + 1)}><Icon name="bolt" size={16}/>{refreshing ? "Sincronizando…" : "Sincronizar"}</button></div>
    <section className="command-hero">
      <div className="hero-copy"><StatusTag tone={channelLive ? "good" : "neutral"}>{channelLive ? "WhatsApp en marcha" : snapshot.channel?.configured ? "WhatsApp iniciando" : "Artemis platform - Admin Console"}</StatusTag><h2>Tu espacio de Artemis</h2><p>Conecta tus servicios, programa lo importante y deja que los avisos te encuentren.</p><div className="hero-actions"><button className="primary" onClick={() => navigate("Tools", "reminders")}><Icon name="clock" size={18}/>Crear recordatorio<Icon name="arrow" size={18}/></button><button className="hero-link" onClick={() => navigate("Skills")}>Ver habilidades<Icon name="arrow" size={16}/></button></div></div>
      <PixelScene light={light}/>
    </section>
    <section className="metric-grid" aria-label="Resumen del sistema">{metrics.map(metric => <button key={metric.label} className={`metric-card ${metric.tone}`} onClick={() => navigate(metric.view, metric.tool)}><div className="metric-top"><span className="metric-icon"><Icon name={metric.icon}/></span><Icon name="arrow" size={16}/></div><strong>{metric.value}</strong><span className="metric-label">{metric.label}</span><small>{metric.note}</small></button>)}</section>
    <div className="dashboard-columns">
      <section className="panel activity-panel"><div className="section-heading"><div><p className="eyebrow">LO QUE ESTÁ PASANDO</p><h3>Actividad de Artemis</h3></div><button className="text-button" onClick={() => navigate("Tools", "notifications")}>Ver avisos<Icon name="arrow" size={15}/></button></div>
        {snapshot.activity === null ? <div className="empty-inline"><Icon name="bell"/><p>{refreshing ? "Consultando actividad…" : "No se pudo consultar la actividad."}</p></div>
          : snapshot.activity.length === 0 ? <div className="empty-inline"><Icon name="bell"/><p>Aquí aparecerán los aprendizajes, las tareas y los avisos de Artemis.</p></div>
          : <div className="activity-stream">{snapshot.activity.map(item => <article key={item.id}>
            <span className={`activity-dot ${item.status === "retry" ? "warn" : ""}`}/>
            <div className="activity-copy"><strong>{item.title}</strong><p>{item.source}<span>·</span>{dateTime(new Date(item.at).toISOString())}</p></div>
            <span className={`event-pill ${item.status}`}>{item.label}</span>
          </article>)}</div>}
      </section>
      <section className="panel next-panel"><div className="section-heading"><div><p className="eyebrow">EN EL RADAR</p><h3>Próximos disparadores</h3></div><span className="section-icon"><Icon name="clock"/></span></div>{upcoming.length ? upcoming.map(item => <article className="upcoming-item" key={item.id}><div className="upcoming-time"><Icon name="clock" size={15}/>{dateTime(item.next_check_at!)}</div><p>{item.message}</p></article>) : <div className="empty-inline"><Icon name="clock"/><p>{snapshot.reminders === null ? "No se pudieron consultar los recordatorios." : "Sin pendientes en el horizonte."}</p></div>}<button className="dashed-action" onClick={() => navigate("Tools", "reminders")}>＋ Programar algo importante</button></section>
    </div>
    <section className="connections-strip"><div><span className="mini-orbit"/><span>Tus conexiones</span></div>{Object.entries(snapshot.services).map(([id, ready]) => <button key={id} onClick={() => navigate("Skills")}><i className={ready ? "good" : "neutral"}/>{({ seerr: "Seerr", karakeep: "Karakeep", usenet: "Usenet", codex: "Codex", antigravity: "Antigravity" } as Record<string, string>)[id]}<small>{ready === null ? "Sin verificar" : ready ? "Configurado" : "Sin configurar"}</small></button>)}<span className="last-sync">{snapshot.refreshed ? `Actualizado ${snapshot.refreshed.toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" })}` : "Esperando datos"}</span></section>
  </div>;
}
