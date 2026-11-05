import { useEffect, useState } from "react";
import { PageHeader as Header } from "./ui";
import { AntigravityConfiguration } from "./AntigravityConfiguration";
import { CodexConfiguration } from "./CodexConfiguration";
import { UsenetConfiguration } from "./UsenetConfiguration";
type Props = { apiFetch: (path: string, init?: RequestInit) => Promise<Response> };
type SkillCapability = { name: string; method: string; endpoint: string; risk: "READ" | "WRITE"; description: string; inputs: string; output: string };
type SkillDetail = { id: string; name: string; status: string; description: string; help: string; auth: string; availability: string; capabilities: SkillCapability[] };
type SkillConfiguration = { configured: boolean; base_url: string | null; credential_source: string | null; last_test: string | null };
const skills: SkillDetail[] = [
  { id: "antigravity", name: "Antigravity", status: "Asistente con escritura", description: "Busca, revisa y modifica el proyecto real con Google Antigravity.", help: "Escribe ‘utiliza antigravity’ y describe la tarea. Puede ejecutar comandos y editar archivos sin confirmación adicional. Usa ‘estado’, ‘resultado <ID>’ y ‘salir’.", auth: "Sesión local autenticada de agy", availability: "En segundo plano · escritura y ejecución de comandos", capabilities: [
    { name: "Ejecutar tarea", method: "CHAT", endpoint: "WhatsApp", risk: "WRITE", description: "Busca, revisa, ejecuta comandos y modifica archivos del proyecto real.", inputs: "petición", output: "resultado por WhatsApp" },
  ] },
  { id: "codex", name: "Codex", status: "Asistente y desarrollo", description: "Conversa con Codex y pide nuevas herramientas para Artemis desde WhatsApp.", help: "Escribe ‘utiliza codex’, haz una pregunta o pide ‘crear herramienta <descripción>’. Recibirás la respuesta cuando termine. Usa ‘estado’ y ‘resultado <ID>’ para consultar tus peticiones. Puede ejecutar comandos y modificar archivos reales sin confirmación adicional.", auth: "Sesión local de Codex", availability: "Procesamiento en segundo plano · contexto por conversación", capabilities: [
    { name: "Ejecutar tarea con Codex", method: "CHAT", endpoint: "WhatsApp", risk: "WRITE", description: "Responde preguntas en español usando el contexto reciente de la conversación.", inputs: "pregunta", output: "respuesta por WhatsApp" },
    { name: "Crear herramienta", method: "CHAT", endpoint: "WhatsApp", risk: "WRITE", description: "Implementa código y pruebas directamente en el proyecto real.", inputs: "descripción de la herramienta", output: "resultado y cambios aplicados" },
  ] },
  { id: "seerr", name: "Seerr", status: "Películas y series", description: "Encuentra películas y series y solicítalas desde tu conversación de WhatsApp.", help: "WhatsApp: activa con ‘utiliza seerr’. Escribe ‘busca <título>’ o ‘quiero pedir <título>’. Recibirás opciones; responde con su número y luego ‘confirmo’ para crear la solicitud.", auth: "Clave de API · almacenada de forma cifrada", availability: "Servicio externo · comprueba su conexión desde aquí", capabilities: [
    { name: "Buscar títulos", method: "GET", endpoint: "/api/v1/search", risk: "READ", description: "Encuentra películas y series antes de preparar una solicitud.", inputs: "búsqueda", output: "título · año · tipo · ID de TMDB" },
    { name: "Ver detalles", method: "GET", endpoint: "/api/v1/movie|tv/{tmdb_id}", risk: "READ", description: "Consulta los detalles del título antes de solicitarlo.", inputs: "tipo · ID de TMDB", output: "ficha del título" },
    { name: "Solicitar título", method: "POST", endpoint: "/api/v1/request", risk: "WRITE", description: "Solicita el título elegido después de tu confirmación en el chat.", inputs: "título · solicitante · perfil · temporadas", output: "ID de solicitud · estado" },
    { name: "Consultar solicitud", method: "GET", endpoint: "/api/v1/request/{request_id}", risk: "READ", description: "Consulta el estado de una solicitud existente.", inputs: "request_id", output: "estado de la solicitud" },
  ] },
  { id: "karakeep", name: "Karakeep", status: "Marcadores y enlaces", description: "Busca marcadores guardados en Karakeep y recupera sus enlaces por WhatsApp. Guardar enlaces requiere confirmación.", help: "WhatsApp: activa con ‘utiliza karakeep’ y di ‘busca docker’. También puedes escribir ‘busca docker en mis marcadores’ o ‘busca en karakeep recetas’ para recibir hasta 5 resultados con enlaces. Para guardar, escribe ‘guarda https://ejemplo.com’ y después ‘confirmo’.", auth: "Clave de API · almacenada de forma cifrada", availability: "Tu biblioteca personal de enlaces", capabilities: [
    { name: "Buscar marcadores", method: "GET", endpoint: "/api/v1/bookmarks/search", risk: "READ", description: "Busca marcadores existentes y devuelve títulos, enlaces y extractos por WhatsApp.", inputs: "búsqueda", output: "hasta 5 marcadores · título · URL · extracto" },
    { name: "Comprobar conexión", method: "GET", endpoint: "/api/v1/lists", risk: "READ", description: "Comprueba el acceso a tu biblioteca sin modificarla.", inputs: "ninguno", output: "resultado de conexión" },
    { name: "Guardar enlace", method: "POST", endpoint: "/api/v1/bookmarks", risk: "WRITE", description: "Guarda el enlace después de tu confirmación en el chat.", inputs: "URL · título opcional", output: "ID del marcador · URL" },
  ] },
  { id: "usenet", name: "Usenet", status: "Buscador y gestor de descargas", description: "Busca títulos con NZBPlanet y gestiona descargas con NZBGet. Las operaciones que cambian la cola requieren confirmación.", help: "Activa con ‘utiliza usenet’. Escribe ‘busca Rocky en movies’ para ver hasta 10 opciones, ‘detalles 2’ para ampliar y ‘baja el 2’ para elegir. Confirma con ‘confirmo’. Consulta ‘qué está bajando’, ‘estado de descarga’ o ‘historial de descargas’. También puedes decir ‘pausa las descargas’, ‘reanuda las descargas’ o ‘cancelar’ para rechazar una operación pendiente.", auth: "clave de API del buscador y usuario/contraseña del gestor · cifrados", availability: "Disponible para asignar después de configurar las dos conexiones", capabilities: [
    { name: "Buscar", method: "GET", endpoint: "Buscador", risk: "READ", description: "Busca hasta 10 títulos con filtro por categoría.", inputs: "título · categoría opcional", output: "opciones numeradas · tamaño · categoría" },
    { name: "Ver detalles", method: "GET", endpoint: "Buscador", risk: "READ", description: "Amplía una opción de la última búsqueda.", inputs: "número del resultado", output: "título · tamaño · categoría · fecha" },
    { name: "Bajar", method: "POST", endpoint: "Gestor de descargas", risk: "WRITE", description: "Transfiere la opción seleccionada al gestor tras confirmarla.", inputs: "resultado seleccionado", output: "ID de descarga" },
    { name: "Qué está bajando", method: "POST", endpoint: "Gestor de descargas", risk: "READ", description: "Lista la cola y el progreso de cada descarga.", inputs: "ninguno", output: "título · estado · porcentaje · pendiente" },
    { name: "Estado de descarga", method: "POST", endpoint: "Gestor de descargas", risk: "READ", description: "Consulta el estado general.", inputs: "ninguno", output: "velocidad · espacio libre · pendiente · pausa" },
    { name: "Historial", method: "POST", endpoint: "Gestor de descargas", risk: "READ", description: "Muestra las últimas 10 descargas y su resultado.", inputs: "ninguno", output: "título · ID · resultado" },
    { name: "Pausar", method: "POST", endpoint: "Gestor de descargas", risk: "WRITE", description: "Pausa todas las descargas después de confirmar.", inputs: "confirmación", output: "resultado" },
    { name: "Reanudar", method: "POST", endpoint: "Gestor de descargas", risk: "WRITE", description: "Reanuda todas las descargas después de confirmar.", inputs: "confirmación", output: "resultado" },
  ] },
];
type SkillPresentation = { name: string; description: string };
export function Skills({ apiFetch }: Props) {
  const [presentations, setPresentations] = useState<Record<string, SkillPresentation>>({});
  const [displayName, setDisplayName] = useState("");
  const [summary, setSummary] = useState("");
  const [presentationStatus, setPresentationStatus] = useState("");
  useEffect(() => { void apiFetch("/api/v1/skills/presentations").then(async response => {
    if (response.ok) setPresentations(await response.json());
  }).catch(() => setPresentationStatus("No se pudo cargar la presentación.")); }, []);
  const [selectedId, setSelectedId] = useState("seerr");
  const [configuration, setConfiguration] = useState<SkillConfiguration | null>(null);
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const selected = skills.find(skill => skill.id === selectedId) ?? skills[0];
  useEffect(() => {
    setDisplayName(presentations[selectedId]?.name ?? selected.name);
    setSummary(presentations[selectedId]?.description ?? "");
  }, [selectedId, presentations]);
  const savePresentation = async () => {
    try {
      const response = await apiFetch(`/api/v1/skills/${selectedId}/presentation`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: displayName, description: summary }),
      });
      if (!response.ok) { setPresentationStatus("No se pudo guardar. Revisa los campos y la conexión."); return; }
      const value = await response.json() as SkillPresentation;
      setPresentations(previous => ({ ...previous, [selectedId]: value }));
      setPresentationStatus("Presentación guardada.");
    } catch { setPresentationStatus("No se pudo guardar la presentación."); }
  };
  const loadConfiguration = (skillId = selectedId) => void apiFetch(`/api/v1/skills/${skillId}/configuration`).then(async response => {
    if (!response.ok) return;
    const body = await response.json() as SkillConfiguration;
    setConfiguration(body); setBaseUrl(body.base_url ?? "");
  }).catch(() => undefined);
  useEffect(() => { setConfiguration(null); setBaseUrl(""); setApiKey(""); loadConfiguration(selectedId); }, [selectedId]);
  const saveConfiguration = () => {
    if (!baseUrl.trim() || !apiKey.trim()) return;
    void apiFetch(`/api/v1/skills/${selected.id}/configuration`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ base_url: baseUrl.trim(), api_key: apiKey.trim() }) })
      .then(async response => { if (response.ok) { setConfiguration(await response.json() as SkillConfiguration); setApiKey(""); } });
  };
  const testConnection = () => void apiFetch(`/api/v1/skills/${selected.id}/configuration/test`, { method: "POST" }).then(async response => { if (response.ok) setConfiguration(await response.json() as SkillConfiguration); });
  const skillName = selected.id === "seerr" ? "Seerr" : "Karakeep";
  const urlPlaceholder = selected.id === "seerr" ? "http://seerr:5055" : "http://karakeep:3000";
  return <><Header eyebrow="TUS SERVICIOS, CONECTADOS" title="Habilidades"/><section className="skill-canvas"><div className="flowbar"><strong>Elige una habilidad</strong><span>Conexiones personales</span></div><div className="skill-nodes">{skills.map(skill => <button key={skill.id} onClick={() => setSelectedId(skill.id)} className={selected.id === skill.id ? "skill-node selected" : "skill-node"}><strong>{presentations[skill.id]?.name ?? skill.name}</strong><small>{skill.capabilities.length} operaciones · {skill.status}</small></button>)}</div><div className="skill-inspector"><label>HABILIDAD SELECCIONADA</label><div className="skill-head"><div><h3>{presentations[selected.id]?.name ?? selected.name}</h3><p>{selected.description}</p></div><em>{selected.status}</em></div><section className="skill-config"><div><strong>Presentación en la ayuda</strong><span>Nombre y descripción del listado general</span></div><label>Nombre<input aria-label="Nombre de la habilidad" maxLength={80} value={displayName} onChange={event => setDisplayName(event.target.value)} /></label><label>Descripción breve<input aria-label="Descripción breve de la habilidad" maxLength={240} value={summary} onChange={event => setSummary(event.target.value)} /></label><button className="primary" disabled={!displayName.trim() || !summary.trim()} onClick={savePresentation}>Guardar presentación</button><p role="status">{presentationStatus}</p></section>{selected.id === "antigravity" ? <AntigravityConfiguration apiFetch={apiFetch}/> : selected.id === "codex" ? <CodexConfiguration apiFetch={apiFetch}/> : selected.id === "usenet" ? <UsenetConfiguration apiFetch={apiFetch}/> : <section className="skill-config"><div><strong>Conexión al servicio</strong><span>{configuration?.configured ? `Configurado desde ${configuration.credential_source === "environment" ? "el entorno" : "este panel"}` : "Sin configurar"}</span></div><label>URL DE {skillName.toUpperCase()}<input aria-label={`URL de ${skillName}`} value={baseUrl} placeholder={urlPlaceholder} onChange={event => setBaseUrl(event.target.value)} /></label><label>CLAVE DE API<input aria-label={`${skillName} clave de API`} type="password" value={apiKey} placeholder={configuration?.configured ? "Guardada; escribe otra solo para sustituirla" : `Introduce la clave de API de ${skillName}`} onChange={event => setApiKey(event.target.value)} /></label><div className="config-actions"><button className="primary" onClick={saveConfiguration}>Guardar conexión</button><button onClick={testConnection}>Probar conexión</button></div>{configuration?.last_test && <p role="status">{configuration.last_test}</p>}</section>}<section className="skill-config"><strong>Herramientas compartidas</strong><p>Notificaciones · envío de avisos al destino configurado en Herramientas.</p></section><section className="skill-config"><div><strong>Cómo usarla</strong><span>Disponible con ayuda HABILIDAD</span></div><p>{selected.help}</p></section><div className="skill-meta"><span>ACCESO · {selected.auth}</span><span>{selected.availability}</span></div><details className="capability-contracts"><summary>Ver operaciones disponibles <span>{selected.capabilities.length}</span></summary><div className="capabilities">{selected.capabilities.map(capability => <article key={capability.name}><div className="capability-title"><strong>{capability.name}</strong><code>{capability.method} {capability.endpoint}</code><em className={capability.risk === "WRITE" ? "write" : "read"}>{capability.risk === "WRITE" ? "Modifica datos" : "Consulta"}</em></div><p>{capability.description}</p><dl><div><dt>ENTRADA</dt><dd>{capability.inputs}</dd></div><div><dt>RESULTADO</dt><dd>{capability.output}</dd></div></dl></article>)}</div></details></div></section><p className="hint">Las consultas se ejecutan directamente. Codex y Antigravity ejecutan las tareas solicitadas con permisos de escritura; las demás habilidades conservan sus confirmaciones.</p></>;
}
