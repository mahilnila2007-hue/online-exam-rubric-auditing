/**
 * Shared HTTP API client with automatic CSRF protection and error normalization.
 */

export class ApiError extends Error {
  constructor(message, status = 500, code = "API_ERROR", details = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export function getCsrfToken() {
  const meta = document.querySelector('meta[name="csrf-token"]');
  return meta ? meta.getAttribute("content") || "" : "";
}

export async function apiRequest(url, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  const headers = {
    Accept: "application/json",
    ...(options.headers || {}),
  };

  if (method !== "GET" && method !== "HEAD") {
    headers["X-CSRF-Token"] = getCsrfToken();
  }

  let body = options.body;
  if (body !== undefined && body !== null && typeof body === "object" && !(body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(body);
  }

  const response = await fetch(url, {
    ...options,
    method,
    headers,
    body,
    credentials: "same-origin",
  });

  const contentType = response.headers.get("content-type") || "";
  const isJson = contentType.includes("application/json");
  const payload = isJson ? await response.json() : await response.text();

  if (!response.ok) {
    const errObj = payload && payload.error ? payload.error : {};
    throw new ApiError(
      errObj.message || `Request failed with status ${response.status}.`,
      response.status,
      errObj.code || "HTTP_ERROR",
      errObj.details || {}
    );
  }

  return payload;
}

export const api = {
  get: (url) => apiRequest(url, { method: "GET" }),
  post: (url, body) => apiRequest(url, { method: "POST", body }),
  put: (url, body) => apiRequest(url, { method: "PUT", body }),
  patch: (url, body) => apiRequest(url, { method: "PATCH", body }),
  delete: (url) => apiRequest(url, { method: "DELETE" }),
};

