import { useEffect, useRef, useState } from "react";
import "./reminders.css";

type Props = { apiFetch: (path: string, init?: RequestInit) => Promise<Response> };
type ReadTool = { name: string; description: string; input_example: Record<string, unknown> };
type Condition = { path: string; operator: string; value: unknown };
type Trigger = { kind: "time"; at: string } | { kind: "tool"; tool_name: string; input: Record<string, unknown>; condition: Condition; interval_seconds: number };
type Reminder = {
  id: string; message: string; trigger: Trigger; status: string; next_check_at: string | null;
  last_checked_at: string | null; last_value: string | null; last_error: string | null;
};
const operators = [
  ["equals", "Es igual a"], ["not_equals", "Es distinto de"], ["contains", "Contiene"],
  ["gt", "Es mayor que"], ["gte", "Es mayor o igual que"], ["lt", "Es menor que"],
  ["lte", "Es menor o igual que"], ["exists", "Existe"], ["not_exists", "Ya no existe"],
  ["is_empty", "Está vacío"], ["changed", "Cambia respecto a la revisión anterior"],
];
const stateLabels: Record<string, string> = {
  active: "Activo", paused: "Pausado", firing: "Pendiente de notificación", completed: "Aviso encolado", cancelled: "Cancelado",
};
function conditionNeedsValue(operator: string) {
  return !["exists", "not_exists", "is_empty", "changed"].includes(operator);
}
function operatorLabel(operator: string) {
  return operators.find(([key]) => key === operator)?.[1] ?? operator;
}
function initialDate() {
  const date = new Date(Date.now() + 3600000);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}
function newId() {
  if (crypto.randomUUID) return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
  const hex = Array.from(bytes, byte => byte.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
async function failure(response: Response, fallback: string) {
  try { const body = await response.json() as { detail?: unknown }; return typeof body.detail === "string" ? body.detail : fallback; }
  catch { return fallback; }
}

export function Reminders({ apiFetch }: Props) {
  const [tools, setTools] = useState<ReadTool[]>([]);
  const [reminders, setReminders] = useState<Reminder[]>([]);
  const [message, setMessage] = useState("");
  const [kind, setKind] = useState<"time" | "tool">("time");
  const [at, setAt] = useState(initialDate);
  const [toolName, setToolName] = useState("");
  const [parameters, setParameters] = useState("{}");
  const [path, setPath] = useState("status.remaining_mb");
  const [operator, setOperator] = useState("equals");
  const [expected, setExpected] = useState("0");
  const [frequency, setFrequency] = useState(1);
  const [unit, setUnit] = useState(60);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [previewBusy, setPreviewBusy] = useState(false);
  const [preview, setPreview] = useState<{ matched: boolean; values: unknown[]; output: unknown } | null>(null);
  const [error, setError] = useState("");
  const [listError, setListError] = useState("");
  const [status, setStatus] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [changing, setChanging] = useState<string | null>(null);
  const requestId = useRef<string | null>(null);
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const needsValue = conditionNeedsValue(operator);
  const change = (update: () => void) => { update(); requestId.current = null; setPreview(null); setError(""); };

  useEffect(() => {
    let active = true;
    void apiFetch("/api/v1/tools/reminders/catalog").then(async response => {
      if (!response.ok) throw new Error("catalog");
      const available = await response.json() as ReadTool[];
      if (!active) return;
      setTools(available);
      const first = available.find(tool => tool.name === "usenet.status") ?? available[0];
      if (first) { setToolName(first.name); setParameters(JSON.stringify(first.input_example ?? {}, null, 2)); }
    }).catch(() => { if (active) setError("No se pudo cargar la lista de herramientas."); });
    return () => { active = false; };
  }, [apiFetch]);

  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const response = await apiFetch("/api/v1/tools/reminders");
        if (!response.ok) throw new Error("list");
        const items = await response.json() as Reminder[];
        if (active) { setReminders(items); setListError(""); }
      } catch { if (active) setListError("No se pudieron cargar los recordatorios. Revisa PostgreSQL y la conexión."); }
      finally { if (active) setLoading(false); }
    };
    void load();
    const timer = window.setInterval(() => { void load(); }, 5000);
    return () => { active = false; window.clearInterval(timer); };
  }, [apiFetch, refresh]);

  const toolTrigger = (): Extract<Trigger, { kind: "tool" }> => {
    const input: unknown = JSON.parse(parameters);
    if (!input || typeof input !== "object" || Array.isArray(input)) throw new Error("Los parámetros deben ser un objeto JSON.");
    let value: unknown = null;
    if (needsValue) { try { value = JSON.parse(expected); } catch { value = expected; } }
    return { kind: "tool", tool_name: toolName, input: input as Record<string, unknown>,
      condition: { path: path.trim(), operator, value }, interval_seconds: frequency * unit };
  };
  const testCondition = async () => {
    setPreviewBusy(true); setError(""); setPreview(null);
    try {
      const response = await apiFetch("/api/v1/tools/reminders/preview", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(toolTrigger()),
      });
      if (!response.ok) throw new Error(await failure(response, "No se pudo comprobar la condición."));
      setPreview(await response.json());
    } catch (cause) { setError(cause instanceof Error ? cause.message : "No se pudo consultar la herramienta."); }
    finally { setPreviewBusy(false); }
  };
  const create = async () => {
    setBusy(true); setError(""); setStatus("");
    try {
      let trigger: Trigger;
      if (kind === "time") {
        const date = new Date(at);
        if (!Number.isFinite(date.getTime())) throw new Error("Elige una fecha y hora válidas.");
        trigger = { kind: "time", at: date.toISOString() };
      } else trigger = toolTrigger();
      requestId.current ??= newId();
      const response = await apiFetch("/api/v1/tools/reminders", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: message.trim(), trigger, request_id: requestId.current }),
      });
      if (!response.ok) throw new Error(await failure(response, "No se pudo crear el recordatorio. Revisa los campos."));
      setMessage(""); requestId.current = null;
      setStatus("Recordatorio creado. El aviso se enviará mediante Notificaciones cuando se cumpla el disparador.");
      setRefresh(value => value + 1);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "No se pudo crear el recordatorio."); }
    finally { setBusy(false); }
  };
  const update = async (reminder: Reminder, action: "active" | "paused" | "cancel") => {
    setChanging(reminder.id); setError("");
    try {
      const response = await apiFetch(`/api/v1/tools/reminders/${reminder.id}`, {
        method: action === "cancel" ? "DELETE" : "PATCH", headers: { "Content-Type": "application/json" },
        ...(action === "cancel" ? {} : { body: JSON.stringify({ status: action }) }),
      });
      if (!response.ok) throw new Error(await failure(response, "No se pudo modificar el recordatorio."));
      setRefresh(value => value + 1);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "No se pudo modificar el recordatorio."); }
    finally { setChanging(null); }
  };

  return <div className="reminders-tool">
    <section className="panel">
      <h2>Recordatorios</h2><p>Escribe el mensaje y elige qué debe dispararlo. Cada recordatorio avisa una sola vez mediante Notificaciones.</p>
      <form onSubmit={event => { event.preventDefault(); void create(); }}>
        <label>Mensaje<textarea aria-label="Mensaje del recordatorio" required maxLength={4096} value={message} disabled={busy} onChange={event => change(() => setMessage(event.target.value))} /></label>
        <label>Disparador<select aria-label="Disparador del recordatorio" value={kind} disabled={busy} onChange={event => change(() => setKind(event.target.value as "time" | "tool"))}><option value="time">Fecha y hora</option><option value="tool">Resultado de una herramienta</option></select></label>
        {kind === "time" ? <label>Fecha y hora · {timezone}<input aria-label="Fecha y hora del recordatorio" type="datetime-local" required value={at} disabled={busy} onChange={event => change(() => setAt(event.target.value))} /></label> : <>
          <label>Herramienta de consulta<select aria-label="Herramienta del disparador" required value={toolName} disabled={busy} onChange={event => change(() => { setToolName(event.target.value); const selected = tools.find(tool => tool.name === event.target.value); setParameters(JSON.stringify(selected?.input_example ?? {}, null, 2)); })}>
            {tools.length === 0 && <option value="">No hay herramientas de consulta disponibles</option>}
            {tools.map(tool => <option key={tool.name} value={tool.name}>{tool.name} · {tool.description}</option>)}
          </select></label>
          <details><summary>Parámetros de la herramienta</summary><label>Parámetros (JSON)<textarea aria-label="Parámetros de la herramienta" value={parameters} disabled={busy} onChange={event => change(() => setParameters(event.target.value))} /></label></details>
          <label>Campo a revisar<input aria-label="Campo del resultado" required maxLength={256} value={path} placeholder="items[id=42].status" disabled={busy} onChange={event => change(() => setPath(event.target.value))} /></label>
          <p className="hint">Ejemplos: status.remaining_mb, items[*].status o items[id=42].status. La condición se cumple si coincide algún valor.</p>
          <label>Condición<select aria-label="Condición del resultado" value={operator} disabled={busy} onChange={event => change(() => setOperator(event.target.value))}>{operators.map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
          {needsValue && <label>Valor esperado<input aria-label="Valor esperado" value={expected} disabled={busy} onChange={event => change(() => setExpected(event.target.value))} /></label>}
          <div className="reminder-frequency"><label>Revisar cada<input aria-label="Frecuencia de revisión" type="number" step="1" required min={unit === 1 ? 10 : 1} max={Math.floor(604800 / unit)} value={frequency} disabled={busy} onChange={event => change(() => setFrequency(Number(event.target.value)))} /></label><label>Unidad<select aria-label="Unidad de frecuencia" value={unit} disabled={busy} onChange={event => change(() => setUnit(Number(event.target.value)))}><option value={1}>Segundos</option><option value={60}>Minutos</option><option value={3600}>Horas</option></select></label></div>
          {operator === "changed" && <p>La primera comprobación establece la referencia. Se avisará si cambia en una revisión posterior.</p>}
          <button type="button" onClick={testCondition} disabled={previewBusy || busy || !toolName}>{previewBusy ? "Comprobando…" : "Probar condición"}</button>
          {preview && <div className="reminder-preview"><p>{preview.matched ? "La condición se cumple ahora." : "La condición todavía no se cumple."}</p><details open><summary>Resultado de la herramienta</summary><pre>{JSON.stringify(preview.output, null, 2)}</pre></details></div>}
        </>}
        <button className="primary" type="submit" disabled={busy || loading || !message.trim() || (kind === "tool" && !toolName)}>{busy ? "Guardando…" : "Crear recordatorio"}</button>
      </form>
      {error && <p role="alert">{error}</p>}{status && <p role="status">{status}</p>}
    </section>
    <section className="panel reminder-list">
      <div className="reminder-list-head"><h3>Mis recordatorios</h3><button onClick={() => setRefresh(value => value + 1)}>Actualizar recordatorios</button></div>
      {loading && <p>Cargando recordatorios…</p>}{listError && <p role="alert">{listError}</p>}
      {!loading && !listError && reminders.length === 0 && <p>Todavía no hay recordatorios.</p>}
      {!listError && reminders.map(reminder => <article key={reminder.id}>
        <div className="reminder-list-head"><strong>{stateLabels[reminder.status] ?? reminder.status}</strong><span>{reminder.trigger.kind === "time" ? new Date(reminder.trigger.at).toLocaleString("es-ES") : `${reminder.trigger.tool_name} · cada ${reminder.trigger.interval_seconds} s`}</span></div>
        <p className="reminder-message">{reminder.message}</p>
        {reminder.trigger.kind === "tool" && <p>{reminder.trigger.condition.path} · {operatorLabel(reminder.trigger.condition.operator)} {conditionNeedsValue(reminder.trigger.condition.operator) && JSON.stringify(reminder.trigger.condition.value)}</p>}
        {reminder.next_check_at && reminder.status === "active" && <small>Próxima revisión: {new Date(reminder.next_check_at).toLocaleString("es-ES")}</small>}
        {reminder.last_checked_at && <small>Última revisión: {new Date(reminder.last_checked_at).toLocaleString("es-ES")}</small>}
        {reminder.last_value && <details><summary>Último resultado revisado</summary><pre>{reminder.last_value}</pre></details>}
        {reminder.last_error && <p className="reminder-error">{reminder.last_error}</p>}
        {["active", "paused"].includes(reminder.status) && <div className="reminder-actions"><button disabled={changing === reminder.id} onClick={() => update(reminder, reminder.status === "active" ? "paused" : "active")}>{reminder.status === "active" ? "Pausar" : "Reanudar"}</button><button disabled={changing === reminder.id} onClick={() => update(reminder, "cancel")}>Cancelar</button></div>}
      </article>)}
    </section>
  </div>;
}
