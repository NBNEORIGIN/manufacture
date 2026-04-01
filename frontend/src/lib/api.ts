const API_BASE = 'http://127.0.0.1:8000'

export function api(path: string, init?: RequestInit) {
  return fetch(`${API_BASE}${path}`, init)
}
