import { useEffect, useState } from 'react'
import { ArrowUpRight, FileText, MessageSquare } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import type { Session } from '@supabase/supabase-js'

import { Button } from '@/components/ui/button'
import { WorkspaceShell } from '@/components/workspace-shell'
import { api } from '@/lib/api'
import { ApiError } from '@/lib/http'

type ActivityEvent = {
  id: string
  event_type: string
  resource_id: string | null
  label: string
  created_at: string
}

type ActivityPageProps = { session: Session }

const formatter = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' })

function messageFrom(error: unknown): string {
  return error instanceof ApiError ? error.message : 'Unable to load your activity. Try again.'
}

function eventDetails(event: ActivityEvent) {
  if (event.event_type.startsWith('document_')) return { kind: 'Document', icon: FileText, target: '/documents' }
  return { kind: 'Research chat', icon: MessageSquare, target: event.resource_id ? `/chat?thread=${event.resource_id}` : '/chat' }
}

export function ActivityPage({ session }: ActivityPageProps) {
  const navigate = useNavigate()
  const [events, setEvents] = useState<ActivityEvent[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  async function loadActivity() {
    setIsLoading(true)
    try {
      setEvents(await api.get<ActivityEvent[]>('/activity?limit=50'))
      setError(null)
    } catch (caughtError) {
      setError(messageFrom(caughtError))
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    // oxlint-disable-next-line react/set-state-in-effect -- the route loads external data on mount
    void loadActivity()
  }, [])

  return (
    <WorkspaceShell session={session}>
      <section className="workspace-page" aria-labelledby="activity-title">
        <div className="page-heading">
          <p className="page-kicker">Private record</p>
          <h1 id="activity-title">Your activity</h1>
          <p>Recent document and research events from your workspace.</p>
        </div>
        {error && <div className="workspace-error" role="alert"><span>{error}</span><Button onClick={() => void loadActivity()} variant="outline">Try again</Button></div>}
        {isLoading ? (
          <div className="activity-list" aria-label="Loading activity">
            {[1, 2, 3, 4, 5].map((item) => <div className="activity-row" key={item}><span className="skeleton skeleton-icon" /><div><span className="skeleton skeleton-line" /><span className="skeleton skeleton-short" /></div></div>)}
          </div>
        ) : events.length === 0 ? (
          <div className="workspace-empty"><MessageSquare /><h2>No activity yet</h2><p>Your document and research events will appear here.</p><Button onClick={() => navigate('/chat')}>Ask a question</Button></div>
        ) : (
          <ol className="activity-list">
            {events.map((event) => {
              const details = eventDetails(event)
              const Icon = details.icon
              return <li className="activity-row" key={event.id}>
                <span className="activity-icon"><Icon /></span>
                <div className="activity-copy"><span>{details.kind}</span><strong>{event.label}</strong><time dateTime={event.created_at}>{formatter.format(new Date(event.created_at))}</time></div>
                <button aria-label={`Open ${details.kind.toLowerCase()}`} onClick={() => navigate(details.target)} type="button"><ArrowUpRight /></button>
              </li>
            })}
          </ol>
        )}
      </section>
    </WorkspaceShell>
  )
}
