'use client'

import { useState, useEffect, useCallback } from 'react'
import { useRouter } from 'next/navigation'

import { useBrief, useBriefAssist, useSaveBrief } from '@/hooks/useProjects'
import { MarginMark, CritiqueUnderline } from './PressRoomMarks'
import MarginNote from './MarginNote'

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

const s = {
  mono: 'var(--font-mono), monospace',
  serif: 'var(--font-serif), serif',
  red: '#c0392b',
  ink: '#1a1a1a',
  mute: '#888',
  cream: '#f5f0e8',
}

/* ─── Field input label ─────────────────────────────────── */

function FieldLabel({ label, hint }: { label: string; hint: string }) {
  return (
    <>
      <div style={{ fontFamily: s.mono, fontSize: 10, letterSpacing: '0.22em', color: s.ink, marginBottom: 6 }}>{label}</div>
      <div style={{ fontFamily: s.serif, fontStyle: 'italic', fontSize: 14, color: s.mute, marginBottom: 16 }}>{hint}</div>
    </>
  )
}

/* ─── Loading state ─────────────────────────────────────── */

function LoadingDots() {
  return (
    <span style={{ display: 'inline-flex', gap: 2, verticalAlign: 'middle' }}>
      <span style={{ width: 4, height: 4, borderRadius: '50%', background: s.red, display: 'inline-block', animation: 'blink 1.2s ease-in-out infinite' }} />
      <span style={{ width: 4, height: 4, borderRadius: '50%', background: s.red, display: 'inline-block', animation: 'blink 1.2s ease-in-out infinite', animationDelay: '0.2s' }} />
      <span style={{ width: 4, height: 4, borderRadius: '50%', background: s.red, display: 'inline-block', animation: 'blink 1.2s ease-in-out infinite', animationDelay: '0.4s' }} />
    </span>
  )
}

function EditorLoading() {
  return (
    <div style={{ marginTop: 18, padding: 24, border: '0.5px solid #c0392b', opacity: 0, animation: 'fadeSlideIn 0.35s ease-out forwards' }}>
      <div style={{ fontFamily: s.mono, fontSize: 9, letterSpacing: '0.22em', color: s.red, marginBottom: 14 }}>
        THE EDITOR IS READING <LoadingDots />
      </div>
      <div style={{ width: '60%', height: 10, background: 'rgba(192,57,43,0.06)', borderRadius: 2, marginBottom: 8, animation: 'pulseWidth 1.8s ease-in-out infinite' }} />
      <div style={{ width: '40%', height: 10, background: 'rgba(192,57,43,0.04)', borderRadius: 2, animation: 'pulseWidth 1.8s ease-in-out infinite', animationDelay: '0.3s' }} />
    </div>
  )
}

/* ─── Field section with margin marks ───────────────────── */

function FieldWithMarks({
  field, children, pressRoomMode, markDefs, critiqueDelay, helpResult, onClearResult, onApplySuggestion,
}: {
  field: FieldName
  children: React.ReactNode
  pressRoomMode: boolean
  markDefs: { label: string; hint: string; mode: 'refine' | 'suggest'; delay: number }[]
  critiqueDelay: number
  helpResult: { mode: string; result: string | string[] } | null
  onClearResult: () => void
  onApplySuggestion: (v: string) => void
}) {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '1fr 220px',
        gap: 32,
        marginBottom: 56,
        position: 'relative',
      }}
    >
      {/* Left — field content */}
      <div style={{ position: 'relative' }}>
        {children}
      </div>

      {/* Right — margin column */}
      <div style={{ position: 'relative' }}>
        {pressRoomMode && markDefs.map((m) => (
          <MarginMark key={m.mode} field={field} label={m.label} hint={m.hint} onClick={() => {}} delay={m.delay} visible={pressRoomMode} />
        ))}
        {helpResult && (
          <div style={{ marginTop: 12 }}>
            <MarginNote mode={helpResult.mode as 'refine' | 'suggest' | 'critique'} result={helpResult.result} onClose={onClearResult} onApply={onApplySuggestion} />
          </div>
        )}
      </div>
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
  const [pressRoomMode, setPressRoomMode] = useState(false)
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
    <div>
      {/* Fixed HELP button — top right */}
      <button
        onClick={() => { setPressRoomMode(!pressRoomMode); setActiveField(null); setHelpResult(null) }}
        style={{
          position: 'fixed', top: 28, right: 36, zIndex: 200,
          background: pressRoomMode ? s.red : s.ink,
          color: s.cream, border: 'none',
          padding: '12px 22px', fontFamily: s.mono, fontSize: 10,
          letterSpacing: '0.22em', cursor: 'pointer',
          transition: 'background 0.3s ease, padding 0.3s ease, box-shadow 0.3s ease',
          boxShadow: pressRoomMode ? '0 4px 18px rgba(192,57,43,0.30)' : '0 2px 8px rgba(0,0,0,0.12)',
        }}
      >
        {pressRoomMode ? '✕ CLOSE THE PROOF' : '— HELP'}
      </button>

      {/* Main content — desaturates in press room mode */}
      <div
        style={{
          maxWidth: 1180, margin: '0 auto', padding: '60px 48px 120px',
          filter: pressRoomMode ? 'saturate(0.85)' : 'saturate(1)',
          transition: 'filter 320ms ease 50ms',
        }}
      >
        <style>{`
          @keyframes blink { 0%,100%{opacity:0.3} 50%{opacity:1} }
          @keyframes fadeSlideIn { from{opacity:0;transform:translateY(6px)} to{opacity:1;transform:translateY(0)} }
          @keyframes pulseWidth { 0%,100%{width:60%} 50%{width:75%} }
          @media (max-width: 1100px) { .field-grid { grid-template-columns: 1fr !important; } }
        `}</style>

        {/* TOP LABEL */}
        <div style={{ fontFamily: s.mono, fontSize: 10, letterSpacing: '0.22em', color: s.red, marginBottom: 24 }}>
          — {copy.topLabel}
        </div>

        {/* PAGE TITLE */}
        <h1 style={{
          fontFamily: s.serif, fontSize: 'clamp(48px, 6vw, 76px)', fontWeight: 700,
          lineHeight: 0.95, letterSpacing: '-0.03em', color: s.ink, margin: 0, marginBottom: 12,
        }}>{copy.pageTitle}</h1>
        <p style={{
          fontFamily: s.serif, fontStyle: 'italic', fontSize: 20, color: s.mute,
          margin: 0, marginBottom: 56,
        }}>{copy.pageSubtitle}</p>

        {/* DOSSIER REFERENCE */}
        <div style={{ paddingBottom: 24, marginBottom: 48, borderBottom: '0.5px solid #1a1a1a' }}>
          <div style={{ fontFamily: s.mono, fontSize: 9, letterSpacing: '0.24em', color: s.mute, marginBottom: 8 }}>ON FILE</div>
          <div style={{ fontFamily: s.serif, fontStyle: 'italic', fontSize: 16, color: s.ink }}>{dossierTitle}</div>
        </div>

        {/* === POSITIONING === */}
        <div className="field-grid" style={{ display: 'grid', gridTemplateColumns: '1fr 220px', gap: 32, marginBottom: 56, position: 'relative' }}>
          <div style={{ position: 'relative' }}>
            <FieldLabel label={copy.positioningLabel} hint={copy.positioningHint} />
            {activeField === 'positioning' ? (
              <EditorLoading />
            ) : (
              <>
                <textarea value={positioning} onChange={(e) => setPositioning(e.target.value)}
                  placeholder={copy.positioningPlaceholder} rows={2}
                  style={{
                    width: '100%', background: 'transparent', border: 'none', borderBottom: '0.5px solid #1a1a1a',
                    fontFamily: s.serif, fontSize: 22, color: s.ink, padding: '8px 0', outline: 'none', resize: 'none',
                    boxSizing: 'border-box', opacity: isWaiting ? 0.4 : 1, transition: 'opacity 0.2s ease',
                  }} />
                {pressRoomMode && (
                  <CritiqueUnderline visible={pressRoomMode} delay={260} onClick={() => handleAssist('positioning', 'critique')} />
                )}
              </>
            )}
          </div>
          <div style={{ position: 'relative' }}>
            {pressRoomMode && (
              <>
                <MarginMark field="positioning" label="refine" hint="tighten your sentence" onClick={() => handleAssist('positioning', 'refine')} delay={180} visible={pressRoomMode} />
                <MarginMark field="positioning" label="suggest" hint="three fresh angles" onClick={() => handleAssist('positioning', 'suggest')} delay={220} visible={pressRoomMode} />
              </>
            )}
            {helpResult?.field === 'positioning' && (
              <div style={{ marginTop: 12 }}><MarginNote mode={helpResult.mode as 'refine' | 'suggest' | 'critique'} result={helpResult.result} onClose={() => setHelpResult(null)} onApply={(v) => applySuggestion('positioning', v)} /></div>
            )}
          </div>
        </div>

        {/* === FEATURES === */}
        <div className="field-grid" style={{ display: 'grid', gridTemplateColumns: '1fr 220px', gap: 32, marginBottom: 56, position: 'relative' }}>
          <div style={{ position: 'relative' }}>
            <FieldLabel label={copy.featuresLabel} hint={copy.featuresHint} />
            {activeField === 'features' ? (
              <EditorLoading />
            ) : (
              <>
                {[0, 1, 2].map((i) => (
                  <div key={i} style={{ display: 'grid', gridTemplateColumns: '32px 1fr', alignItems: 'baseline', gap: 16, marginBottom: 12, opacity: isWaiting ? 0.4 : 1, transition: 'opacity 0.2s ease' }}>
                    <span style={{ fontFamily: s.mono, fontSize: 11, color: s.red, letterSpacing: '0.18em' }}>{String(i + 1).padStart(2, '0')}</span>
                    <input value={features[i]} onChange={(e) => { const n = [...features]; n[i] = e.target.value; setFeatures(n) }}
                      placeholder={copy.featuresPlaceholder}
                      style={{ width: '100%', background: 'transparent', border: 'none', borderBottom: '0.5px solid #1a1a1a', fontFamily: s.serif, fontSize: 18, color: s.ink, padding: '8px 0', outline: 'none', boxSizing: 'border-box' }} />
                  </div>
                ))}
                {pressRoomMode && (
                  <CritiqueUnderline visible={pressRoomMode} delay={340} onClick={() => handleAssist('features', 'critique')} />
                )}
              </>
            )}
          </div>
          <div style={{ position: 'relative' }}>
            {pressRoomMode && (
              <>
                <MarginMark field="features" label="suggest" hint="three defining specs" onClick={() => handleAssist('features', 'suggest')} delay={260} visible={pressRoomMode} />
                <MarginMark field="features" label="refine" hint="sharpen the list" onClick={() => handleAssist('features', 'refine')} delay={300} visible={pressRoomMode} />
              </>
            )}
            {helpResult?.field === 'features' && (
              <div style={{ marginTop: 12 }}><MarginNote mode={helpResult.mode as 'refine' | 'suggest' | 'critique'} result={helpResult.result} onClose={() => setHelpResult(null)} onApply={() => {}} /></div>
            )}
          </div>
        </div>

        {/* === HOOK === */}
        <div className="field-grid" style={{ display: 'grid', gridTemplateColumns: '1fr 220px', gap: 32, marginBottom: 56, position: 'relative' }}>
          <div style={{ position: 'relative' }}>
            <FieldLabel label={copy.hookLabel} hint={copy.hookHint} />
            {activeField === 'hook' ? (
              <EditorLoading />
            ) : (
              <>
                <input value={hook} onChange={(e) => setHook(e.target.value)} placeholder={copy.hookPlaceholder}
                  style={{ width: '100%', background: 'transparent', border: 'none', borderBottom: '0.5px solid #1a1a1a', fontFamily: s.serif, fontSize: 22, color: s.ink, padding: '8px 0', outline: 'none', boxSizing: 'border-box', opacity: isWaiting ? 0.4 : 1, transition: 'opacity 0.2s ease' }} />
                {pressRoomMode && (
                  <CritiqueUnderline visible={pressRoomMode} delay={420} onClick={() => handleAssist('hook', 'critique')} />
                )}
              </>
            )}
          </div>
          <div style={{ position: 'relative' }}>
            {pressRoomMode && (
              <>
                <MarginMark field="hook" label="refine" hint="make it cut" onClick={() => handleAssist('hook', 'refine')} delay={340} visible={pressRoomMode} />
                <MarginMark field="hook" label="suggest" hint="three headline options" onClick={() => handleAssist('hook', 'suggest')} delay={380} visible={pressRoomMode} />
              </>
            )}
            {helpResult?.field === 'hook' && (
              <div style={{ marginTop: 12 }}><MarginNote mode={helpResult.mode as 'refine' | 'suggest' | 'critique'} result={helpResult.result} onClose={() => setHelpResult(null)} onApply={(v) => applySuggestion('hook', v)} /></div>
            )}
          </div>
        </div>

        {/* ERROR */}
        {errorMsg && (
          <div style={{ marginTop: 16, padding: 12, background: 'rgba(192,57,43,0.06)', border: '0.5px solid #c0392b', fontFamily: s.mono, fontSize: 10, letterSpacing: '0.12em', color: s.red, lineHeight: 1.5, opacity: 0, animation: 'fadeSlideIn 0.3s ease-out forwards' }}>
            {errorMsg}
          </div>
        )}

        {/* CTA */}
        <div style={{ marginTop: 64, display: 'flex', gap: 12 }}>
          <button onClick={() => handleSave(true)} disabled={!isComplete || saveBrief.isPending}
            style={{ background: isComplete ? s.red : '#bbb', color: s.cream, border: 'none', padding: '16px 28px', fontFamily: s.mono, fontSize: 11, letterSpacing: '0.20em', cursor: isComplete ? 'pointer' : 'not-allowed', transition: 'background 0.25s ease, opacity 0.2s ease', opacity: saveBrief.isPending ? 0.6 : 1 }}>
            {saveBrief.isPending ? 'FILING...' : isComplete ? copy.ctaReady : copy.ctaNotReady}
          </button>
          <button onClick={() => handleSave(false)} disabled={saveBrief.isPending}
            style={{ background: 'transparent', color: s.ink, border: '0.5px solid #1a1a1a', padding: '16px 24px', fontFamily: s.mono, fontSize: 11, letterSpacing: '0.20em', cursor: 'pointer', opacity: saveBrief.isPending ? 0.4 : 1, transition: 'opacity 0.2s ease' }}>
            SAVE DRAFT
          </button>
        </div>
      </div>
    </div>
  )
}
