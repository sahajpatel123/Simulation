'use client'

import { useEffect, useRef, useState } from 'react'
import { AlertTriangle, Bell, Check, Download, KeyRound, Layers, Loader2, LogOut, Trash2, User } from 'lucide-react'

import { useLogout } from '@/hooks/useAuth'
import { useAuthStore } from '@/store/auth.store'

type SectionKey = 'identity' | 'preferences' | 'cast' | 'archive' | 'danger'

const sections: { key: SectionKey; num: string; title: string; note: string; icon: React.ComponentType<{ style?: React.CSSProperties }> }[] = [
  { key: 'identity',    num: 'I',   title: 'Identity',        note: 'Your name on the masthead',             icon: User },
  { key: 'preferences', num: 'II',  title: 'House preferences', note: 'How the paper is set on your desk',    icon: Bell },
  { key: 'cast',        num: 'III', title: 'Cast defaults',    note: 'How synthetic readers are drawn up',   icon: Layers },
  { key: 'archive',     num: 'IV',  title: 'Archive & data',   note: 'Your filings, in your hands',          icon: Download },
  { key: 'danger',      num: 'V',   title: 'Errata column',    note: 'Things that cannot be undone',          icon: AlertTriangle },
]

export default function SettingsPage() {
  const user = useAuthStore((s) => s.user)
  const logout = useLogout()
  const [active, setActive] = useState<SectionKey>('identity')
  const [toast, setToast] = useState<string | null>(null)

  const sectionRefs = useRef<Record<SectionKey, HTMLDivElement | null>>({
    identity: null,
    preferences: null,
    cast: null,
    archive: null,
    danger: null,
  })

  const scrollTo = (key: SectionKey) => {
    setActive(key)
    const el = sectionRefs.current[key]
    if (el) {
      const y = el.getBoundingClientRect().top + window.scrollY - 140
      window.scrollTo({ top: y, behavior: 'smooth' })
    }
  }

  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(null), 2400)
    return () => clearTimeout(t)
  }, [toast])

  const flash = (msg: string) => setToast(msg)

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
          deadline. Your press office is the room where those choices are made.
        </p>
      </header>

      <div style={{ height: 3, background: 'var(--ink)', marginBottom: 4 }} />
      <div style={{ height: 0.5, background: 'var(--border-color)', marginBottom: 48 }} />

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '220px 1fr',
          gap: 72,
          alignItems: 'start',
        }}
      >
        {/* Table of contents — sticky side index */}
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
              input={<Input defaultValue={user?.full_name || ''} placeholder="Your name in print" />}
            />
            <SettingRow
              label="Email"
              hint="Used for sign-in and editor notices. Private."
              input={<Input defaultValue={user?.email || ''} type="email" />}
            />
            <SettingRow
              label="Handle"
              hint="Short signature for the sidebar and filings. Lowercase."
              input={<Input defaultValue={(user?.email || '').split('@')[0]} />}
            />
            <RowActions onSave={() => flash('Identity updated.')} />
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
              input={<Pills options={[{ id: 'editorial', label: 'Editorial · paper & ink' }]} value="editorial" />}
            />
            <SettingRow
              label="Reduced motion"
              hint="Quieter transitions, for desks that prefer still type."
              input={<Toggle defaultOn={false} />}
            />
            <SettingRow
              label="Email notices"
              hint="A brief when a run returns, or the press catches fire."
              input={<Toggle defaultOn={true} />}
            />
            <SettingRow
              label="Weekly brief"
              hint="A short Sunday edition of what’s on your desk."
              input={<Toggle defaultOn={false} />}
            />
            <SettingRow
              label="Default units"
              hint="How currency and volume are printed across reports."
              input={
                <Pills
                  options={[
                    { id: 'inr', label: '₹ INR' },
                    { id: 'usd', label: '$ USD' },
                    { id: 'eur', label: '€ EUR' },
                  ]}
                  value="inr"
                />
              }
            />
            <RowActions onSave={() => flash('Preferences saved.')} />
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
              hint="How many agents the press draws for a standard run."
              input={<Input defaultValue="10,000" />}
            />
            <SettingRow
              label="Default scenario"
              hint="Market posture used when you do not choose one."
              input={
                <Pills
                  options={[
                    { id: 'base',       label: 'Base case' },
                    { id: 'recession',  label: 'Recession' },
                    { id: 'viral',      label: 'Viral moment' },
                    { id: 'competitor', label: 'Competitor entry' },
                  ]}
                  value="base"
                />
              }
            />
            <SettingRow
              label="Average order value"
              hint="The default ₹ value used for new dossiers."
              input={<Input defaultValue="1,000" />}
            />
            <SettingRow
              label="Keep past results on file"
              hint="If off, each new run replaces the prior one."
              input={<Toggle defaultOn={true} />}
            />
            <RowActions onSave={() => flash('Cast defaults set.')} />
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
              hint="A full folio of your dossiers, proofs and filings as JSON."
              input={
                <button className="btn-ghost" type="button" onClick={() => flash('Export sent to your email.')}>
                  <Download style={{ width: 13, height: 13 }} /> Export .json
                </button>
              }
            />
            <SettingRow
              label="Download proofs (PDF)"
              hint="Every completed report, typeset for printing."
              input={
                <button className="btn-ghost" type="button" onClick={() => flash('Proof folio queued.')}>
                  <Download style={{ width: 13, height: 13 }} /> Compile folio
                </button>
              }
            />
            <SettingRow
              label="Change password"
              hint="Rotate your sign-in key. You’ll be asked to sign in again."
              input={
                <button className="btn-ghost" type="button" onClick={() => flash('Password mail dispatched.')}>
                  <KeyRound style={{ width: 13, height: 13 }} /> Send reset link
                </button>
              }
            />
            <SettingRow
              label="Sessions"
              hint="End all active sittings on other devices."
              input={
                <button className="btn-ghost" type="button" onClick={() => logout()}>
                  <LogOut style={{ width: 13, height: 13 }} /> Sign out everywhere
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
                  onClick={() => flash('Archive clear cancelled — require confirm in production.')}
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
                  onClick={() => flash('Account deletion cancelled — require confirm in production.')}
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

      {/* Toast */}
      {toast && (
        <div
          role="status"
          aria-live="polite"
          style={{
            position: 'fixed',
            bottom: 32,
            left: '50%',
            transform: 'translateX(-50%)',
            background: 'var(--ink)',
            color: 'var(--paper)',
            padding: '10px 18px',
            fontSize: 11,
            letterSpacing: '0.22em',
            textTransform: 'uppercase',
            fontWeight: 600,
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            zIndex: 50,
            boxShadow: '8px 8px 0 rgba(192,57,43,0.2)',
          }}
        >
          <Check style={{ width: 13, height: 13, color: '#8bc8a2' }} />
          {toast}
        </div>
      )}
    </div>
  )
}

/* ── Section wrapper ─────────────────────────────────────────────── */
function Section({
  kicker,
  title,
  subtitle,
  icon: Icon,
  children,
  refCb,
  red,
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
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 12,
            marginBottom: 12,
          }}
        >
          <Icon style={{ width: 14, height: 14, color: 'var(--red)' }} />
          <span className="kicker" style={{ color: 'var(--red)' }}>
            {kicker}
          </span>
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
        <p
          style={{
            fontSize: 13.5,
            lineHeight: 1.65,
            color: 'var(--ink-secondary)',
            maxWidth: 560,
            fontWeight: 300,
          }}
        >
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
  label,
  hint,
  input,
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
      className="setting-row"
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

/* ── Row actions (Save) ──────────────────────────────────────────── */
function RowActions({ onSave }: { onSave: () => void }) {
  const [saving, setSaving] = useState(false)
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'flex-end',
        padding: '18px 28px',
      }}
    >
      <button
        type="button"
        className="btn-ink"
        disabled={saving}
        onClick={async () => {
          setSaving(true)
          await new Promise((r) => setTimeout(r, 500))
          setSaving(false)
          onSave()
        }}
      >
        {saving ? (
          <>
            <Loader2 className="animate-spin" style={{ width: 12, height: 12 }} /> Setting type…
          </>
        ) : (
          'Set in type'
        )}
      </button>
    </div>
  )
}

/* ── Input ───────────────────────────────────────────────────────── */
function Input({
  defaultValue = '',
  placeholder,
  type = 'text',
}: {
  defaultValue?: string
  placeholder?: string
  type?: string
}) {
  const [v, setV] = useState(defaultValue)
  return (
    <input
      type={type}
      value={v}
      onChange={(e) => setV(e.target.value)}
      placeholder={placeholder}
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

/* ── Toggle (editorial, square, letterpress) ─────────────────────── */
function Toggle({ defaultOn }: { defaultOn: boolean }) {
  const [on, setOn] = useState(defaultOn)
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      onClick={() => setOn((v) => !v)}
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

/* ── Pills (segmented, editorial) ────────────────────────────────── */
function Pills({
  options,
  value,
}: {
  options: { id: string; label: string }[]
  value: string
}) {
  const [v, setV] = useState(value)
  return (
    <div
      role="radiogroup"
      style={{
        display: 'inline-flex',
        flexWrap: 'wrap',
        gap: 0,
        border: '0.5px solid var(--ink)',
      }}
    >
      {options.map((o, i) => {
        const isActive = v === o.id
        return (
          <button
            key={o.id}
            type="button"
            role="radio"
            aria-checked={isActive}
            onClick={() => setV(o.id)}
            style={{
              padding: '10px 16px',
              border: 'none',
              borderRight: i < options.length - 1 ? '0.5px solid var(--border-color)' : 'none',
              background: isActive ? 'var(--ink)' : 'transparent',
              color: isActive ? 'var(--paper)' : 'var(--ink)',
              cursor: 'pointer',
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
