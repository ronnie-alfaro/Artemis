import { useCallback, useEffect, useState } from "react";

type Provider = { id: string; label: string; status: "ready" | "untested" | "cooldown" | "missing" };
type Catalog = { providers: Provider[]; discoverable: string[] };
type Routing = { providers: string[]; last_provider: string | null };
type Props = {
  apiFetch: (path: string, init?: RequestInit) => Promise<Response>;
  channel: "whatsapp" | "telegram";
};

const base = "/api/v1/conversation-bridge";
const statusLabels = {
  ready: "Respondió correctamente",
  untested: "Instalado · sin verificar",
  cooldown: "Pausa tras un fallo",
  missing: "No disponible",
};

export function ConversationBridgeConfiguration({ apiFetch, channel }: Props) {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [order, setOrder] = useState<string[]>([]);
  const [last, setLast] = useState<string | null>(null);
  const [candidate, setCandidate] = useState("");
  const [label, setLabel] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);

  const reloadCatalog = useCallback(async () => {
    const response = await apiFetch(`${base}/providers`);
    if (!response.ok) throw new Error();
    setCatalog(await response.json() as Catalog);
  }, [apiFetch]);

  useEffect(() => {
    let active = true;
    void Promise.all([reloadCatalog(), apiFetch(`${base}/routing/${channel}`)])
      .then(async ([, response]) => {
        if (!response.ok) throw new Error();
        const routing = await response.json() as Routing;
        if (active) {
          setOrder(routing.providers);
          setLast(routing.last_provider);
          setLoaded(true);
        }
      })
      .catch(() => { if (active) setNotice("No se pudo consultar el bridge conversacional."); });
    return () => { active = false; };
  }, [apiFetch, channel, reloadCatalog]);

  async function update(path: string, method: "POST" | "PUT", body: object) {
    setBusy(true);
    setNotice("");
    try {
      const response = await apiFetch(`${base}${path}`, {
        method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      if (!response.ok) throw new Error();
      await reloadCatalog();
      setNotice(method === "PUT" ? "Orden de proveedores guardado." : "Adaptador registrado.");
      if (method === "POST") { setCandidate(""); setLabel(""); }
    } catch {
      setNotice("No se pudo aplicar el cambio.");
    } finally {
      setBusy(false);
    }
  }

  async function probe(id: string) {
    setBusy(true);
    setNotice("Probando proveedor…");
    try {
      const response = await apiFetch(`${base}/providers/${id}/probe`, { method: "POST" });
      if (!response.ok) throw new Error();
      const result = await response.json() as { ready: boolean };
      await reloadCatalog();
      setNotice(result.ready ? "El proveedor respondió correctamente." : "El proveedor no respondió.");
    } catch {
      setNotice("No se pudo verificar el proveedor.");
    } finally {
      setBusy(false);
    }
  }

  function move(index: number, direction: -1 | 1) {
    const next = [...order];
    [next[index], next[index + direction]] = [next[index + direction], next[index]];
    setOrder(next);
  }

  const names = new Map(catalog?.providers.map(provider => [provider.id, provider.label]));
  return <div className="persona-editor">
    <h2>LLM de {channel === "telegram" ? "Telegram" : "WhatsApp"}</h2>
    {catalog && loaded && <>
      <div>
        <label htmlFor={`bridge-primary-${channel}`}>LLM principal</label>{" "}
        <select id={`bridge-primary-${channel}`} value={order[0] ?? ""} disabled={busy}
          onChange={event => {
            const id = event.target.value;
            setOrder(id ? [id, ...order.filter(item => item !== id)].slice(0, 8) : []);
          }}>
          <option value="">Solo modo básico</option>
          {catalog.providers.map(provider => <option key={provider.id} value={provider.id}>
            {provider.label}
          </option>)}
        </select>{" "}
        <button className="primary" disabled={busy}
          onClick={() => void update(`/routing/${channel}`, "PUT", { providers: order })}>
          Guardar selección
        </button>
      </div>
      <p>El bot prueba los siguientes proveedores en orden si falla el principal.</p>
      {last && <p>Último proveedor utilizado: {names.get(last) ?? last}</p>}
      <ol>
        {order.map((id, index) => <li key={id}>
          {names.get(id) ?? id}{" · "}{statusLabels[catalog.providers.find(item => item.id === id)?.status ?? "missing"]}
          {" "}<button type="button" disabled={busy || catalog.providers.find(item => item.id === id)?.status === "missing"} onClick={() => void probe(id)}>Probar {names.get(id) ?? id}</button>
          {" "}<button type="button" disabled={busy || index === 0} onClick={() => move(index, -1)} aria-label={`Subir ${names.get(id) ?? id}`}>↑</button>
          {" "}<button type="button" disabled={busy || index === order.length - 1} onClick={() => move(index, 1)} aria-label={`Bajar ${names.get(id) ?? id}`}>↓</button>
          {" "}<button type="button" disabled={busy} onClick={() => setOrder(order.filter(item => item !== id))}>Quitar {names.get(id) ?? id}</button>
        </li>)}
      </ol>
      <div>
        <label htmlFor={`bridge-add-${channel}`}>Añadir al orden</label>{" "}
        <select id={`bridge-add-${channel}`} value="" disabled={busy || order.length >= 8} onChange={event => {
          if (event.target.value) setOrder([...order, event.target.value]);
        }}>
          <option value="">Seleccionar proveedor</option>
          {catalog.providers.filter(item => !order.includes(item.id)).map(item =>
            <option key={item.id} value={item.id}>{item.label}</option>)}
        </select>{" "}

      </div>
      <details>
        <summary>Registrar proveedor CLI</summary>
        {catalog.discoverable.length === 0 ? <p>Instala un adaptador en el host para registrarlo aquí.</p> : <form onSubmit={event => {
          event.preventDefault();
          void update("/providers", "POST", { id: candidate, label });
        }}>
          <label htmlFor={`bridge-adapter-${channel}`}>Adaptador instalado</label>{" "}
          <select id={`bridge-adapter-${channel}`} required value={candidate} onChange={event => setCandidate(event.target.value)}>
            <option value="">Seleccionar adaptador</option>
            {catalog.discoverable.map(id => <option key={id} value={id}>{id}</option>)}
          </select>{" "}
          <label htmlFor={`bridge-label-${channel}`}>Nombre</label>{" "}
          <input id={`bridge-label-${channel}`} required maxLength={60} value={label} onChange={event => setLabel(event.target.value)}/>{" "}
          <button disabled={busy || !candidate || !label.trim()}>Registrar</button>
        </form>}
      </details>
    </>}
    {notice && <p role="status">{notice}</p>}
  </div>;
}
