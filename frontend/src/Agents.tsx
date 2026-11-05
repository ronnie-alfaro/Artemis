import { useEffect, useState, type DragEvent } from "react";
import { PageHeader as Header, List } from "./ui";
type Props = { apiFetch: (path: string, init?: RequestInit) => Promise<Response> };
type WhatsAppChannelStatus = {
  configured: boolean;
  agent_name: string | null;
  running: boolean;
  last_error: string | null;
};

export function Agents({ apiFetch }: Props) {
  const [whatsapp, setWhatsApp] = useState<WhatsAppChannelStatus | null>(null);
  const [availableSkills, setAvailableSkills] = useState<string[]>([]);
  const [boundSkills, setBoundSkills] = useState<string[]>([]);
  const [savedSkills, setSavedSkills] = useState<string[]>([]);
  const [skillSaveStatus, setSkillSaveStatus] = useState<string | null>(null);
  const [savingSkills, setSavingSkills] = useState(false);
  const [greeting, setGreeting] = useState("");
  const [greetingStatus, setGreetingStatus] = useState("");

  useEffect(() => {
    let active = true;
    void apiFetch("/api/v1/channels/whatsapp")
      .then((response) => response.ok ? response.json() as Promise<WhatsAppChannelStatus> : null)
      .then(async (status) => {
        if (!active) return;
        setWhatsApp(status);
        if (!status?.configured || !status.agent_name) return;
        const [binding, profile] = await Promise.all([
          apiFetch(`/api/v1/agents/whatsapp/${status.agent_name}/skills`),
          apiFetch(`/api/v1/agents/whatsapp/${status.agent_name}/profile`),
        ]);
        if (binding.ok && active) {
          const body = await binding.json() as { capabilities: string[]; available_capabilities: string[] };
          setBoundSkills(body.capabilities); setSavedSkills(body.capabilities); setAvailableSkills(body.available_capabilities);
        }
        if (profile.ok && active) setGreeting((await profile.json() as { greeting: string }).greeting);
      })
      .catch(() => { if (active) setWhatsApp(null); });
    return () => { active = false; };
  }, []);

  const rows = [["Asistente general", "Recibe tus mensajes y te ayuda a elegir una habilidad.", "Activo · sistema"]];
  if (whatsapp?.configured) {
    rows.push([
      `Agente de WhatsApp · ${whatsapp.agent_name ?? "sin nombre"}`,
      whatsapp.last_error ?? "Conversación conectada con tus habilidades y herramientas.",
      whatsapp.running ? "Activo · WhatsApp" : "Configurado · iniciando",
    ]);
  }
  const saveSkills = () => {
    if (!whatsapp?.agent_name) return;
    setSavingSkills(true); setSkillSaveStatus(null);
    void apiFetch(`/api/v1/agents/whatsapp/${whatsapp.agent_name}/skills`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ capabilities: boundSkills.filter(skill => skill !== "assistant.status") }),
    }).then(async response => {
      if (!response.ok) { setSkillSaveStatus("No se pudieron guardar las habilidades. Inténtalo de nuevo."); return; }
      const body = await response.json() as { capabilities: string[] };
      setBoundSkills(body.capabilities); setSavedSkills(body.capabilities); setSkillSaveStatus("Habilidades asignadas guardadas.");
    }).catch(() => setSkillSaveStatus("No se pudieron guardar las habilidades. Inténtalo de nuevo.")).finally(() => setSavingSkills(false));
  };
  const toggleSkill = (capability: string) => {
    setBoundSkills(previous => previous.includes(capability) ? previous.filter(item => item !== capability) : [...previous, capability]);
    setSkillSaveStatus("Hay cambios sin guardar.");
  };
  const moveSkill = (event: DragEvent, target: "bound" | "available") => {
    event.preventDefault();
    const capability = event.dataTransfer.getData("text/plain");
    if (!availableSkills.includes(capability)) return;
    setBoundSkills(target === "bound" ? [...new Set([...boundSkills, capability])] : boundSkills.filter(item => item !== capability));
    setSkillSaveStatus("Hay cambios sin guardar.");
  };
  const saveGreeting = () => {
    if (!whatsapp?.agent_name || !greeting.trim()) return;
    void apiFetch(`/api/v1/agents/whatsapp/${whatsapp.agent_name}/profile`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ greeting: greeting.trim() }),
    }).then(async response => { if (!response.ok) throw new Error("save"); setGreeting((await response.json() as { greeting: string }).greeting); setGreetingStatus("Mensaje de bienvenida guardado."); }).catch(() => setGreetingStatus("No se pudo guardar el mensaje de bienvenida."));
  };
  const skillLabel = (skill: string) => ({
    "seerr.media": "Películas y series · Seerr",
    "karakeep.bookmarks": "Buscar y guardar enlaces · Karakeep",
    "usenet.downloads": "Buscar y gestionar descargas · Usenet",
  }[skill] ?? skill);
  const skillsChanged = boundSkills.length !== savedSkills.length || boundSkills.some(skill => !savedSkills.includes(skill));
  return <><Header eyebrow="IDENTIDADES Y CONVERSACIONES" title="Agentes"/><List rows={rows}/>{whatsapp?.configured && <section className="panel skill-binding"><div><label>MENSAJE DE BIENVENIDA</label><h3>Agente de WhatsApp · {whatsapp.agent_name}</h3><p>En modo general se muestra este saludo y las habilidades asignadas. Usa «utiliza HABILIDAD» para activar una, «ayuda» para ver sus comandos y «salir» para volver al modo general.</p><textarea aria-label="Mensaje de bienvenida" value={greeting} onChange={event => setGreeting(event.target.value)} /><button className="primary" onClick={saveGreeting}>Guardar mensaje</button>{greetingStatus && <p role="status">{greetingStatus}</p>}</div><div className="binding-lanes"><div className="binding-lane" onDragOver={event => event.preventDefault()} onDrop={event => moveSkill(event, "available")}><strong>Habilidades disponibles</strong>{availableSkills.filter(skill => !boundSkills.includes(skill)).map(skill => <button draggable key={skill} onClick={() => toggleSkill(skill)} onDragStart={event => event.dataTransfer.setData("text/plain", skill)}>{skillLabel(skill)}</button>)}</div><div className="binding-lane agent-drop" onDragOver={event => event.preventDefault()} onDrop={event => moveSkill(event, "bound")}><strong>Asignadas al agente</strong><button disabled>Asistente general · respuesta del sistema</button>{boundSkills.filter(skill => skill !== "assistant.status").map(skill => <button draggable key={skill} onClick={() => toggleSkill(skill)} onDragStart={event => event.dataTransfer.setData("text/plain", skill)}>{skillLabel(skill)}</button>)}</div></div><div className="binding-save"><span role="status">{skillSaveStatus ?? (skillsChanged ? "Hay cambios sin guardar." : "Todas las asignaciones están guardadas.")}</span><button className="primary" onClick={saveSkills} disabled={!skillsChanged || savingSkills}>{savingSkills ? "Guardando…" : "Guardar habilidades asignadas"}</button></div></section>}<p className="hint">Arrastra una habilidad o púlsala para asignarla. Guarda los cambios para usarlos en WhatsApp.</p></>;
}
