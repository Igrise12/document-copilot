import { request, upload } from '@/lib/http'

export const api = {
  delete: (path: string) => request<void>(path, { method: 'DELETE' }),
  get: <T>(path: string, signal?: AbortSignal) => request<T>(path, { signal }),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: 'POST',
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
  upload: <T>(path: string, file: File, onProgress: (percent: number) => void, signal?: AbortSignal) =>
    upload<T>(path, file, onProgress, signal),
}
