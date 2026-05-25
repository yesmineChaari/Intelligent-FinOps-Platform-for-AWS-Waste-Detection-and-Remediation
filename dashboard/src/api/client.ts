export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api"

export async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      Accept: "application/json",
    },
  })

  if (!response.ok) {
    throw new Error(`API request failed: ${response.status} ${response.statusText}`)
  }

  return response.json() as Promise<T>
}

// Services use this until FastAPI endpoints exist. It preserves the same async
// contract as a network request and protects fixtures from component mutation.
export async function resolveMockResponse<T>(payload: T): Promise<T> {
  return Promise.resolve(structuredClone(payload))
}
