import type { ReactNode } from "react";

export type IconName = "brain" | "home" | "agents" | "skills" | "tools" | "channels" | "settings" | "search" | "arrow" | "clock" | "bolt" | "check" | "moon" | "sun" | "close" | "menu" | "bell" | "webhook";
const paths: Record<IconName, ReactNode> = {
  brain: <><path d="M12 5c-3-5-8-1-7 3-4 1-3 7 0 8-1 5 5 7 7 3V5Zm0 0c3-5 8-1 7 3 4 1 3 7 0 8 1 5-5 7-7 3M5 8l3 2M5 16l3-2m11-6-3 2m3 6-3-2"/></>,
  home: <><rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/></>,
  agents: <><circle cx="12" cy="8" r="4"/><path d="M4 21v-2a8 8 0 0 1 16 0v2M19 4l2 2M3 4l2 2"/></>,
  skills: <><path d="m12 3 8 4.5v9L12 21l-8-4.5v-9L12 3Z M4 7.5l8 5 8-5M12 12.5V21"/></>,
  tools: <><path d="M14 6a5 5 0 0 0-6 6L3 17a3 3 0 0 0 4 4l6-6a5 5 0 0 0 6-6l-4 3-3-3 2-3Z"/></>,
  channels: <><path d="M4 5h16v12H9l-5 4V5Z M8 9h8M8 13h5"/></>,
  settings: <><path d="M3 6h18M3 12h18M3 18h18"/><circle cx="8" cy="6" r="2"/><circle cx="16" cy="12" r="2"/><circle cx="10" cy="18" r="2"/></>,
  search: <><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/></>,
  arrow: <path d="M5 12h14m-6-6 6 6-6 6"/>,
  clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
  bolt: <path d="m14 2-9 12h7l-2 8 9-12h-7l2-8Z"/>,
  check: <path d="m5 12 4 4L19 6"/>,
  moon: <path d="M20 15A9 9 0 0 1 9 4a9 9 0 1 0 11 11Z"/>,
  sun: <><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l2 2m10 10 2 2M5 19l2-2M17 7l2-2"/></>,
  close: <path d="m6 6 12 12M6 18 18 6"/>,
  menu: <path d="M4 6h16M4 12h10M4 18h16"/>,
  bell: <><path d="M5 17h14l-2-3V9a5 5 0 0 0-10 0v5l-2 3Zm5 3h4"/></>,
  webhook: <><circle cx="12" cy="5" r="3"/><circle cx="5" cy="18" r="3"/><circle cx="19" cy="18" r="3"/><path d="m10 8-4 7m8-7 4 7M8 18h8"/></>,
};
export function Icon({ name, size = 20, className = "" }: { name: IconName; size?: number; className?: string }) {
  return <svg aria-hidden="true" className={`icon ${className}`} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">{paths[name]}</svg>;
}
export function PageHeader({ eyebrow, title, description }: { eyebrow: string; title: string; description?: string }) {
  return <header className="page-heading"><p className="eyebrow"><span/>{eyebrow}</p><div className="head"><h1>{title}</h1></div>{description && <p className="page-description">{description}</p>}</header>;
}
export function List({ rows }: { rows: string[][] }) {
  return <section className="panel list">{rows.map(([title, description, status]) => <article key={title}><div className="list-mark"><Icon name="agents"/></div><div className="list-copy"><h3>{title}</h3><p>{description}</p></div><span className="status-tag">{status}</span></article>)}</section>;
}
export function StatusTag({ children, tone = "neutral" }: { children: ReactNode; tone?: "good" | "warn" | "neutral" }) {
  return <span className={`status-tag ${tone}`}><i/>{children}</span>;
}
