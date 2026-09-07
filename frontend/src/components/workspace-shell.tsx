import { type ReactNode, useRef } from 'react'
import { FileText, History, LogOut, Menu, MessageSquare, Plus, X } from 'lucide-react'
import { NavLink, useNavigate } from 'react-router-dom'
import type { Session } from '@supabase/supabase-js'

import { Button } from '@/components/ui/button'
import { supabase } from '@/lib/supabase'

type Thread = { id: string; title: string }
type WorkspaceShellProps = {
  children: ReactNode
  session: Session
  threads?: Thread[]
  activeThreadId?: string | null
  onNewQuestion?: () => void
  onSelectThread?: (id: string) => void
}

const navClass = ({ isActive }: { isActive: boolean }) =>
  `workspace-nav-link ${isActive ? 'workspace-nav-link-active' : ''}`

export function WorkspaceShell({ children, session, threads = [], activeThreadId, onNewQuestion, onSelectThread }: WorkspaceShellProps) {
  const navigate = useNavigate()
  const menu = useRef<HTMLDialogElement>(null)

  function closeMenu() {
    menu.current?.close()
  }

  function startQuestion() {
    closeMenu()
    if (onNewQuestion) {
      navigate('/chat')
      onNewQuestion()
      return
    }
    navigate('/chat', { state: { newChat: true } })
  }

  async function signOut() {
    await supabase.auth.signOut()
    navigate('/login', { replace: true })
  }

  const navigation = (
    <>
      <div className="workspace-brand">Driftwood Capital<span>Document Copilot</span></div>
      <Button className="workspace-new-question" onClick={startQuestion} size="lg"><Plus />New question</Button>
      <nav className="workspace-nav" aria-label="Workspace navigation">
        <NavLink className={navClass} onClick={closeMenu} to="/chat"><MessageSquare />Research chat</NavLink>
        <NavLink className={navClass} onClick={closeMenu} to="/documents"><FileText />Documents</NavLink>
        <NavLink className={navClass} onClick={closeMenu} to="/activity"><History />Your activity</NavLink>
      </nav>
      {threads.length > 0 && (
        <section className="workspace-history" aria-label="Recent conversations">
          <p>Conversations</p>
          <ul>
            {threads.map((thread) => (
              <li key={thread.id}>
                <button className={thread.id === activeThreadId ? 'workspace-thread-active' : ''} onClick={() => { closeMenu(); onSelectThread?.(thread.id) }} type="button">{thread.title}</button>
              </li>
            ))}
          </ul>
        </section>
      )}
      <div className="workspace-account">
        <span>{session.user.email}</span>
        <button onClick={() => void signOut()} type="button"><LogOut />Sign out</button>
      </div>
    </>
  )

  return (
    <main className="workspace-layout">
      <aside className="workspace-sidebar">{navigation}</aside>
      <header className="workspace-mobile-bar">
        <button aria-label="Open navigation" onClick={() => menu.current?.showModal()} type="button"><Menu /></button>
        <span>Document Copilot</span>
      </header>
      <dialog className="workspace-menu" ref={menu} onClose={closeMenu}>
        <div className="workspace-menu-content">
          <Button aria-label="Close navigation" className="workspace-menu-close" onClick={closeMenu} size="icon" variant="ghost"><X /></Button>
          {navigation}
        </div>
      </dialog>
      <div className="workspace-content">{children}</div>
    </main>
  )
}
