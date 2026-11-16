import { ChannelConfiguration } from "./ChannelConfiguration";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { Agents } from "./Agents";
import { Skills } from "./Skills";
import { Brain } from "./Brain";
import { Tools } from "./Tools";
import { Overview } from "./Overview";
import { apiFetch } from "./api";
import { Icon, PageHeader, StatusTag, type IconName } from "./ui";
import "./styles.css";
import "./brand.css";
import "./skills.css";

type View = "Overview" | "Agents" | "Skills" | "Tools" | "Channels" | "Settings" | "Brain";
type ToolId = "notifications" | "webhooks" | "reminders";
type Route = { view: View; tool?: ToolId };
type Preferences = { theme: "dark" | "light"; motion: "full" | "reduced"; density: "comfortable" | "compact" };
const navigation: { id: View; label: string; icon: IconName; path: string; description: string }[] = [
  { id: "Overview", label: "Inicio", icon: "home", path: "inicio", description: "Tus herramientas, de un vistazo" },
  { id: "Agents", label: "Agentes", icon: "agents", path: "agentes", description: "Conversaciones y habilidades asignadas" },
  { id: "Skills", label: "Habilidades", icon: "skills", path: "habilidades", description: "Seerr, Karakeep, Usenet, Codex y Antigravity" },
  { id: "Tools", label: "Herramientas", icon: "tools", path: "herramientas", description: "Notificaciones, webhooks y recordatorios" },
  { id: "Brain", label: "Cerebro", icon: "brain", path: "cerebro", description: "Memoria vectorial, herramientas nativas y minions" },
  { id: "Channels", label: "Canales", icon: "channels", path: "canales", description: "Tus conexiones con WhatsApp y Telegram" },
  { id: "Settings", label: "Ajustes", icon: "settings", path: "ajustes", description: "Haz que este espacio sea tuyo" },
];
function readRoute(): Route {
  const [path, tool] = window.location.hash.replace(/^#\/?/, "").split("/");
  const match = navigation.find(item => item.path === path);
  return { view: match?.id ?? "Overview", ...(match?.id === "Tools" && ["notifications", "webhooks", "reminders"].includes(tool) ? { tool: tool as ToolId } : {}) };
}
function readPreferences(): Preferences {
  try {
    const saved = JSON.parse(localStorage.getItem("artemis_preferences") ?? "{}");
    return { theme: saved.themeRevision === 2 && saved.theme === "dark" ? "dark" : "light", motion: saved.motion === "reduced" ? "reduced" : "full", density: saved.density === "compact" ? "compact" : "comfortable" };
  } catch { return { theme: "light", motion: "full", density: "comfortable" }; }
}
function Clock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => { const timer = window.setInterval(() => setNow(new Date()), 1000); return () => window.clearInterval(timer); }, []);
  return <time className="live-clock" dateTime={now.toISOString()}><span>{now.toLocaleDateString("es-ES", { day: "numeric", month: "short" })}</span>{now.toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</time>;
}
function ChannelCard({ onAgents, provider }: { onAgents: () => void; provider: "whatsapp" | "telegram" }) {
  const label = provider === "telegram" ? "Telegram" : "WhatsApp";
  const [revision, setRevision] = useState(0);
  const [channel, setChannel] = useState<{ configured: boolean; running: boolean; agent_name: string | null; last_error: string | null } | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => { let active = true; void apiFetch(`/api/v1/channels/${provider}`).then(async response => { if (!response.ok) throw new Error("status"); const value = await response.json(); if (active) setChannel(value); }).catch(() => { if (active) setError(true); }); return () => { active = false; }; }, [provider, revision]);
  return <section className="panel channel-card"><div className="channel-emblem"><img src={`/channels/${provider}.svg`} alt={`Logo de ${label}`} width={48} height={48}/></div><div className="channel-copy"><div className="section-heading"><h2>{label}</h2><StatusTag tone={channel?.running ? "good" : "neutral"}>{error ? "Sin verificar" : !channel ? "Consultando…" : channel.running ? "En marcha" : channel.configured ? "Iniciando" : "Sin configurar"}</StatusTag></div><p>{provider === "telegram" ? "Conecta tu bot y conversa con las habilidades de Artemis en un chat privado." : "Tu acceso directo a las habilidades, las notificaciones y los recordatorios de Artemis."}</p><div className="channel-facts"><div><span>AGENTE</span><strong>{channel?.agent_name ?? "Sin asignar"}</strong></div><div><span>CONVERSACIÓN</span><strong>{channel?.configured ? "Personal" : "Pendiente de configuración"}</strong></div></div>{channel?.last_error && <p role="status">{channel.last_error}</p>}{error && <p role="alert">No se pudo comprobar el canal. Inténtalo de nuevo más tarde.</p>}<ChannelConfiguration provider={provider} onApplied={() => setRevision(value => value + 1)}/><button className="primary" onClick={onAgents}>Configurar mi agente<Icon name="arrow" size={16}/></button></div></section>;
}
function Channels({ onAgents }: { onAgents: () => void }) {
  return <><PageHeader eyebrow="DE LA IDEA A TU CONVERSACIÓN" title="Canales" description="Artemis trabaja aquí. Tú recibes lo importante donde ya estás."/><ChannelCard provider="whatsapp" onAgents={onAgents}/><ChannelCard provider="telegram" onAgents={onAgents}/><section className="panel channel-guide"><p className="eyebrow">TRES MENSAJES PARA EMPEZAR</p><div className="chat-examples"><code>¿Qué puedes hacer?</code><code>Busca Matrix para descargar</code><code>¿Cómo van mis descargas?</code></div><p>Habla con naturalidad. El bot utiliza AGY y las habilidades que tenga asignadas, sin activar menús.</p></section></>;
}

function Settings({ preferences, onChange }: { preferences: Preferences; onChange: (value: Preferences) => void }) {
  const update = (value: Partial<Preferences>) => onChange({ ...preferences, ...value });
  return <><PageHeader eyebrow="ESTE ESPACIO ES TUYO" title="Ajustes" description="Elige cómo se ve y cómo se mueve tu central de mando."/><div className="settings-grid"><section className="panel"><span className="settings-icon"><Icon name="moon"/></span><h3>Apariencia</h3><p>De madrugada o a plena luz. Elige tu ambiente.</p><div className="preference-options"><button aria-pressed={preferences.theme === "dark"} onClick={() => update({ theme: "dark" })}><Icon name="moon"/>Tema oscuro</button><button aria-pressed={preferences.theme === "light"} onClick={() => update({ theme: "light" })}><Icon name="sun"/>Tema claro</button></div></section><section className="panel"><span className="settings-icon"><Icon name="bolt"/></span><h3>Movimiento</h3><p>Animaciones con personalidad, a tu ritmo. También respetamos las preferencias de tu dispositivo.</p><div className="preference-options"><button aria-pressed={preferences.motion === "full"} onClick={() => update({ motion: "full" })}>Animaciones completas</button><button aria-pressed={preferences.motion === "reduced"} onClick={() => update({ motion: "reduced" })}>Menos movimiento</button></div></section><section className="panel"><span className="settings-icon"><Icon name="home"/></span><h3>Densidad</h3><p>Más aire o más información en el mismo espacio.</p><div className="preference-options"><button aria-pressed={preferences.density === "comfortable"} onClick={() => update({ density: "comfortable" })}>Cómoda</button><button aria-pressed={preferences.density === "compact"} onClick={() => update({ density: "compact" })}>Compacta</button></div></section><section className="panel personal-note"><Icon name="check"/><h3>Tu panel, tus preferencias</h3><p>Estos ajustes se guardan en este navegador. Tus conexiones, mensajes y recordatorios siguen en tu servidor.</p><div className="key-hint"><kbd>Ctrl</kbd><span>+</span><kbd>K</kbd><span>para moverte por Artemis</span></div></section></div></>;
}
function CommandPalette({ close, navigate }: { close: () => void; navigate: (view: View, tool?: ToolId) => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const destinations = [...navigation.map(item => ({ ...item, view: item.id, tool: undefined as ToolId | undefined })),
    { id: "reminders", label: "Recordatorios", description: "Un mensaje y su disparador", icon: "clock" as IconName, view: "Tools" as View, tool: "reminders" as ToolId },
    { id: "notifications", label: "Notificaciones", description: "Envía un aviso directamente", icon: "bell" as IconName, view: "Tools" as View, tool: "notifications" as ToolId },
    { id: "webhooks", label: "Webhooks", description: "Eventos de tus aplicaciones", icon: "webhook" as IconName, view: "Tools" as View, tool: "webhooks" as ToolId }];
  const fold = (value: string) => value.toLocaleLowerCase("es").normalize("NFD").replace(/\p{Diacritic}/gu, "");
  const search = fold(query.trim());
  const score = (label: string) => fold(label) === search ? 0 : fold(label).startsWith(search) ? 1 : fold(label).includes(search) ? 2 : 3;
  const results = destinations.filter(item => fold(`${item.label} ${item.description}`).includes(search)).sort((a, b) => score(a.label) - score(b.label));
  useEffect(() => { if (dialog.current?.showModal) dialog.current.showModal(); else dialog.current?.setAttribute("open", ""); input.current?.focus(); }, []);
  const open = (item: typeof results[number]) => { navigate(item.view, item.tool); close(); };
  return <dialog ref={dialog} className="command-palette" aria-label="Buscar en Artemis" onCancel={event => { event.preventDefault(); close(); }} onClick={event => { if (event.target === dialog.current) close(); }}><div className="command-search"><Icon name="search"/><input ref={input} aria-label="Buscar sección o herramienta" placeholder="¿A dónde vamos?" value={query} onChange={event => setQuery(event.target.value)} onKeyDown={event => { if (event.key === "Enter" && results[0]) open(results[0]); }}/><button aria-label="Cerrar búsqueda" onClick={close}><kbd>Esc</kbd></button></div><p className="command-caption">ENCUENTRA TUS HERRAMIENTAS</p><div className="command-results">{results.map(item => <button key={item.id} onClick={() => open(item)}><span><Icon name={item.icon}/></span><div><strong>{item.label}</strong><small>{item.description}</small></div><Icon name="arrow" size={16}/></button>)}{!results.length && <p>No encontré esa sección. Prueba con otro nombre.</p>}</div></dialog>;
}
function SignIn({ onAuthenticated }: { onAuthenticated: () => void }) {
  const [token, setToken] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true); setError("");
    try { const response = await fetch("/api/v1/channels/whatsapp", { headers: { Authorization: `Bearer ${token.trim()}` } }); if (!response.ok) throw new Error("auth"); sessionStorage.setItem("artemis_admin_token", token.trim()); onAuthenticated(); }
    catch { setError("No se pudo iniciar sesión. Comprueba tu clave y la conexión."); }
    finally { setBusy(false); }
  };
  return <main className="sign-in"><div className="login-glow"/><section className="panel"><div className="login-brand"><img src="/artemis-logo.png?v=2" alt=""/><span>ARTEMIS</span></div><p className="eyebrow">TUS HERRAMIENTAS, EN UN SOLO LUGAR</p><h1>Bienvenido<br/>a tu panel.</h1><p>Introduce tu clave de acceso para entrar al panel.</p><form onSubmit={event => { event.preventDefault(); void submit(); }}><label>Clave de acceso<input aria-label="Clave de acceso" type="password" required value={token} autoComplete="current-password" onChange={event => setToken(event.target.value)}/></label><button className="primary" disabled={busy || !token.trim()} type="submit">{busy ? "Entrando…" : "Entrar a Artemis"}<Icon name="arrow" size={18}/></button></form>{error && <p role="alert">{error}</p>}</section></main>;
}
export function App() {
  const [route, setRoute] = useState<Route>(readRoute);
  const [preferences, setPreferences] = useState<Preferences>(readPreferences);
  const [authRequired, setAuthRequired] = useState(false);
  const [authChecked, setAuthChecked] = useState(false);
  const [authenticated, setAuthenticated] = useState(Boolean(sessionStorage.getItem("artemis_admin_token")));
  const [searchOpen, setSearchOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [health, setHealth] = useState<"checking" | "online" | "offline">("checking");
  useEffect(() => { void fetch("/api/v1/auth/status").then(async response => { if (response.ok) setAuthRequired((await response.json()).authentication_required); }).catch(() => undefined).finally(() => setAuthChecked(true)); }, []);
  useEffect(() => { let active = true; const check = async () => { try { const response = await fetch("/api/v1/health"); if (active) setHealth(response.ok ? "online" : "offline"); } catch { if (active) setHealth("offline"); } }; void check(); const timer = window.setInterval(() => { void check(); }, 20000); return () => { active = false; window.clearInterval(timer); }; }, []);
  useEffect(() => { document.documentElement.dataset.theme = preferences.theme; document.documentElement.dataset.motion = preferences.motion; document.documentElement.dataset.density = preferences.density; localStorage.setItem("artemis_preferences", JSON.stringify({ ...preferences, themeRevision: 2 })); }, [preferences]);
  useEffect(() => { const handler = (event: KeyboardEvent) => { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") { event.preventDefault(); setSearchOpen(value => !value); } if (event.key === "Escape") setSearchOpen(false); }; window.addEventListener("keydown", handler); return () => window.removeEventListener("keydown", handler); }, []);
  useEffect(() => { const handler = () => setRoute(readRoute()); window.addEventListener("hashchange", handler); return () => window.removeEventListener("hashchange", handler); }, []);
  const navigate = (view: View, tool?: ToolId) => { setRoute({ view, tool }); const path = navigation.find(item => item.id === view)!.path; window.history.replaceState(null, "", `#/${path}${view === "Tools" && tool ? `/${tool}` : ""}`); setSearchOpen(false); };
  if (!authChecked) return <main className="boot-screen"><img src="/artemis-logo.png?v=2" alt="Artemis"/><p>Conectando tus herramientas…</p></main>;
  if (authRequired && !authenticated) return <SignIn onAuthenticated={() => setAuthenticated(true)}/>;
  const selected = navigation.find(item => item.id === route.view)!;
  const pages: Record<View, ReactNode> = {
    Overview: <Overview navigate={navigate}/>, Agents: <Agents apiFetch={apiFetch}/>, Skills: <Skills apiFetch={apiFetch}/>,
    Tools: <Tools apiFetch={apiFetch} activeTool={route.tool ?? "notifications"} onSelectTool={tool => navigate("Tools", tool)}/>,
    Brain: <Brain/>,
    Channels: <Channels onAgents={() => navigate("Agents")}/>, Settings: <Settings preferences={preferences} onChange={setPreferences}/>,
  };
  return <main className={`app-shell ${collapsed ? "sidebar-collapsed" : ""}`}><a href="#contenido" className="skip-link" onClick={event => { event.preventDefault(); document.getElementById("contenido")?.focus(); }}>Ir al contenido</a><aside className="sidebar"><button className="brand" onClick={() => navigate("Overview")} aria-label="Artemis, ir al inicio"><img src="/artemis-logo.png?v=2" alt=""/><span>ARTEMIS<small>TU CENTRAL DE MANDO</small></span><span className="brand-spark">✦</span></button><div className="workspace-chip"><span className="workspace-avatar">A</span><div><strong>Mi espacio</strong><small>Espacio personal</small></div><Icon name="check" size={15}/></div><span className="nav-caption">EXPLORAR</span><nav aria-label="Navegación principal">{navigation.map((item, index) => <button key={item.id} onClick={() => navigate(item.id)} className={route.view === item.id ? "active" : ""} aria-current={route.view === item.id ? "page" : undefined} aria-label={item.label} title={collapsed ? item.label : undefined}><Icon name={item.icon}/><span>{item.label}</span><small>0{index + 1}</small>{route.view === item.id && <i className="nav-beam"/>}</button>)}</nav><div className="sidebar-note"><span>✦</span><p>Tus herramientas.<br/><strong>En un solo lugar.</strong></p><div className="signal-line"/></div><div className="sidebar-footer"><span className={`connection-dot ${health}`}/><div><strong>{health === "online" ? "Servidor conectado" : health === "offline" ? "Servidor sin respuesta" : "Comprobando servidor"}</strong><small>Tu servidor, tus reglas.</small></div></div></aside><section className="app-main"><div className="topbar"><div className="topbar-breadcrumb"><button aria-label={collapsed ? "Expandir menú" : "Contraer menú"} className="icon-button collapse-button" onClick={() => setCollapsed(value => !value)}><Icon name="menu" size={19}/></button><span>Mi espacio</span><b>/</b><strong>{selected.label}</strong></div><div className="topbar-actions"><button className="search-trigger" onClick={() => setSearchOpen(true)}><Icon name="search" size={16}/><span>Buscar algo…</span><kbd>Ctrl K</kbd></button><Clock/><button className="icon-button" aria-label={preferences.theme === "dark" ? "Activar tema claro" : "Activar tema oscuro"} onClick={() => setPreferences(value => ({ ...value, theme: value.theme === "dark" ? "light" : "dark" }))}><Icon name={preferences.theme === "dark" ? "sun" : "moon"} size={19}/></button></div></div><div className="workspace" id="contenido" tabIndex={-1}><div className="view-stage" key={route.view}>{pages[route.view]}</div><footer className="workspace-footer"><span>ARTEMIS <b>✦</b> TODO EN UN SOLO LUGAR</span><StatusTag tone={health === "online" ? "good" : "neutral"}>{health === "online" ? "Servidor en línea" : health === "offline" ? "Revisar conexión" : "Comprobando"}</StatusTag></footer></div></section>{searchOpen && <CommandPalette close={() => setSearchOpen(false)} navigate={navigate}/>}</main>;
}
const root = document.getElementById("root");
if (root) createRoot(root).render(<App/>);
