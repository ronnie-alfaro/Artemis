import { useEffect, useState } from "react";
import { apiFetch, dateTime } from "./api";
import { Icon } from "./ui";
import "./overview.css";

type Navigate = (view: "Overview" | "Agents" | "Skills" | "Tools" | "Channels" | "Settings", tool?: "notifications" | "webhooks" | "reminders") => void;
type Event = { id: string; title: string; message: string; source: string; whatsapp_status: string; received_at: string };
type Reminder = { id: string; message: string; status: string; next_check_at: string | null };
type Job = { id: string; status: string; created_at: number; prompt?: string };
type MemoryNote = { id: string; text: string; metadata: { created_at: number | string; kind?: string } };
type Activity = { id: string; title: string; source: string; status: string; label: string; at: number };
type Snapshot = { activity: Activity[] | null; events: Event[] | null; reminders: Reminder[] | null; services: Record<string, boolean | null> };
const initial: Snapshot = { activity: null, events: null, reminders: null, services: { seerr: null, karakeep: null, usenet: null, codex: null, antigravity: null } };
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

export function Overview({ navigate }: { navigate: Navigate }) {
  const [snapshot, setSnapshot] = useState<Snapshot>(initial);
  const [refreshing, setRefreshing] = useState(true);
  useEffect(() => {
    let active = true;
    const load = async () => {
      setRefreshing(true);
      const paths = ["/api/v1/tools/notifications/history?limit=50", "/api/v1/tools/reminders", "/api/v1/activity/memories", ...workers.map(worker => `/api/v1/skills/${worker.toLowerCase()}/jobs`), ...services.map(id => `/api/v1/skills/${id}/configuration`)];
      const results = await Promise.allSettled(paths.map(async path => {
        const response = await apiFetch(path);
        if (!response.ok) throw new Error("unavailable");
        return response.json();
      }));
      if (!active) return;
      const data = results.map(result => result.status === "fulfilled" ? result.value : null);
      setSnapshot({
        events: data[0],
        reminders: data[1],
        activity: recentActivity(data[0], data[2], data.slice(3, 3 + workers.length)),
        services: Object.fromEntries(services.map((id, index) => [id, data[3 + workers.length + index]?.configured ?? null])),
      });
      setRefreshing(false);
    };
    void load();
    const timer = window.setInterval(() => { void load(); }, 30000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);
  const configured = Object.values(snapshot.services).filter(value => value === true).length;
  const serviceCount = Object.keys(snapshot.services).length;
  const verified = Object.values(snapshot.services).filter(value => value !== null).length;
  const activeReminders = snapshot.reminders?.filter(item => item.status === "active") ?? [];
  const upcoming = activeReminders.filter(item => item.next_check_at).sort((a, b) => Date.parse(a.next_check_at!) - Date.parse(b.next_check_at!)).slice(0, 3);
  const pending = snapshot.events?.filter(event => ["pending", "sending", "retry"].includes(event.whatsapp_status)).length;
  const metrics = [
    { icon: "skills" as const, label: "Habilidades configuradas", value: verified ? `${configured} / ${serviceCount}` : "—", note: verified < serviceCount ? "Verificación parcial" : "Tus servicios personales", view: "Skills" as const, tone: "violet" },
    { icon: "clock" as const, label: "Recordatorios activos", value: snapshot.reminders ? String(activeReminders.length) : "—", note: "El tiempo también trabaja para ti", view: "Tools" as const, tool: "reminders" as const, tone: "mint" },
    { icon: "bell" as const, label: "Avisos pendientes", value: pending === undefined ? "—" : String(pending), note: "En las últimas 50 notificaciones", view: "Tools" as const, tool: "notifications" as const, tone: "amber" },
  ];
  return <div className="overview">
    <header className="panel console-heading" aria-labelledby="console-title">
      <img src="/images/arty_final.png" alt="Artemis" width={64} height={64}/>
      <h1 id="console-title">Consola de administración</h1>
    </header>
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
  </div>;
}
