// Central fetch wrapper: same-origin cookie auth, double-submit CSRF token,
// normalized errors and automatic redirect on expired sessions.

function getCookie(name: string): string | null {
  const match = document.cookie.match(new RegExp('(?:^|; )' + name + '=([^;]*)'))
  return match ? decodeURIComponent(match[1]) : null
}

export class ApiError extends Error {
  status: number
  details?: unknown

  constructor(status: number, message: string, details?: unknown) {
    super(message)
    this.status = status
    this.details = details
  }
}

type Method = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'

async function request<T>(method: Method, path: string, body?: unknown, query?: Record<string, string | number | boolean | undefined>): Promise<T> {
  const url = new URL(path, window.location.origin)
  if (query) {
    Object.entries(query).forEach(([k, v]) => {
      if (v !== undefined && v !== '') url.searchParams.set(k, String(v))
    })
  }

  const headers: Record<string, string> = {}
  const csrf = getCookie('bluekvm_csrf')
  if (csrf && method !== 'GET') headers['X-CSRF-Token'] = csrf
  if (body !== undefined) headers['Content-Type'] = 'application/json'

  let response: Response
  try {
    response = await fetch(url.toString(), {
      method,
      credentials: 'same-origin',
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
  } catch {
    throw new ApiError(0, 'Cannot reach the BLUEKVM API. Check that the backend is running.')
  }

  if (response.status === 401 && !path.includes('/auth/login')) {
    window.dispatchEvent(new CustomEvent('bluekvm:unauthorized'))
  }

  const contentType = response.headers.get('content-type') || ''
  const data = contentType.includes('application/json') ? await response.json().catch(() => null) : null

  if (!response.ok) {
    const detail = (data as { detail?: unknown })?.detail
    const message =
      typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? (detail as { msg?: string }[]).map((d) => d.msg).join(', ')
          : `Request failed (${response.status})`
    throw new ApiError(response.status, message, data)
  }
  return data as T
}

export const api = {
  get: <T>(path: string, query?: Record<string, string | number | boolean | undefined>) =>
    request<T>('GET', path, undefined, query),
  post: <T>(path: string, body?: unknown, query?: Record<string, string | number | boolean | undefined>) =>
    request<T>('POST', path, body, query),
  put: <T>(path: string, body?: unknown) => request<T>('PUT', path, body),
  patch: <T>(path: string, body?: unknown) => request<T>('PATCH', path, body),
  delete: <T>(path: string, query?: Record<string, string | number | boolean | undefined>) =>
    request<T>('DELETE', path, undefined, query),
}

export function wsUrl(pathWithQuery: string): string {
  const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${scheme}://${window.location.host}${pathWithQuery}`
}
