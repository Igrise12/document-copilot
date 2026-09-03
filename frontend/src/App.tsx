import { useEffect, useState } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import type { Session } from '@supabase/supabase-js'

import { supabase } from '@/lib/supabase'
import { DocumentsPage } from '@/pages/documents-page'
import { ChatPage } from '@/pages/chat-page'
import { LoginPage } from '@/pages/login-page'

function App() {
  const [session, setSession] = useState<Session | null | undefined>(undefined)
  useEffect(() => {
    void supabase.auth.getSession().then(({ data }) => setSession(data.session))
    const { data: listener } = supabase.auth.onAuthStateChange((_event, nextSession) => setSession(nextSession))
    return () => listener.subscription.unsubscribe()
  }, [])

  if (session === undefined) return <main className="loading-screen">Restoring your session…</main>

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage session={session} />} />
        <Route path="/documents" element={session ? <DocumentsPage session={session} /> : <Navigate replace to="/login" />} />
        <Route path="/chat" element={session ? <ChatPage session={session} /> : <Navigate replace to="/login" />} />
        <Route path="*" element={<Navigate replace to={session ? '/chat' : '/login'} />} />
      </Routes>
    </BrowserRouter>
  )
}

export default App
