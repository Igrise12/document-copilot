import { type FormEvent, useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import type { Session } from '@supabase/supabase-js'
import { FileText, MessageSquare, Send, Square, X } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { WorkspaceShell } from '@/components/workspace-shell'
import { api } from '@/lib/api'
import { ApiError, type StreamEvent } from '@/lib/http'

type DocumentSummary = {
  id: string
  original_filename: string
  source_type: string
  filing_type?: string | null
  filing_date?: string | null
  status: 'uploaded' | 'processing' | 'ready' | 'failed'
  can_manage: boolean
}

type Thread = { id: string; title: string; created_at: string; updated_at: string }

type Citation = {
  chunk_id: string
  document_name: string
  excerpt: string
  page_numbers: number[]
  section: string | null
  filing_type: string | null
  filing_date: string | null
  source_type: string
}

type ChatMessage = {
  id: string
  role: 'user' | 'assistant'
  content: string
  created_at: string
  citations: Citation[]
  state: 'running' | 'completed' | 'failed' | 'cancelled'
  error_code: string | null
  document_ids: string[] | null
  insufficient_evidence: boolean
  retry?: { content: string; documentIds: string[] | null }
}

type Passage = {
  chunk_id: string
  document_id: string
  document_name: string
  text: string
  page_numbers: number[]
  section: string | null
  neighboring_text: string[]
  filing_type: string | null
  filing_date: string | null
  source_type: string
  original_url: string | null
}

type ChatPageProps = { session: Session }

const dateFormatter = new Intl.DateTimeFormat(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
const statusCopy = {
  persisted: 'Saving your question…',
  retrieving: 'Searching selected filings…',
  generating: 'Reviewing evidence and drafting…',
  persisting: 'Saving answer and citations…',
} as const

function messageFrom(error: unknown): string {
  return error instanceof ApiError ? error.message : 'Something went wrong. Please try again.'
}

function eventObject(event: StreamEvent): Record<string, unknown> {
  if (typeof event.data !== 'object' || event.data === null) throw new ApiError('Document Copilot returned an invalid answer event.')
  return event.data as Record<string, unknown>
}

function titleForQuestion(question: string): string {
  return question.replace(/\s+/g, ' ').trim().slice(0, 80)
}

function citationLocation(citation: Citation): string {
  const location = []
  if (citation.page_numbers.length) location.push(`p. ${citation.page_numbers.join(', ')}`)
  if (citation.section) location.push(citation.section)
  return location.join(' · ')
}

export function ChatPage({ session }: ChatPageProps) {
  const navigate = useNavigate()
  const location = useLocation()
  const [searchParams] = useSearchParams()
  const startNewChat = useRef(location.state?.newChat === true)
  const requestedThreadId = useRef(searchParams.get('thread'))
  const streamController = useRef<AbortController | null>(null)
  const sending = useRef(false)
  const passageDialog = useRef<HTMLDialogElement>(null)
  const questionInput = useRef<HTMLTextAreaElement>(null)
  const [documents, setDocuments] = useState<DocumentSummary[]>([])
  const [threads, setThreads] = useState<Thread[]>([])
  const [threadId, setThreadId] = useState<string | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [question, setQuestion] = useState('')
  const [scope, setScope] = useState<'all' | 'selected'>('all')
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<string[]>([])
  const [status, setStatus] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isStreaming, setIsStreaming] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [passage, setPassage] = useState<Passage | null>(null)
  const [passageError, setPassageError] = useState<string | null>(null)
  const [passageChunkId, setPassageChunkId] = useState<string | null>(null)
  const readyDocuments = documents.filter((document) => document.status === 'ready')

  async function loadMessages(id: string, signal?: AbortSignal) {
    try {
      setMessages(await api.get<ChatMessage[]>(`/threads/${id}/messages`, signal))
      setLoadError(null)
    } catch (error) {
      if (!signal?.aborted) setLoadError(messageFrom(error))
    }
  }

  async function selectThread(id: string, signal?: AbortSignal) {
    if (isStreaming) return
    setThreadId(id)
    setStatus(null)
    await loadMessages(id, signal)
  }

  useEffect(() => {
    const controller = new AbortController()
    async function loadWorkspace() {
      try {
        const [nextDocuments, nextThreads] = await Promise.all([
          api.get<DocumentSummary[]>('/documents', controller.signal),
          api.get<Thread[]>('/threads', controller.signal),
        ])
        setDocuments(nextDocuments)
        setThreads(nextThreads)
        const initialThread = startNewChat.current ? undefined : nextThreads.find((thread) => thread.id === requestedThreadId.current) ?? nextThreads[0]
        if (initialThread) {
          setThreadId(initialThread.id)
          setMessages(await api.get<ChatMessage[]>(`/threads/${initialThread.id}/messages`, controller.signal))
        }
      } catch (error) {
        if (!controller.signal.aborted) setLoadError(messageFrom(error))
      } finally {
        if (!controller.signal.aborted) setIsLoading(false)
      }
    }
    void loadWorkspace()
    return () => controller.abort()
  }, [])

  useEffect(() => () => streamController.current?.abort(), [])

  useEffect(() => {
    const dialog = passageDialog.current
    if (!dialog || !passageChunkId) return
    dialog.showModal()
  }, [passageChunkId])

  function resetChat() {
    if (isStreaming) return
    setThreadId(null)
    setMessages([])
    setQuestion('')
    setStatus(null)
    setLoadError(null)
    questionInput.current?.focus()
  }

  function toggleDocument(documentId: string) {
    setSelectedDocumentIds((ids) => ids.includes(documentId) ? ids.filter((id) => id !== documentId) : [...ids, documentId])
  }

  function replaceMessage(id: string, update: (message: ChatMessage) => ChatMessage) {
    setMessages((current) => current.map((message) => message.id === id ? update(message) : message))
  }

  async function sendQuestion(content?: string, documentIds = scope === 'all' ? null : selectedDocumentIds) {
    const fromInput = content === undefined
    const cleaned = (content ?? question).trim()
    if (!cleaned || sending.current || !readyDocuments.length || documentIds?.length === 0) return
    sending.current = true

    if (fromInput) setQuestion('')
    setIsStreaming(true)
    setLoadError(null)
    let targetThreadId = threadId
    try {
      if (!targetThreadId) {
        const thread = await api.post<Thread>('/threads', { title: titleForQuestion(cleaned) })
        targetThreadId = thread.id
        setThreadId(thread.id)
        setThreads((current) => [thread, ...current])
      }
    } catch (error) {
      if (fromInput) setQuestion(cleaned)
      setIsStreaming(false)
      sending.current = false
      setLoadError(messageFrom(error))
      return
    }

    const now = new Date().toISOString()
    const attemptId = `pending-${crypto.randomUUID()}`
    const assistantId = `${attemptId}-assistant`
    setMessages((current) => [
      ...current,
      {
        id: attemptId,
        role: 'user',
        content: cleaned,
        created_at: now,
        citations: [],
        state: 'running',
        error_code: null,
        document_ids: documentIds,
        insufficient_evidence: false,
      },
      {
        id: assistantId,
        role: 'assistant',
        content: '',
        created_at: now,
        citations: [],
        state: 'running',
        error_code: null,
        document_ids: null,
        insufficient_evidence: false,
        retry: { content: cleaned, documentIds },
      },
    ])
    const controller = new AbortController()
    streamController.current = controller
    let completed = false
    let terminalError = false

    try {
      await api.stream(
        `/threads/${targetThreadId}/messages/stream`,
        { content: cleaned, document_ids: documentIds },
        async (event) => {
          const data = eventObject(event)
          if (event.event === 'status' && typeof data.phase === 'string' && data.phase in statusCopy) {
            setStatus(statusCopy[data.phase as keyof typeof statusCopy])
          }
          const text = data.text
          if (event.event === 'answer' && typeof text === 'string') {
            replaceMessage(assistantId, (message) => ({ ...message, content: text }))
          }
          if (event.event === 'citations' && Array.isArray(data.citations)) {
            replaceMessage(assistantId, (message) => ({ ...message, citations: data.citations as Citation[] }))
          }
          const errorMessage = data.message
          if (event.event === 'error' && typeof errorMessage === 'string') {
            terminalError = true
            replaceMessage(assistantId, (message) => ({
              ...message,
              state: 'failed',
              error_code: typeof data.code === 'string' ? data.code : 'generation_failed',
              content: errorMessage,
            }))
          }
          if (event.event === 'complete') {
            completed = true
            replaceMessage(assistantId, (message) => ({
              ...message,
              state: 'completed',
              insufficient_evidence: data.insufficient_evidence === true,
            }))
          }
        },
        controller.signal,
      )
      if (!completed && !terminalError) throw new ApiError('The answer stream ended before completion. Please retry.')
      await loadMessages(targetThreadId)
    } catch (error) {
      if (controller.signal.aborted) {
        replaceMessage(assistantId, (message) => ({ ...message, state: 'cancelled', content: 'Answer generation stopped.' }))
      } else {
        const apiError = error instanceof ApiError ? error : new ApiError('Unable to generate an answer.')
        replaceMessage(assistantId, (message) => ({
          ...message,
          state: 'failed',
          content: apiError.isNetworkError ? 'Connection lost while waiting for an answer. Retry when you are back online.' : apiError.message,
        }))
      }
    } finally {
      if (streamController.current === controller) streamController.current = null
      setIsStreaming(false)
      sending.current = false
      setStatus(null)
    }
  }

  async function openPassage(chunkId: string) {
    setPassageChunkId(chunkId)
    setPassage(null)
    setPassageError(null)
    try {
      setPassage(await api.get<Passage>(`/passages/${chunkId}`))
    } catch (error) {
      setPassageError(messageFrom(error))
    }
  }

  function closePassage() {
    passageDialog.current?.close()
    setPassageChunkId(null)
    setPassage(null)
    setPassageError(null)
  }

  function scopeLabel(documentIds: string[] | null): string {
    if (documentIds === null) return 'All ready documents'
    if (documentIds.length === 1) return documents.find((document) => document.id === documentIds[0])?.original_filename ?? '1 selected document'
    return `${documentIds.length} selected documents`
  }

  function previousQuestion(index: number): ChatMessage | undefined {
    return [...messages.slice(0, index)].reverse().find((message) => message.role === 'user')
  }

  const canSend = Boolean(question.trim()) && !isStreaming && readyDocuments.length > 0 && (scope === 'all' || selectedDocumentIds.length > 0)

  return (
    <WorkspaceShell activeThreadId={threadId} onNewQuestion={resetChat} onSelectThread={(id) => void selectThread(id)} session={session} threads={threads}>
      <section className="chat-page" aria-labelledby="conversation-title">
          <div className="flex flex-wrap items-end justify-between gap-4 border-b border-border pb-5">
            <div>
              <h2 className="text-3xl" id="conversation-title">{threadId ? threads.find((thread) => thread.id === threadId)?.title ?? 'Conversation' : 'New conversation'}</h2>
              <p className="mt-2 text-sm text-muted-foreground">Evidence and source passages stay attached to every answer.</p>
            </div>
            {isStreaming && <Button onClick={() => streamController.current?.abort()} variant="outline"><Square />Stop answer</Button>}
          </div>

          {loadError && <p className="mt-5 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-900" role="alert">{loadError}</p>}
          {isLoading ? <div className="chat-loading" aria-label="Loading your research workspace"><span className="skeleton skeleton-line" /><span className="skeleton skeleton-line" /><span className="skeleton skeleton-short" /></div> : !readyDocuments.length ? (
            <div className="mt-10 border-y border-border py-12 text-center">
              <FileText className="mx-auto size-7 text-muted-foreground" />
              <p className="mt-4 font-medium">The research corpus is not ready yet</p>
              <p className="mt-2 text-sm text-muted-foreground">Try again once the corpus has finished processing, or optionally upload a PDF.</p>
              <Button className="mt-5" onClick={() => navigate('/documents')} variant="outline"><FileText />Go to documents</Button>
            </div>
          ) : (
            <>
              <div className="chat-messages" aria-live="polite">
                {messages.length === 0 ? (
                  <div className="chat-empty">
                    <MessageSquare className="size-7 text-primary" />
                    <p className="mt-4 font-medium">Start with a question about the research corpus</p>
                    <p className="mt-2 max-w-xl text-sm leading-6 text-muted-foreground">Answers use only ready documents and link back to the precise supporting passage.</p>
                    <div className="starter-prompts">
                      {[
                        'How did Apple’s revenue mix change from 2021 to 2025?',
                        'Compare AWS operating margins with Amazon’s other segments.',
                        'What changed in NVIDIA’s Data Center demand drivers?',
                      ].map((prompt) => <button key={prompt} onClick={() => { setQuestion(prompt); questionInput.current?.focus() }} type="button">{prompt}</button>)}
                    </div>
                  </div>
                ) : messages.map((message, index) => {
                  const questionForAnswer = message.role === 'assistant' ? previousQuestion(index) : undefined
                  const failedQuestion = message.role === 'user' && (message.state === 'failed' || message.state === 'cancelled')
                  return (
                    <article className={message.role === 'user' ? 'chat-message-user' : 'chat-message-answer'} key={message.id}>
                      <div className="chat-message-label">
                        <span>{message.role === 'user' ? 'You' : 'Document Copilot'}</span>
                        {message.role === 'assistant' && questionForAnswer && <span className="normal-case tracking-normal">· {scopeLabel(questionForAnswer.document_ids)}</span>}
                      </div>
                      {message.role === 'assistant' && message.state === 'running' && !message.content && <p className="chat-stream-status"><span className="stream-dot" />{status ?? 'Preparing your answer…'}</p>}
                      {message.content && <p className={`mt-2 whitespace-pre-wrap text-sm leading-7 ${message.insufficient_evidence ? 'rounded-lg bg-amber-50 px-4 py-3 text-amber-950' : ''}`}>{message.content}</p>}
                      {message.insufficient_evidence && <p className="mt-2 text-xs text-muted-foreground">This is a grounded refusal, not a connection or server error.</p>}
                      {(message.state === 'failed' || message.state === 'cancelled') && (
                        <div className="mt-3 flex flex-wrap items-center gap-3 text-sm">
                          <span className="text-destructive">{message.state === 'cancelled' ? 'Answer stopped.' : message.error_code === 'generation_timeout' ? 'The answer timed out. Please retry.' : message.error_code === 'grounding_failed' ? 'The answer could not be verified against the evidence.' : 'The answer could not be generated. Please retry.'}</span>
                          {message.retry && <Button onClick={() => void sendQuestion(message.retry?.content, message.retry?.documentIds)} size="sm" variant="outline">Retry</Button>}
                          {failedQuestion && <Button onClick={() => void sendQuestion(message.content, message.document_ids)} size="sm" variant="outline">Retry</Button>}
                        </div>
                      )}
                      {message.role === 'assistant' && message.citations.length > 0 && (
                        <div className="citation-list">
                          {message.citations.map((citation) => (
                            <button className="citation-control" key={`${citation.chunk_id}-${citation.excerpt}`} onClick={() => void openPassage(citation.chunk_id)}>
                              {citation.document_name} · {citation.filing_type ?? citation.source_type.toUpperCase()}{citation.filing_date ? ` · ${dateFormatter.format(new Date(`${citation.filing_date}T00:00:00`))}` : ''}{citationLocation(citation) ? ` · ${citationLocation(citation)}` : ''}
                            </button>
                          ))}
                        </div>
                      )}
                    </article>
                  )
                })}
              </div>

              <form className="question-composer" onSubmit={(event: FormEvent<HTMLFormElement>) => { event.preventDefault(); void sendQuestion() }}>
                <div className="flex flex-wrap items-center gap-3">
                  <label className="text-sm font-semibold" htmlFor="scope">Search scope</label>
                  <select className="rounded-lg border border-input bg-background px-3 py-2 text-sm" id="scope" onChange={(event) => setScope(event.target.value as 'all' | 'selected')} value={scope}>
                    <option value="all">All ready documents</option>
                    <option value="selected">Selected documents</option>
                  </select>
                  {scope === 'selected' && <span className="text-sm text-muted-foreground">{selectedDocumentIds.length} selected</span>}
                </div>
                {scope === 'selected' && (
                  <fieldset className="mt-4 grid gap-2 border-l border-border pl-4">
                    <legend className="sr-only">Documents to search</legend>
                    {readyDocuments.map((document) => (
                      <label className="flex items-center gap-2 text-sm" key={document.id}>
                        <input checked={selectedDocumentIds.includes(document.id)} onChange={() => toggleDocument(document.id)} type="checkbox" />
                        <span>{document.original_filename}</span>
                      </label>
                    ))}
                  </fieldset>
                )}
                <label className="sr-only" htmlFor="question">Your question</label>
                <textarea className="mt-5 min-h-28 w-full resize-y rounded-xl border border-input bg-background px-4 py-3 text-sm leading-6" disabled={isStreaming} id="question" maxLength={12000} onChange={(event) => setQuestion(event.target.value)} placeholder="Ask a question grounded in the research corpus…" ref={questionInput} value={question} />
                {scope === 'selected' && selectedDocumentIds.length === 0 && <p className="mt-2 text-sm text-destructive">Select at least one ready document.</p>}
                <div className="mt-3 flex justify-end"><Button disabled={!canSend} type="submit"><Send />Ask question</Button></div>
              </form>
            </>
          )}
        </section>

      <dialog className="m-0 ml-auto h-dvh w-full max-w-xl border-0 bg-card p-0 text-foreground shadow-[-12px_0_40px_rgb(26_33_53_/_0.18)] backdrop:bg-foreground/25" onClose={closePassage} ref={passageDialog}>
        <section className="flex h-full flex-col" aria-labelledby="passage-title">
          <header className="flex items-start justify-between gap-4 border-b border-border px-6 py-5">
            <div><h2 className="text-xl" id="passage-title">Source passage</h2><p className="mt-1 text-sm text-muted-foreground">{passage?.document_name ?? 'Loading source…'}</p></div>
            <Button aria-label="Close source passage" onClick={closePassage} size="icon" variant="outline"><X /></Button>
          </header>
          <div className="min-h-0 flex-1 overflow-y-auto px-6 py-6">
            {passageError && <p className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-900" role="alert">{passageError}</p>}
            {!passage && !passageError && <div className="passage-loading" aria-label="Loading cited evidence"><span className="skeleton skeleton-line" /><span className="skeleton skeleton-line" /><span className="skeleton skeleton-short" /></div>}
            {passage && <>
              <p className="text-sm text-muted-foreground">{passage.filing_type ?? passage.source_type.toUpperCase()}{passage.filing_date ? ` · ${dateFormatter.format(new Date(`${passage.filing_date}T00:00:00`))}` : ''}{passage.page_numbers.length ? ` · p. ${passage.page_numbers.join(', ')}` : ''}{passage.section ? ` · ${passage.section}` : ''}</p>
              <p className="mt-5 whitespace-pre-wrap text-sm leading-7">{passage.text}</p>
              {passage.neighboring_text.length > 0 && <div className="mt-8 border-t border-border pt-5"><h3 className="text-sm font-semibold">Nearby context</h3>{passage.neighboring_text.map((text, index) => <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-muted-foreground" key={`${index}-${text.slice(0, 24)}`}>{text}</p>)}</div>}
            </>}
          </div>
          {passage?.original_url && <footer className="border-t border-border px-6 py-4"><Button asChild><a href={passage.original_url} rel="noreferrer" target="_blank">Open original PDF</a></Button></footer>}
        </section>
      </dialog>
    </WorkspaceShell>
  )
}
