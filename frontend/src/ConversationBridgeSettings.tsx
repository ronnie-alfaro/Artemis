import { useEffect, useState } from "react";

type Settings = { enabled: boolean; url: string; allowed_urls: string[] };
type Props = {
  apiFetch: (path: string, init?: RequestInit) => Promise<Response>;
  onSaved: () => void;
};

const endpoint = "/api/v1/conversation-bridge/settings";

export function ConversationBridgeSettings({ apiFetch, onSaved }: Props) {
  const [saved, setSaved] = useState<Settings | null>(null);
  const [enabled, setEnabled] = useState(false);
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");

  useEffect(() => {
    const abort = new AbortController();
    void apiFetch(endpoint, { signal: abort.signal }).then(async response => {
      if (!response.ok) throw new Error();
      const settings = await response.json() as Settings;
      if (abort.signal.aborted) return;
      setSaved(settings);
      setEnabled(settings.enabled);
      setUrl(settings.url);
    }).catch(() => {
      if (!abort.signal.aborted) setNotice("No se pudo cargar la configuración del bridge.");
    });
    return () => abort.abort();
  }, [apiFetch]);

  async function save() {
    setBusy(true);
    setNotice("");
    try {
      const response = await apiFetch(endpoint, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled, url }),
      });
      if (!response.ok) throw new Error();
      setSaved(await response.json() as Settings);
      setNotice("Configuración guardada. Se aplica a los mensajes nuevos.");
      onSaved();
    } catch {
      setNotice("No se pudo guardar la configuración del bridge.");
    } finally {
      setBusy(false);
    }
  }

  return <section className="panel skill-binding">
    <div className="persona-editor">
      <h2>Bridge conversacional</h2>
      {saved && <form onSubmit={event => { event.preventDefault(); void save(); }}>
        <label><input type="checkbox" checked={enabled} disabled={busy}
          onChange={event => setEnabled(event.target.checked)}/> Activar para WhatsApp y Telegram</label>
        <div>
          <label htmlFor="conversation-bridge-url">Dirección del bridge</label>{" "}
          <select id="conversation-bridge-url" value={url} disabled={busy}
            onChange={event => setUrl(event.target.value)}>
            {saved.allowed_urls.map(option => <option key={option} value={option}>{option}</option>)}
          </select>
        </div>
        <button className="primary" disabled={busy || (saved.enabled === enabled && saved.url === url)}>
          {busy ? "Guardando…" : "Guardar bridge"}
        </button>
      </form>}
      {notice && <p role="status">{notice}</p>}
    </div>
  </section>;
}
