'use client'

import { useState, useEffect } from 'react'
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

/* ─── Sub-components ────────────────────────── */

function FieldHeader({
  label,
  hint,
  helpOpen,
  onToggleHelp,
  onAssist,
}: {
  label: string
  hint: string
  helpOpen: boolean
  onToggleHelp: () => void
  onAssist: (mode: 'refine' | 'suggest' | 'critique') => void
}) {
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'baseline',
        marginBottom: 16,
        position: 'relative',
      }}
    >
      <div>
        <div
          style={{
            fontFamily: 'var(--font-mono), monospace',
            fontSize: 10,
            letterSpacing: '0.22em',
            color: '#1a1a1a',
            marginBottom: 6,
          }}
        >
          {label}
        </div>
        <div
          style={{
            fontFamily: 'var(--font-serif), serif',
            fontStyle: 'italic',
            fontSize: 14,
            color: '#888',
          }}
        >
          {hint}
        </div>
      </div>
      <div style={{ position: 'relative' }}>
        <button
          onClick={onToggleHelp}
          style={{
            background: 'transparent',
            border: '0.5px solid #1a1a1a',
            padding: '6px 14px',
            fontFamily: 'var(--font-mono), monospace',
            fontSize: 9,
            letterSpacing: '0.20em',
            cursor: 'pointer',
            color: '#1a1a1a',
          }}
        >
          GET HELP {helpOpen ? '▴' : '▾'}
        </button>
        {helpOpen && (
          <div
            style={{
              position: 'absolute',
              top: 'calc(100% + 6px)',
              right: 0,
              background: '#f5f0e8',
              border: '0.5px solid #1a1a1a',
              zIndex: 10,
              minWidth: 200,
              boxShadow: '0 4px 16px rgba(0,0,0,0.08)',
            }}
          >
            {[
              { k: 'refine' as const, t: 'REFINE MY DRAFT' },
              { k: 'suggest' as const, t: 'SUGGEST OPTIONS' },
              { k: 'critique' as const, t: 'CRITIQUE MY WRITING' },
            ].map((opt, i, arr) => (
              <button
                key={opt.k}
                onClick={() => onAssist(opt.k)}
                style={{
                  display: 'block',
                  width: '100%',
                  padding: '10px 14px',
                  background: 'transparent',
                  border: 'none',
                  borderBottom: i < arr.length - 1 ? '0.5px solid #e8e3d8' : 'none',
                  fontFamily: 'var(--font-mono), monospace',
                  fontSize: 10,
                  letterSpacing: '0.18em',
                  color: '#1a1a1a',
                  cursor: 'pointer',
                  textAlign: 'left',
                }}
              >
                {opt.t}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function HelpResultPanel({
  result,
  onClose,
  onApply,
}: {
  result: { mode: string; result: string | string[] }
  onClose: () => void
  onApply: (value: string) => void
}) {
  return (
    <div
      style={{
        marginTop: 18,
        padding: 18,
        background: 'rgba(192,57,43,0.04)',
        border: '0.5px solid #c0392b',
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 12,
        }}
      >
        <span
          style={{
            fontFamily: 'var(--font-mono), monospace',
            fontSize: 9,
            letterSpacing: '0.22em',
            color: '#c0392b',
          }}
        >
          EDITOR&apos;S {result.mode.toUpperCase()}
        </span>
        <button
          onClick={onClose}
          style={{
            background: 'transparent',
            border: 'none',
            cursor: 'pointer',
            fontFamily: 'var(--font-mono), monospace',
            fontSize: 9,
            letterSpacing: '0.20em',
            color: '#888',
          }}
        >
          DISMISS
        </button>
      </div>
      {Array.isArray(result.result) ? (
        <div>
          {result.result.map((opt, i, arr) => (
            <div
              key={i}
              style={{
                paddingBottom: 12,
                marginBottom: 12,
                borderBottom: i < arr.length - 1 ? '0.5px solid rgba(0,0,0,0.07)' : 'none',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'baseline',
                gap: 16,
              }}
            >
              <span
                style={{
                  fontFamily: 'var(--font-serif), serif',
                  fontSize: 17,
                  color: '#1a1a1a',
                  lineHeight: 1.5,
                }}
              >
                {opt}
              </span>
              <button
                onClick={() => onApply(opt)}
                style={{
                  background: '#1a1a1a',
                  color: '#f5f0e8',
                  border: 'none',
                  padding: '6px 12px',
                  fontFamily: 'var(--font-mono), monospace',
                  fontSize: 9,
                  letterSpacing: '0.18em',
                  cursor: 'pointer',
                  flexShrink: 0,
                }}
              >
                USE THIS
              </button>
            </div>
          ))}
        </div>
      ) : (
        <div
          style={{
            fontFamily: 'var(--font-serif), serif',
            fontSize: 16,
            color: '#1a1a1a',
            lineHeight: 1.55,
            whiteSpace: 'pre-wrap',
          }}
        >
          {result.result}
        </div>
      )}
    </div>
  )
}

/* ─── Main component ────────────────────────── */

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
  const [helpOpenField, setHelpOpenField] = useState<FieldName | null>(null)
  const [helpResult, setHelpResult] = useState<{
    field: FieldName
    mode: 'refine' | 'suggest' | 'critique'
    result: string | string[]
  } | null>(null)

  useEffect(() => {
    if (brief) {
      setPositioning(brief.positioning || '')
      const f = brief.features || []
      setFeatures([f[0] || '', f[1] || '', f[2] || ''])
      setHook(brief.hook || '')
    }
  }, [brief])

  const isComplete = positioning.trim() && features.filter((f) => f.trim()).length >= 1 && hook.trim()

  const handleSave = async (markComplete: boolean) => {
    await saveBrief.mutateAsync({
      positioning,
      features: features.filter((f) => f.trim()),
      hook,
      mark_complete: markComplete,
    })
    if (markComplete) {
      router.push(`/project/${projectId}`)
    }
  }

  const handleAssist = async (field: FieldName, mode: 'refine' | 'suggest' | 'critique') => {
    let current_value = ''
    if (field === 'positioning') current_value = positioning
    if (field === 'hook') current_value = hook
    if (field === 'features') current_value = features.filter((f) => f.trim()).join(' / ')

    try {
      const result = await assistBrief.mutateAsync({ mode, field, current_value })
      setHelpResult({ field, mode, result: result.result })
    } catch {
      setHelpResult(null)
    }
    setHelpOpenField(null)
  }

  const applySuggestion = (field: FieldName, value: string) => {
    if (field === 'positioning') setPositioning(value)
    if (field === 'hook') setHook(value)
    setHelpResult(null)
  }

  const loading = assistBrief.isPending

  return (
    <div style={{ maxWidth: 880, margin: '0 auto', padding: '60px 48px 120px', background: '#f5f0e8', minHeight: '100vh' }}>
      {/* TOP LABEL */}
      <div
        style={{
          fontFamily: 'var(--font-mono), monospace',
          fontSize: 10,
          letterSpacing: '0.22em',
          color: '#c0392b',
          marginBottom: 24,
        }}
      >
        — {copy.topLabel}
      </div>

      {/* PAGE TITLE */}
      <h1
        style={{
          fontFamily: 'var(--font-serif), serif',
          fontSize: 'clamp(48px, 6vw, 76px)',
          fontWeight: 700,
          lineHeight: 0.95,
          letterSpacing: '-0.03em',
          color: '#1a1a1a',
          margin: 0,
          marginBottom: 12,
        }}
      >
        {copy.pageTitle}
      </h1>
      <p
        style={{
          fontFamily: 'var(--font-serif), serif',
          fontStyle: 'italic',
          fontSize: 20,
          color: '#888',
          margin: 0,
          marginBottom: 56,
        }}
      >
        {copy.pageSubtitle}
      </p>

      {/* DOSSIER REFERENCE */}
      <div style={{ paddingBottom: 24, marginBottom: 48, borderBottom: '0.5px solid #1a1a1a' }}>
        <div
          style={{
            fontFamily: 'var(--font-mono), monospace',
            fontSize: 9,
            letterSpacing: '0.24em',
            color: '#888',
            marginBottom: 8,
          }}
        >
          ON FILE
        </div>
        <div style={{ fontFamily: 'var(--font-serif), serif', fontStyle: 'italic', fontSize: 16, color: '#1a1a1a' }}>
          {dossierTitle}
        </div>
      </div>

      {/* FIELD: POSITIONING */}
      <div style={{ marginBottom: 56 }}>
        <FieldHeader
          label={copy.positioningLabel}
          hint={copy.positioningHint}
          helpOpen={helpOpenField === 'positioning'}
          onToggleHelp={() => setHelpOpenField(helpOpenField === 'positioning' ? null : 'positioning')}
          onAssist={(mode) => handleAssist('positioning', mode)}
        />
        <textarea
          value={positioning}
          onChange={(e) => setPositioning(e.target.value)}
          placeholder={copy.positioningPlaceholder}
          rows={2}
          style={{
            width: '100%',
            background: 'transparent',
            border: 'none',
            borderBottom: '0.5px solid #1a1a1a',
            fontFamily: 'var(--font-serif), serif',
            fontSize: 22,
            color: '#1a1a1a',
            padding: '8px 0',
            outline: 'none',
            resize: 'none',
            boxSizing: 'border-box',
          }}
        />
        {loading && helpOpenField !== 'positioning' && (
          <div style={{ marginTop: 12, fontFamily: 'var(--font-mono), monospace', fontSize: 10, letterSpacing: '0.18em', color: '#888' }}>
            THE EDITOR IS READING...
          </div>
        )}
        {helpResult?.field === 'positioning' && (
          <HelpResultPanel result={helpResult} onClose={() => setHelpResult(null)} onApply={(v) => applySuggestion('positioning', v)} />
        )}
      </div>

      {/* FIELD: FEATURES */}
      <div style={{ marginBottom: 56 }}>
        <FieldHeader
          label={copy.featuresLabel}
          hint={copy.featuresHint}
          helpOpen={helpOpenField === 'features'}
          onToggleHelp={() => setHelpOpenField(helpOpenField === 'features' ? null : 'features')}
          onAssist={(mode) => handleAssist('features', mode)}
        />
        {[0, 1, 2].map((i) => (
          <div
            key={i}
            style={{
              display: 'grid',
              gridTemplateColumns: '32px 1fr',
              alignItems: 'baseline',
              gap: 16,
              marginBottom: 12,
            }}
          >
            <span
              style={{
                fontFamily: 'var(--font-mono), monospace',
                fontSize: 11,
                color: '#c0392b',
                letterSpacing: '0.18em',
              }}
            >
              {String(i + 1).padStart(2, '0')}
            </span>
            <input
              value={features[i]}
              onChange={(e) => {
                const next = [...features]
                next[i] = e.target.value
                setFeatures(next)
              }}
              placeholder={copy.featuresPlaceholder}
              style={{
                width: '100%',
                background: 'transparent',
                border: 'none',
                borderBottom: '0.5px solid #1a1a1a',
                fontFamily: 'var(--font-serif), serif',
                fontSize: 18,
                color: '#1a1a1a',
                padding: '8px 0',
                outline: 'none',
                boxSizing: 'border-box',
              }}
            />
          </div>
        ))}
        {helpResult?.field === 'features' && (
          <HelpResultPanel result={helpResult} onClose={() => setHelpResult(null)} onApply={() => {}} />
        )}
      </div>

      {/* FIELD: HOOK */}
      <div style={{ marginBottom: 56 }}>
        <FieldHeader
          label={copy.hookLabel}
          hint={copy.hookHint}
          helpOpen={helpOpenField === 'hook'}
          onToggleHelp={() => setHelpOpenField(helpOpenField === 'hook' ? null : 'hook')}
          onAssist={(mode) => handleAssist('hook', mode)}
        />
        <input
          value={hook}
          onChange={(e) => setHook(e.target.value)}
          placeholder={copy.hookPlaceholder}
          style={{
            width: '100%',
            background: 'transparent',
            border: 'none',
            borderBottom: '0.5px solid #1a1a1a',
            fontFamily: 'var(--font-serif), serif',
            fontSize: 22,
            color: '#1a1a1a',
            padding: '8px 0',
            outline: 'none',
            boxSizing: 'border-box',
          }}
        />
        {helpResult?.field === 'hook' && (
          <HelpResultPanel result={helpResult} onClose={() => setHelpResult(null)} onApply={(v) => applySuggestion('hook', v)} />
        )}
      </div>

      {/* CTA */}
      <div style={{ marginTop: 64, display: 'flex', gap: 12 }}>
        <button
          onClick={() => handleSave(true)}
          disabled={!isComplete || saveBrief.isPending}
          style={{
            background: isComplete ? '#c0392b' : '#bbb',
            color: '#f5f0e8',
            border: 'none',
            padding: '16px 28px',
            fontFamily: 'var(--font-mono), monospace',
            fontSize: 11,
            letterSpacing: '0.20em',
            cursor: isComplete ? 'pointer' : 'not-allowed',
            transition: 'background 0.18s ease',
          }}
        >
          {saveBrief.isPending ? 'FILING...' : isComplete ? copy.ctaReady : copy.ctaNotReady}
        </button>
        <button
          onClick={() => handleSave(false)}
          disabled={saveBrief.isPending}
          style={{
            background: 'transparent',
            color: '#1a1a1a',
            border: '0.5px solid #1a1a1a',
            padding: '16px 24px',
            fontFamily: 'var(--font-mono), monospace',
            fontSize: 11,
            letterSpacing: '0.20em',
            cursor: 'pointer',
          }}
        >
          SAVE DRAFT
        </button>
      </div>
    </div>
  )
}
