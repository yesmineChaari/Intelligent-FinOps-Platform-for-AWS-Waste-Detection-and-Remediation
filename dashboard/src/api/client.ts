const configuredBaseUrl =
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1"

export const API_BASE_URL = configuredBaseUrl.replace(/\/$/, "")
export const USE_MOCKS =
  (import.meta.env.VITE_USE_MOCKS ?? "true").trim().toLowerCase() !== "false"

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

// Mock mode preserves the same async contract as a request and protects
// fixtures from component mutation.
export async function resolveMockResponse<T>(payload: T): Promise<T> {
  return Promise.resolve(structuredClone(payload))
}
