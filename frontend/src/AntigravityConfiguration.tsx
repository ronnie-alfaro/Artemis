import { useEffect, useState } from "react";
import { dateTime } from "./api";
type Props = { apiFetch: (path: string, init?: RequestInit) => Promise<Response> };
type Job = { id: string; prompt: string; status: string; mode: string; answer: string; has_patch: boolean; created_at: number };
export function AntigravityConfiguration({ apiFetch }: Props) {
  const [connected, setConnected] = useState<boolean | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const [status, history] = await Promise.all([apiFetch("/api/v1/skills/antigravity/configuration"), apiFetch("/api/v1/skills/antigravity/jobs")]);
        if (!status.ok || !history.ok) throw new Error("unavailable");
        const configuration = await status.json(); const items = await history.json() as Job[];
        if (active) { setConnected(configuration.connected); setJobs(items); setError(""); }
      } catch { if (active) { setConnected(null); setError("No se pudo consultar Antigravity. Inténtalo de nuevo."); } }
    };
    void load(); const timer = window.setInterval(() => { void load(); }, 5000);
    return () => { active = false; window.clearInterval(timer); };
  }, [apiFetch, refresh]);
  const download = async (job: Job) => {
    try {
      const response = await apiFetch(`/api/v1/skills/antigravity/jobs/${job.id}/patch`);
      if (!response.ok) throw new Error("download");
      const url = URL.createObjectURL(await response.blob()); const anchor = document.createElement("a");
      anchor.href = url; anchor.download = `artemis-${job.id}.patch`; anchor.click(); URL.revokeObjectURL(url);
    } catch { setError("No se pudo descargar el parche."); }
  };
  const labels: Record<string, string> = { queued: "En cola", running: "En marcha", completed: "Terminado", failed: "Falló" };
  return <><section className="skill-config"><div><strong>Conexión con Antigravity</strong><span>{connected === null ? "Comprobando…" : connected ? "Conectado" : "Sin conexión"}</span></div><p>Usa Antigravity desde WhatsApp con la sesión del servidor. Las preguntas se procesan en segundo plano y la respuesta regresa a la conversación que la pidió.</p><p>Activa la habilidad en Agentes y escribe <code>utiliza antigravity</code>. Pregunta con naturalidad o pide <code>crear herramienta para consultar el estado de mi servidor</code>.</p><p>Antigravity puede buscar, ejecutar comandos y modificar archivos del proyecto real. Las tareas solicitadas se ejecutan sin confirmación adicional.</p><button onClick={() => setRefresh(value => value + 1)}>Actualizar estado</button>{error && <p role="alert">{error}</p>}</section><section className="skill-config antigravity-jobs"><div><strong>Peticiones recientes</strong><span>{jobs.length} peticiones</span></div>{!jobs.length && <p>Tus preguntas y herramientas solicitadas aparecerán aquí.</p>}{jobs.map(job => <article key={job.id}><div><strong>{labels[job.status] ?? job.status} · {job.mode === "tool" ? "Nueva herramienta" : "Consulta"}</strong><small>{job.id.slice(0, 8)} · {dateTime(new Date(job.created_at * 1000).toISOString())}</small></div><p>{job.prompt}</p>{job.answer && <details><summary>Ver respuesta</summary><p className="antigravity-answer">{job.answer}</p></details>}{job.has_patch && <button onClick={() => void download(job)}>Descargar parche</button>}</article>)}</section></>;
}
