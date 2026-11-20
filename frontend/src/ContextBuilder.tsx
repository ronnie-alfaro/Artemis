import { useEffect, useState, type FormEvent } from "react";
import { apiFetch } from "./api";
import { PageHeader } from "./ui";
import "./context-builder.css";

type Policy = { priority: number; minimum: number; maximum: number; enabled: boolean; compression: string; recovery: string };
type Value = string | number | boolean | null;
type Settings = Record<string, Value | Record<string, Policy>> & { components: Record<string, Policy> };
type Revision = { revision: number; updated_at: string };
type Configuration = { config: Partial<Settings>; defaults: Settings; revisions: Revision[];
  providers: Record<string, string>; agents: Record<string, string>; internal_auth_configured: boolean; bridge_enabled: boolean };
type Profile = { core: string; extended: string; original: string; suggestion: string; version: string;
  versions: { version: string; revision: string; persona_type: string; text: string; updated_at: string }[] };
type Section = { name: string; source: string; tokens: number; reason: string; priority: number };
type Preview = { sections: Section[]; estimated_tokens: number; input_budget: number; baseline_tokens: number;
  capabilities: string[]; prompt: string; runtime_enabled: boolean; persona_revision: string };
type Metric = { provider: string; channel: string; bot: string; conversation: string; created_at: string;
  values: { estimated_tokens?: number; baseline_tokens?: number; context_ms: number; latency_ms: number;
    fallback: boolean; cache_hit: boolean; summary_generated: boolean; memory_candidates: number;
    status: string; estimated_cost?: number; sections: { name: string; tokens: number }[];
    usage?: { input_tokens: number; output_tokens: number; cached_input_tokens?: number } } };
type SettingField = [key: string, label: string, options?: string[]];

const base = "/api/v1/context-builder";
const general: SettingField[] = [
  ["enabled", "Activar Context Builder"], ["mode", "Optimización", ["conservador", "equilibrado", "agresivo", "personalizado"]],
  ["budget", "Presupuesto total"], ["response_reserve", "Reserva de respuesta"],
  ["tool_reserve", "Reserva de herramientas"], ["safety_margin", "Margen de seguridad"],
  ["fallback", "Fallback", ["legacy", "basic"]], ["metrics", "Guardar métricas"], ["cache", "Caché local"],
  ["adaptive_calibration", "Calibrar con mediciones reales"], ["bytes_per_token", "Bytes por token estimado"], ["input_price_per_million", "Tarifa de entrada por millón"],
  ["output_price_per_million", "Tarifa de salida por millón"],
];
const history: SettingField[] = [
  ["recent_turns", "Turnos recientes"], ["summarize_after", "Umbral de resumen"],
  ["summary_size", "Tamaño máximo del resumen"], ["semantic_memory", "Recuperación semántica"],
  ["max_memories", "Máximo de recuerdos"], ["memory_threshold", "Umbral de relevancia"],
  ["memory_recency", "Peso de la recencia"], ["deduplicate", "Deduplicar recuerdos"],
];
const tools: SettingField[] = [
  ["dynamic_tools", "Selección dinámica"], ["include_dependencies", "Incluir dependencias autorizadas"], ["max_tools", "Máximo de candidatas"],
  ["tool_threshold", "Coincidencias mínimas"], ["full_catalog_fallback", "Ampliar al catálogo autorizado"],
];
const persona: SettingField[] = [["persona_policy", "Política de inclusión",
  ["ADAPTIVE", "CORE_ONLY", "CORE_PLUS_RELEVANT_EXTENDED", "FULL_PERSONA"]]];
const names: Record<string, string> = { core: "PERSONA Core", extended: "PERSONA Extended", history: "Historial",
  summary: "Resumen", memory: "Memoria", tools: "Herramientas", operations: "Operaciones", additional: "Contexto adicional" };

async function request<T>(path: string, data?: unknown, method = "POST"): Promise<T> {
  const response = await apiFetch(base + path, data === undefined ? undefined : {
    method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(data),
  });
  const value = await response.json();
  if (!response.ok) throw new Error(typeof value.detail === "string" ? value.detail : "No se pudo completar la solicitud.");
  return value as T;
}

function ConfigFields({ fields, defaults, value, update, inherited }: {
  fields: SettingField[]; defaults: Settings; value: Partial<Settings>;
  update: (key: string, value?: Value) => void; inherited: boolean;
}) {
  return <div className="context-fields">{fields.map(([key, label, options]) => {
    const existing = value[key] as Value | undefined;
    const current = existing === undefined ? defaults[key] as Value : existing;
    return <div key={key}>
      <label>{label}{options ? <select value={String(current)} onChange={event => update(key, event.target.value)}>
        {options.map(option => <option key={option}>{option}</option>)}</select>
        : typeof current === "boolean" ? <input type="checkbox" checked={current} onChange={event => update(key, event.target.checked)}/>
          : <input type="number" step="any" value={typeof current === "number" ? current : ""}
            onChange={event => update(key, event.target.value === "" ? null : Number(event.target.value))}/>}</label>
      {inherited && (existing === undefined
        ? <button type="button" onClick={() => update(key, current)}>Heredado · personalizar</button>
        : <button type="button" onClick={() => update(key)}>Restaurar herencia</button>)}
    </div>;
  })}</div>;
}

function Metrics({ rows }: { rows: Metric[] }) {
  const [group, setGroup] = useState("día");
  const groups = new Map<string, { attempts: number; estimated: number; baseline: number; actual: number;
    output: number; measured: number; cached: number; cost: number; overallMs: number; contextMs: number;
    fallbacks: number; failures: number; summaries: number; memories: number; localHits: number; sections: Record<string, number> }>();
  for (const row of rows) {
    const key = group === "proveedor" ? row.provider : group === "agente" ? `${row.channel} · ${row.bot}`
      : group === "conversación" ? row.conversation : row.created_at.slice(0, 10);
    const point = groups.get(key) ?? { attempts: 0, estimated: 0, baseline: 0, actual: 0, output: 0, measured: 0,
      cached: 0, cost: 0, overallMs: 0, contextMs: 0, fallbacks: 0, failures: 0, summaries: 0,
      memories: 0, localHits: 0, sections: {} };
    const sample = row.values;
    point.attempts++;
    point.estimated += sample.estimated_tokens ?? 0;
    point.baseline += sample.baseline_tokens ?? 0;
    if (sample.usage) {
      point.measured++;
      point.actual += sample.usage.input_tokens;
      point.output += sample.usage.output_tokens;
      point.cached += sample.usage.cached_input_tokens ?? 0;
    }
    for (const section of sample.sections) point.sections[section.name] = (point.sections[section.name] ?? 0) + section.tokens;
    point.cost += sample.estimated_cost ?? 0;
    point.overallMs += sample.latency_ms;
    point.contextMs += sample.context_ms;
    point.fallbacks += Number(sample.fallback);
    point.failures += Number(sample.status !== "ok");
    point.summaries += Number(sample.summary_generated);
    point.memories += sample.memory_candidates;
    point.localHits += Number(sample.cache_hit);
    groups.set(key, point);
  }
  const peak = Math.max(1, ...[...groups.values()].map(point => Math.max(point.estimated, point.actual)));
  return <section className="panel"><h2>Métricas</h2><label>Agrupar por <select value={group} onChange={event => setGroup(event.target.value)}>
    {["día", "proveedor", "agente", "conversación"].map(item => <option key={item}>{item}</option>)}</select></label>
    {groups.size === 0 && <p>Todavía no hay muestras.</p>}
    {[...groups.entries()].map(([key, point]) => <article className="context-sample" key={key}>
      <h3>{key}</h3>
      <label>Entrada estimada · {point.estimated}<meter max={peak} value={point.estimated}/></label>
      {point.measured > 0 && <label>Entrada reportada · {point.actual}<meter max={peak} value={point.actual}/></label>}
      <p>{point.attempts} intentos · {point.measured} con medición real · Salida reportada {point.output} · Caché del proveedor {point.cached} · Caché local {point.localHits}</p>
      {point.baseline > 0 && <p>Ahorro estimado {(100 * (1 - point.estimated / point.baseline)).toFixed(1)}% · Base estimada {point.baseline}</p>}
      <p>Contexto {(point.contextMs / point.attempts).toFixed(1)} ms por intento · Total {(point.overallMs / point.attempts).toFixed(1)} ms por intento · {point.fallbacks} fallbacks · {point.failures} fallos</p>
      <p>{point.summaries} resúmenes · {point.memories} recuerdos candidatos{point.cost > 0 ? ` · Coste estimado ${point.cost.toFixed(6)}` : ""}</p>
      <p>{Object.entries(point.sections).map(([part, tokens]) => `${names[part] ?? part} ${tokens}`).join(" · ")}</p>
    </article>)}
  </section>;
}

export function ContextBuilder() {
  const [scope, setScope] = useState("global");
  const [loadedScope, setLoadedScope] = useState("");
  const [config, setConfig] = useState<Configuration | null>(null);
  const [settings, setSettings] = useState<Partial<Settings>>({});
  const [channel, setChannel] = useState("whatsapp");
  const [provider, setProvider] = useState("codex");
  const [profile, setProfile] = useState<Profile | null>(null);
  const [conversations, setConversations] = useState<{ conversation: string }[]>([]);
  const [conversation, setConversation] = useState("");
  const [message, setMessage] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [metrics, setMetrics] = useState<Metric[]>([]);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const query = `?scope=${encodeURIComponent(scope)}`;
  const run = async (action: () => Promise<void>) => {
    setError(""); setNotice("");
    try { await action(); }
    catch (failure) { setError((failure as Error).message); }
  };
  const load = async (query: string) => {
    const next = await request<Configuration>("/settings" + query);
    setConfig(next); setSettings(next.config); setLoadedScope(query);
  };
  useEffect(() => {
    let active = true;
    void request<Configuration>("/settings" + query).then(next => {
      if (active) { setConfig(next); setSettings(next.config); setLoadedScope(query); }
    }).catch(failure => { if (active) setError(failure.message); });
    return () => { active = false; };
  }, [query]);
  useEffect(() => {
    if (!config?.agents[channel]) return;
    let active = true;
    void Promise.all([request<Profile>("/persona/" + channel),
      request<{ conversation: string }[]>("/conversations/" + channel)]).then(([next, list]) => {
      if (active) { setProfile(next); setConversations(list); setConversation(""); }
    }).catch(failure => { if (active) setError(failure.message); });
    return () => { active = false; };
  }, [channel, config?.agents[channel]]);
  useEffect(() => {
    if (!config) return;
    let active = true;
    const refresh = () => void request<Metric[]>("/metrics")
      .then(rows => { if (active) setMetrics(rows); })
      .catch(failure => { if (active) setError(failure.message); });
    refresh();
    const timer = window.setInterval(refresh, 15_000);
    return () => { active = false; window.clearInterval(timer); };
  }, [config]);

  const update = (key: string, value?: Value) => setSettings(previous => {
    const next = { ...previous };
    if (value === undefined) delete next[key]; else next[key] = value;
    return next;
  });
  const save = (event: FormEvent) => {
    event.preventDefault();
    if (loadedScope !== query) return;
    void run(async () => { await request("/settings" + query, settings, "PUT"); await load(query); setNotice("Configuración guardada."); });
  };
  return <><PageHeader title="Context Builder" eyebrow="CONVERSACIÓN" description="Configura qué información llega a los proveedores conversacionales."/>
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    {config && <>
      {!config.internal_auth_configured && <p role="status">La conexión autenticada con Rust requiere configurar ARTEMIS_CONTEXT_TOKEN.</p>}
      <form className="panel context-panel" onSubmit={save}>
        <h2>Configuración</h2>
        <label>Ámbito <select value={scope} onChange={event => setScope(event.target.value)}>
          <option value="global">Global</option>
          {Object.entries(config.agents).map(([key, bot]) => <option key={key} value={`agent:${key}:${bot}`}>{key} · {bot}</option>)}
          {Object.entries(config.providers).map(([key, label]) => <option key={key} value={`provider:${key}`}>{label}</option>)}
        </select></label>
        {[[general, "General"], [persona, "PERSONA"], [history, "Historial y memoria"], [tools, "Herramientas"]].map(([fields, label]) =>
          <fieldset key={label as string}><legend>{label as string}</legend>
            <ConfigFields fields={fields as SettingField[]} defaults={config.defaults} value={settings} update={update} inherited={scope !== "global"}/>
          </fieldset>)}
        <fieldset><legend>Prioridades y presupuestos</legend><div className="context-table"><table>
          <thead><tr>{["Componente", "Prioridad", "Mínimo", "Máximo", "Activación", "Compresión", "Recuperación", "Ámbito"].map(item => <th key={item}>{item}</th>)}</tr></thead>
          <tbody>{Object.entries(config.defaults.components).map(([key, defaults]) => {
            const item = { ...defaults, ...settings.components?.[key] };
            const mandatory = key === "core" || key === "operations";
            const edit = <K extends keyof Policy>(field: K, value: Policy[K]) =>
              setSettings(previous => ({ ...previous, components: { ...previous.components, [key]: { ...item, [field]: value } } }));
            return <tr key={key}><th scope="row">{names[key]}{mandatory && <small>Protegido</small>}</th>
              {(["priority", "minimum", "maximum"] as const).map(field => <td key={field}><input aria-label={`${names[key]} ${field}`}
                type="number" min={0} value={item[field]} disabled={mandatory && (key === "operations" || field !== "maximum")}
                onChange={event => edit(field, Number(event.target.value))}/></td>)}
              <td><input aria-label={`${names[key]} activo`} type="checkbox" checked={item.enabled} disabled={mandatory}
                onChange={event => edit("enabled", event.target.checked)}/></td>
              <td><select aria-label={`${names[key]} compresión`} value={item.compression} disabled={mandatory}
                onChange={event => edit("compression", event.target.value)}><option value="select">Seleccionar</option><option value="omit">Omitir</option></select></td>
              <td><select aria-label={`${names[key]} recuperación`} value={item.recovery} disabled={mandatory}
                onChange={event => edit("recovery", event.target.value)}><option value="relevant">Relevante</option><option value="always">Siempre</option><option value="never">Nunca</option></select></td>
              <td>{settings.components?.[key] ? <button type="button" onClick={() => setSettings(previous => {
                const components = { ...previous.components }; delete components[key];
                return { ...previous, components };
              })}>Heredar</button> : "Heredado"}</td>
            </tr>;
          })}</tbody>
        </table></div></fieldset>
        <button className="primary" disabled={loadedScope !== query}>Guardar configuración</button>
        <details><summary>Revisiones de configuración</summary>{config.revisions.map(item => <p key={item.revision}>
          #{item.revision} · {new Date(item.updated_at).toLocaleString()} <button type="button" onClick={() => void run(async () => {
            await request("/settings/restore" + query, { revision: item.revision }); await load(query); setNotice("Revisión restaurada.");
          })}>Restaurar</button></p>)}</details>
      </form>
      <section className="panel context-panel">
        <h2>PERSONA</h2>
        <label>Agente <select value={channel} onChange={event => { setProfile(null); setPreview(null); setChannel(event.target.value); }}>
          {!config.agents[channel] && <option value={channel}>Selecciona un agente</option>}
          {Object.entries(config.agents).map(([key, label]) => <option key={key} value={key}>{key} · {label}</option>)}</select></label>
        {profile && <><p>Versión activa · <code>{profile.version}</code></p>
          <label>Core · {Math.ceil(new TextEncoder().encode(profile.core).length / 3)} tokens estimados
            <textarea rows={4} value={profile.core} onChange={event => setProfile({ ...profile, core: event.target.value })}/></label>
          <label>Extended · {Math.ceil(new TextEncoder().encode(profile.extended).length / 3)} tokens estimados
            <textarea rows={8} value={profile.extended} onChange={event => setProfile({ ...profile, extended: event.target.value })}/></label>
          <button onClick={() => void run(async () => {
            const next = await request<{ core: string }>("/persona/propose", { extended: profile.extended });
            setProfile({ ...profile, core: next.core });
          })}>Proponer Core</button>
          <button className="primary" onClick={() => void run(async () => {
            await request("/persona/" + channel, { core: profile.core, extended: profile.extended }, "PUT");
            setProfile(await request<Profile>("/persona/" + channel)); setNotice("PERSONA guardada.");
          })}>Guardar PERSONA</button>
          <details><summary>Vista previa y versiones anteriores</summary><pre>{profile.core}</pre>
            {profile.versions.map(version => <p key={version.version}>{version.persona_type} · {new Date(version.updated_at).toLocaleString()} <button onClick={() => {
              const extended = profile.versions.find(item => item.revision === version.revision && item.persona_type === "extended");
              const core = profile.versions.find(item => item.revision === version.revision && item.persona_type === "core");
              setProfile({ ...profile, core: core?.text ?? profile.core, extended: extended?.text ?? profile.extended });
            }}>Cargar en el editor</button></p>)}</details>
        </>}
      </section>
      <form className="panel context-panel" onSubmit={event => { event.preventDefault(); void run(async () => {
        setPreview(await request<Preview>("/simulate", { channel, provider, message, conversation: conversation || null }));
      }); }}>
        <h2>Simulador</h2>
        <label>Proveedor <select value={provider} onChange={event => setProvider(event.target.value)}>
          {Object.entries(config.providers).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
        <label>Conversación <select value={conversation} onChange={event => setConversation(event.target.value)}>
          <option value="">Nueva conversación</option>
          {conversations.map(item => <option key={item.conversation}>{item.conversation}</option>)}</select></label>
        <label>Mensaje de prueba <textarea required value={message} onChange={event => setMessage(event.target.value)}/></label>
        <button className="primary" disabled={!config.internal_auth_configured || !profile}>Simular contexto</button>
        {preview && <><p>{preview.estimated_tokens} / {preview.input_budget} tokens estimados · Base estimada {preview.baseline_tokens}</p>
          <p>PERSONA {preview.persona_revision} · {preview.runtime_enabled ? "Optimización activa" : "Simulación con optimización desactivada en runtime"}</p>
          <p>Capacidades candidatas · {preview.capabilities.join(", ") || "Ninguna"}</p>
          <ul>{preview.sections.map(section => <li key={section.name}>{names[section.name] ?? section.name} · {section.tokens} tokens · {section.reason}</li>)}</ul>
          <details><summary>Contexto entregado al proveedor</summary><pre>{preview.prompt}</pre></details></>}
      </form>
      {config.bridge_enabled === false && <p role="status">Activa el puente conversacional en Ajustes para registrar métricas de los turnos.</p>}
      <Metrics rows={metrics}/>
    </>}
  </>;
}
