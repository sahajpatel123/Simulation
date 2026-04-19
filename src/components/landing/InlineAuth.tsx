'use client'

import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
import { ArrowRight, Loader2, X } from 'lucide-react'
import api, { apiError } from '@/lib/api'
import { auth } from '@/lib/auth'
import { useAuthStore, type AuthUser } from '@/store/auth.store'

type Mode = 'login' | 'signup'

type TokensResponse = {
  access_token: string
  refresh_token?: string
  user?: AuthUser
}

/**
 * Full-bleed editorial sign-in / sign-up overlay rendered as a portal.
 * Slides in from the right as a single broadsheet "spread" — left page
 * is the dark masthead with a pull-quote, right page is the form.
 *
 * After a successful login or registration the user is routed to
 * `/projects` (the workspace).
 */
export default function InlineAuth({
  open,
  onClose,
  initialMode = 'login',
}: {
  open: boolean
  onClose: () => void
  initialMode?: Mode
}) {
  const [mounted, setMounted] = useState(false)
  useEffect(() => setMounted(true), [])

  const router = useRouter()
  const qc = useQueryClient()
  const setUser = useAuthStore(s => s.setUser)

  const [mode, setMode] = useState<Mode>(initialMode)
  useEffect(() => {
    if (open) setMode(initialMode)
  }, [open, initialMode])

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [name, setName] = useState('')
  const [confirm, setConfirm] = useState('')
  const [err, setErr] = useState('')

  const finish = async (tokens: TokensResponse) => {
    auth.setTokens(tokens.access_token, tokens.refresh_token)
    if (tokens.user) {
      setUser(tokens.user)
    } else {
      try {
        const { data } = await api.get<AuthUser>('/auth/me')
        setUser(data)
      } catch {
        /* non-fatal */
      }
    }
    qc.clear()
    onClose()
    router.push('/projects')
  }

  const loginM = useMutation({
    mutationFn: async () => {
      const { data } = await api.post<TokensResponse>('/auth/login', { email, password })
      return data
    },
    onSuccess: finish,
    onError: (e) => setErr(apiError(e)),
  })

  const signupM = useMutation({
    mutationFn: async () => {
      if (password !== confirm) throw new Error('Passwords do not match')
      const { data } = await api.post<TokensResponse>('/auth/register', {
        email,
        password,
        full_name: name,
      })
      return data
    },
    onSuccess: finish,
    onError: (e) => setErr(apiError(e)),
  })

  const submitting = loginM.isPending || signupM.isPending

  // ESC + lock body scroll
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = ''
    }
  }, [open, onClose])

  // reset error/fields when toggling mode
  useEffect(() => {
    setErr('')
  }, [mode, open])

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    setErr('')
    if (mode === 'login') loginM.mutate()
    else signupM.mutate()
  }

  if (!mounted) return null

  return createPortal(
    <AnimatePresence>
      {open && (
        <>
          {/* Overlay */}
          <motion.div
            key="auth-overlay"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.25 }}
            onClick={onClose}
            style={{
              position: 'fixed',
              inset: 0,
              background: 'rgba(26,23,20,0.55)',
              zIndex: 1000,
              backdropFilter: 'blur(3px)',
            }}
          />

          {/* Spread */}
          <motion.div
            key="auth-spread"
            initial={{ x: '100%' }}
            animate={{ x: 0 }}
            exit={{ x: '100%' }}
            transition={{ duration: 0.55, ease: [0.2, 0.7, 0.2, 1] }}
            style={{
              position: 'fixed',
              top: 0,
              right: 0,
              bottom: 0,
              width: 'min(960px, 96vw)',
              zIndex: 1001,
              display: 'grid',
              gridTemplateColumns: '0.85fr 1.15fr',
              boxShadow: '-24px 0 0 rgba(26,23,20,0.18)',
              background: 'var(--paper)',
            }}
          >
            {/* LEFT page — dark masthead */}
            <div
              style={{
                background: 'var(--ink)',
                color: 'var(--paper)',
                position: 'relative',
                padding: '40px 36px',
                display: 'flex',
                flexDirection: 'column',
                justifyContent: 'space-between',
                overflow: 'hidden',
              }}
            >
              {/* Watermark */}
              <span
                className="font-serif"
                aria-hidden
                style={{
                  position: 'absolute',
                  bottom: -80,
                  right: -40,
                  fontSize: 280,
                  fontWeight: 900,
                  fontStyle: 'italic',
                  color: 'rgba(242,236,224,0.04)',
                  lineHeight: 1,
                  pointerEvents: 'none',
                  userSelect: 'none',
                }}
              >
                C
              </span>

              <div style={{ position: 'relative', zIndex: 2 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 18 }}>
                  <div style={{ width: 24, height: 2, background: 'var(--red)' }} />
                  <span
                    style={{
                      fontSize: 10,
                      letterSpacing: '0.22em',
                      textTransform: 'uppercase',
                      color: 'var(--red)',
                      fontWeight: 600,
                    }}
                  >
                    Vol. I — Issue 04
                  </span>
                </div>
                <div
                  className="font-serif"
                  style={{
                    fontSize: 28,
                    fontWeight: 900,
                    fontStyle: 'italic',
                    letterSpacing: '-0.03em',
                    lineHeight: 1,
                  }}
                >
                  TheCee
                </div>
                <p
                  style={{
                    marginTop: 12,
                    fontSize: 11,
                    letterSpacing: '0.18em',
                    textTransform: 'uppercase',
                    color: 'rgba(242,236,224,0.4)',
                  }}
                >
                  The simulation broadsheet
                </p>
              </div>

              <div style={{ position: 'relative', zIndex: 2 }}>
                <p
                  className="font-serif"
                  style={{
                    fontSize: 22,
                    fontStyle: 'italic',
                    fontWeight: 700,
                    lineHeight: 1.4,
                    color: 'var(--paper)',
                    opacity: 0.92,
                  }}
                >
                  &ldquo;The press is open. Your dossier is half-typeset and
                  the room is loud — sign in and finish the edition.&rdquo;
                </p>
                <div
                  style={{
                    marginTop: 22,
                    fontSize: 10,
                    letterSpacing: '0.18em',
                    textTransform: 'uppercase',
                    color: 'rgba(242,236,224,0.45)',
                  }}
                >
                  — From the Editor
                </div>
              </div>

              <div style={{ position: 'relative', zIndex: 2 }}>
                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: '1fr 1fr',
                    borderTop: '0.5px solid rgba(242,236,224,0.1)',
                    paddingTop: 20,
                  }}
                >
                  {[
                    { v: '243+', l: 'Founders' },
                    { v: '1.4M+', l: 'Scenarios' },
                  ].map((s, i) => (
                    <div key={s.l} style={{ paddingLeft: i ? 16 : 0, borderLeft: i ? '0.5px solid rgba(242,236,224,0.1)' : 'none' }}>
                      <div className="font-serif" style={{ fontSize: 26, fontWeight: 900, letterSpacing: '-0.03em' }}>
                        {s.v}
                      </div>
                      <div style={{ fontSize: 9, letterSpacing: '0.18em', textTransform: 'uppercase', color: 'rgba(242,236,224,0.4)', marginTop: 6 }}>
                        {s.l}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* RIGHT page — form */}
            <div
              style={{
                position: 'relative',
                padding: '40px 48px',
                display: 'flex',
                flexDirection: 'column',
                background: 'var(--paper)',
                overflowY: 'auto',
              }}
            >
              <button
                type="button"
                onClick={onClose}
                aria-label="Close"
                style={{
                  position: 'absolute',
                  top: 18,
                  right: 18,
                  background: 'none',
                  border: '0.5px solid var(--border-color)',
                  width: 32,
                  height: 32,
                  cursor: 'pointer',
                  color: 'var(--ink)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                <X size={14} />
              </button>

              <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20, marginTop: 8 }}>
                <div style={{ width: 24, height: 2, background: 'var(--red)' }} />
                <span
                  style={{
                    fontSize: 10,
                    letterSpacing: '0.22em',
                    textTransform: 'uppercase',
                    color: 'var(--red)',
                    fontWeight: 600,
                  }}
                >
                  {mode === 'login' ? 'Sign in to The Press' : 'Open a Press Account'}
                </span>
              </div>

              <h2
                className="font-serif"
                style={{
                  fontSize: 'clamp(36px, 4.2vw, 56px)',
                  fontWeight: 900,
                  letterSpacing: '-0.04em',
                  lineHeight: 0.96,
                  color: 'var(--ink)',
                  marginBottom: 20,
                }}
              >
                {mode === 'login' ? (
                  <>
                    Welcome <span style={{ fontStyle: 'italic', color: 'var(--red)' }}>back.</span>
                  </>
                ) : (
                  <>
                    Begin your <span style={{ fontStyle: 'italic', color: 'var(--red)' }}>edition.</span>
                  </>
                )}
              </h2>

              <div style={{ display: 'flex', borderBottom: '0.5px solid var(--border-color)', marginBottom: 28 }}>
                {(['login', 'signup'] as Mode[]).map(m => (
                  <button
                    key={m}
                    type="button"
                    onClick={() => setMode(m)}
                    style={{
                      background: 'none',
                      border: 'none',
                      padding: '10px 18px',
                      borderBottom: mode === m ? '2px solid var(--red)' : '2px solid transparent',
                      marginBottom: '-1px',
                      fontSize: 11,
                      fontWeight: 700,
                      letterSpacing: '0.14em',
                      textTransform: 'uppercase',
                      color: mode === m ? 'var(--ink)' : 'var(--ink-tertiary)',
                      cursor: 'pointer',
                      fontFamily: 'inherit',
                    }}
                  >
                    {m === 'login' ? 'Sign in' : 'Create account'}
                  </button>
                ))}
              </div>

              <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: 22 }}>
                {mode === 'signup' && (
                  <Field label="Full name" value={name} onChange={setName} placeholder="Your name" />
                )}
                <Field label="Email address" type="email" value={email} onChange={setEmail} placeholder="you@example.com" />
                <Field label="Password" type="password" value={password} onChange={setPassword} placeholder="Min 8 characters" />
                {mode === 'signup' && (
                  <Field
                    label="Confirm password"
                    type="password"
                    value={confirm}
                    onChange={setConfirm}
                    placeholder="Repeat password"
                  />
                )}

                {err && (
                  <div
                    style={{
                      fontSize: 11,
                      color: 'var(--red)',
                      padding: '10px 12px',
                      background: 'rgba(192,57,43,0.05)',
                      border: '0.5px solid rgba(192,57,43,0.25)',
                    }}
                  >
                    {err}
                  </div>
                )}

                <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginTop: 6 }}>
                  <button
                    type="submit"
                    disabled={submitting}
                    style={{
                      flex: 1,
                      background: 'var(--ink)',
                      color: 'var(--paper)',
                      border: 'none',
                      padding: '16px 24px',
                      fontSize: 11,
                      fontWeight: 700,
                      letterSpacing: '0.16em',
                      textTransform: 'uppercase',
                      cursor: submitting ? 'not-allowed' : 'pointer',
                      opacity: submitting ? 0.6 : 1,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: 10,
                      fontFamily: 'inherit',
                      transition: 'background 0.2s ease',
                    }}
                    onMouseEnter={e => {
                      if (!submitting) (e.currentTarget as HTMLButtonElement).style.background = '#12100e'
                    }}
                    onMouseLeave={e => {
                      (e.currentTarget as HTMLButtonElement).style.background = 'var(--ink)'
                    }}
                  >
                    {submitting ? (
                      <>
                        <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} />
                        {mode === 'login' ? 'Signing in…' : 'Creating…'}
                      </>
                    ) : (
                      <>
                        {mode === 'login' ? 'Sign in & enter the press' : 'Create account & begin'}
                        <ArrowRight size={14} />
                      </>
                    )}
                  </button>
                </div>

                <p style={{ fontSize: 11, color: 'var(--ink-tertiary)', marginTop: 4 }}>
                  {mode === 'login' ? (
                    <>
                      No account?{' '}
                      <button
                        type="button"
                        onClick={() => setMode('signup')}
                        style={{
                          background: 'none',
                          border: 'none',
                          color: 'var(--red)',
                          borderBottom: '0.5px solid rgba(192,57,43,0.4)',
                          cursor: 'pointer',
                          fontSize: 11,
                          padding: 0,
                          fontFamily: 'inherit',
                        }}
                      >
                        Open one free
                      </button>
                    </>
                  ) : (
                    <>
                      Already have one?{' '}
                      <button
                        type="button"
                        onClick={() => setMode('login')}
                        style={{
                          background: 'none',
                          border: 'none',
                          color: 'var(--red)',
                          borderBottom: '0.5px solid rgba(192,57,43,0.4)',
                          cursor: 'pointer',
                          fontSize: 11,
                          padding: 0,
                          fontFamily: 'inherit',
                        }}
                      >
                        Sign in
                      </button>
                    </>
                  )}
                </p>
              </form>

              <div
                style={{
                  marginTop: 'auto',
                  paddingTop: 28,
                  borderTop: '0.5px solid var(--border-color)',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  fontSize: 9,
                  letterSpacing: '0.18em',
                  textTransform: 'uppercase',
                  color: 'var(--ink-tertiary)',
                }}
              >
                <span>ESC to close</span>
                <span>thecee.app</span>
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>,
    document.body,
  )
}

function Field({
  label,
  value,
  onChange,
  type = 'text',
  placeholder,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  type?: string
  placeholder: string
}) {
  const ref = useRef<HTMLInputElement>(null)
  return (
    <div>
      <label
        style={{
          display: 'block',
          fontSize: 10,
          color: 'var(--ink-tertiary)',
          letterSpacing: '0.18em',
          textTransform: 'uppercase',
          marginBottom: 8,
        }}
      >
        {label}
      </label>
      <input
        ref={ref}
        type={type}
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        style={{
          width: '100%',
          border: 'none',
          borderBottom: '0.5px solid var(--border-strong)',
          background: 'transparent',
          padding: '11px 0',
          fontSize: 15,
          color: 'var(--ink)',
          outline: 'none',
          fontFamily: 'inherit',
          fontWeight: 300,
          transition: 'border-color 0.2s ease',
        }}
        onFocus={e => (e.currentTarget.style.borderBottomColor = 'var(--ink)')}
        onBlur={e => (e.currentTarget.style.borderBottomColor = 'var(--border-strong)')}
      />
    </div>
  )
}
