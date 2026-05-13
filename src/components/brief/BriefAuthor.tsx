'use client'

import { useState, useEffect, useCallback } from 'react'
import { useRouter } from 'next/navigation'

import { useBrief, useBriefAssist, useSaveBrief } from '@/hooks/useProjects'

type Variant = 'software' | 'hardware'
type FieldName = 'positioning' | 'features' | 'hook'

interface BriefCopy {
  topLabel: string
  pageTitle: string
  pageSubtitle: string
  positioningLabel: string
  positioningHint: string
  positioningPlaceholder: string
  featuresLabel: string
  featuresHint: string
  featuresPlaceholder: string
  hookLabel: string
  hookHint: string
  hookPlaceholder: string
  ctaReady: string
  ctaNotReady: string
}

const COPY: Record<Variant, BriefCopy> = {
  software: {
    topLabel: 'GALLEY PROOF · THE BRIEF · SOFTWARE FOLIO',
    pageTitle: 'The Brief',
    pageSubtitle: 'Three commitments before the readers begin.',
    positioningLabel: 'POSITIONING',
    positioningHint: 'Who installs this and who pays. One sentence.',
    positioningPlaceholder: 'A scheduling tool for solo therapists who hate paperwork.',
    featuresLabel: 'THREE KILLER FEATURES',
    featuresHint: 'Ranked from most to least defining.',
    featuresPlaceholder: 'e.g. Auto-generated SOAP notes',
    hookLabel: 'THE HOOK',
    hookHint: 'The headline on your landing page. 6–12 words.',
    hookPlaceholder: 'Spend Friday with patients, not paperwork.',
    ctaReady: 'FILE THE BRIEF · BEGIN READING',
    ctaNotReady: 'COMPLETE ALL FIELDS TO CONTINUE',
  },
  hardware: {
    topLabel: 'GALLEY PROOF · THE BRIEF · HARDWARE ATELIER',
    pageTitle: 'The Brief',
    pageSubtitle: 'Three commitments before the readers begin.',
    positioningLabel: 'POSITIONING',
    positioningHint: 'Who builds with this and who uses it. One sentence.',
    positioningPlaceholder: 'A modular workstation for traveling makers.',
    featuresLabel: 'THREE DEFINING SPECIFICATIONS',
    featuresHint: 'Ranked from most to least defining.',
    featuresPlaceholder: 'e.g. Tool-less component swap',
    hookLabel: 'THE HOOK',
    hookHint: 'The line on the back of the box. 6–12 words.',
    hookPlaceholder: 'Pack the shop. Unpack the workshop.',
    ctaReady: 'FILE THE BRIEF · BEGIN READING',
    ctaNotReady: 'COMPLETE ALL FIELDS TO CONTINUE',
  },
}

/* ─── Inline styles for reused patterns ──────────────────── */

const s = {
  mono: 'var(--font-mono), monospace',
  serif: 'var(--font-serif), serif',
  red: '#c0392b',
  ink: '#1a1a1a',
  mute: '#888',
  cream: '#f5f0e8',
}

/* ─── Loading ellipsis animation ─────────────────────────── */

function LoadingDots() {
  return (
    <span style={{ display: 'inline-flex', gap: 2, verticalAlign: 'middle' }}>
      <span style={{
        width: 4, height: 4, borderRadius: '50%', background: s.red, display: 'inline-block',
        animation: 'blink 1.2s ease-in-out infinite',
      }} />
      <span style={{
        width: 4, height: 4, borderRadius: '50%', background: s.red, display: 'inline-block',
        animation: 'blink 1.2s ease-in-out infinite',
        animationDelay: '0.2s',
      }} />
      <span style={{
        width: 4, height: 4, borderRadius: '50%', background: s.red, display: 'inline-block',
        animation: 'blink 1.2s ease-in-out infinite',
        animationDelay: '0.4s',
      }} />
    </span>
  )
}

/* ─── Editor loading panel (replaces field while waiting) ── */

function EditorLoading() {
  return (
    <div style={{
      marginTop: 18, padding: 24, border: '0.5px solid #c0392b', opacity: 0,
      animation: 'fadeSlideIn 0.35s ease-out forwards',
    }}>
      <div style={{
        fontFamily: s.mono, fontSize: 9, letterSpacing: '0.22em', color: s.red, marginBottom: 14,
      }}>
        THE EDITOR IS READING <LoadingDots />
      </div>
      <div style={{
        width: '60%', height: 10, background: 'rgba(192,57,43,0.06)', borderRadius: 2,
        marginBottom: 8, animation: 'pulseWidth 1.8s ease-in-out infinite',
      }} />
      <div style={{
        width: '40%', height: 10, background: 'rgba(192,57,43,0.04)', borderRadius: 2,
        animation: 'pulseWidth 1.8s ease-in-out infinite',
        animationDelay: '0.3s',
      }} />
    </div>
  )
}

/* ─── Single GET HELP dropdown (top-right, by page title) ── */

function HelpDropdown({
  open, onToggle, onAssist, disabled, activeField,
}: {
  open: boolean
  onToggle: () => void
  onAssist: (field: FieldName, mode: 'refine' | 'suggest' | 'critique') => void
  disabled?: boolean
  activeField?: FieldName | null
}) {
  const items: { field: FieldName; label: string; modes: { k: 'refine' | 'suggest' | 'critique'; t: string }[] }[] = [
    { field: 'positioning', label: 'Positioning', modes: [
      { k: 'refine', t: 'Refine' }, { k: 'suggest', t: 'Suggest' }, { k: 'critique', t: 'Critique' },
    ]},
    { field: 'features', label: 'Features', modes: [
      { k: 'suggest', t: 'Suggest' }, { k: 'refine', t: 'Refine' }, { k: 'critique', t: 'Critique' },
    ]},
    { field: 'hook', label: 'Hook', modes: [
      { k: 'refine', t: 'Refine' }, { k: 'suggest', t: 'Suggest' }, { k: 'critique', t: 'Critique' },
    ]},
  ]

  return (
    <div style={{ position: 'relative' }}>
      <button onClick={onToggle} disabled={disabled}
        style={{
          background: open ? s.ink : 'transparent',
          color: open ? s.cream : s.ink,
          border: '0.5px solid #1a1a1a',
          padding: '8px 18px', fontFamily: s.mono, fontSize: 10,
          letterSpacing: '0.22em', cursor: disabled ? 'not-allowed' : 'pointer',
          opacity: disabled ? 0.4 : 1, transition: 'all 0.2s ease',
        }}
        onMouseEnter={(e) => { if (!open && !disabled) e.currentTarget.style.background = 'rgba(26,26,26,0.04)' }}
        onMouseLeave={(e) => { if (!open && !disabled) e.currentTarget.style.background = 'transparent' }}
      >
        {disabled ? 'EDITING\u00A0\u00A0\u2022\u2022\u2022' : `GET HELP ${open ? '\u25B4' : '\u25BE'}`}
      </button>
      {open && !disabled && (
        <div style={{
          position: 'absolute', top: 'calc(100% + 6px)', right: 0,
          background: s.cream, border: '0.5px solid #1a1a1a', zIndex: 10,
          minWidth: 280, boxShadow: '0 8px 24px rgba(0,0,0,0.10)',
          opacity: 0, animation: 'fadeSlideIn 0.2s ease-out forwards',
        }}>
          {items.map((group, gi) => (
            <div key={group.field}>
              {gi > 0 && <div style={{ height: 1, background: '#e8e3d8', margin: '4px 12px' }} />}
              <div style={{ padding: '8px 12px 4px', fontFamily: s.mono, fontSize: 8, letterSpacing: '0.24em', color: s.mute }}>
                {group.label}
              </div>
              <div style={{ display: 'flex', gap: 0 }}>
                {group.modes.map((mode) => (
                  <button key={mode.k} onClick={() => { onAssist(group.field, mode.k); onToggle(); }}
                    style={{
                      flex: 1, padding: '8px 4px', background: 'transparent', border: 'none',
                      fontFamily: s.mono, fontSize: 9, letterSpacing: '0.16em',
                      color: s.ink, cursor: 'pointer', textAlign: 'center',
                      opacity: activeField === group.field ? 0.3 : 1,
                      transition: 'background 0.12s ease',
                    }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = 'rgba(192,57,43,0.05)')}
                    onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                  >
                    {mode.t}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function HelpResultPanel({
  result, onClose, onApply,
}: {
  result: { mode: string; result: string | string[] }
  onClose: () => void
  onApply: (value: string) => void
}) {
  return (
    <div style={{
      marginTop: 18, padding: 18, background: 'rgba(192,57,43,0.04)',
      border: '0.5px solid #c0392b',
      opacity: 0, animation: 'fadeSlideIn 0.35s ease-out forwards',
    }}>
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12,
      }}>
        <span style={{
          fontFamily: s.mono, fontSize: 9, letterSpacing: '0.22em', color: s.red,
        }}>
          EDITOR&apos;S {result.mode.toUpperCase()}
        </span>
        <button onClick={onClose} style={{
          background: 'transparent', border: 'none', cursor: 'pointer',
          fontFamily: s.mono, fontSize: 9, letterSpacing: '0.20em', color: s.mute,
        }}>DISMISS</button>
      </div>
      {Array.isArray(result.result) ? (
        <div>
          {result.result.map((opt, i, arr) => (
            <div key={i} style={{
              paddingBottom: 12, marginBottom: 12,
              borderBottom: i < arr.length - 1 ? '0.5px solid rgba(0,0,0,0.07)' : 'none',
              display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 16,
              opacity: 0, animation: 'fadeSlideIn 0.3s ease-out forwards',
              animationDelay: `${i * 0.12}s`,
            }}>
              <span style={{
                fontFamily: s.serif, fontSize: 17, color: s.ink, lineHeight: 1.5,
              }}>{opt}</span>
              <button onClick={() => onApply(opt)} style={{
                background: s.ink, color: s.cream, border: 'none',
                padding: '6px 12px', fontFamily: s.mono, fontSize: 9,
                letterSpacing: '0.18em', cursor: 'pointer', flexShrink: 0,
                transition: 'opacity 0.15s ease',
              }}
                onMouseEnter={(e) => (e.currentTarget.style.opacity = '0.8')}
                onMouseLeave={(e) => (e.currentTarget.style.opacity = '1')}
              >
                USE THIS
              </button>
            </div>
          ))}
        </div>
      ) : (
        <div style={{
          fontFamily: s.serif, fontSize: 16, color: s.ink, lineHeight: 1.55, whiteSpace: 'pre-wrap',
        }}>{result.result}</div>
      )}
      {!Array.isArray(result.result) && (
        <button onClick={() => onApply(result.result as string)} style={{
          marginTop: 14, background: s.ink, color: s.cream, border: 'none',
          padding: '8px 16px', fontFamily: s.mono, fontSize: 9,
          letterSpacing: '0.20em', cursor: 'pointer',
          transition: 'opacity 0.15s ease',
        }}
          onMouseEnter={(e) => (e.currentTarget.style.opacity = '0.8')}
          onMouseLeave={(e) => (e.currentTarget.style.opacity = '1')}
        >
          APPLY THIS VERSION
        </button>
      )}
    </div>
  )
}

/* ─── Brief field wrapper ────────────────────────────────── */

function BriefField({
  label, hint, placeholder, value, onChange, multiline,
  helpResult, onApplySuggestion, onClearResult,
  isWaiting, isFieldLoading,
}: {
  label: string
  hint: string
  placeholder: string
  value: string
  onChange: (v: string) => void
  multiline?: boolean
  helpResult: { mode: string; result: string | string[] } | null
  onApplySuggestion: (v: string) => void
  onClearResult: () => void
  isWaiting: boolean
  isFieldLoading: boolean
}) {
  return (
    <div style={{ marginBottom: 56 }}>
      <div style={{
        fontFamily: s.mono, fontSize: 10, letterSpacing: '0.22em', color: s.ink, marginBottom: 6,
      }}>{label}</div>
      <div style={{
        fontFamily: s.serif, fontStyle: 'italic', fontSize: 14, color: s.mute, marginBottom: 16,
      }}>{hint}</div>
      {isFieldLoading ? (
        <EditorLoading />
      ) : (
        <>
          {multiline ? (
            <textarea value={value} onChange={(e) => onChange(e.target.value)}
              placeholder={placeholder} rows={2}
              style={{
                width: '100%', background: 'transparent', border: 'none',
                borderBottom: '0.5px solid #1a1a1a',
                fontFamily: s.serif, fontSize: 22, color: s.ink,
                padding: '8px 0', outline: 'none', resize: 'none',
                boxSizing: 'border-box',
                opacity: isWaiting ? 0.4 : 1,
                transition: 'opacity 0.2s ease',
              }} />
          ) : (
            <input value={value} onChange={(e) => onChange(e.target.value)}
              placeholder={placeholder}
              style={{
                width: '100%', background: 'transparent', border: 'none',
                borderBottom: '0.5px solid #1a1a1a',
                fontFamily: s.serif, fontSize: 22, color: s.ink,
                padding: '8px 0', outline: 'none', boxSizing: 'border-box',
                opacity: isWaiting ? 0.4 : 1,
                transition: 'opacity 0.2s ease',
              }} />
          )}
          {helpResult && (
            <HelpResultPanel result={helpResult} onClose={onClearResult} onApply={onApplySuggestion} />
          )}
        </>
      )}
    </div>
  )
}

/* ─── Main component ────────────────────────────────────── */

interface BriefAuthorProps {
  projectId: string | number
  variant: Variant
  dossierTitle: string
}

export default function BriefAuthor({ projectId, variant, dossierTitle }: BriefAuthorProps) {
  const copy = COPY[variant]
  const router = useRouter()
  const { data: brief } = useBrief(projectId)
  const saveBrief = useSaveBrief(projectId)
  const assistBrief = useBriefAssist(projectId)

  const [positioning, setPositioning] = useState('')
  const [features, setFeatures] = useState<string[]>(['', '', ''])
  const [hook, setHook] = useState('')
  const [helpOpen, setHelpOpen] = useState(false)
  const [activeField, setActiveField] = useState<FieldName | null>(null)
  const [helpResult, setHelpResult] = useState<{
    field: FieldName
    mode: 'refine' | 'suggest' | 'critique'
    result: string | string[]
  } | null>(null)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  useEffect(() => {
    if (brief) {
      setPositioning(brief.positioning || '')
      const f = brief.features || []
      setFeatures([f[0] || '', f[1] || '', f[2] || ''])
      setHook(brief.hook || '')
    }
  }, [brief])

  const isComplete = positioning.trim() && features.filter((f) => f.trim()).length >= 1 && hook.trim()
  const isWaiting = saveBrief.isPending || assistBrief.isPending

  const handleSave = async (markComplete: boolean) => {
    setErrorMsg(null)
    try {
      await saveBrief.mutateAsync({
        positioning, features: features.filter((f) => f.trim()), hook,
        mark_complete: markComplete,
      })
      if (markComplete) router.push(`/project/${projectId}`)
    } catch {
      setErrorMsg('Failed to save. Check your connection and try again.')
    }
  }

  const handleAssist = useCallback(async (field: FieldName, mode: 'refine' | 'suggest' | 'critique') => {
    let current_value = ''
    if (field === 'positioning') current_value = positioning
    if (field === 'hook') current_value = hook
    if (field === 'features') current_value = features.filter((f) => f.trim()).join(' / ')

    if (!current_value.trim() && mode !== 'suggest') {
      setErrorMsg(`Write a draft for ${field} first, then use ${mode}.`)
      return
    }

    setActiveField(field)
    setErrorMsg(null)
    setHelpResult(null)

    try {
      const result = await assistBrief.mutateAsync({ mode, field, current_value })
      if (result?.result) {
        setHelpResult({ field, mode, result: result.result })
      } else {
        setErrorMsg('The editor returned no response. Try again.')
      }
    } catch {
      setErrorMsg('The editor could not be reached. Check your API connection and try again.')
    } finally {
      setActiveField(null)
    }
  }, [positioning, features, hook, assistBrief])

  const applySuggestion = (field: FieldName, value: string) => {
    if (field === 'positioning') setPositioning(value)
    if (field === 'hook') setHook(value)
    setHelpResult(null)
  }

  return (
    <div style={{ maxWidth: 880, margin: '0 auto', padding: '60px 48px 120px', background: s.cream, minHeight: '100vh' }}>
      {/* Global animation keyframes injected once */}
      <style>{`
        @keyframes blink { 0%,100%{opacity:0.3} 50%{opacity:1} }
        @keyframes fadeSlideIn { from{opacity:0;transform:translateY(6px)} to{opacity:1;transform:translateY(0)} }
        @keyframes pulseWidth { 0%,100%{width:60%} 50%{width:75%} }
      `}</style>

      {/* TOP LABEL */}
      <div style={{ fontFamily: s.mono, fontSize: 10, letterSpacing: '0.22em', color: s.red, marginBottom: 24 }}>
        — {copy.topLabel}
      </div>

      {/* PAGE TITLE + GET HELP (single dropdown, top-right) */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 12 }}>
        <h1 style={{
          fontFamily: s.serif, fontSize: 'clamp(48px, 6vw, 76px)', fontWeight: 700,
          lineHeight: 0.95, letterSpacing: '-0.03em', color: s.ink, margin: 0,
        }}>{copy.pageTitle}</h1>
        <HelpDropdown
          open={helpOpen}
          onToggle={() => setHelpOpen(!helpOpen)}
          onAssist={handleAssist}
          disabled={isWaiting}
          activeField={activeField}
        />
      </div>
      <p style={{
        fontFamily: s.serif, fontStyle: 'italic', fontSize: 20, color: s.mute,
        margin: 0, marginBottom: 56,
      }}>{copy.pageSubtitle}</p>

      {/* DOSSIER REFERENCE */}
      <div style={{ paddingBottom: 24, marginBottom: 48, borderBottom: '0.5px solid #1a1a1a' }}>
        <div style={{ fontFamily: s.mono, fontSize: 9, letterSpacing: '0.24em', color: s.mute, marginBottom: 8 }}>
          ON FILE
        </div>
        <div style={{ fontFamily: s.serif, fontStyle: 'italic', fontSize: 16, color: s.ink }}>
          {dossierTitle}
        </div>
      </div>

      {/* FIELD: POSITIONING */}
      <BriefField
        label={copy.positioningLabel} hint={copy.positioningHint}
        placeholder={copy.positioningPlaceholder} value={positioning} onChange={setPositioning}
        multiline
        helpResult={helpResult?.field === 'positioning' ? helpResult : null}
        onApplySuggestion={(v) => applySuggestion('positioning', v)}
        onClearResult={() => setHelpResult(null)}
        isWaiting={isWaiting}
        isFieldLoading={activeField === 'positioning'}
      />

      {/* FIELD: FEATURES */}
      <div style={{ marginBottom: 56 }}>
        <div style={{
          fontFamily: s.mono, fontSize: 10, letterSpacing: '0.22em', color: s.ink, marginBottom: 6,
        }}>{copy.featuresLabel}</div>
        <div style={{
          fontFamily: s.serif, fontStyle: 'italic', fontSize: 14, color: s.mute, marginBottom: 16,
        }}>{copy.featuresHint}</div>
        {activeField === 'features' ? (
          <EditorLoading />
        ) : (
          <>
            {[0, 1, 2].map((i) => (
              <div key={i} style={{
                display: 'grid', gridTemplateColumns: '32px 1fr',
                alignItems: 'baseline', gap: 16, marginBottom: 12,
                opacity: isWaiting ? 0.4 : 1, transition: 'opacity 0.2s ease',
              }}>
                <span style={{
                  fontFamily: s.mono, fontSize: 11, color: s.red, letterSpacing: '0.18em',
                }}>{String(i + 1).padStart(2, '0')}</span>
                <input value={features[i]}
                  onChange={(e) => { const n = [...features]; n[i] = e.target.value; setFeatures(n) }}
                  placeholder={copy.featuresPlaceholder}
                  style={{
                    width: '100%', background: 'transparent', border: 'none',
                    borderBottom: '0.5px solid #1a1a1a',
                    fontFamily: s.serif, fontSize: 18, color: s.ink,
                    padding: '8px 0', outline: 'none', boxSizing: 'border-box',
                  }} />
              </div>
            ))}
            {helpResult?.field === 'features' && (
              <HelpResultPanel result={helpResult} onClose={() => setHelpResult(null)} onApply={() => {}} />
            )}
          </>
        )}
      </div>

      {/* FIELD: HOOK */}
      <BriefField
        label={copy.hookLabel} hint={copy.hookHint}
        placeholder={copy.hookPlaceholder} value={hook} onChange={setHook}
        helpResult={helpResult?.field === 'hook' ? helpResult : null}
        onApplySuggestion={(v) => applySuggestion('hook', v)}
        onClearResult={() => setHelpResult(null)}
        isWaiting={isWaiting}
        isFieldLoading={activeField === 'hook'}
      />

      {/* ERROR MESSAGE */}
      {errorMsg && (
        <div style={{
          marginTop: 16, padding: 12, background: 'rgba(192,57,43,0.06)',
          border: '0.5px solid #c0392b', fontFamily: s.mono, fontSize: 10,
          letterSpacing: '0.12em', color: s.red, lineHeight: 1.5,
          opacity: 0, animation: 'fadeSlideIn 0.3s ease-out forwards',
        }}>
          {errorMsg}
        </div>
      )}

      {/* CTA */}
      <div style={{ marginTop: 64, display: 'flex', gap: 12 }}>
        <button onClick={() => handleSave(true)} disabled={!isComplete || saveBrief.isPending}
          style={{
            background: isComplete ? s.red : '#bbb', color: s.cream,
            border: 'none', padding: '16px 28px',
            fontFamily: s.mono, fontSize: 11, letterSpacing: '0.20em',
            cursor: isComplete ? 'pointer' : 'not-allowed',
            transition: 'background 0.25s ease, opacity 0.2s ease',
            opacity: saveBrief.isPending ? 0.6 : 1,
          }}>
          {saveBrief.isPending ? 'FILING...' : isComplete ? copy.ctaReady : copy.ctaNotReady}
        </button>
        <button onClick={() => handleSave(false)} disabled={saveBrief.isPending}
          style={{
            background: 'transparent', color: s.ink, border: '0.5px solid #1a1a1a',
            padding: '16px 24px', fontFamily: s.mono, fontSize: 11,
            letterSpacing: '0.20em', cursor: 'pointer',
            opacity: saveBrief.isPending ? 0.4 : 1,
            transition: 'opacity 0.2s ease',
          }}>
          SAVE DRAFT
        </button>
      </div>
    </div>
  )
}
