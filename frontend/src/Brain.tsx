import { useEffect, useState } from "react";
import { apiFetch } from "./api";
import { MemoryMap, type Memory } from "./MemoryMap";
import { PageHeader, StatusTag } from "./ui";
import "./brain.css";

type Page = { total: number; items: Memory[] };
type Job = { id: string; name: string; mythology: string; state: string; task: string; target: string };
type Contract = { name: string; capability: string; parameters: unknown };
const collections = { agent_persona: "Personalidad", agent_memory: "Recuerdos", agent_relations: "Relaciones" };
const states: Record<string, string> = { pending: "Pendiente", running: "En marcha", completed: "Completado", failed: "Fallido", cancelled: "Cancelado" };
async function read<T>(path: string, signal: AbortSignal): Promise<T> {
  const response = await apiFetch(path, { signal });
  if (!response.ok) throw new Error("No se pudo consultar el servidor. Comprueba la conexión y tu sesión.");
  return response.json();
}
function Vector({ values }: { values: number[] }) {
  const max = Math.max(...values.map(Math.abs), 0.001);
  return <div><p>{values.length} dimensiones · MiniLM local · CPU</p><svg className="brain-vector" viewBox={`0 -1 ${Math.max(values.length, 1)} 2`} preserveAspectRatio="none" role="img" aria-label={`Vector de ${values.length} dimensiones; cada barra representa un componente`}><line x1="0" y1="0" x2={values.length} y2="0" stroke="currentColor" strokeWidth="0.01"/>{values.map((v, i) => <rect key={i} x={i} y={v >= 0 ? -v / max : 0} width="0.8" height={Math.abs(v) / max} fill={v >= 0 ? "#359a86" : "#ac77cb"}><title>Dimensión {i + 1}: {v}</title></rect>)}</svg><details><summary>Ver valores del vector</summary><pre>{JSON.stringify(values, null, 2)}</pre></details></div>;
}
export function Brain() {
  const [tab, setTab] = useState("memory");
  const [memoryView, setMemoryView] = useState<"map" | "list">("map");
  const [collection, setCollection] = useState("agent_memory");
  const [agent, setAgent] = useState("");
  const [filter, setFilter] = useState("");
  const [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState(0);
  const [page, setPage] = useState<Page | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [contracts, setContracts] = useState<Contract[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    const controller = new AbortController();
    const load = async () => {
      setLoading(true); setError("");
      try {
        if (tab === "memory") {
          const params = new URLSearchParams(memoryView === "list"
            ? { offset: String(offset), limit: "20" } : {});
          if (filter) params.set("agent", filter);
          const resource = memoryView === "map" ? `${collection}/map` : collection;
          const value = await read<Page>(`/api/v1/memory/${resource}?${params}`, controller.signal);
          if (!controller.signal.aborted) setPage(value);
        } else if (tab === "minions") {
          const value = await read<Job[]>("/api/v1/minions", controller.signal);
          if (!controller.signal.aborted) setJobs(value);
        } else {
          const value = await read<Contract[]>("/api/v1/tools/contracts", controller.signal);
          if (!controller.signal.aborted) setContracts(value);
        }
      } catch (e) { if (!controller.signal.aborted) setError((e as Error).message); }
      finally { if (!controller.signal.aborted) setLoading(false); }
    };
    void load();
    const timer = tab === "minions" ? window.setInterval(() => { void load(); }, 10000) : undefined;
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [tab, collection, filter, offset, revision, memoryView]);
  return <><PageHeader eyebrow="MEMORIA Y ACTIVIDAD" title="Cerebro" description="Artemis recuerda lo que aprende, el reconocimiento que recibe y lo que le pides guardar."/>
    <section className="panel brain-panel">
      <div className="brain-toolbar" aria-label="Vistas de Cerebro">{[["memory", "Memoria"], ["contracts", "Herramientas nativas"], ["minions", "Minions"]].map(([id, label]) => <button key={id} aria-pressed={tab === id} onClick={() => { if (tab !== id) { setTab(id); setPage(null); } }}>{label}</button>)}<button onClick={() => setRevision(v => v + 1)}>Actualizar</button></div>
      {tab === "memory" && <>
        <div className="brain-toolbar memory-view-toggle" aria-label="Presentación de memoria">
          <button type="button" aria-pressed={memoryView === "map"} onClick={() => {
            if (memoryView !== "map") { setPage(null); setMemoryView("map"); }
          }}>Mapa</button>
          <button type="button" aria-pressed={memoryView === "list"} onClick={() => {
            if (memoryView !== "list") { setPage(null); setMemoryView("list"); }
          }}>Lista</button>
        </div>
        <div className="brain-toolbar"><label>Colección<select value={collection} onChange={e => { setCollection(e.target.value); setOffset(0); setPage(null); }}>{Object.entries(collections).map(([id, label]) => <option key={id} value={id}>{label} · {id}</option>)}</select></label><form onSubmit={e => {
          e.preventDefault();
          if (filter !== agent.trim() || offset) { setFilter(agent.trim()); setOffset(0); setPage(null); }
        }}><label>Agente<input value={agent} onChange={e => setAgent(e.target.value)} placeholder="Todos los agentes" maxLength={200}/></label><button type="submit">Filtrar</button></form></div>
      </>}
      {error && <p role="alert">{error}</p>}{loading && <p role="status">Consultando…</p>}
      {!loading && !error && tab === "memory" && page && (memoryView === "map"
        ? <MemoryMap {...page} collection={collection} agent={filter}/>
        : <><p>{page.total} recuerdos{filter ? ` · Agente: ${filter}` : " · Todos los agentes"}</p>{!page.items.length && <p>No hay recuerdos en esta página.</p>}{page.items.map(item => <article className="brain-record" key={item.id}><div className="brain-toolbar"><strong>{String(item.metadata?.agent ?? "Sin agente")}</strong><code>{item.id}</code></div><p className="brain-document">{item.text}</p><details><summary>Datos y embedding</summary><pre>{JSON.stringify(item.metadata, null, 2)}</pre><Vector values={item.embedding}/></details></article>)}<div className="brain-toolbar"><button disabled={offset === 0} onClick={() => setOffset(v => Math.max(0, v - 20))}>Anterior</button><span>Página {offset / 20 + 1}</span><button disabled={offset + 20 >= page.total} onClick={() => setOffset(v => v + 20)}>Siguiente</button></div></>)}
      {!loading && !error && tab === "contracts" && <><p>Inventario de esquemas disponibles. La ejecución depende de las habilidades activadas, los permisos del agente y las confirmaciones requeridas.</p>{!contracts.length && <p>No hay contratos registrados.</p>}{contracts.map(item => <article className="brain-record" key={item.name}><h2>{item.name}</h2><p>Capacidad: {item.capability}</p><details><summary>Esquema de parámetros · JSON Schema</summary><pre>{JSON.stringify(item.parameters, null, 2)}</pre></details></article>)}</>}
      {!error && tab === "minions" && <><p>Actualización cada 10 segundos. Los trabajadores y su historial son efímeros.</p>{!loading && !jobs.length && <p>No hay minions registrados en esta sesión del servidor.</p>}{jobs.map(job => <article className="brain-record" key={job.id}><div className="brain-toolbar"><h2>{job.name}</h2><StatusTag tone={job.state === "completed" ? "good" : job.state === "failed" ? "warn" : "neutral"}>{states[job.state] ?? job.state}</StatusTag></div><p>{job.task}</p><p>Mitología: {job.mythology} · Destino: {job.target}</p><code>{job.id}</code></article>)}</>}
    </section></>;
}
