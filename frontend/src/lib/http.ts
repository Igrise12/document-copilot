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

function errorMessage(body: unknown): string {
  const detail = typeof body === 'object' && body && 'detail' in body ? body.detail : null
  return typeof detail === 'string' ? detail : 'Request failed. Please try again.'
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
      signal: init.signal
        ? AbortSignal.any([init.signal, AbortSignal.timeout(15_000)])
        : AbortSignal.timeout(15_000),
    })
  } catch {
    throw new ApiError('Unable to reach Document Copilot. Check your connection and try again.')
  }

  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null)
    throw new ApiError(errorMessage(body), response.status)
  }

  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export async function upload<T>(
  path: string,
  file: File,
  onProgress: (percent: number) => void,
  signal?: AbortSignal,
): Promise<T> {
  const token = await getAccessToken()
  if (signal?.aborted) throw new ApiError('Upload cancelled.')
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    const abort = () => xhr.abort()
    const cleanup = () => signal?.removeEventListener('abort', abort)

    xhr.open('POST', `${env.apiBaseUrl}${path}`)
    xhr.timeout = 120_000
    xhr.setRequestHeader('Accept', 'application/json')
    if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`)

    xhr.upload.addEventListener('progress', (event) => {
      if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100))
    })
    xhr.addEventListener('load', () => {
      cleanup()
      let body: unknown = null
      try {
        body = xhr.responseText ? JSON.parse(xhr.responseText) : null
      } catch {
        reject(new ApiError('Document Copilot returned an invalid response.', xhr.status))
        return
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as T)
      else reject(new ApiError(errorMessage(body), xhr.status))
    })
    xhr.addEventListener('error', () => {
      cleanup()
      reject(new ApiError('Unable to reach Document Copilot. Check your connection and try again.'))
    })
    xhr.addEventListener('timeout', () => {
      cleanup()
      reject(new ApiError('The upload timed out. Check your connection and try again.'))
    })
    xhr.addEventListener('abort', () => {
      cleanup()
      reject(new ApiError('Upload cancelled.'))
    })

    signal?.addEventListener('abort', abort, { once: true })

    const body = new FormData()
    body.append('file', file)
    xhr.send(body)
  })
}
