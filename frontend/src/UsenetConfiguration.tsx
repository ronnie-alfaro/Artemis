import { useEffect, useState } from "react";

type Configuration = {
  configured: boolean;
  provider_url: string | null;
  nzbget_url: string;
  nzbget_username: string | null;
  provider_test: string | null;
  downloader_test: string | null;
  last_test: string | null;
};

type Props = { apiFetch: (path: string, init?: RequestInit) => Promise<Response> };
const defaultUrl = "https://ronnie.nunavut.usbx.me/nzbget/xmlrpc";

export function UsenetConfiguration({ apiFetch }: Props) {
  const [configuration, setConfiguration] = useState<Configuration | null>(null);
  const [providerUrl, setProviderUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [downloadUrl, setDownloadUrl] = useState(defaultUrl);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    let active = true;
    void apiFetch("/api/v1/skills/usenet/configuration").then(async response => {
      if (!response.ok) throw new Error("load");
      const value = await response.json() as Configuration;
      if (!active) return;
      setConfiguration(value); setProviderUrl(value.provider_url ?? "");
      setDownloadUrl(value.nzbget_url || defaultUrl); setUsername(value.nzbget_username ?? "");
    }).catch(() => { if (active) setMessage("No se pudo cargar la configuración."); });
    return () => { active = false; };
  }, [apiFetch]);

  const changed = (update: () => void) => { update(); setDirty(true); setMessage(""); };
  const save = async () => {
    setBusy(true); setMessage("");
    try {
      const response = await apiFetch("/api/v1/skills/usenet/configuration", {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider_url: providerUrl.trim(), provider_api_key: apiKey || null,
          nzbget_url: downloadUrl.trim(), nzbget_username: username.trim(),
          nzbget_password: password || null,
        }),
      });
      if (!response.ok) throw new Error("save");
      setConfiguration(await response.json() as Configuration);
      setApiKey(""); setPassword(""); setDirty(false); setMessage("Conexiones guardadas.");
    } catch { setMessage("No se pudo guardar. Revisa las URLs y las credenciales de ambas conexiones."); }
    finally { setBusy(false); }
  };
  const test = async () => {
    setBusy(true); setMessage("");
    try {
      const response = await apiFetch("/api/v1/skills/usenet/configuration/test", { method: "POST" });
      if (!response.ok) throw new Error("test");
      const result = await response.json() as Configuration;
      setConfiguration(result); setMessage(result.last_test ?? "");
    } catch { setMessage("No se pudo comprobar la conexión. Inténtalo de nuevo."); }
    finally { setBusy(false); }
  };
  const valid = providerUrl.trim() && downloadUrl.trim() && username.trim()
    && (configuration?.configured || (apiKey && password));

  return <section className="skill-config">
    <div><strong>Conexiones de Usenet</strong><span>{configuration?.configured ? "Credenciales guardadas" : "Configura las dos conexiones"}</span></div>
    <h4>Buscador · NZBPlanet</h4>
    <label>URL del proveedor<input aria-label="URL de NZBPlanet" value={providerUrl} placeholder="URL de la API del proveedor" onChange={event => changed(() => setProviderUrl(event.target.value))}/></label>
    <label>Clave de API<input aria-label="Clave de API de NZBPlanet" type="password" autoComplete="new-password" value={apiKey} placeholder={configuration?.configured ? "Guardada; deja vacío para conservarla" : "Introduce tu clave de API"} onChange={event => changed(() => setApiKey(event.target.value))}/></label>
    {configuration?.provider_test && <p>Buscador: {configuration.provider_test}</p>}
    <h4>Gestor de descargas · NZBGet</h4>
    <label>URL de conexión<input aria-label="URL de NZBGet" value={downloadUrl} onChange={event => changed(() => setDownloadUrl(event.target.value))}/></label>
    <label>Usuario<input aria-label="Usuario de NZBGet" autoComplete="off" value={username} onChange={event => changed(() => setUsername(event.target.value))}/></label>
    <label>Contraseña<input aria-label="Contraseña de NZBGet" type="password" autoComplete="new-password" value={password} placeholder={configuration?.configured ? "Guardada; deja vacío para conservarla" : "Introduce tu contraseña"} onChange={event => changed(() => setPassword(event.target.value))}/></label>
    {configuration?.downloader_test && <p>Gestor de descargas: {configuration.downloader_test}</p>}
    <div className="config-actions"><button className="primary" disabled={busy || !valid} onClick={() => void save()}>Guardar conexiones</button><button disabled={busy || dirty || !configuration?.configured} onClick={() => void test()}>{busy ? "Procesando…" : "Probar conexiones"}</button></div>
    {dirty && <p>Guarda los cambios antes de probar las conexiones.</p>}
    {message && <p role="status">{message}</p>}
  </section>;
}
