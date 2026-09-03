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

export type StreamEvent = { event: string; data: unknown }

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
  fields: Record<string, string> = {},
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
    for (const [name, value] of Object.entries(fields)) if (value) body.append(name, value)
    xhr.send(body)
  })
}

export async function stream(
  path: string,
  body: unknown,
  onEvent: (event: StreamEvent) => void | Promise<void>,
  signal: AbortSignal,
): Promise<void> {
  const token = await getAccessToken()
  let response: Response
  try {
    response = await fetch(`${env.apiBaseUrl}${path}`, {
      method: 'POST',
      headers: {
        Accept: 'text/event-stream',
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(body),
      signal,
    })
  } catch {
    throw new ApiError('Unable to reach Document Copilot. Check your connection and try again.')
  }

  if (!response.ok) {
    const errorBody: unknown = await response.json().catch(() => null)
    throw new ApiError(errorMessage(errorBody), response.status)
  }
  if (!response.body) throw new ApiError('Document Copilot returned an empty answer stream.', response.status)

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    buffer += decoder.decode(value, { stream: !done })
    let separator = buffer.search(/\r?\n\r?\n/)
    while (separator >= 0) {
      const block = buffer.slice(0, separator)
      buffer = buffer.slice(separator).replace(/^\r?\n\r?\n/, '')
      const lines = block.split(/\r?\n/)
      const event = lines.find((line) => line.startsWith('event: '))?.slice(7) ?? 'message'
      const data = lines
        .filter((line) => line.startsWith('data: '))
        .map((line) => line.slice(6))
        .join('\n')
      if (data) await onEvent({ event, data: JSON.parse(data) as unknown })
      separator = buffer.search(/\r?\n\r?\n/)
    }
    if (done) return
  }
}
