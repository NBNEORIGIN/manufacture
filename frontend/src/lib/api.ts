const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://127.0.0.1:8000'

function getCsrfToken(): string {
  if (typeof document === 'undefined') return ''
  const value = `; ${document.cookie}`
  const parts = value.split('; csrftoken=')
  if (parts.length === 2) return parts.pop()!.split(';').shift() || ''
  return ''
}

export function api(path: string, init?: RequestInit) {
  const method = ((init?.method) || 'GET').toUpperCase()
  const mutating = ['POST', 'PATCH', 'PUT', 'DELETE'].includes(method)

  const headers: Record<string, string> = {
    ...(init?.headers as Record<string, string> || {}),
  }
  if (mutating) {
    const token = getCsrfToken()
    if (token) headers['X-CSRFToken'] = token
  }

  const opts: RequestInit = {
    ...init,
    credentials: 'include' as RequestCredentials,
    headers,
  }
  return fetch(`${API_BASE}${path}`, opts)
}
