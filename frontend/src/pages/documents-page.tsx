import { useNavigate } from 'react-router-dom'
import type { Session } from '@supabase/supabase-js'

import { Button } from '@/components/ui/button'
import { supabase } from '@/lib/supabase'

type DocumentsPageProps = { session: Session }

export function DocumentsPage({ session }: DocumentsPageProps) {
  const navigate = useNavigate()
  async function signOut() {
    await supabase.auth.signOut()
    navigate('/login', { replace: true })
  }

  return (
    <main className="workspace-shell">
      <header className="workspace-header">
        <p className="wordmark">Driftwood Capital</p>
        <Button onClick={signOut} variant="outline">Sign out</Button>
      </header>
      <section className="workspace-copy" aria-labelledby="workspace-title">
        <p>{session.user.email}</p>
        <h1 id="workspace-title">Your research workspace</h1>
        <p>Authentication is ready. The next slice adds private filing uploads and processing status.</p>
      </section>
    </main>
  )
}
