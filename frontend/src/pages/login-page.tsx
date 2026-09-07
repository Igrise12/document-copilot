import { type FormEvent, useState } from 'react'
import { Navigate } from 'react-router-dom'
import type { Session } from '@supabase/supabase-js'

import { Button } from '@/components/ui/button'
import { env } from '@/lib/env'
import { supabase } from '@/lib/supabase'

type LoginPageProps = { session: Session | null }

export function LoginPage({ session }: LoginPageProps) {
  const [isSignUp, setIsSignUp] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  if (session) return <Navigate replace to="/chat" />

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const email = String(form.get('email')).trim().toLowerCase()
    const password = String(form.get('password'))
    if (!email.endsWith(`@${env.allowedEmailDomain}`)) {
      setError(`Use your @${env.allowedEmailDomain} email address.`)
      return
    }

    setError(null)
    setIsSubmitting(true)
    const result = isSignUp
      ? await supabase.auth.signUp({ email, password, options: { emailRedirectTo: window.location.origin } })
      : await supabase.auth.signInWithPassword({ email, password })
    setIsSubmitting(false)

    if (result.error) return setError(result.error.message)
    if (isSignUp && !result.data.session) setError('Check your email to confirm your account, then sign in.')
  }

  return (
    <main className="auth-shell">
      <div className="auth-frame">
        <section className="auth-aside" aria-label="Document Copilot">
          <p className="wordmark">Driftwood Capital</p>
          <h1>Find the line. Verify the claim.</h1>
          <p>Document Copilot keeps each answer tied to the filing passage that supports it.</p>
          <div className="auth-evidence"><span>Evidence stays attached</span><strong>Filing → page → passage</strong></div>
        </section>
        <section className="auth-panel" aria-labelledby="login-title">
          <p className="auth-panel-label">Analyst access</p>
          <h2 id="login-title">{isSignUp ? 'Create your account' : 'Sign in to your workspace'}</h2>
          <p className="auth-intro">Use your Driftwood work email address.</p>
          <form className="auth-form" onSubmit={submit}>
            <label htmlFor="email">Work email</label>
            <input id="email" name="email" type="email" autoComplete="email" required />
            <label htmlFor="password">Password</label>
            <input id="password" name="password" type="password" autoComplete={isSignUp ? 'new-password' : 'current-password'} minLength={6} required />
            {error && <p className="form-error" role="alert">{error}</p>}
            <Button className="auth-submit" size="lg" disabled={isSubmitting} type="submit">
              {isSubmitting ? 'Please wait…' : isSignUp ? 'Create account' : 'Sign in'}
            </Button>
          </form>
          <button className="auth-switch" onClick={() => setIsSignUp((value) => !value)} type="button">
            {isSignUp ? 'Already have an account? Sign in' : 'Need an account? Sign up'}
          </button>
        </section>
      </div>
    </main>
  )
}
