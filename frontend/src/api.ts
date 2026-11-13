export type User = { name: string; role: "admin" | "reviewer" | "assessor" | "viewer" };

const KEY = "pat.user";
export function getUser(): User {
  try {
    return JSON.parse(localStorage.getItem(KEY) || "") as User;
  } catch {
    return { name: "admin", role: "admin" };
  }
}
export function setUser(u: User) {
  localStorage.setItem(KEY, JSON.stringify(u));
}

export class ApiError extends Error {
  status: number;
  detail: any;
  constructor(status: number, detail: any) {
    super(typeof detail === "string" ? detail : detail?.message || JSON.stringify(detail));
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(method: string, path: string, body?: unknown, isForm = false): Promise<T> {
  const u = getUser();
  const headers: Record<string, string> = { "X-User-Name": u.name, "X-User-Role": u.role };
  if (body !== undefined && !isForm) headers["Content-Type"] = "application/json";
  const res = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : isForm ? (body as FormData) : JSON.stringify(body),
  });
  if (res.status === 204) return undefined as T;
  const ct = res.headers.get("content-type") || "";
  const data = ct.includes("json") ? await res.json() : await res.text();
  if (!res.ok) throw new ApiError(res.status, (data as any)?.detail ?? data);
  return data as T;
}

export const api = {
  get: <T = any>(p: string) => request<T>("GET", p),
  post: <T = any>(p: string, b?: unknown) => request<T>("POST", p, b ?? {}),
  put: <T = any>(p: string, b?: unknown) => request<T>("PUT", p, b ?? {}),
  patch: <T = any>(p: string, b?: unknown) => request<T>("PATCH", p, b ?? {}),
  del: <T = any>(p: string) => request<T>("DELETE", p),
  form: <T = any>(p: string, f: FormData) => request<T>("POST", p, f, true),
};

export function errorText(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.detail?.errors) return e.detail.errors.map((x: any) => `${x.location}: ${x.message}`).join("\n");
    if (Array.isArray(e.detail)) return e.detail.map((x: any) => `${(x.loc || []).join(".")}: ${x.msg}`).join("\n");
    return e.message;
  }
  return String(e);
}
