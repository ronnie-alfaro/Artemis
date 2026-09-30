import { useEffect, useState, type DragEvent, type ReactElement } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
import "./skills.css";

type View = "Overview" | "Agents" | "Skills" | "Flows" | "Channels" | "Runs" | "Approvals" | "Settings";
const nav: View[] = ["Overview", "Agents", "Skills", "Channels", "Runs", "Approvals", "Settings"];
const Header = ({ eyebrow, title }: { eyebrow: string; title: string; action?: string }) => <header><p>{eyebrow}</p><div className="head"><h1>{title}</h1></div></header>;
const apiFetch = (path: string, init: RequestInit = {}) => {
  const token = sessionStorage.getItem("artemis_admin_token");
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  return fetch(path, { ...init, headers });
};

function Overview() { return <><Header eyebrow="CONTROL PLANE" title="Your agent platform."/><div className="grid"><article className="hero"><label>READY TO CONNECT</label><h2>Build once. Deliver through any channel.</h2><p>Compose trusted skills, agents, and approval policy into versioned flows. Channels are delivery adapters—not orchestration logic.</p></article><Stat n="1" label="SYSTEM AGENT" text="Assistant status · always available"/><Stat n="1" label="CHANNEL" text="WhatsApp Agent API"/><Stat n="—" label="RUNS · 24 HOURS" text="Operational history appears in Runs"/></div><section className="panel"><label>GET STARTED</label><h3>From capability to channel</h3><ol className="steps"><Step n="1" title="Configure a skill" text="Add its endpoint and secret through the skill configuration."/><Step n="2" title="Attach skills" text="Drag approved capabilities onto the WhatsApp agent."/><Step n="3" title="Set the status response" text="Explain exactly what the agent can do for the user."/><Step n="4" title="Operate safely" text="Inspect runs and approve any write operation."/></ol></section></>; }
const Stat = ({n,label,text}:{n:string;label:string;text:string}) => <article className="stat"><label>{label}</label><strong>{n}</strong><span>{text}</span></article>;
const Step = ({n,title,text}:{n:string;title:string;text:string}) => <li><b>{n}</b><div><strong>{title}</strong><span>{text}</span></div></li>;
type WhatsAppChannelStatus = {
  configured: boolean;
  agent_name: string | null;
  running: boolean;
  last_error: string | null;
};

function Agents() {
  const [whatsapp, setWhatsApp] = useState<WhatsAppChannelStatus | null>(null);
  const [availableSkills, setAvailableSkills] = useState<string[]>([]);
  const [boundSkills, setBoundSkills] = useState<string[]>([]);
  const [greeting, setGreeting] = useState("");

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
          setBoundSkills(body.capabilities); setAvailableSkills(body.available_capabilities);
        }
        if (profile.ok && active) setGreeting((await profile.json() as { greeting: string }).greeting);
      })
      .catch(() => { if (active) setWhatsApp(null); });
    return () => { active = false; };
  }, []);

  const rows = [["Assistant status", "Always-on response that explains available skills.", "healthy · system"]];
  if (whatsapp?.configured) {
    rows.push([
      `WhatsApp Agent · ${whatsapp.agent_name ?? "unnamed"}`,
      whatsapp.last_error ?? "Long-poll channel connected to the Artemis orchestrator.",
      whatsapp.running ? "healthy · whatsapp" : "configured · starting",
    ]);
  }
  const saveSkills = (next: string[]) => {
    if (!whatsapp?.agent_name) return;
    setBoundSkills(next);
    void apiFetch(`/api/v1/agents/whatsapp/${whatsapp.agent_name}/skills`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ capabilities: next }),
    }).then(async response => { if (response.ok) setBoundSkills((await response.json()).capabilities); });
  };
  const moveSkill = (event: DragEvent, target: "bound" | "available") => {
    event.preventDefault();
    const capability = event.dataTransfer.getData("text/plain");
    if (!availableSkills.includes(capability)) return;
    saveSkills(target === "bound" ? [...new Set([...boundSkills, capability])] : boundSkills.filter(item => item !== capability));
  };
  const saveGreeting = () => {
    if (!whatsapp?.agent_name || !greeting.trim()) return;
    void apiFetch(`/api/v1/agents/whatsapp/${whatsapp.agent_name}/profile`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ greeting: greeting.trim() }),
    }).then(async response => { if (response.ok) setGreeting((await response.json() as { greeting: string }).greeting); });
  };
  const skillLabel = (skill: string) => skill === "seerr.media" ? "Media requests · movies & series" : skill;
  return <><Header eyebrow="RUNTIME IDENTITIES" title="Agents" action="New agent"/><List rows={rows}/>{whatsapp?.configured && <section className="panel skill-binding"><div><label>WHATSAPP STATUS RESPONSE</label><h3>WhatsApp Agent · {whatsapp.agent_name}</h3><p>Every ordinary message receives this editable welcome/status response. It lists only skills currently assigned below.</p><textarea aria-label="Status response" value={greeting} onChange={event => setGreeting(event.target.value)} /><button className="primary" onClick={saveGreeting}>Save message</button></div><div className="binding-lanes"><div className="binding-lane" onDragOver={event => event.preventDefault()} onDrop={event => moveSkill(event, "available")}><strong>Available skills</strong>{availableSkills.filter(skill => !boundSkills.includes(skill)).map(skill => <button draggable key={skill} onDragStart={event => event.dataTransfer.setData("text/plain", skill)}>{skillLabel(skill)}</button>)}</div><div className="binding-lane agent-drop" onDragOver={event => event.preventDefault()} onDrop={event => moveSkill(event, "bound")}><strong>Assigned to this agent</strong><button disabled>Assistant status · system response</button>{boundSkills.filter(skill => skill !== "assistant.status").map(skill => <button draggable key={skill} onDragStart={event => event.dataTransfer.setData("text/plain", skill)}>{skillLabel(skill)}</button>)}</div></div></section>}<p className="hint">Agents own instructions, model policy, memory scope, permissions and health. Skills are attached through explicit contracts.</p></>;
}
type SkillCapability = { name: string; method: string; endpoint: string; risk: "READ" | "WRITE"; description: string; inputs: string; output: string };
type SkillDetail = { id: string; name: string; status: string; description: string; auth: string; availability: string; capabilities: SkillCapability[] };
type SeerrConfiguration = { configured: boolean; base_url: string | null; credential_source: string | null; last_test: string | null };
const skills: SkillDetail[] = [
  { id: "seerr", name: "Seerr media requests", status: "optional · enabled when configured", description: "Search and request movies or TV through Seerr. The agent selects it only when it holds seerr.media.", auth: "X-Api-Key · never shown in runs", availability: "External business tool · no live connection verified", capabilities: [
    { name: "search_media", method: "GET", endpoint: "/api/v1/search", risk: "READ", description: "Finds movies and TV candidates before any mutation.", inputs: "query", output: "title · year · type · TMDB ID" },
    { name: "get_media_details", method: "GET", endpoint: "/api/v1/movie|tv/{tmdb_id}", risk: "READ", description: "Resolves an ambiguous candidate before a request is proposed.", inputs: "media_type · tmdb_id", output: "typed media details" },
    { name: "create_request", method: "POST", endpoint: "/api/v1/request", risk: "WRITE", description: "Creates the selected request only after an expiring, concrete approval.", inputs: "media · requester · profile · seasons", output: "request ID · status" },
    { name: "get_request_status", method: "GET", endpoint: "/api/v1/request/{request_id}", risk: "READ", description: "Reads the status of a request or an existing duplicate.", inputs: "request_id", output: "typed request status" },
  ] },
];
function Skills() {
  const [selectedId, setSelectedId] = useState("seerr");
  const [configuration, setConfiguration] = useState<SeerrConfiguration | null>(null);
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const selected = skills.find(skill => skill.id === selectedId) ?? skills[0];
  const loadConfiguration = () => void apiFetch("/api/v1/skills/seerr/configuration").then(async response => {
    if (!response.ok) return;
    const body = await response.json() as SeerrConfiguration;
    setConfiguration(body); setBaseUrl(body.base_url ?? "");
  }).catch(() => undefined);
  useEffect(loadConfiguration, []);
  const saveConfiguration = () => {
    if (!baseUrl.trim() || !apiKey.trim()) return;
    void apiFetch("/api/v1/skills/seerr/configuration", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ base_url: baseUrl.trim(), api_key: apiKey.trim() }) })
      .then(async response => { if (response.ok) { setConfiguration(await response.json() as SeerrConfiguration); setApiKey(""); } });
  };
  const testConnection = () => void apiFetch("/api/v1/skills/seerr/configuration/test", { method: "POST" }).then(async response => { if (response.ok) setConfiguration(await response.json() as SeerrConfiguration); });
  return <><Header eyebrow="TRUSTED EXECUTION" title="Skills" action="Add skill"/><section className="skill-canvas"><div className="flowbar"><strong>Capability inventory</strong><span>typed · policy-aware</span><button>View contracts</button></div><div className="skill-nodes">{skills.map(skill => <button key={skill.id} onClick={() => setSelectedId(skill.id)} className={selected.id === skill.id ? "skill-node selected" : "skill-node"}><strong>{skill.name}</strong><small>{skill.capabilities.length} capabilities · {skill.status}</small></button>)}</div><div className="skill-inspector"><label>SELECTED SKILL</label><div className="skill-head"><div><h3>{selected.name}</h3><p>{selected.description}</p></div><em>{selected.status}</em></div>{selected.id === "seerr" && <section className="skill-config"><div><strong>Connection configuration</strong><span>{configuration?.configured ? `Configured from ${configuration.credential_source}` : "Not configured"}</span></div><label>SEERR URL<input aria-label="Seerr URL" value={baseUrl} placeholder="https://seerr.your-network" onChange={event => setBaseUrl(event.target.value)} /></label><label>API KEY<input aria-label="Seerr API key" type="password" value={apiKey} placeholder={configuration?.configured ? "Stored securely — enter only to replace" : "Paste the Seerr API key"} onChange={event => setApiKey(event.target.value)} /></label><div className="config-actions"><button className="primary" onClick={saveConfiguration}>Save connection</button><button onClick={testConnection}>Test connection</button></div>{configuration?.last_test && <p role="status">{configuration.last_test}</p>}</section>}<div className="skill-meta"><span>AUTH · {selected.auth}</span><span>{selected.availability}</span></div><div className="capabilities">{selected.capabilities.map(capability => <article key={capability.name}><div className="capability-title"><strong>{capability.name}</strong><code>{capability.method} {capability.endpoint}</code><em className={capability.risk === "WRITE" ? "write" : "read"}>{capability.risk}</em></div><p>{capability.description}</p><dl><div><dt>INPUT</dt><dd>{capability.inputs}</dd></div><div><dt>OUTPUT</dt><dd>{capability.output}</dd></div></dl></article>)}</div></div></section><p className="hint">Capabilities describe allowlisted contracts, not arbitrary canvas code. WRITE operations always create a concrete approval.</p></>;
}
function List({rows}:{rows:string[][]}) { return <section className="panel list">{rows.map(([title,description,status])=><article key={title}><div><h3>{title}</h3><span>{description}</span></div><em>{status}</em></article>)}</section>; }
function Flows() { const [node,setNode]=useState("Inbound request"); const names=["Inbound request","Capability planner","Library Agent","Research Agent","Synthesis"]; return <><Header eyebrow="VERSIONED ORCHESTRATION" title="Flows" action="New flow"/><section className="canvas"><div className="flowbar"><strong>Library + research comparison</strong><span>Draft · validated</span><button>Publish</button></div><div className="nodes">{names.map((name,index)=><><button key={name} onClick={()=>setNode(name)} className={node===name?"node selected":"node"}>{name}<small>{index===0?"Channel message":index===1?"Execution plan":index===4?"Validated response":"Capability"}</small></button>{index<names.length-1&&<b key={`${name}-arrow`}>→</b>}</>)}</div><div className="inspector"><label>SELECTED NODE</label><h3>{node}</h3><p>Typed contract, declared permissions, timeout and retry policy are validated before publishing.</p></div></section><p className="hint">The builder is declarative: visual composition produces a reviewed execution DAG, not arbitrary code execution.</p></>; }
function Channels() { return <><Header eyebrow="DELIVERY ADAPTERS" title="Channels" action="Add channel"/><List rows={[["WhatsApp Agent","Long-poll adapter. Create the agent in WhatsApp, then configure its secret-backed API token.","configured in deployment"]]}/></>; }
function Runs() { return <><Header eyebrow="OPERATIONS" title="Runs"/><section className="empty"><h3>Operational history is private by default.</h3><p>WhatsApp inbound events are durably queued in PostgreSQL. A production deployment exposes metadata and audits here without exposing message content.</p></section></>; }
function Approvals() { return <><Header eyebrow="HUMAN CONTROL" title="Approvals"/><section className="empty"><h3>Nothing requires your attention.</h3><p>Seerr create_request is WRITE: a concrete title, requester and expiry must be approved here. READ skills run automatically.</p></section></>; }
function Settings() { return <><Header eyebrow="PLATFORM CONFIGURATION" title="Settings"/><List rows={[["Access control","Production deployment requires an operator token","Configure in deployment"],["MCP servers","No trusted MCP connections configured","Configure"],["Privacy & observability","Correlation IDs and Prometheus metrics enabled","Configure"]]}/></>; }
function SignIn({ onAuthenticated }: { onAuthenticated: () => void }) { const [token, setToken] = useState(""); return <main className="sign-in"><section className="panel"><label>ARTEMIS CONTROL PLANE</label><h1>Operator access</h1><p>Enter the deployment’s operator token. It stays only in this browser session.</p><input aria-label="Operator token" type="password" value={token} onChange={event => setToken(event.target.value)} /><button className="primary" onClick={() => { if (token.trim()) { sessionStorage.setItem("artemis_admin_token", token.trim()); onAuthenticated(); } }}>Continue</button></section></main>; }
export function App() { const [view,setView]=useState<View>("Overview"); const [authRequired, setAuthRequired] = useState(false); const [authenticated, setAuthenticated] = useState(Boolean(sessionStorage.getItem("artemis_admin_token"))); useEffect(() => { void fetch("/api/v1/auth/status").then(async response => { if (response.ok) setAuthRequired((await response.json() as { authentication_required: boolean }).authentication_required); }).catch(() => undefined); }, []); if (authRequired && !authenticated) return <SignIn onAuthenticated={() => setAuthenticated(true)} />; const pages:Record<View,ReactElement>={Overview:<Overview/>,Agents:<Agents/>,Skills:<Skills/>,Flows:<Flows/>,Channels:<Channels/>,Runs:<Runs/>,Approvals:<Approvals/>,Settings:<Settings/>}; return <main><aside><div className="mark">ARTEMIS<small>CONTROL PLANE</small></div><nav>{nav.map(item=><button key={item} onClick={()=>setView(item)} className={view===item?"active":""}>{item}</button>)}</nav><div className="foot"><i/>System healthy<br/><span>Local deployment</span></div></aside><section className="workspace">{pages[view]}</section></main>; }
const root=document.getElementById("root"); if(root) createRoot(root).render(<App/>);
