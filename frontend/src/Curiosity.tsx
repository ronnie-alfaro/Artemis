import { useEffect, useState } from "react";
import { apiFetch, dateTime } from "./api";
import { PageHeader, StatusTag } from "./ui";
import "./curiosity.css";

const endpoint = "/api/v1/curiosity/explorations";
const labels = {
  DISCOVERED: "Descubierta",
  ANALYZED: "Analizada",
  FAILED: "Fallida",
  BLOCKED: "Bloqueada",
};
type Status = keyof typeof labels;
type Summary = { id: string; objective: string; created_at: string; status: Status };
type Operation = {
  method: string;
  path: string;
  operation_id: string | null;
  parameters: string[];
  responses: string[];
  authentication_declared: boolean;
  references_present: boolean;
};
type Report = Summary & {
  fingerprint: string;
  specification_version: string | null;
  operations: Operation[];
  reason: string | null;
  history: Status[];
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await apiFetch(path, init);
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(typeof payload?.detail === "string" ? payload.detail : "No se pudo completar la consulta.");
  }
  return response.json() as Promise<T>;
}

export function Curiosity() {
  const [objective, setObjective] = useState("");
  const [specification, setSpecification] = useState("");
  const [reports, setReports] = useState<Summary[] | null>(null);
  const [selected, setSelected] = useState<Report | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    void request<Summary[]>(endpoint, { signal: controller.signal })
      .then(items => { if (!controller.signal.aborted) setReports(items); })
      .catch((failure: Error) => { if (!controller.signal.aborted) setError(failure.message); });
    return () => controller.abort();
  }, []);

  async function perform(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "No se pudo completar la consulta.");
    } finally {
      setBusy(false);
    }
  }

  return <div className="curiosity">
    <PageHeader eyebrow="INVESTIGACIÓN" title="Curiosidad"
      description="Inventario de operaciones declaradas en Swagger u OpenAPI."/>
    <section className="panel curiosity-panel">
      <h2>Nueva exploración</h2>
      <form onSubmit={event => {
        event.preventDefault();
        void perform(async () => {
          const report = await request<Report>(endpoint, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ objective, specification }),
          });
          setSelected(report);
          setReports(await request<Summary[]>(endpoint));
        });
      }}>
        <label>Objetivo
          <input required maxLength={500} value={objective}
            onChange={event => setObjective(event.target.value)}/>
        </label>
        <label>Especificación JSON sin credenciales
          <textarea required rows={8} maxLength={131072} value={specification}
            onChange={event => setSpecification(event.target.value)}/>
        </label>
        <button className="primary" disabled={busy || !objective.trim() || !specification.trim()}>
          Analizar especificación
        </button>
      </form>
    </section>
    {error && <p role="alert">{error}</p>}
    <section className="panel curiosity-panel">
      <h2>Exploraciones recientes</h2>
      <button className="subtle-button" disabled={busy} onClick={() => {
        void perform(async () => setReports(await request<Summary[]>(endpoint)));
      }}>Actualizar</button>
      {reports?.length === 0 && <p>Todavía no hay exploraciones.</p>}
      {!!reports?.length && <ul className="curiosity-list">{reports.map(report =>
        <li key={report.id}>
          <button className="subtle-button" disabled={busy} onClick={() => {
            void perform(async () => setSelected(await request<Report>(`${endpoint}/${report.id}`)));
          }}>{report.objective}</button>
          <StatusTag tone={report.status === "ANALYZED" ? "good" : "neutral"}>{labels[report.status]}</StatusTag>
          <time dateTime={report.created_at}>{dateTime(report.created_at)}</time>
        </li>
      )}</ul>}
    </section>
    {selected && <section className="panel curiosity-panel" aria-label="Resultado de la exploración">
      <h2>{selected.objective}</h2>
      <p>{selected.history.map(status => labels[status]).join(" → ")}</p>
      {selected.specification_version && <p>Versión {selected.specification_version}</p>}
      {selected.reason && <p>{selected.reason}</p>}
      {!!selected.operations.length && <>
        <h3>Operaciones declaradas, sin verificación externa</h3>
        <ul className="curiosity-list">{selected.operations.map(operation =>
          <li key={`${operation.method} ${operation.path}`}>
            <strong><code>{operation.method} {operation.path}</code></strong>
            {operation.operation_id && <span>{operation.operation_id}</span>}
            {operation.parameters.length > 0 && <span>Parámetros · {operation.parameters.join(", ")}</span>}
            {operation.responses.length > 0 && <span>Respuestas · {operation.responses.join(", ")}</span>}
            {operation.authentication_declared && <span>Autenticación declarada</span>}
            {operation.references_present && <span>Referencias sin resolver</span>}
          </li>
        )}</ul>
      </>}
    </section>}
  </div>;
}
