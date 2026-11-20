import { useEffect, useState, type DragEvent } from "react";
import { ConversationBridgeSettings } from "./ConversationBridgeSettings";
import { ConversationBridgeConfiguration } from "./ConversationBridgeConfiguration";
import { PageHeader as Header, List } from "./ui";
type Props = { apiFetch: (path: string, init?: RequestInit) => Promise<Response> };
export type AgentChannel = "whatsapp" | "telegram";
type WhatsAppChannelStatus = {
  configured: boolean;
  agent_name: string | null;
  running: boolean;
  last_error: string | null;
};

function ChannelAgent({ apiFetch, channel, bridgeRevision }: Props & { channel: AgentChannel; bridgeRevision: number }) {
  const channelLabel = channel === "telegram" ? "Telegram" : "WhatsApp";
  const [whatsapp, setWhatsApp] = useState<WhatsAppChannelStatus | null>(null);
  const [availableSkills, setAvailableSkills] = useState<string[]>([]);
  const [boundSkills, setBoundSkills] = useState<string[]>([]);
  const [savedSkills, setSavedSkills] = useState<string[]>([]);
  const [skillSaveStatus, setSkillSaveStatus] = useState<string | null>(null);
  const [savingSkills, setSavingSkills] = useState(false);
  const [persona, setPersona] = useState("");
  const [personaStatus, setPersonaStatus] = useState("");

  useEffect(() => {
    let active = true;
    void apiFetch(`/api/v1/channels/${channel}`)
      .then((response) => response.ok ? response.json() as Promise<WhatsAppChannelStatus> : null)
      .then(async (status) => {
        if (!active) return;
        setWhatsApp(status);
        if (!status?.configured || !status.agent_name) return;
        const [binding, profile] = await Promise.all([
          apiFetch(`/api/v1/agents/${channel}/${status.agent_name}/skills`),
          apiFetch(`/api/v1/agents/${channel}/${status.agent_name}/profile`),
        ]);
        if (binding.ok && active) {
          const body = await binding.json() as { capabilities: string[]; available_capabilities: string[] };
          setBoundSkills(body.capabilities); setSavedSkills(body.capabilities); setAvailableSkills(body.available_capabilities);
        }
        if (profile.ok && active) {
          const body = await profile.json() as { persona?: string };
          setPersona(body.persona ?? "");
        }
      })
      .catch(() => { if (active) setWhatsApp(null); });
    return () => { active = false; };
  }, [apiFetch, channel]);

  const rows = [["Asistente general", "Conversa y utiliza las habilidades asignadas según lo que necesites.", "Activo · sistema"]];
  if (whatsapp?.configured) {
    rows.push([
      `Agente de ${channelLabel} · ${whatsapp.agent_name ?? "sin nombre"}`,
      whatsapp.last_error ?? "Conversación conectada con tus habilidades y herramientas.",
      whatsapp.running ? `Activo · ${channelLabel}` : "Configurado · iniciando",
    ]);
  }
  const saveSkills = () => {
    if (!whatsapp?.agent_name) return;
    setSavingSkills(true); setSkillSaveStatus(null);
    void apiFetch(`/api/v1/agents/${channel}/${whatsapp.agent_name}/skills`, {
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
  const savePersona = async () => {
    if (!whatsapp?.agent_name || !persona.trim()) return;
    setPersonaStatus("");
    try {
      const response = await apiFetch(`/api/v1/agents/${channel}/${whatsapp.agent_name}/profile`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ persona: persona.trim() }),
      });
      if (!response.ok) throw new Error("save");
      const body = await response.json() as { persona: string };
      setPersona(body.persona); setPersonaStatus("PERSONA guardada. Se aplicará al próximo mensaje.");
    } catch { setPersonaStatus("No se pudo guardar la PERSONA."); }
  };
  const skillLabel = (skill: string) => ({
    "curiosity.api": "Integrar APIs · Curiosidad",
    "memory.records": "Buscar y editar recuerdos · Chroma",
    "seerr.media": "Películas y series · Seerr",
    "github.repositories": "Repositorios y actividad · GitHub",
    "karakeep.bookmarks": "Buscar y guardar enlaces · Karakeep",
    "usenet.downloads": "Buscar y gestionar descargas · Usenet",
    "antigravity.assistant": "Desarrollo y tareas del proyecto · AGY",
    "codex.assistant": "Asistencia y herramientas · Codex",
  }[skill] ?? skill);
  const skillsChanged = boundSkills.length !== savedSkills.length || boundSkills.some(skill => !savedSkills.includes(skill));
  return <section className="agent-profile" aria-label={`Agente de ${channelLabel}`}>
    <h2>{channelLabel}</h2>
    <List rows={rows}/>
    {whatsapp?.configured && <>
      <section className="panel skill-binding">
        <div className="persona-editor">
          <label htmlFor={`persona-${channel}`}>PERSONA</label>
          <p>Define la personalidad, el tono y cómo quieres que actúe este bot. Las habilidades asignadas determinan lo que puede utilizar.</p>
          <textarea id={`persona-${channel}`} aria-label={`PERSONA de ${channelLabel}`}
            maxLength={8000} value={persona} onChange={event => setPersona(event.target.value)}
            placeholder="Eres Artemis: cercano, ingenioso y claro. Respondes de forma breve y ayudas a usar la app…"/>
          <div className="binding-save">
            <span role="status">{personaStatus}</span>
            <button className="primary" disabled={!persona.trim()} onClick={() => void savePersona()}>Guardar PERSONA</button>
          </div>
        </div>
      </section>
      <section className="panel skill-binding">
        <div>
          <h3>Habilidades del agente</h3>
          <p>Arrastra una habilidad o púlsala para cambiar su asignación. Guarda los cambios para que el bot los aplique en {channelLabel}.</p>
        </div>
        <div className="binding-lanes">
          <div className="binding-lane" onDragOver={event => event.preventDefault()} onDrop={event => moveSkill(event, "available")}>
            <strong>Habilidades disponibles</strong>
            {availableSkills.filter(skill => !boundSkills.includes(skill)).map(skill =>
              <button draggable key={skill} onClick={() => toggleSkill(skill)}
                onDragStart={event => event.dataTransfer.setData("text/plain", skill)}>{skillLabel(skill)}</button>)}
          </div>
          <div className="binding-lane agent-drop" onDragOver={event => event.preventDefault()} onDrop={event => moveSkill(event, "bound")}>
            <strong>Asignadas al agente</strong>
            <button disabled>Conversación natural</button>
            {boundSkills.filter(skill => skill !== "assistant.status").map(skill =>
              <button draggable key={skill} onClick={() => toggleSkill(skill)}
                onDragStart={event => event.dataTransfer.setData("text/plain", skill)}>{skillLabel(skill)}</button>)}
          </div>
        </div>
        <div className="binding-save">
          <span role="status">{skillSaveStatus ?? (skillsChanged ? "Hay cambios sin guardar." : "Todas las asignaciones están guardadas.")}</span>
          <button className="primary" onClick={saveSkills} disabled={!skillsChanged || savingSkills}>
            {savingSkills ? "Guardando…" : "Guardar habilidades asignadas"}
          </button>
        </div>
      </section>
      <section className="panel skill-binding">
        <ConversationBridgeConfiguration key={`${whatsapp.agent_name}:${bridgeRevision}`} apiFetch={apiFetch} channel={channel}/>
      </section>
    </>}
  </section>;
}

export function Agents({ apiFetch, channel, onChannelChange }: Props & {
  channel: AgentChannel;
  onChannelChange: (channel: AgentChannel) => void;
}) {
  const [bridgeRevision, setBridgeRevision] = useState(0);
  return <>
    <Header eyebrow="IDENTIDADES Y CONVERSACIONES" title="Agentes"
      description="Configura la personalidad y las habilidades de cada agente."/>
    <div className="agent-switch" role="group" aria-label="Canal del agente">
      <button type="button" aria-pressed={channel === "whatsapp"} onClick={() => onChannelChange("whatsapp")}>WhatsApp</button>
      <button type="button" aria-pressed={channel === "telegram"} onClick={() => onChannelChange("telegram")}>Telegram</button>
    </div>
    <div hidden={channel !== "whatsapp"}><ChannelAgent apiFetch={apiFetch} channel="whatsapp" bridgeRevision={bridgeRevision}/></div>
    <div hidden={channel !== "telegram"}><ChannelAgent apiFetch={apiFetch} channel="telegram" bridgeRevision={bridgeRevision}/></div>
    <ConversationBridgeSettings apiFetch={apiFetch}
      onSaved={() => setBridgeRevision(revision => revision + 1)}/>
  </>;
}
