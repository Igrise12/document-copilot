import { type ChangeEvent, type FormEvent, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { Session } from '@supabase/supabase-js'
import { FileText, MessageSquare, LogOut, RotateCcw, Trash2, Upload } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import { env } from '@/lib/env'
import { ApiError } from '@/lib/http'
import { supabase } from '@/lib/supabase'

type DocumentStatus = 'uploaded' | 'processing' | 'ready' | 'failed'

type DocumentSummary = {
  id: string
  original_filename: string
  source_type: string
  filing_type?: string | null
  filing_date?: string | null
  status: DocumentStatus
  failure_detail: string | null
  created_at: string
  updated_at: string
  can_manage: boolean
}

type DocumentsPageProps = { session: Session }

const dateFormatter = new Intl.DateTimeFormat(undefined, {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
})

const statusStyles: Record<DocumentStatus, string> = {
  uploaded: 'bg-amber-100 text-amber-900',
  processing: 'bg-blue-100 text-blue-900',
  ready: 'bg-emerald-100 text-emerald-900',
  failed: 'bg-red-100 text-red-900',
}

function messageFrom(error: unknown): string {
  return error instanceof ApiError ? error.message : 'Something went wrong. Please try again.'
}

export function DocumentsPage({ session }: DocumentsPageProps) {
  const navigate = useNavigate()
  const documentsRef = useRef<DocumentSummary[]>([])
  const fileInputRef = useRef<HTMLInputElement>(null)
  const uploadControllerRef = useRef<AbortController | null>(null)
  const [documents, setDocuments] = useState<DocumentSummary[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [filingType, setFilingType] = useState('')
  const [filingDate, setFilingDate] = useState('')
  const [fileError, setFileError] = useState<string | null>(null)
  const [isUploading, setIsUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [actingDocumentId, setActingDocumentId] = useState<string | null>(null)
  const [announcement, setAnnouncement] = useState('')
  const hasPendingDocuments = documents.some(({ status }) => status === 'uploaded' || status === 'processing')
  const maxUploadMegabytes = Math.round(env.maxUploadBytes / 1024 / 1024)

  function replaceDocuments(next: DocumentSummary[]) {
    documentsRef.current = next
    setDocuments(next)
  }

  async function loadDocuments(signal?: AbortSignal) {
    try {
      replaceDocuments(await api.get<DocumentSummary[]>('/documents', signal))
    } catch (loadError) {
      if (!signal?.aborted) setLoadError(messageFrom(loadError))
    } finally {
      if (!signal?.aborted) setIsLoading(false)
    }
  }

  useEffect(() => {
    const controller = new AbortController()
    // oxlint-disable-next-line react/set-state-in-effect -- the route loads external data on mount
    void loadDocuments(controller.signal)
    return () => controller.abort()
  }, [])

  useEffect(() => {
    if (!hasPendingDocuments) return

    let timer = 0
    let controller: AbortController | null = null
    async function poll() {
      controller = new AbortController()
      try {
        const next = await api.get<DocumentSummary[]>('/documents', controller.signal)
        const changed = next.some((document) =>
          documentsRef.current.some(
            (previous) => previous.id === document.id && previous.status !== document.status,
          ),
        )
        replaceDocuments(next)
        setLoadError(null)
        if (changed) setAnnouncement('Document statuses updated.')
        if (next.some(({ status }) => status === 'uploaded' || status === 'processing')) {
          timer = window.setTimeout(poll, 2_000)
        }
      } catch (pollError) {
        if (!controller.signal.aborted) {
          setLoadError(messageFrom(pollError))
          timer = window.setTimeout(poll, 2_000)
        }
      }
    }

    timer = window.setTimeout(poll, 2_000)
    return () => {
      window.clearTimeout(timer)
      controller?.abort()
    }
  }, [hasPendingDocuments])

  useEffect(() => () => uploadControllerRef.current?.abort(), [])

  function chooseFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null
    setSelectedFile(file)
    setFileError(null)
    setUploadError(null)
    if (!file) return
    if (file.type !== 'application/pdf' && !file.name.toLowerCase().endsWith('.pdf')) {
      setFileError('Choose a PDF file.')
    } else if (file.size > env.maxUploadBytes) {
      setFileError(`Choose a PDF no larger than ${maxUploadMegabytes} MiB.`)
    }
  }

  async function submitUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!selectedFile || fileError) return

    const controller = new AbortController()
    uploadControllerRef.current = controller
    setUploadError(null)
    setIsUploading(true)
    setUploadProgress(0)
    try {
      const document = await api.upload<DocumentSummary>(
        '/documents',
        selectedFile,
        setUploadProgress,
        controller.signal,
        { filing_type: filingType, filing_date: filingDate },
      )
      replaceDocuments([document, ...documentsRef.current.filter(({ id }) => id !== document.id)])
      setSelectedFile(null)
      setFilingType('')
      setFilingDate('')
      if (fileInputRef.current) fileInputRef.current.value = ''
      setAnnouncement(`${document.original_filename} uploaded and queued for processing.`)
    } catch (caughtError) {
      if (!controller.signal.aborted) setUploadError(messageFrom(caughtError))
    } finally {
      if (!controller.signal.aborted) setIsUploading(false)
      uploadControllerRef.current = null
    }
  }

  async function retryDocument(document: DocumentSummary) {
    setActingDocumentId(document.id)
    setActionError(null)
    try {
      const next = await api.post<DocumentSummary>(`/documents/${document.id}/retry`)
      replaceDocuments(documentsRef.current.map((item) => (item.id === next.id ? next : item)))
      setAnnouncement(`${document.original_filename} queued for another attempt.`)
    } catch (retryError) {
      setActionError(messageFrom(retryError))
    } finally {
      setActingDocumentId(null)
    }
  }

  async function deleteDocument(document: DocumentSummary) {
    if (!window.confirm(`Delete “${document.original_filename}”? This cannot be undone.`)) return

    setActingDocumentId(document.id)
    setActionError(null)
    try {
      await api.delete(`/documents/${document.id}`)
      replaceDocuments(documentsRef.current.filter(({ id }) => id !== document.id))
      setAnnouncement(`${document.original_filename} deleted.`)
    } catch (deleteError) {
      setActionError(messageFrom(deleteError))
    } finally {
      setActingDocumentId(null)
    }
  }

  async function signOut() {
    await supabase.auth.signOut()
    navigate('/login', { replace: true })
  }

  return (
    <main className="mx-auto min-h-screen w-full max-w-6xl px-5 pb-16 sm:px-8">
      <header className="flex min-h-20 items-center justify-between border-b border-border">
        <p className="m-0 text-xs font-semibold uppercase tracking-[0.08em] text-primary">Driftwood Capital</p>
        <div className="flex items-center gap-3">
          <span className="hidden text-sm text-muted-foreground sm:inline">{session.user.email}</span>
          <Button onClick={() => navigate('/chat')} variant="outline"><MessageSquare />Ask questions</Button>
          <Button onClick={signOut} variant="outline"><LogOut />Sign out</Button>
        </div>
      </header>

      <section className="mt-14 max-w-3xl" aria-labelledby="documents-title">
        <h1 id="documents-title">Documents</h1>
        <p className="mt-4 max-w-2xl text-base leading-7 text-muted-foreground">
          The shared research corpus is ready for chat. Upload a PDF only when you need to add a filing.
        </p>
      </section>

      <form className="mt-10 rounded-xl bg-card p-5 shadow-[0_14px_38px_rgb(26_33_53_/_0.09)] sm:p-7" onSubmit={submitUpload}>
        <div className="flex flex-col gap-5 md:flex-row md:items-end md:justify-between">
          <div className="min-w-0 flex-1">
            <label className="block text-sm font-semibold" htmlFor="filing">Upload a filing <span className="font-normal text-muted-foreground">optional</span></label>
            <p className="mt-1 text-sm leading-6 text-muted-foreground" id="filing-guidance">PDF only · Maximum {maxUploadMegabytes} MiB</p>
            <input
              ref={fileInputRef}
              className="mt-4 block w-full max-w-xl rounded-lg border border-input bg-background px-3 py-2 text-sm file:mr-4 file:rounded-md file:border-0 file:bg-muted file:px-3 file:py-1.5 file:font-medium file:text-foreground hover:file:bg-border focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50"
              id="filing"
              type="file"
              accept=".pdf,application/pdf"
              aria-describedby={`filing-guidance${fileError ? ' filing-error' : ''}${uploadError ? ' upload-error' : ''}`}
              disabled={isUploading}
              onChange={chooseFile}
            />
          </div>
          <div className="grid gap-3 sm:grid-cols-2 md:w-[19rem]">
            <label className="text-sm font-semibold" htmlFor="filing-type">Filing type <span className="font-normal text-muted-foreground">optional</span>
              <input className="mt-1.5 w-full rounded-lg border border-input bg-background px-3 py-2 text-sm" disabled={isUploading} id="filing-type" onChange={(event) => setFilingType(event.target.value)} placeholder="10-K" value={filingType} />
            </label>
            <label className="text-sm font-semibold" htmlFor="filing-date">Filing date <span className="font-normal text-muted-foreground">optional</span>
              <input className="mt-1.5 w-full rounded-lg border border-input bg-background px-3 py-2 text-sm" disabled={isUploading} id="filing-date" onChange={(event) => setFilingDate(event.target.value)} type="date" value={filingDate} />
            </label>
          </div>
          <Button className="h-10 px-4 md:self-end" disabled={!selectedFile || Boolean(fileError) || isUploading} type="submit">
            <Upload />{isUploading ? 'Uploading…' : 'Upload PDF'}
          </Button>
        </div>
        {fileError && <p className="mt-3 text-sm text-destructive" id="filing-error" role="alert">{fileError}</p>}
        {uploadError && <p className="mt-3 text-sm text-destructive" id="upload-error" role="alert">{uploadError}</p>}
        {isUploading && (
          <div className="mt-5">
            <div className="mb-2 flex justify-between text-sm"><span>Uploading {selectedFile?.name}</span><span className="tabular-nums">{uploadProgress}%</span></div>
            <progress className="h-2 w-full overflow-hidden rounded-full accent-[var(--primary)]" max="100" value={uploadProgress} aria-label={`Upload progress: ${uploadProgress}%`} />
          </div>
        )}
      </form>

      <section className="mt-14" aria-labelledby="your-documents-title">
        <div className="flex items-end justify-between gap-4">
          <div>
            <h2 className="text-2xl font-semibold tracking-[-0.025em]" id="your-documents-title">Research corpus</h2>
            <p className="mt-2 text-sm text-muted-foreground">Ready filings are available to every Driftwood analyst.</p>
          </div>
          {!isLoading && loadError && <Button onClick={() => { setLoadError(null); void loadDocuments() }} variant="outline">Try again</Button>}
        </div>

        {loadError && <p className="mt-5 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-900" role="alert">{loadError}</p>}
        {actionError && <p className="mt-5 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-900" role="alert">{actionError}</p>}
        {isLoading ? (
          <p className="mt-8 text-sm text-muted-foreground">Loading the research corpus…</p>
        ) : documents.length === 0 ? (
          <div className="mt-8 border-y border-border py-12 text-center">
            <FileText className="mx-auto size-7 text-muted-foreground" aria-hidden="true" />
            <p className="mt-4 font-medium">No ready filings yet</p>
            <p className="mt-2 text-sm text-muted-foreground">The corpus is still being prepared. You can optionally upload a PDF.</p>
          </div>
        ) : (
          <ul className="mt-8 divide-y divide-border border-y border-border" aria-label="Research corpus documents">
            {documents.map((document) => {
              const isActing = actingDocumentId === document.id
              return (
                <li className="grid gap-4 py-5 md:grid-cols-[minmax(0,1fr)_auto_auto] md:items-center" key={document.id}>
                  <div className="min-w-0">
                    <div className="flex min-w-0 items-center gap-3">
                      <FileText className="size-5 shrink-0 text-primary" aria-hidden="true" />
                      <p className="truncate font-medium" title={document.original_filename}>{document.original_filename}</p>
                    </div>
                    <div className="mt-2 flex flex-wrap items-center gap-2 pl-8 text-sm text-muted-foreground">
                      <span className={`rounded-full px-2.5 py-1 text-xs font-semibold capitalize ${statusStyles[document.status]}`}>{document.status}</span>
                      <span>Uploaded {dateFormatter.format(new Date(document.created_at))}</span>
                      {document.filing_type && <span>{document.filing_type}</span>}
                      {document.filing_date && <span>{dateFormatter.format(new Date(document.filing_date))}</span>}
                    </div>
                    {document.status === 'failed' && document.failure_detail && (
                      <p className="mt-3 pl-8 text-sm text-red-800">{document.failure_detail}</p>
                    )}
                  </div>
                  {(document.status === 'uploaded' || document.status === 'processing') && (
                    <span className="text-sm text-muted-foreground" aria-label={`${document.original_filename} is ${document.status}`}>
                      {document.status === 'uploaded' ? 'Waiting to start' : 'Extracting text…'}
                    </span>
                  )}
                  <div className="flex items-center gap-2 md:justify-end">
                    {document.can_manage && document.status === 'failed' && (
                      <Button disabled={actingDocumentId !== null} onClick={() => void retryDocument(document)} variant="outline">
                        <RotateCcw />{isActing ? 'Retrying…' : 'Retry'}
                      </Button>
                    )}
                    {document.can_manage && <Button disabled={actingDocumentId !== null} onClick={() => void deleteDocument(document)} variant="destructive">
                      <Trash2 />{isActing ? 'Working…' : 'Delete'}
                    </Button>}
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </section>
      <p className="sr-only" aria-live="polite">{announcement}</p>
    </main>
  )
}
