const BACKEND_BASE_URL =
  process.env.BACKEND_BASE_URL ?? "http://localhost:8000";

export async function backendFetch(path, init = {}) {
  const url = new URL(path, BACKEND_BASE_URL);
  const response = await fetch(url, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...init.headers,
    },
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`Backend request failed: ${response.status} ${body}`);
  }

  return response;
}

export async function backendJson(path, init = {}) {
  const response = await backendFetch(path, init);
  return response.json();
}
