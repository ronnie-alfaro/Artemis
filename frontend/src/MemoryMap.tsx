import { useEffect, useMemo, useState } from "react";
import { apiFetch } from "./api";
import { Icon } from "./ui";

export type Memory = { id: string; text: string; metadata: Record<string, unknown>; embedding: number[] };
type Match = { id: string; text: string; distance: number };
type Explore = { text: string } | { memory_id: string };
const colors = ["#60e5cc", "#c9a1ff", "#7fb6ff", "#ffd486", "#ff94a9", "#bce384", "#f9a779"];
const missingAgent = "Sin agente";
const width = 760;
const height = 420;

function agentOf(memory: Memory) {
  return String(memory.metadata?.agent ?? missingAgent);
}

function dateOf(memory: Memory) {
  const value = memory.metadata?.created_at;
  if (typeof value !== "string" && typeof value !== "number") return null;
  const numeric = Number(value);
  const date = new Date(Number.isFinite(numeric) ? numeric * 1000 : Date.parse(String(value)));
  return Number.isFinite(date.getTime()) ? date.toISOString().slice(0, 10) : null;
}

function scalePoints(points: number[][]) {
  const xs = points.map(([x]) => x);
  const ys = points.map(([, y]) => y);
  const left = Math.min(...xs);
  const bottom = Math.min(...ys);
  const rangeX = Math.max(...xs) - left;
  const rangeY = Math.max(...ys) - bottom;
  const scale = Math.min((width - 88) / (rangeX || 1), (height - 88) / (rangeY || 1));
  return points.map(([x, y]) => ({
    x: width / 2 + (x - left - rangeX / 2) * scale,
    y: height / 2 - (y - bottom - rangeY / 2) * scale,
  }));
}

export function MemoryMap({ items, total, collection, agent }: {
  items: Memory[]; total: number; collection: string; agent: string;
}) {
  const memories = useMemo(() => items.filter(item =>
    item.embedding?.length && item.embedding.every(Number.isFinite)), [items]);
  const agents = useMemo(() => [...new Set(memories.map(agentOf))].sort(), [memories]);
  const [coordinates, setCoordinates] = useState<number[][] | null>(null);
  const [projectionFailed, setProjectionFailed] = useState(false);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [query, setQuery] = useState("");
  const [zoom, setZoom] = useState(1);
  const [explore, setExplore] = useState<Explore | null>(null);
  const [selection, setSelection] = useState<Memory | Match | null>(null);
  const [matches, setMatches] = useState<Match[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState(false);

  useEffect(() => {
    if (memories.length < 3) return;
    const worker = new Worker(new URL("./memoryProjection.worker.ts", import.meta.url), { type: "module" });
    worker.onmessage = ({ data }: MessageEvent<number[][] | null>) => {
      setCoordinates(data);
      setProjectionFailed(data === null);
      worker.terminate();
    };
    worker.onerror = () => { setProjectionFailed(true); worker.terminate(); };
    worker.postMessage(memories.map(item => item.embedding));
    return () => worker.terminate();
  }, [memories]);

  const dateFiltered = Boolean(from || to);
  const visible = useMemo(() => memories.filter(item => {
    if (!from && !to) return true;
    const date = dateOf(item);
    return date && (!from || date >= from) && (!to || date <= to);
  }), [memories, from, to]);
  const visibleIds = new Set(visible.map(item => item.id));

  useEffect(() => {
    if (!explore) return;
    const controller = new AbortController();
    async function load() {
      setSearching(true);
      setSearchError(false);
      setMatches([]);
      try {
        const response = await apiFetch(`/api/v1/memory/${collection}/explore`, {
          method: "POST", signal: controller.signal,
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ...explore, agent: agent || undefined,
            ids: dateFiltered ? visible.map(item => item.id) : undefined }),
        });
        if (!response.ok) throw new Error();
        const results: Match[] = await response.json();
        if (!controller.signal.aborted) setMatches(results);
      } catch {
        if (!controller.signal.aborted) setSearchError(true);
      } finally {
        if (!controller.signal.aborted) setSearching(false);
      }
    }
    void load();
    return () => controller.abort();
  }, [explore, agent, collection, dateFiltered, visible]);

  const positions = scalePoints(
    coordinates ?? (memories.length === 1 ? [[0, 0]] : [[-1, 0], [1, 0]]),
  );
  const highlighted = new Set(matches.map(item => item.id));
  const focus = positions[memories.findIndex(item => item.id === selection?.id)];
  const selectionDate = selection && "metadata" in selection ? dateOf(selection) : null;
  const viewWidth = width / zoom;
  const viewHeight = height / zoom;
  const viewLeft = Math.min(width - viewWidth, Math.max(0, (focus?.x ?? width / 2) - viewWidth / 2));
  const viewTop = Math.min(height - viewHeight, Math.max(0, (focus?.y ?? height / 2) - viewHeight / 2));
  function select(item: Memory | Match) {
    setSelection(items.find(memory => memory.id === item.id) ?? item);
    setExplore({ memory_id: item.id });
  }
  function clearSelection() {
    setSelection(null);
    setExplore(null);
    setMatches([]);
    setSearching(false);
    setSearchError(false);
  }

  return <div className="memory-explorer">
    <div className="memory-controls">
      <form className="memory-search brain-toolbar" onSubmit={event => {
        event.preventDefault();
        if (!query.trim()) return;
        setSelection(null);
        setExplore({ text: query.trim() });
      }}>
        <label>Buscar por significado<input value={query} onChange={event => setQuery(event.target.value)}
          placeholder="Ej. Preferencias de idioma" maxLength={1000}/></label>
        <button type="submit" className="primary" disabled={!query.trim() || (dateFiltered && !visible.length)}>
          <Icon name="search" size={17}/>Buscar
        </button>
        {explore && <button type="button" className="secondary" onClick={clearSelection}>Limpiar selección</button>}
      </form>
      <div className="brain-toolbar memory-dates">
        <label>Desde<input type="date" value={from} max={to || undefined} onChange={event => {
          clearSelection(); setFrom(event.target.value);
        }}/></label>
        <label>Hasta<input type="date" value={to} min={from || undefined} onChange={event => {
          clearSelection(); setTo(event.target.value);
        }}/></label>
        {dateFiltered && <button type="button" className="secondary" onClick={() => {
          clearSelection(); setFrom(""); setTo("");
        }}>Quitar fechas</button>}
      </div>
    </div>
    {dateFiltered && <small>Los registros sin fecha se ocultan al aplicar este filtro.</small>}
    <div className="memory-map-layout">
      <section className="memory-map-stage" aria-label="Proyección de recuerdos">
        <div className="memory-map-top">
          <div><h2>Mapa de memoria</h2><p>{visible.length} visibles de {total} registros</p></div>
          <div className="memory-zoom" aria-label="Zoom del mapa">
            <button type="button" aria-label="Alejar" disabled={zoom <= 1} onClick={() => setZoom(value => value / 1.5)}>−</button>
            <button type="button" aria-label="Acercar" disabled={zoom >= 3.375} onClick={() => setZoom(value => value * 1.5)}>+</button>
            <button type="button" onClick={() => setZoom(1)}>Restablecer</button>
          </div>
        </div>
        {!visible.length ? <p className="memory-map-message">No hay recuerdos con vectores en esta vista.</p>
          : projectionFailed ? <p className="memory-map-message" role="alert">No se pudo generar la proyección. Puedes consultar la vista Lista.</p>
          : memories.length > 2 && !coordinates ? <p className="memory-map-message" role="status">Calculando la proyección UMAP…</p>
          : <svg className="memory-plot" viewBox={`${viewLeft} ${viewTop} ${viewWidth} ${viewHeight}`}
            role="group" aria-label="Puntos de memoria. Selecciona un punto para ver sus vecinos.">
            {memories.map((item, index) => {
              if (!visibleIds.has(item.id)) return null;
              const { x, y } = positions[index];
              const selected = selection?.id === item.id;
              const matched = highlighted.has(item.id);
              const color = colors[agents.indexOf(agentOf(item)) % colors.length];
              return <g key={item.id} transform={`translate(${x} ${y})`} role="button" tabIndex={0}
                aria-label={`${agentOf(item)} · ${item.text.slice(0, 100)}`} aria-pressed={selected}
                className={`memory-point${selected || matched ? " is-highlighted" : ""}${matches.length && !selected && !matched ? " is-muted" : ""}`}
                onClick={() => select(item)} onKeyDown={event => {
                  if (event.key === "Enter" || event.key === " ") { event.preventDefault(); select(item); }
                }}>
                <title>{item.text.slice(0, 140)}</title>
                <circle r="13" fill="transparent"/>
                <circle className="memory-point-ring" r="10" fill="none" stroke={color}/>
                <circle r={selected || matched ? 6.5 : 4.5} fill={color}/>
              </g>;
            })}
          </svg>}
        <div className="memory-legend" aria-label="Colores por agente">{agents.map((name, index) =>
          <span key={name}><svg width="10" height="10" aria-hidden="true"><circle cx="5" cy="5" r="4"
            fill={colors[index % colors.length]}/></svg>{name}</span>)}</div>
      </section>
      <aside className="memory-inspector" aria-label="Detalles del mapa">
        <h2>{selection ? "Recuerdo seleccionado" : "Explorar recuerdos"}</h2>
        {selection && <>
          {"metadata" in selection && <p className="memory-meta">{agentOf(selection)} · {selectionDate ?? "Sin fecha"}</p>}
          <p className="memory-selected">{selection.text}</p>
        </>}
        {!explore && <p>Selecciona un punto para abrir un recuerdo y ver sus vecinos, o busca una frase.</p>}
        {searching && <p role="status">Buscando en ChromaDB…</p>}
        {searchError && <p role="alert">No se pudo consultar ChromaDB. Vuelve a intentarlo.</p>}
        {explore && !searching && !searchError && <>
          <h3>{selection ? "Recuerdos similares" : "Resultados de búsqueda"}</h3>
          {!matches.length && <p>No se encontraron coincidencias.</p>}
          <ul className="memory-matches">{matches.map(item => <li key={item.id}>
            <button type="button" onClick={() => select(item)}>
              <span>{item.text}</span>
              <small>Distancia {item.distance.toFixed(3)}{visibleIds.has(item.id) ? " · En el mapa" : " · Fuera del mapa"}</small>
            </button>
          </li>)}</ul>
        </>}
      </aside>
    </div>
    <p className="memory-map-note">La cercanía en la proyección es aproximada. Los resultados se ordenan por la distancia vectorial de ChromaDB.
      {items.length < total && ` El mapa muestra hasta ${items.length} registros de esta colección.`}
    </p>
  </div>;
}
