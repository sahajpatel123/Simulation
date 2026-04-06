'use client'

import { Suspense, useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { useRouter, useSearchParams } from 'next/navigation'
import Link from 'next/link'
import { ArrowRight, Loader2 } from 'lucide-react'
import type { UseFormRegisterReturn } from 'react-hook-form'

/* ─── SCHEMAS ───────────────────────────────────── */
const loginSchema = z.object({
  email: z.string().email('Enter a valid email'),
  password: z.string().min(8, 'Min 8 characters'),
})

const signupSchema = z
  .object({
    name: z.string().min(2, 'Enter your name'),
    email: z.string().email('Enter a valid email'),
    password: z.string().min(8, 'Min 8 characters'),
    confirm: z.string(),
  })
  .refine(d => d.password === d.confirm, {
    message: 'Passwords do not match',
    path: ['confirm'],
  })

type LoginData = z.infer<typeof loginSchema>
type SignupData = z.infer<typeof signupSchema>

/* ─── SPRING CONFIG ─────────────────────────────── */
const SPRING = {
  type: 'spring' as const,
  stiffness: 260,
  damping: 32,
  mass: 1.1,
}

const SPRING_SLOW = {
  type: 'spring' as const,
  stiffness: 180,
  damping: 28,
  mass: 1.2,
}

/* ─── FIELD COMPONENT ───────────────────────────── */
function Field({
  label,
  type = 'text',
  placeholder,
  error,
  register,
  delay = 0,
}: {
  label: string
  type?: string
  placeholder: string
  error?: string
  register: UseFormRegisterReturn
  delay?: number
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      transition={{ ...SPRING, delay }}
    >
      <label
        style={{
          display: 'block',
          fontSize: '9px',
          color: 'rgba(26,23,20,0.4)',
          letterSpacing: '0.18em',
          textTransform: 'uppercase',
          marginBottom: '6px',
          fontFamily: 'DM Sans, sans-serif',
        }}
      >
        {label}
      </label>
      <input
        {...register}
        type={type}
        placeholder={placeholder}
        style={{
          width: '100%',
          border: 'none',
          borderBottom: error ? '1px solid #c0392b' : '0.5px solid rgba(26,23,20,0.2)',
          background: 'transparent',
          padding: '9px 0',
          fontSize: '13px',
          color: '#1a1714',
          outline: 'none',
          fontFamily: 'DM Sans, sans-serif',
          fontWeight: 300,
          transition: 'border-color 0.3s ease',
        }}
        onFocus={e => {
          e.target.style.borderBottomColor = '#1a1714'
        }}
        onBlur={e => {
          e.target.style.borderBottomColor = error ? '#c0392b' : 'rgba(26,23,20,0.2)'
        }}
      />
      {error && (
        <motion.p
          initial={{ opacity: 0, y: -4 }}
          animate={{ opacity: 1, y: 0 }}
          style={{ fontSize: '9px', color: '#c0392b', marginTop: '4px', fontFamily: 'DM Sans, sans-serif' }}
        >
          {error}
        </motion.p>
      )}
    </motion.div>
  )
}

/* ─── MAIN (uses search params — wrap in Suspense) ─ */
function AuthPage() {
  const [mode, setMode] = useState<'login' | 'signup'>('login')
  const router = useRouter()
  const searchParams = useSearchParams()

  useEffect(() => {
    if (searchParams.get('mode') === 'signup') setMode('signup')
  }, [searchParams])

  const loginForm = useForm<LoginData>({ resolver: zodResolver(loginSchema) })
  const signupForm = useForm<SignupData>({ resolver: zodResolver(signupSchema) })

  const onLogin = async (_data: LoginData) => {
    await new Promise(r => setTimeout(r, 1400))
    router.push('/dashboard')
  }

  const onSignup = async (_data: SignupData) => {
    await new Promise(r => setTimeout(r, 1600))
    router.push('/dashboard')
  }

  const isLogin = mode === 'login'

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        background: '#f2ece0',
        overflow: 'hidden',
        fontFamily: 'DM Sans, sans-serif',
      }}
    >
      {/* ━━━ DARK EDITORIAL PANEL ━━━ */}
      <motion.div
        layout
        transition={SPRING_SLOW}
        style={{
          background: '#1a1714',
          position: 'relative',
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
          flexShrink: 0,
          width: isLogin ? '58%' : '64px',
        }}
      >
        {/* Ghost watermark letter */}
        <motion.div
          animate={{ opacity: isLogin ? 1 : 0, scale: isLogin ? 1 : 0.8 }}
          transition={SPRING}
          style={{
            position: 'absolute',
            bottom: '-80px',
            right: '-40px',
            fontSize: '280px',
            fontWeight: 900,
            color: 'rgba(242,236,224,0.035)',
            fontFamily: 'Playfair Display, Georgia, serif',
            fontStyle: 'italic',
            lineHeight: 1,
            userSelect: 'none',
            pointerEvents: 'none',
          }}
        >
          T
        </motion.div>

        {/* Red accent line top */}
        <motion.div
          layout
          style={{
            height: '3px',
            background: '#c0392b',
            flexShrink: 0,
          }}
        />

        {/* SIGN IN — full dark content */}
        <AnimatePresence mode="wait">
          {isLogin && (
            <motion.div
              key="dark-content"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.35, delay: 0.15 }}
              style={{
                flex: 1,
                display: 'flex',
                flexDirection: 'column',
                justifyContent: 'space-between',
                padding: '36px 52px',
                position: 'relative',
                zIndex: 2,
              }}
            >
              {/* Top */}
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '48px' }}>
                  <Link
                    href="/"
                    style={{
                      fontSize: '20px',
                      fontWeight: 900,
                      color: '#f2ece0',
                      fontFamily: 'Playfair Display, Georgia, serif',
                      fontStyle: 'italic',
                      letterSpacing: '-0.03em',
                      textDecoration: 'none',
                    }}
                  >
                    TheCee
                  </Link>
                  <span
                    style={{
                      fontSize: '9px',
                      color: 'rgba(242,236,224,0.2)',
                      letterSpacing: '0.2em',
                      textTransform: 'uppercase',
                    }}
                  >
                    Vol. 01 — 2026
                  </span>
                </div>

                <div
                  style={{
                    width: '24px',
                    height: '2px',
                    background: '#c0392b',
                    marginBottom: '14px',
                  }}
                />
                <div
                  style={{
                    fontSize: '10px',
                    color: '#c0392b',
                    letterSpacing: '0.22em',
                    textTransform: 'uppercase',
                    fontWeight: 600,
                    marginBottom: '20px',
                  }}
                >
                  Welcome back
                </div>

                <motion.h1
                  initial={{ opacity: 0, y: 24 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ ...SPRING, delay: 0.1 }}
                  style={{
                    fontSize: 'clamp(44px, 4.5vw, 72px)',
                    fontWeight: 900,
                    color: '#f2ece0',
                    fontFamily: 'Playfair Display, Georgia, serif',
                    fontStyle: 'italic',
                    lineHeight: 0.96,
                    letterSpacing: '-0.04em',
                    marginBottom: '24px',
                  }}
                >
                  Know before
                  <br />
                  you{' '}
                  <span style={{ color: 'rgba(242,236,224,0.18)' }}>build.</span>
                </motion.h1>

                <motion.p
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ duration: 0.6, delay: 0.3 }}
                  style={{
                    fontSize: '13px',
                    color: 'rgba(242,236,224,0.35)',
                    lineHeight: 1.85,
                    maxWidth: '360px',
                    fontWeight: 300,
                  }}
                >
                  You are one simulation away from certainty. Sign in and continue where you left off.
                </motion.p>
              </div>

              {/* Stats bottom */}
              <motion.div
                initial={{ opacity: 0, y: 16 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ ...SPRING, delay: 0.25 }}
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(3, 1fr)',
                  gap: '0',
                  borderTop: '0.5px solid rgba(242,236,224,0.08)',
                  paddingTop: '28px',
                }}
              >
                {[
                  { v: '10K+', l: 'Scenarios per run' },
                  { v: '240+', l: 'Founders validated' },
                  { v: '<2min', l: 'To first insight' },
                ].map(({ v, l }, i) => (
                  <div
                    key={l}
                    style={{
                      paddingRight: i < 2 ? '20px' : '0',
                      paddingLeft: i > 0 ? '20px' : '0',
                      borderRight: i < 2 ? '0.5px solid rgba(242,236,224,0.08)' : 'none',
                    }}
                  >
                    <div
                      style={{
                        fontSize: '26px',
                        fontWeight: 900,
                        color: '#f2ece0',
                        fontFamily: 'Playfair Display, Georgia, serif',
                        letterSpacing: '-0.04em',
                        lineHeight: 1,
                      }}
                    >
                      {v}
                    </div>
                    <div
                      style={{
                        fontSize: '8px',
                        color: 'rgba(242,236,224,0.28)',
                        letterSpacing: '0.14em',
                        textTransform: 'uppercase',
                        marginTop: '4px',
                      }}
                    >
                      {l}
                    </div>
                  </div>
                ))}
              </motion.div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* SIGNUP — collapsed spine content */}
        <AnimatePresence mode="wait">
          {!isLogin && (
            <motion.div
              key="spine-content"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.3, delay: 0.2 }}
              style={{
                flex: 1,
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '20px 0',
              }}
            >
              <div
                style={{
                  width: '2px',
                  height: '20px',
                  background: '#c0392b',
                }}
              />
              <Link
                href="/"
                style={{
                  writingMode: 'vertical-rl',
                  textOrientation: 'mixed',
                  transform: 'rotate(180deg)',
                  fontSize: '12px',
                  fontWeight: 900,
                  color: 'rgba(242,236,224,0.5)',
                  fontFamily: 'Playfair Display, Georgia, serif',
                  fontStyle: 'italic',
                  letterSpacing: '-0.02em',
                  textDecoration: 'none',
                }}
              >
                TheCee
              </Link>
              <div
                style={{
                  writingMode: 'vertical-rl',
                  textOrientation: 'mixed',
                  transform: 'rotate(180deg)',
                  fontSize: '7px',
                  color: 'rgba(242,236,224,0.18)',
                  letterSpacing: '0.16em',
                  textTransform: 'uppercase',
                }}
              >
                2026
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>

      {/* ━━━ PAPER FORM PANEL ━━━ */}
      <motion.div
        layout
        transition={SPRING_SLOW}
        style={{
          flex: 1,
          background: '#f2ece0',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          padding: isLogin ? '52px 64px' : '48px 64px',
          position: 'relative',
          overflow: 'hidden',
        }}
      >
        {/* Ghost watermark — signup only */}
        <AnimatePresence>
          {!isLogin && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.5 }}
              style={{
                position: 'absolute',
                right: '-60px',
                top: '-40px',
                fontSize: '260px',
                fontWeight: 900,
                color: 'rgba(26,23,20,0.03)',
                fontFamily: 'Playfair Display, Georgia, serif',
                fontStyle: 'italic',
                lineHeight: 1,
                userSelect: 'none',
                pointerEvents: 'none',
                zIndex: 0,
              }}
            >
              C
            </motion.div>
          )}
        </AnimatePresence>

        <div style={{ position: 'relative', zIndex: 2, maxWidth: isLogin ? '360px' : '100%' }}>
          {/* Kicker */}
          <motion.div layout style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '20px' }}>
            <div style={{ width: '20px', height: '1.5px', background: '#c0392b' }} />
            <span
              style={{
                fontSize: '9px',
                color: '#c0392b',
                letterSpacing: '0.22em',
                textTransform: 'uppercase',
                fontWeight: 600,
              }}
            >
              {isLogin ? 'Sign in to TheCee' : 'Create your account'}
            </span>
          </motion.div>

          {/* Toggle tabs */}
          <motion.div
            layout
            style={{
              display: 'flex',
              borderBottom: '1.5px solid rgba(26,23,20,0.1)',
              marginBottom: '32px',
            }}
          >
            {(['login', 'signup'] as const).map(m => (
              <button
                key={m}
                type="button"
                onClick={() => setMode(m)}
                style={{
                  background: 'none',
                  border: 'none',
                  borderBottom: mode === m ? '2px solid #c0392b' : '2px solid transparent',
                  marginBottom: '-2px',
                  padding: '6px 18px',
                  fontSize: '9px',
                  fontWeight: 700,
                  letterSpacing: '0.1em',
                  textTransform: 'uppercase',
                  color: mode === m ? '#1a1714' : 'rgba(26,23,20,0.28)',
                  cursor: 'pointer',
                  transition: 'color 0.25s ease, border-color 0.25s ease',
                  fontFamily: 'DM Sans, sans-serif',
                }}
              >
                {m === 'login' ? 'Sign in' : 'Create account'}
              </button>
            ))}
          </motion.div>

          {/* ── LOGIN / SIGNUP FORMS ── */}
          <AnimatePresence mode="wait">
            {isLogin && (
              <motion.form
                key="login-form"
                initial={{ opacity: 0, x: 24 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -24 }}
                transition={{ ...SPRING }}
                onSubmit={loginForm.handleSubmit(onLogin)}
              >
                <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                  <Field
                    label="Email address"
                    type="email"
                    placeholder="you@example.com"
                    error={loginForm.formState.errors.email?.message}
                    register={loginForm.register('email')}
                    delay={0.05}
                  />
                  <Field
                    label="Password"
                    type="password"
                    placeholder="Your password"
                    error={loginForm.formState.errors.password?.message}
                    register={loginForm.register('password')}
                    delay={0.1}
                  />
                </div>

                <motion.div
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ delay: 0.18 }}
                  style={{ marginTop: '8px', marginBottom: '28px' }}
                >
                  <span
                    style={{
                      fontSize: '9px',
                      color: '#c0392b',
                      letterSpacing: '0.08em',
                      borderBottom: '0.5px solid rgba(192,57,43,0.35)',
                      paddingBottom: '1px',
                      cursor: 'pointer',
                    }}
                  >
                    Forgot password?
                  </span>
                </motion.div>

                <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ ...SPRING, delay: 0.22 }}>
                  <div style={{ width: '20px', height: '2px', background: '#c0392b', marginBottom: '20px' }} />
                  <button
                    type="submit"
                    disabled={loginForm.formState.isSubmitting}
                    style={{
                      width: '100%',
                      background: '#1a1714',
                      color: '#f2ece0',
                      border: 'none',
                      padding: '14px',
                      fontSize: '9px',
                      fontWeight: 700,
                      letterSpacing: '0.14em',
                      textTransform: 'uppercase',
                      cursor: loginForm.formState.isSubmitting ? 'not-allowed' : 'pointer',
                      opacity: loginForm.formState.isSubmitting ? 0.6 : 1,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: '8px',
                      fontFamily: 'DM Sans, sans-serif',
                      transition: 'background 0.2s ease',
                    }}
                    onMouseEnter={e => {
                      if (!loginForm.formState.isSubmitting) (e.currentTarget as HTMLButtonElement).style.background = '#c0392b'
                    }}
                    onMouseLeave={e => {
                      (e.currentTarget as HTMLButtonElement).style.background = '#1a1714'
                    }}
                  >
                    {loginForm.formState.isSubmitting ? (
                      <>
                        <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} /> Signing in...
                      </>
                    ) : (
                      <>
                        Sign in <ArrowRight size={13} />
                      </>
                    )}
                  </button>
                  <p
                    style={{
                      fontSize: '10px',
                      color: 'rgba(26,23,20,0.35)',
                      marginTop: '16px',
                      textAlign: 'center',
                      fontFamily: 'DM Sans, sans-serif',
                    }}
                  >
                    No account?{' '}
                    <button
                      type="button"
                      onClick={() => setMode('signup')}
                      style={{
                        background: 'none',
                        border: 'none',
                        borderBottom: '0.5px solid rgba(192,57,43,0.4)',
                        color: '#c0392b',
                        fontSize: '10px',
                        cursor: 'pointer',
                        padding: '0 0 1px',
                        fontFamily: 'DM Sans, sans-serif',
                      }}
                    >
                      Create one free
                    </button>
                  </p>
                </motion.div>
              </motion.form>
            )}

            {!isLogin && (
              <motion.form
                key="signup-form"
                initial={{ opacity: 0, x: 24 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -24 }}
                transition={{ ...SPRING }}
                onSubmit={signupForm.handleSubmit(onSignup)}
              >
                {/* Italic serif headline — signup only */}
                <motion.h2
                  initial={{ opacity: 0, y: 16 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0 }}
                  transition={{ ...SPRING, delay: 0.08 }}
                  style={{
                    fontSize: 'clamp(28px, 3vw, 44px)',
                    fontWeight: 900,
                    color: '#1a1714',
                    fontFamily: 'Playfair Display, Georgia, serif',
                    fontStyle: 'italic',
                    lineHeight: 1.0,
                    letterSpacing: '-0.04em',
                    marginBottom: '32px',
                  }}
                >
                  Join the founders
                  <br />
                  who <span style={{ color: 'rgba(26,23,20,0.2)' }}>simulate first.</span>
                </motion.h2>

                {/* 3-column field grid */}
                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(3, 1fr)',
                    gap: '0 40px',
                    marginBottom: '20px',
                  }}
                >
                  <Field
                    label="Full name"
                    placeholder="Your name"
                    error={signupForm.formState.errors.name?.message}
                    register={signupForm.register('name')}
                    delay={0.08}
                  />
                  <Field
                    label="Email address"
                    type="email"
                    placeholder="you@example.com"
                    error={signupForm.formState.errors.email?.message}
                    register={signupForm.register('email')}
                    delay={0.13}
                  />
                  <Field
                    label="Password"
                    type="password"
                    placeholder="Min 8 characters"
                    error={signupForm.formState.errors.password?.message}
                    register={signupForm.register('password')}
                    delay={0.18}
                  />
                </div>
                <div style={{ maxWidth: 'calc(33.33% - 27px)', marginBottom: '32px' }}>
                  <Field
                    label="Confirm password"
                    type="password"
                    placeholder="Repeat password"
                    error={signupForm.formState.errors.confirm?.message}
                    register={signupForm.register('confirm')}
                    delay={0.23}
                  />
                </div>

                {/* Bottom row */}
                <motion.div
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ ...SPRING, delay: 0.28 }}
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    paddingTop: '20px',
                    borderTop: '0.5px solid rgba(26,23,20,0.08)',
                  }}
                >
                  <div>
                    <p
                      style={{
                        fontSize: '9px',
                        color: 'rgba(26,23,20,0.3)',
                        lineHeight: 1.7,
                        maxWidth: '260px',
                        fontFamily: 'DM Sans, sans-serif',
                      }}
                    >
                      By creating an account you agree to our{' '}
                      <span style={{ color: '#c0392b', borderBottom: '0.5px solid rgba(192,57,43,0.35)' }}>Terms</span> and{' '}
                      <span style={{ color: '#c0392b', borderBottom: '0.5px solid rgba(192,57,43,0.35)' }}>Privacy Policy</span>.
                    </p>
                    <button
                      type="button"
                      onClick={() => setMode('login')}
                      style={{
                        background: 'none',
                        border: 'none',
                        fontSize: '9px',
                        color: 'rgba(26,23,20,0.32)',
                        marginTop: '8px',
                        cursor: 'pointer',
                        padding: 0,
                        fontFamily: 'DM Sans, sans-serif',
                      }}
                    >
                      Already have one?{' '}
                      <span style={{ color: '#c0392b', borderBottom: '0.5px solid rgba(192,57,43,0.35)' }}>Sign in</span>
                    </button>
                  </div>
                  <button
                    type="submit"
                    disabled={signupForm.formState.isSubmitting}
                    style={{
                      background: '#c0392b',
                      color: '#fff',
                      border: 'none',
                      padding: '14px 36px',
                      fontSize: '9px',
                      fontWeight: 700,
                      letterSpacing: '0.14em',
                      textTransform: 'uppercase',
                      cursor: signupForm.formState.isSubmitting ? 'not-allowed' : 'pointer',
                      opacity: signupForm.formState.isSubmitting ? 0.7 : 1,
                      display: 'flex',
                      alignItems: 'center',
                      gap: '8px',
                      fontFamily: 'DM Sans, sans-serif',
                      flexShrink: 0,
                      transition: 'background 0.2s ease',
                    }}
                    onMouseEnter={e => {
                      if (!signupForm.formState.isSubmitting) (e.currentTarget as HTMLButtonElement).style.background = '#a93226'
                    }}
                    onMouseLeave={e => {
                      (e.currentTarget as HTMLButtonElement).style.background = '#c0392b'
                    }}
                  >
                    {signupForm.formState.isSubmitting ? (
                      <>
                        <Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} /> Creating...
                      </>
                    ) : (
                      <>
                        Create account <ArrowRight size={13} />
                      </>
                    )}
                  </button>
                </motion.div>
              </motion.form>
            )}
          </AnimatePresence>
        </div>
      </motion.div>

      <style>{`
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
        * { box-sizing: border-box; }
        input::placeholder { color: rgba(26,23,20,0.22); }
      `}</style>
    </div>
  )
}

export default function LoginPage() {
  return (
    <Suspense fallback={<div style={{ minHeight: '100vh', background: '#f2ece0' }} />}>
      <AuthPage />
    </Suspense>
  )
}
