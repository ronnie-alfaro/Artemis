import { useEffect, useState } from "react";
import { apiFetch } from "./api";

type Props = { provider: "whatsapp" | "telegram"; onApplied: () => void };
type Configuration = {
  configured: boolean; enabled: boolean; editable: boolean;
  credential_source: string | null; agent_name: string | null; allowed_user_ids: number[];
};

export function ChannelConfiguration({ provider, onApplied }: Props) {
  const [configuration, setConfiguration] = useState<Configuration | null>(null);
  const [token, setToken] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [agent, setAgent] = useState("primary");
  const [users, setUsers] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const label = provider === "telegram" ? "Telegram" : "WhatsApp";
  useEffect(() => {
    let active = true;
    void apiFetch(`/api/v1/channels/${provider}/configuration`).then(async response => {
      if (!response.ok) throw new Error("load");
      const result = await response.json() as Configuration;
      if (!active) return;
      setConfiguration(result); setEnabled(result.configured ? result.enabled : true);
      setAgent(result.agent_name ?? "primary"); setUsers(result.allowed_user_ids.join(", "));
    }).catch(() => { if (active) setMessage("No se pudo cargar la configuración del canal."); });
    return () => { active = false; };
  }, [provider]);
  const save = async () => {
    const parts = users.split(",").map(value => value.trim());
    if (provider === "telegram" && (!users.trim() || parts.some(value => !/^[1-9]\d*$/.test(value) || !Number.isSafeInteger(Number(value))))) {
      setMessage("Introduce identificadores numéricos positivos separados por comas."); return;
    }
    setBusy(true); setMessage("");
    try {
      const response = await apiFetch(`/api/v1/channels/${provider}/configuration`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled, token: token || null, agent_name: provider === "whatsapp" ? agent.trim() : "primary", allowed_user_ids: provider === "telegram" ? parts.map(Number) : [] }),
      });
      if (!response.ok) throw new Error("save");
      setConfiguration(await response.json() as Configuration); setToken("");
      setMessage(enabled ? "Configuración guardada y aplicada." : "Canal desactivado."); onApplied();
    } catch { setMessage("No se pudo aplicar. Revisa las credenciales, los usuarios autorizados y el servicio de cifrado."); }
    finally { setBusy(false); }
  };
  return <details className="channel-configuration"><summary>Conexión de {label}</summary>
    {configuration?.editable ? <fieldset disabled={busy}>
      <label><input type="checkbox" checked={enabled} onChange={event => setEnabled(event.target.checked)}/> Canal habilitado</label>
      <label>Token de {label}<input aria-label={`Token de ${label}`} type="password" autoComplete="new-password" value={token} onChange={event => setToken(event.target.value)} placeholder={configuration.configured ? "Deja vacío para conservar el token" : "Introduce el token"}/></label>
      {provider === "whatsapp" ? <label>Nombre del agente<input aria-label="Nombre del agente de WhatsApp" value={agent} onChange={event => setAgent(event.target.value)}/></label> : <label>Usuarios autorizados<input aria-label="Usuarios autorizados de Telegram" value={users} onChange={event => setUsers(event.target.value)} placeholder="Identificadores numéricos separados por comas"/></label>}
      <button className="primary" disabled={busy || (!configuration.configured && !token)} onClick={() => void save()}>{busy ? "Aplicando…" : "Guardar y aplicar"}</button>
    </fieldset> : configuration && <p>La edición requiere configurar el almacenamiento cifrado del servidor.</p>}
    {message && <p role="status">{message}</p>}
  </details>;
}
