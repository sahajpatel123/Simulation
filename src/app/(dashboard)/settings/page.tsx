'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { AnimatePresence, motion } from 'framer-motion'
import {
  AlertTriangle,
  Bell,
  Check,
  Download,
  KeyRound,
  Layers,
  Loader2,
  LogOut,
  Trash2,
  User,
  X,
} from 'lucide-react'

import { apiError } from '@/lib/api'
import { useCurrentUser, useLogout } from '@/hooks/useAuth'
import {
  useChangePassword,
  useClearArchive,
  useDeleteAccount,
  useExportArchive,
  useUpdateProfile,
  type ProfileUpdatePayload,
} from '@/hooks/useSettings'
import { useAuthStore } from '@/store/auth.store'

/* ── Types & constants ───────────────────────────────────────── */
type SectionKey = 'identity' | 'preferences' | 'cast' | 'archive' | 'danger'

const READER_MIN = 1000
const READER_MAX = 10000  /* Aligns with the environment slider ceiling. */

const sections: {
  key: SectionKey
  num: string
  title: string
  note: string
  icon: React.ComponentType<{ style?: React.CSSProperties }>
}[] = [
  { key: 'identity',    num: 'I',   title: 'Identity',        note: 'Your name on the masthead',          icon: User },
  { key: 'preferences', num: 'II',  title: 'House preferences', note: 'How the paper is set on your desk', icon: Bell },
  { key: 'cast',        num: 'III', title: 'Cast defaults',    note: 'How synthetic readers are drawn up',icon: Layers },
  { key: 'archive',     num: 'IV',  title: 'Archive & data',   note: 'Your filings, in your hands',       icon: Download },
  { key: 'danger',      num: 'V',   title: 'Errata column',    note: 'Things that cannot be undone',       icon: AlertTriangle },
]

const unitOptions = [
  { id: 'inr', label: '₹ INR' },
  { id: 'usd', label: '$ USD' },
  { id: 'eur', label: '€ EUR' },
] as const

const scenarioOptions = [
  { id: 'base',       label: 'Base case' },
  { id: 'recession',  label: 'Recession' },
  { id: 'viral',      label: 'Viral moment' },
  { id: 'competitor', label: 'Competitor entry' },
] as const

type Flash = { kind: 'ok' | 'err'; msg: string }

/* ── Page ────────────────────────────────────────────────────── */
export default function SettingsPage() {
  /* Fetch latest user from the server so settings hydrate after reload. */
  useCurrentUser()

  const user          = useAuthStore((s) => s.user)
  const logoutLocal   = useLogout()

  const updateProfile = useUpdateProfile()
  const changePass    = useChangePassword()
  const clearArchive  = useClearArchive()
  const deleteAccount = useDeleteAccount()
  const exportArchive = useExportArchive()

  const [active, setActive] = useState<SectionKey>('identity')
  const [flash, setFlash]   = useState<Flash | null>(null)

  const [pwOpen, setPwOpen]       = useState(false)
  const [clearOpen, setClearOpen] = useState(false)
  const [nukeOpen, setNukeOpen]   = useState(false)

  const sectionRefs = useRef<Record<SectionKey, HTMLDivElement | null>>({
    identity: null, preferences: null, cast: null, archive: null, danger: null,
  })

  /* ── Identity form ── */
  const [fullName, setFullName] = useState('')
  const [email, setEmail]       = useState('')
  const [handle, setHandle]     = useState('')

  /* ── Preferences form ── */
  const [reducedMotion, setReducedMotion] = useState(false)
  const [emailNotices,  setEmailNotices]  = useState(true)
  const [weeklyBrief,   setWeeklyBrief]   = useState(false)
  const [units, setUnits]                 = useState<'inr' | 'usd' | 'eur'>('inr')

  /* ── Cast defaults form ── */
  const [readerCount, setReaderCount]         = useState<number>(10000)
  const [scenario,    setScenario]            = useState<'base' | 'recession' | 'viral' | 'competitor'>('base')
  const [aov,         setAov]                 = useState<number>(1000)
  const [keepResults, setKeepResults]         = useState(true)

  /* Hydrate local form state whenever the authenticated user changes. */
  useEffect(() => {
    if (!user) return
    setFullName(user.full_name ?? '')
    setEmail(user.email ?? '')
    setHandle(user.handle ?? (user.email ?? '').split('@')[0] ?? '')
    setReducedMotion(user.reduced_motion ?? false)
    setEmailNotices(user.email_notices ?? true)
    setWeeklyBrief(user.weekly_brief ?? false)
    setUnits(user.default_units ?? 'inr')
    setReaderCount(user.default_reader_count ?? 10000)
    setScenario(user.default_scenario ?? 'base')
    setAov(user.default_aov ?? 1000)
    setKeepResults(user.keep_past_results ?? true)
  }, [user])

  /* Auto-dismiss the flash. */
  useEffect(() => {
    if (!flash) return
    const t = setTimeout(() => setFlash(null), 2600)
    return () => clearTimeout(t)
  }, [flash])

  const scrollTo = (key: SectionKey) => {
    setActive(key)
    const el = sectionRefs.current[key]
    if (el) {
      const y = el.getBoundingClientRect().top + window.scrollY - 140
      window.scrollTo({ top: y, behavior: 'smooth' })
    }
  }

  /* ── Dirty trackers (per section) ── */
  const identityDirty = useMemo(() => {
    if (!user) return false
    return (
      (fullName || '') !== (user.full_name ?? '') ||
      (email || '')    !== (user.email ?? '')     ||
      (handle || '')   !== (user.handle ?? (user.email ?? '').split('@')[0] ?? '')
    )
  }, [fullName, email, handle, user])

  const prefsDirty = useMemo(() => {
    if (!user) return false
    return (
      reducedMotion !== (user.reduced_motion ?? false) ||
      emailNotices  !== (user.email_notices ?? true)   ||
      weeklyBrief   !== (user.weekly_brief ?? false)   ||
      units         !== (user.default_units ?? 'inr')
    )
  }, [reducedMotion, emailNotices, weeklyBrief, units, user])

  const castDirty = useMemo(() => {
    if (!user) return false
    return (
      readerCount !== (user.default_reader_count ?? 10000) ||
      scenario    !== (user.default_scenario ?? 'base')    ||
      aov         !== (user.default_aov ?? 1000)           ||
      keepResults !== (user.keep_past_results ?? true)
    )
  }, [readerCount, scenario, aov, keepResults, user])

  /* ── Save handlers ── */
  const save = async (
    payload: ProfileUpdatePayload,
    okMsg: string,
  ) => {
    try {
      await updateProfile.mutateAsync(payload)
      setFlash({ kind: 'ok', msg: okMsg })
    } catch (err) {
      setFlash({ kind: 'err', msg: apiError(err) })
    }
  }

  const saveIdentity = () =>
    save(
      {
        full_name: fullName.trim() || null,
        email:     email.trim(),
        handle:    handle.trim() || null,
      },
      'Identity set in type.',
    )

  const savePrefs = () =>
    save(
      {
        reduced_motion: reducedMotion,
        email_notices:  emailNotices,
        weekly_brief:   weeklyBrief,
        default_units:  units,
      },
      'Preferences saved.',
    )

  const saveCast = () => {
    const clamped = Math.max(READER_MIN, Math.min(READER_MAX, Math.round(readerCount || 0)))
    if (clamped !== readerCount) setReaderCount(clamped)
    return save(
      {
        default_reader_count: clamped,
        default_scenario:     scenario,
        default_aov:          Math.max(0, Number(aov) || 0),
        keep_past_results:    keepResults,
      },
      'Cast defaults set.',
    )
  }

  return (
    <div className="rise" style={{ padding: '48px 48px 160px', maxWidth: 1280, margin: '0 auto' }}>
      {/* Masthead */}
      <header style={{ marginBottom: 28 }}>
        <div
          className="kicker"
          style={{ color: 'var(--red)', marginBottom: 18, display: 'flex', alignItems: 'center', gap: 12 }}
        >
          <span style={{ width: 24, height: 0.5, background: 'var(--red)' }} />
          The Press Office
          <span style={{ color: 'var(--ink-secondary)' }}>·</span>
          <span style={{ color: 'var(--ink-secondary)' }}>Private Files</span>
        </div>
        <h1
          className="font-serif"
          style={{
            fontSize: 'clamp(52px, 7vw, 88px)',
            fontWeight: 900,
            lineHeight: 0.95,
            letterSpacing: '-0.035em',
            color: 'var(--ink)',
            marginBottom: 8,
          }}
        >
          Settings,<span style={{ fontStyle: 'italic', color: 'var(--red)' }}> set quietly</span>.
        </h1>
        <p
          style={{
            fontFamily: 'var(--font-body)',
            fontSize: 15,
            lineHeight: 1.7,
            color: 'var(--ink-secondary)',
            maxWidth: 600,
            marginTop: 16,
            fontWeight: 300,
          }}
        >
          The way a paper runs is a series of small, steady choices — the typeface, the margin, the
          deadline. Your press office is the room where those choices are made. Every change is
          written straight to your file.
        </p>
      </header>

      <div style={{ height: 3, background: 'var(--ink)', marginBottom: 4 }} />
      <div style={{ height: 0.5, background: 'var(--border-color)', marginBottom: 48 }} />

      <div style={{ display: 'grid', gridTemplateColumns: '220px 1fr', gap: 72, alignItems: 'start' }}>
        {/* Table of contents */}
        <nav
          aria-label="Settings index"
          style={{
            position: 'sticky',
            top: 140,
            alignSelf: 'start',
            paddingRight: 16,
            borderRight: '0.5px solid var(--border-color)',
          }}
        >
          <div className="kicker" style={{ color: 'var(--red)', marginBottom: 16 }}>
            Index
          </div>
          <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: 2 }}>
            {sections.map((s) => {
              const isActive = active === s.key
              const Icon = s.icon
              return (
                <li key={s.key}>
                  <button
                    type="button"
                    onClick={() => scrollTo(s.key)}
                    style={{
                      width: '100%',
                      display: 'grid',
                      gridTemplateColumns: '28px 1fr',
                      alignItems: 'baseline',
                      gap: 10,
                      padding: '8px 0 8px 12px',
                      border: 'none',
                      background: 'transparent',
                      textAlign: 'left',
                      cursor: 'pointer',
                      color: isActive ? 'var(--red)' : 'var(--ink)',
                      borderLeft: isActive ? '2px solid var(--red)' : '2px solid transparent',
                      transition: 'color 180ms ease, border-color 180ms ease',
                    }}
                  >
                    <span className="numeral" style={{ fontSize: 12, fontWeight: 700, color: isActive ? 'var(--red)' : 'var(--ink-tertiary)' }}>
                      {s.num}
                    </span>
                    <span>
                      <span
                        className="font-serif"
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: 8,
                          fontSize: 16,
                          fontWeight: isActive ? 800 : 700,
                          fontStyle: isActive ? 'italic' : 'normal',
                          letterSpacing: '-0.01em',
                          lineHeight: 1.1,
                        }}
                      >
                        <Icon style={{ width: 12, height: 12, color: isActive ? 'var(--red)' : 'var(--ink-tertiary)', flexShrink: 0 }} />
                        {s.title}
                      </span>
                      <span
                        style={{
                          display: 'block',
                          fontSize: 10,
                          color: 'var(--ink-secondary)',
                          letterSpacing: '0.12em',
                          textTransform: 'uppercase',
                          marginTop: 3,
                          fontWeight: 500,
                        }}
                      >
                        {s.note}
                      </span>
                    </span>
                  </button>
                </li>
              )
            })}
          </ul>
        </nav>

        {/* Main column */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 72 }}>
          {/* ─── Identity ─────────────────────────────────────────── */}
          <Section
            refCb={(el) => (sectionRefs.current.identity = el)}
            kicker="Chapter I"
            title="Identity"
            subtitle="Your name on the masthead."
            icon={User}
          >
            <SettingRow
              label="Full name"
              hint="Shown on your dossiers, reports and saved filings."
              input={
                <Input
                  value={fullName}
                  onChange={setFullName}
                  placeholder="Your name in print"
                />
              }
            />
            <SettingRow
              label="Email"
              hint="Used for sign-in and editor notices. Private."
              input={<Input value={email} onChange={setEmail} type="email" />}
            />
            <SettingRow
              label="Handle"
              hint="Short signature for the sidebar and filings. Lowercase."
              input={
                <Input
                  value={handle}
                  onChange={(v) => setHandle(v.toLowerCase().replace(/\s+/g, ''))}
                  maxLength={64}
                />
              }
            />
            <RowActions
              dirty={identityDirty}
              saving={updateProfile.isPending}
              onSave={saveIdentity}
            />
          </Section>

          {/* ─── Preferences ──────────────────────────────────────── */}
          <Section
            refCb={(el) => (sectionRefs.current.preferences = el)}
            kicker="Chapter II"
            title="House preferences"
            subtitle="How the paper is set on your desk."
            icon={Bell}
          >
            <SettingRow
              label="Paper palette"
              hint="Editorial is fixed for now. Future issues may offer more."
              input={<Pills options={[{ id: 'editorial', label: 'Editorial · paper & ink' }]} value="editorial" onChange={() => {}} disabled />}
            />
            <SettingRow
              label="Reduced motion"
              hint="Quieter transitions, for desks that prefer still type."
              input={<Toggle on={reducedMotion} onChange={setReducedMotion} />}
            />
            <SettingRow
              label="Email notices"
              hint="A brief when a run returns, or the press catches fire."
              input={<Toggle on={emailNotices} onChange={setEmailNotices} />}
            />
            <SettingRow
              label="Weekly brief"
              hint="A short Sunday edition of what’s on your desk."
              input={<Toggle on={weeklyBrief} onChange={setWeeklyBrief} />}
            />
            <SettingRow
              label="Default units"
              hint="How currency and volume are printed across reports."
              input={
                <Pills
                  options={[...unitOptions]}
                  value={units}
                  onChange={(v) => setUnits(v as 'inr' | 'usd' | 'eur')}
                />
              }
            />
            <RowActions
              dirty={prefsDirty}
              saving={updateProfile.isPending}
              onSave={savePrefs}
            />
          </Section>

          {/* ─── Cast defaults ────────────────────────────────────── */}
          <Section
            refCb={(el) => (sectionRefs.current.cast = el)}
            kicker="Chapter III"
            title="Cast defaults"
            subtitle="How synthetic readers are drawn up when you file a new dossier."
            icon={Layers}
          >
            <SettingRow
              label="Default reader count"
              hint={`How many agents the press draws for a standard run. Capped at ${READER_MAX.toLocaleString()} to match the simulation ceiling.`}
              input={
                <NumberInput
                  value={readerCount}
                  onChange={setReaderCount}
                  min={READER_MIN}
                  max={READER_MAX}
                  step={500}
                  suffix="agents"
                />
              }
            />
            <SettingRow
              label="Default scenario"
              hint="Market posture used when you do not choose one."
              input={
                <Pills
                  options={[...scenarioOptions]}
                  value={scenario}
                  onChange={(v) => setScenario(v as typeof scenario)}
                />
              }
            />
            <SettingRow
              label="Average order value"
              hint="The default value used for new dossiers. Printed in your chosen units."
              input={
                <NumberInput
                  value={aov}
                  onChange={setAov}
                  min={0}
                  step={50}
                  suffix={units === 'inr' ? '₹' : units === 'usd' ? '$' : '€'}
                  prefix
                />
              }
            />
            <SettingRow
              label="Keep past results on file"
              hint="If off, each new run replaces the prior one."
              input={<Toggle on={keepResults} onChange={setKeepResults} />}
            />
            <RowActions
              dirty={castDirty}
              saving={updateProfile.isPending}
              onSave={saveCast}
            />
          </Section>

          {/* ─── Archive ──────────────────────────────────────────── */}
          <Section
            refCb={(el) => (sectionRefs.current.archive = el)}
            kicker="Chapter IV"
            title="Archive & data"
            subtitle="Your filings, in your hands."
            icon={Download}
          >
            <SettingRow
              label="Export archive"
              hint="A full folio of your dossiers and preferences as JSON, downloaded to this device."
              input={
                <button
                  className="btn-ghost"
                  type="button"
                  disabled={exportArchive.isPending}
                  onClick={async () => {
                    try {
                      await exportArchive.mutateAsync()
                      setFlash({ kind: 'ok', msg: 'Archive exported.' })
                    } catch (err) {
                      setFlash({ kind: 'err', msg: apiError(err) })
                    }
                  }}
                >
                  {exportArchive.isPending ? (
                    <><Loader2 className="animate-spin" style={{ width: 12, height: 12 }} /> Compiling…</>
                  ) : (
                    <><Download style={{ width: 13, height: 13 }} /> Export .json</>
                  )}
                </button>
              }
            />
            <SettingRow
              label="Change password"
              hint="Rotate your sign-in key. You stay signed in here."
              input={
                <button
                  className="btn-ghost"
                  type="button"
                  onClick={() => setPwOpen(true)}
                >
                  <KeyRound style={{ width: 13, height: 13 }} /> Change password
                </button>
              }
            />
            <SettingRow
              label="Sessions"
              hint="End your current sitting on this device."
              input={
                <button className="btn-ghost" type="button" onClick={() => logoutLocal()}>
                  <LogOut style={{ width: 13, height: 13 }} /> Sign out
                </button>
              }
            />
          </Section>

          {/* ─── Danger ──────────────────────────────────────────── */}
          <Section
            refCb={(el) => (sectionRefs.current.danger = el)}
            kicker="Chapter V"
            title="Errata column"
            subtitle="Decisions the typesetter cannot take back. Read twice."
            icon={AlertTriangle}
            red
          >
            <SettingRow
              label="Clear the archive"
              hint="Removes every dossier, proof and filing. Keeps your account."
              input={
                <button
                  type="button"
                  onClick={() => setClearOpen(true)}
                  className="btn-ghost"
                  style={{ borderColor: 'var(--red)', color: 'var(--red)' }}
                >
                  <Trash2 style={{ width: 13, height: 13 }} /> Clear filings
                </button>
              }
            />
            <SettingRow
              label="Close the press office"
              hint="Permanently deletes your account. There is no later issue."
              input={
                <button
                  type="button"
                  onClick={() => setNukeOpen(true)}
                  style={{
                    padding: '14px 22px',
                    background: 'var(--red)',
                    color: 'var(--paper)',
                    border: '0.5px solid var(--red)',
                    fontSize: 11,
                    fontWeight: 600,
                    letterSpacing: '0.2em',
                    textTransform: 'uppercase',
                    cursor: 'pointer',
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 8,
                  }}
                >
                  <AlertTriangle style={{ width: 13, height: 13 }} /> Delete account
                </button>
              }
            />
          </Section>
        </div>
      </div>

      {/* ── Password modal ── */}
      <AnimatePresence>
        {pwOpen && (
          <PasswordModal
            onClose={() => setPwOpen(false)}
            onSubmit={async (current, next) => {
              try {
                await changePass.mutateAsync({ current_password: current, new_password: next })
                setFlash({ kind: 'ok', msg: 'Password updated.' })
                setPwOpen(false)
              } catch (err) {
                throw new Error(apiError(err))
              }
            }}
          />
        )}
      </AnimatePresence>

      {/* ── Clear archive confirm ── */}
      <AnimatePresence>
        {clearOpen && (
          <ConfirmModal
            kicker="Errata · Clear filings"
            title="Clear every dossier."
            body="This removes every filing, proof and run from your archive. Your account and preferences stay. This cannot be undone."
            confirmWord="CLEAR"
            confirmLabel={clearArchive.isPending ? 'Clearing…' : 'Clear filings'}
            pending={clearArchive.isPending}
            onClose={() => setClearOpen(false)}
            onConfirm={async () => {
              try {
                const res = await clearArchive.mutateAsync()
                setFlash({ kind: 'ok', msg: res.message })
                setClearOpen(false)
              } catch (err) {
                setFlash({ kind: 'err', msg: apiError(err) })
              }
            }}
          />
        )}
      </AnimatePresence>

      {/* ── Delete account confirm ── */}
      <AnimatePresence>
        {nukeOpen && (
          <DeleteAccountModal
            onClose={() => setNukeOpen(false)}
            pending={deleteAccount.isPending}
            onConfirm={async (password) => {
              try {
                await deleteAccount.mutateAsync({ password })
                /* deleteAccount onSuccess logs out; no flash needed. */
              } catch (err) {
                throw new Error(apiError(err))
              }
            }}
          />
        )}
      </AnimatePresence>

      {/* ── Flash toast ── */}
      <AnimatePresence>
        {flash && (
          <motion.div
            key={flash.msg}
            role="status"
            aria-live="polite"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 8 }}
            transition={{ duration: 0.2 }}
            style={{
              position: 'fixed',
              bottom: 32,
              left: '50%',
              transform: 'translateX(-50%)',
              background: flash.kind === 'ok' ? 'var(--ink)' : 'var(--red)',
              color: 'var(--paper)',
              padding: '10px 18px',
              fontSize: 11,
              letterSpacing: '0.22em',
              textTransform: 'uppercase',
              fontWeight: 600,
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              zIndex: 120,
              boxShadow: '8px 8px 0 rgba(192,57,43,0.2)',
              maxWidth: 'min(520px, calc(100vw - 48px))',
            }}
          >
            {flash.kind === 'ok'
              ? <Check style={{ width: 13, height: 13, color: '#8bc8a2' }} />
              : <AlertTriangle style={{ width: 13, height: 13 }} />}
            <span style={{ whiteSpace: 'normal', lineHeight: 1.4, textTransform: 'none', letterSpacing: '0.02em', fontSize: 12, fontWeight: 500 }}>
              {flash.msg}
            </span>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

/* ── Section wrapper ─────────────────────────────────────────────── */
function Section({
  kicker, title, subtitle, icon: Icon, children, refCb, red,
}: {
  kicker: string
  title: string
  subtitle: string
  icon: React.ComponentType<{ style?: React.CSSProperties }>
  children: React.ReactNode
  refCb: (el: HTMLDivElement | null) => void
  red?: boolean
}) {
  return (
    <section ref={refCb} style={{ scrollMarginTop: 140 }}>
      <header style={{ marginBottom: 22 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
          <Icon style={{ width: 14, height: 14, color: 'var(--red)' }} />
          <span className="kicker" style={{ color: 'var(--red)' }}>{kicker}</span>
        </div>
        <h2
          className="font-serif"
          style={{
            fontSize: 'clamp(32px, 3.6vw, 46px)',
            fontWeight: 900,
            fontStyle: 'italic',
            lineHeight: 1,
            letterSpacing: '-0.03em',
            color: red ? 'var(--red)' : 'var(--ink)',
            marginBottom: 10,
          }}
        >
          {title}
        </h2>
        <p style={{ fontSize: 13.5, lineHeight: 1.65, color: 'var(--ink-secondary)', maxWidth: 560, fontWeight: 300 }}>
          {subtitle}
        </p>
        <div style={{ height: 2, background: red ? 'var(--red)' : 'var(--ink)', width: 56, marginTop: 14 }} />
      </header>
      <div
        style={{
          border: `0.5px solid ${red ? 'var(--red)' : 'var(--border-strong)'}`,
          background: red ? 'rgba(192,57,43,0.03)' : 'var(--paper)',
          padding: '8px 0',
        }}
      >
        {children}
      </div>
    </section>
  )
}

/* ── Row ─────────────────────────────────────────────────────────── */
function SettingRow({
  label, hint, input,
}: {
  label: string
  hint: string
  input: React.ReactNode
}) {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'minmax(0, 1.2fr) minmax(0, 1fr)',
        gap: 32,
        alignItems: 'center',
        padding: '22px 28px',
        borderBottom: '0.5px solid var(--border-color)',
      }}
    >
      <div>
        <div
          className="font-serif"
          style={{
            fontSize: 18,
            fontWeight: 700,
            letterSpacing: '-0.01em',
            color: 'var(--ink)',
            lineHeight: 1.2,
            marginBottom: 4,
          }}
        >
          {label}
        </div>
        <div
          style={{
            fontSize: 12.5,
            lineHeight: 1.55,
            color: 'var(--ink-secondary)',
            fontWeight: 300,
            maxWidth: 420,
          }}
        >
          {hint}
        </div>
      </div>
      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>{input}</div>
    </div>
  )
}

/* ── Row actions ─────────────────────────────────────────────── */
function RowActions({
  dirty,
  saving,
  onSave,
}: {
  dirty: boolean
  saving: boolean
  onSave: () => void
}) {
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'flex-end',
        alignItems: 'center',
        gap: 14,
        padding: '18px 28px',
      }}
    >
      <span
        className="kicker"
        style={{
          color: dirty ? 'var(--red)' : 'var(--ink-tertiary)',
          fontSize: 10,
        }}
      >
        {dirty ? 'Unsaved changes' : 'In type'}
      </span>
      <button
        type="button"
        className="btn-ink"
        disabled={saving || !dirty}
        onClick={onSave}
        style={{ opacity: !dirty && !saving ? 0.45 : 1 }}
      >
        {saving ? (
          <><Loader2 className="animate-spin" style={{ width: 12, height: 12 }} /> Setting type…</>
        ) : (
          'Set in type'
        )}
      </button>
    </div>
  )
}

/* ── Controlled input ────────────────────────────────────────── */
function Input({
  value, onChange, placeholder, type = 'text', maxLength,
}: {
  value: string
  onChange: (v: string) => void
  placeholder?: string
  type?: string
  maxLength?: number
}) {
  return (
    <input
      type={type}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      maxLength={maxLength}
      style={{
        width: 'min(360px, 100%)',
        padding: '12px 14px',
        border: '0.5px solid var(--border-strong)',
        background: 'var(--paper)',
        color: 'var(--ink)',
        fontFamily: 'var(--font-body)',
        fontSize: 14,
        outline: 'none',
        transition: 'border-color 150ms ease',
      }}
      onFocus={(e) => (e.currentTarget.style.borderColor = 'var(--ink)')}
      onBlur={(e) => (e.currentTarget.style.borderColor = 'var(--border-strong)')}
    />
  )
}

/* ── Number input with min/max/step ──────────────────────────── */
function NumberInput({
  value, onChange, min, max, step = 1, suffix, prefix,
}: {
  value: number
  onChange: (n: number) => void
  min?: number
  max?: number
  step?: number
  suffix?: string
  prefix?: boolean
}) {
  const display = Number.isFinite(value) ? value : 0
  return (
    <div
      style={{
        display: 'inline-flex',
        alignItems: 'stretch',
        border: '0.5px solid var(--border-strong)',
        background: 'var(--paper)',
      }}
    >
      {prefix && suffix && (
        <span
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            padding: '0 12px',
            fontFamily: 'var(--font-serif)',
            fontStyle: 'italic',
            fontSize: 14,
            color: 'var(--ink-secondary)',
            borderRight: '0.5px solid var(--border-color)',
          }}
        >
          {suffix}
        </span>
      )}
      <input
        type="number"
        value={display}
        min={min}
        max={max}
        step={step}
        onChange={(e) => {
          const n = Number(e.target.value)
          if (Number.isNaN(n)) return
          onChange(n)
        }}
        onBlur={(e) => {
          let n = Number(e.target.value)
          if (Number.isNaN(n)) n = min ?? 0
          if (min !== undefined) n = Math.max(min, n)
          if (max !== undefined) n = Math.min(max, n)
          onChange(n)
        }}
        style={{
          width: 140,
          padding: '12px 14px',
          border: 'none',
          background: 'transparent',
          color: 'var(--ink)',
          fontFamily: 'var(--font-body)',
          fontSize: 14,
          outline: 'none',
          textAlign: 'right',
        }}
      />
      {!prefix && suffix && (
        <span
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            padding: '0 12px',
            fontFamily: 'var(--font-body)',
            fontSize: 10,
            fontWeight: 600,
            letterSpacing: '0.18em',
            textTransform: 'uppercase',
            color: 'var(--ink-tertiary)',
            borderLeft: '0.5px solid var(--border-color)',
          }}
        >
          {suffix}
        </span>
      )}
    </div>
  )
}

/* ── Controlled toggle ───────────────────────────────────────── */
function Toggle({ on, onChange }: { on: boolean; onChange: (on: boolean) => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      onClick={() => onChange(!on)}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 0,
        border: '0.5px solid var(--ink)',
        background: 'var(--paper)',
        cursor: 'pointer',
        padding: 0,
        height: 36,
      }}
    >
      {(['ON', 'OFF'] as const).map((label) => {
        const isActive = (label === 'ON') === on
        return (
          <span
            key={label}
            style={{
              padding: '0 18px',
              height: '100%',
              display: 'inline-flex',
              alignItems: 'center',
              fontFamily: 'var(--font-body)',
              fontSize: 10,
              fontWeight: 700,
              letterSpacing: '0.26em',
              background: isActive ? 'var(--ink)' : 'transparent',
              color: isActive ? 'var(--paper)' : 'var(--ink-tertiary)',
              transition: 'background 160ms ease, color 160ms ease',
            }}
          >
            {label}
          </span>
        )
      })}
    </button>
  )
}

/* ── Controlled pills ────────────────────────────────────────── */
function Pills({
  options, value, onChange, disabled,
}: {
  options: { id: string; label: string }[]
  value: string
  onChange: (v: string) => void
  disabled?: boolean
}) {
  return (
    <div
      role="radiogroup"
      style={{
        display: 'inline-flex',
        flexWrap: 'wrap',
        gap: 0,
        border: '0.5px solid var(--ink)',
        opacity: disabled ? 0.55 : 1,
      }}
    >
      {options.map((o, i) => {
        const isActive = value === o.id
        return (
          <button
            key={o.id}
            type="button"
            role="radio"
            aria-checked={isActive}
            disabled={disabled}
            onClick={() => !disabled && onChange(o.id)}
            style={{
              padding: '10px 16px',
              border: 'none',
              borderRight: i < options.length - 1 ? '0.5px solid var(--border-color)' : 'none',
              background: isActive ? 'var(--ink)' : 'transparent',
              color: isActive ? 'var(--paper)' : 'var(--ink)',
              cursor: disabled ? 'not-allowed' : 'pointer',
              fontFamily: 'var(--font-body)',
              fontSize: 10,
              fontWeight: 600,
              letterSpacing: '0.2em',
              textTransform: 'uppercase',
              transition: 'background 160ms ease, color 160ms ease',
            }}
          >
            {o.label}
          </button>
        )
      })}
    </div>
  )
}

/* ── Modal shell (shared) ────────────────────────────────────── */
function Modal({
  onClose,
  children,
  width = 560,
}: {
  onClose: () => void
  children: React.ReactNode
  width?: number
}) {
  useEffect(() => {
    document.body.classList.add('modal-open')
    return () => {
      document.body.classList.remove('modal-open')
    }
  }, [])

  if (typeof document === 'undefined') return null

  return createPortal(
    <>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        onClick={onClose}
        style={{ position: 'fixed', inset: 0, background: 'rgba(26,23,20,0.12)', zIndex: 100 }}
      />
      <motion.div
        role="dialog"
        aria-modal="true"
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: 16 }}
        transition={{ duration: 0.3, ease: [0.2, 0.7, 0.2, 1] }}
        style={{
          position: 'fixed',
          inset: 0,
          zIndex: 101,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: 24,
          pointerEvents: 'none',
        }}
      >
        <div
          onClick={(e) => e.stopPropagation()}
          className="editorial-workspace"
          style={{
            width: `min(${width}px, 100%)`,
            maxHeight: 'calc(100vh - 48px)',
            background: 'var(--paper)',
            border: '0.5px solid var(--ink)',
            boxShadow: '24px 24px 0 rgba(26,23,20,0.12)',
            padding: '26px 32px 24px',
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden',
            pointerEvents: 'auto',
          }}
        >
          {children}
        </div>
      </motion.div>
    </>,
    document.body,
  )
}

/* ── Password modal ──────────────────────────────────────────── */
function PasswordModal({
  onClose,
  onSubmit,
}: {
  onClose: () => void
  onSubmit: (current: string, next: string) => Promise<void>
}) {
  const [current, setCurrent] = useState('')
  const [next, setNext]       = useState('')
  const [confirm, setConfirm] = useState('')
  const [err, setErr]         = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  const canSubmit = current && next.length >= 8 && next === confirm && !pending

  return (
    <Modal onClose={onClose} width={520}>
      <ModalHeader kicker="Archive · Sign-in key" onClose={onClose} />
      <h2
        className="font-serif"
        style={{
          fontSize: 'clamp(24px, 3vw, 34px)',
          fontWeight: 900,
          lineHeight: 1,
          letterSpacing: '-0.03em',
          color: 'var(--ink)',
          marginBottom: 10,
          marginTop: 16,
        }}
      >
        Change your<span style={{ fontStyle: 'italic', color: 'var(--red)' }}> password</span>.
      </h2>
      <p style={{ fontSize: 13.5, lineHeight: 1.65, color: 'var(--ink-secondary)', marginBottom: 20, fontWeight: 300 }}>
        Must be at least eight characters. The new key replaces the old one everywhere immediately.
      </p>

      <Field label="Current password">
        <RawInput type="password" value={current} onChange={setCurrent} autoFocus />
      </Field>
      <Field label="New password">
        <RawInput type="password" value={next} onChange={setNext} />
      </Field>
      <Field label="Confirm new password">
        <RawInput type="password" value={confirm} onChange={setConfirm} />
      </Field>

      {err && (
        <div style={{ color: 'var(--red)', fontSize: 12, marginTop: 6, marginBottom: 4 }}>
          {err}
        </div>
      )}

      <ModalFooter
        meta={next && confirm && next !== confirm ? 'Passwords do not match' : next && next.length < 8 ? 'Too short' : ''}
        left={<button className="btn-ghost" type="button" onClick={onClose}>Close</button>}
        right={
          <button
            className="btn-ink"
            type="button"
            disabled={!canSubmit}
            onClick={async () => {
              setErr(null)
              setPending(true)
              try {
                await onSubmit(current, next)
              } catch (e) {
                setErr((e as Error).message)
              } finally {
                setPending(false)
              }
            }}
          >
            {pending ? <><Loader2 className="animate-spin" style={{ width: 12, height: 12 }} /> Updating…</> : 'Update password'}
          </button>
        }
      />
    </Modal>
  )
}

/* ── Confirm (type-to-confirm) modal ─────────────────────────── */
function ConfirmModal({
  kicker, title, body, confirmWord, confirmLabel, pending, onClose, onConfirm,
}: {
  kicker: string
  title: string
  body: string
  confirmWord: string
  confirmLabel: string
  pending: boolean
  onClose: () => void
  onConfirm: () => void
}) {
  const [typed, setTyped] = useState('')
  const matches = typed.trim().toUpperCase() === confirmWord

  return (
    <Modal onClose={onClose} width={520}>
      <ModalHeader kicker={kicker} onClose={onClose} red />
      <h2
        className="font-serif"
        style={{
          fontSize: 'clamp(24px, 3vw, 34px)',
          fontWeight: 900,
          fontStyle: 'italic',
          lineHeight: 1,
          letterSpacing: '-0.03em',
          color: 'var(--red)',
          marginBottom: 10,
          marginTop: 16,
        }}
      >
        {title}
      </h2>
      <p style={{ fontSize: 13.5, lineHeight: 1.65, color: 'var(--ink-secondary)', marginBottom: 20, fontWeight: 300 }}>
        {body}
      </p>

      <Field label={`Type ${confirmWord} to confirm`}>
        <RawInput value={typed} onChange={setTyped} />
      </Field>

      <ModalFooter
        meta=""
        left={<button className="btn-ghost" type="button" onClick={onClose}>Withdraw</button>}
        right={
          <button
            type="button"
            disabled={!matches || pending}
            onClick={onConfirm}
            style={{
              padding: '14px 22px',
              background: matches && !pending ? 'var(--red)' : 'rgba(192,57,43,0.45)',
              color: 'var(--paper)',
              border: '0.5px solid var(--red)',
              fontSize: 11,
              fontWeight: 600,
              letterSpacing: '0.2em',
              textTransform: 'uppercase',
              cursor: matches && !pending ? 'pointer' : 'not-allowed',
              display: 'inline-flex',
              alignItems: 'center',
              gap: 8,
            }}
          >
            {pending ? <><Loader2 className="animate-spin" style={{ width: 12, height: 12 }} /> {confirmLabel}</> : confirmLabel}
          </button>
        }
      />
    </Modal>
  )
}

/* ── Delete-account modal (password-gated) ───────────────────── */
function DeleteAccountModal({
  onClose, pending, onConfirm,
}: {
  onClose: () => void
  pending: boolean
  onConfirm: (password: string) => Promise<void>
}) {
  const [typed, setTyped]       = useState('')
  const [password, setPassword] = useState('')
  const [err, setErr]           = useState<string | null>(null)
  const [localPending, setLocalPending] = useState(false)
  const matches = typed.trim().toUpperCase() === 'DELETE'
  const canSubmit = matches && password.length > 0 && !pending && !localPending

  return (
    <Modal onClose={onClose} width={560}>
      <ModalHeader kicker="Errata · Close press office" onClose={onClose} red />
      <h2
        className="font-serif"
        style={{
          fontSize: 'clamp(26px, 3.2vw, 38px)',
          fontWeight: 900,
          fontStyle: 'italic',
          lineHeight: 1,
          letterSpacing: '-0.03em',
          color: 'var(--red)',
          marginBottom: 10,
          marginTop: 16,
        }}
      >
        This cannot be undone.
      </h2>
      <p style={{ fontSize: 13.5, lineHeight: 1.65, color: 'var(--ink-secondary)', marginBottom: 20, fontWeight: 300 }}>
        Your account, every dossier you have filed, every proof, and every filing will be deleted
        from the archive permanently. There is no later issue.
      </p>

      <Field label="Type DELETE to confirm">
        <RawInput value={typed} onChange={setTyped} />
      </Field>
      <Field label="Confirm with your password">
        <RawInput type="password" value={password} onChange={setPassword} />
      </Field>

      {err && (
        <div style={{ color: 'var(--red)', fontSize: 12, marginTop: 6, marginBottom: 4 }}>
          {err}
        </div>
      )}

      <ModalFooter
        meta=""
        left={<button className="btn-ghost" type="button" onClick={onClose}>Withdraw</button>}
        right={
          <button
            type="button"
            disabled={!canSubmit}
            onClick={async () => {
              setErr(null)
              setLocalPending(true)
              try {
                await onConfirm(password)
              } catch (e) {
                setErr((e as Error).message)
              } finally {
                setLocalPending(false)
              }
            }}
            style={{
              padding: '14px 22px',
              background: canSubmit ? 'var(--red)' : 'rgba(192,57,43,0.45)',
              color: 'var(--paper)',
              border: '0.5px solid var(--red)',
              fontSize: 11,
              fontWeight: 600,
              letterSpacing: '0.2em',
              textTransform: 'uppercase',
              cursor: canSubmit ? 'pointer' : 'not-allowed',
              display: 'inline-flex',
              alignItems: 'center',
              gap: 8,
            }}
          >
            {pending || localPending
              ? <><Loader2 className="animate-spin" style={{ width: 12, height: 12 }} /> Closing…</>
              : <><AlertTriangle style={{ width: 13, height: 13 }} /> Delete forever</>}
          </button>
        }
      />
    </Modal>
  )
}

/* ── Modal primitives ────────────────────────────────────────── */
function ModalHeader({
  kicker, onClose, red,
}: {
  kicker: string
  onClose: () => void
  red?: boolean
}) {
  return (
    <>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          paddingBottom: 12,
          borderBottom: `2px solid ${red ? 'var(--red)' : 'var(--ink)'}`,
        }}
      >
        <div className="kicker" style={{ color: red ? 'var(--red)' : 'var(--red)' }}>
          {kicker}
        </div>
        <button
          onClick={onClose}
          aria-label="Close"
          type="button"
          style={{
            width: 28,
            height: 28,
            border: '0.5px solid var(--border-strong)',
            background: 'transparent',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: 'var(--ink)',
          }}
        >
          <X style={{ width: 14, height: 14 }} />
        </button>
      </div>
      <div style={{ height: 0.5, background: 'var(--border-color)', marginTop: 6 }} />
    </>
  )
}

function ModalFooter({
  meta, left, right,
}: {
  meta: string
  left: React.ReactNode
  right: React.ReactNode
}) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        marginTop: 20,
        gap: 12,
      }}
    >
      <div
        style={{
          fontSize: 10,
          letterSpacing: '0.22em',
          textTransform: 'uppercase',
          color: 'var(--ink-tertiary)',
          fontWeight: 500,
        }}
      >
        {meta}
      </div>
      <div style={{ display: 'flex', gap: 12 }}>
        {left}
        {right}
      </div>
    </div>
  )
}

function Field({
  label, children,
}: {
  label: string
  children: React.ReactNode
}) {
  return (
    <div style={{ marginBottom: 14 }}>
      <label
        className="kicker"
        style={{ color: 'var(--ink-secondary)', display: 'block', marginBottom: 6 }}
      >
        {label}
      </label>
      {children}
    </div>
  )
}

function RawInput({
  value, onChange, type = 'text', autoFocus,
}: {
  value: string
  onChange: (v: string) => void
  type?: string
  autoFocus?: boolean
}) {
  return (
    <input
      type={type}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      autoFocus={autoFocus}
      style={{
        width: '100%',
        padding: '12px 14px',
        border: '0.5px solid var(--border-strong)',
        background: 'var(--paper)',
        color: 'var(--ink)',
        fontFamily: 'var(--font-body)',
        fontSize: 14,
        outline: 'none',
        transition: 'border-color 150ms ease',
      }}
      onFocus={(e) => (e.currentTarget.style.borderColor = 'var(--ink)')}
      onBlur={(e) => (e.currentTarget.style.borderColor = 'var(--border-strong)')}
    />
  )
}
