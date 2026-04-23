'use client'

/**
 * Scan-line label for whether a dossier is software-only, hardware-only,
 * or a legacy “full folio” (both workshop paths). New filings set axis at creation.
 */
export function FolioAxisChip({ axis }: { axis?: string | null }) {
  if (axis === 'software') {
    return (
      <span
        className="kicker"
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 6,
          color: 'var(--red)',
          fontSize: 9,
          letterSpacing: '0.22em',
          textTransform: 'uppercase',
          fontWeight: 600,
        }}
      >
        <span style={{ width: 12, height: 0.5, background: 'var(--red)' }} />
        Software folio
      </span>
    )
  }
  if (axis === 'hardware') {
    return (
      <span
        className="kicker"
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 6,
          color: 'var(--workshop)',
          fontSize: 9,
          letterSpacing: '0.22em',
          textTransform: 'uppercase',
          fontWeight: 600,
        }}
      >
        <span style={{ width: 12, height: 0.5, background: 'var(--workshop)' }} />
        Hardware atelier
      </span>
    )
  }
  return (
    <span
      className="kicker"
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        color: 'var(--ink-tertiary)',
        fontSize: 9,
        letterSpacing: '0.2em',
        textTransform: 'uppercase',
        fontWeight: 600,
      }}
    >
      <span style={{ width: 12, height: 0.5, background: 'var(--ink-tertiary)' }} />
      Full folio · both plates
    </span>
  )
}

/** Editor’s slip for legacy dossiers that pre-date single-path filing. */
export function LegacyFolioSlip() {
  return (
    <div
      style={{
        marginTop: 36,
        marginBottom: 4,
        padding: '16px 18px 18px',
        border: '0.5px dashed var(--ink-tertiary)',
        background: 'repeating-linear-gradient(0deg, rgba(26,23,20,0.02) 0 0.5px, transparent 0.5px 20px)',
        maxWidth: 640,
      }}
    >
      <div className="kicker" style={{ color: 'var(--ink-secondary)', marginBottom: 8, letterSpacing: '0.2em' }}>
        From the editor&rsquo;s desk
      </div>
      <p
        style={{
          fontSize: 13,
          lineHeight: 1.65,
          color: 'var(--ink-secondary)',
          fontFamily: 'var(--font-serif)',
          fontStyle: 'italic',
          margin: 0,
        }}
      >
        This dossier was filed before we split the press into <strong style={{ fontWeight: 600, color: 'var(--ink)' }}>software</strong> and{' '}
        <strong style={{ fontWeight: 600, color: 'var(--ink)' }}>hardware</strong> paths. Both the prototype plate and the
        atelier folio stay available here — that is the archive rule. New filings choose a single path when you press{' '}
        <em>File New Dossier</em>.
      </p>
    </div>
  )
}
