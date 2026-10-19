export const apiBase = (import.meta as any).env.VITE_API_BASE_URL || "";

export class ApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

/** Single fetch wrapper for every /api call. Empty (204) bodies resolve to undefined. */
export async function request<T>(
  path: string,
  token: string,
  options?: RequestInit,
): Promise<T> {
  const response = await fetch(apiBase + "/api" + path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: "Bearer " + token } : {}),
      ...options?.headers,
    },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail =
      typeof body.detail === "string"
        ? body.detail
        : "Request failed (" + response.status + ")";
    throw new ApiError(response.status, detail);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function createApi(token: string) {
  const send = <T>(method: string, path: string, body?: unknown) =>
    request<T>(path, token, {
      method,
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
  return {
    get: <T>(path: string) => request<T>(path, token),
    post: <T>(path: string, body?: unknown) => send<T>("POST", path, body),
    patch: <T>(path: string, body?: unknown) => send<T>("PATCH", path, body),
    del: <T>(path: string) => send<T>("DELETE", path),
  };
}

export function withProject(path: string, projectId: string | null): string {
  if (!projectId) return path;
  return path + (path.includes("?") ? "&" : "?") + "project_id=" + encodeURIComponent(projectId);
}
