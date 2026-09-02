import { env } from '@/lib/env'
import { getAccessToken } from '@/lib/supabase'

export class ApiError extends Error {
  readonly isNetworkError: boolean
  readonly status: number | null

  constructor(message: string, status: number | null = null) {
    super(message)
    this.name = 'ApiError'
    this.isNetworkError = status === null
    this.status = status
  }
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = await getAccessToken()
  const headers = new Headers(init.headers)
  headers.set('Accept', 'application/json')
  if (token) headers.set('Authorization', `Bearer ${token}`)

  let response: Response
  try {
    response = await fetch(`${env.apiBaseUrl}${path}`, {
      ...init,
      headers,
      signal: init.signal ?? AbortSignal.timeout(15_000),
    })
  } catch {
    throw new ApiError('Unable to reach Document Copilot. Check your connection and try again.')
  }

  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null)
    const detail = typeof body === 'object' && body && 'detail' in body ? body.detail : null
    throw new ApiError(typeof detail === 'string' ? detail : 'Request failed. Please try again.', response.status)
  }

  return response.json() as Promise<T>
}
