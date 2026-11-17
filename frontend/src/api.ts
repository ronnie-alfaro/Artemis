export function apiFetch(path: string, init: RequestInit = {}) {
  const token = sessionStorage.getItem("artemis_admin_token");
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  return fetch(path, { ...init, headers });
}
export const dateTime = (value: string) => new Date(value).toLocaleString("es-ES", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
