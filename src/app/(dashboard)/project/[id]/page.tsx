'use client'

import { useMemo } from 'react'
import { motion } from 'framer-motion'
import { ArrowUpRight, Loader2 } from 'lucide-react'
import Link from 'next/link'
import { useParams } from 'next/navigation'

import { useAssumptions } from '@/hooks/useAssumptions'
import { useProject } from '@/hooks/useProjects'
import { useSimulations } from '@/hooks/useSimulation'
import type { Assumption } from '@/types'

/* ── Editorial status taxonomy ───────────────────────────────────── */
const statusMeta: Record<string, { bucket: 'draft' | 'ready' | 'running' | 'done' | 'failed'; label: string }> = {
  DRAFT:                 { bucket: 'draft',   label: 'In notes' },
  ASSUMPTIONS_EXTRACTED: { bucket: 'ready',   label: 'Outline ready' },
  PROTOTYPE_GENERATED:   { bucket: 'ready',   label: 'Draft typeset' },
  ENVIRONMENT_SET:       { bucket: 'ready',   label: 'Cast assembled' },
  QUEUED:                { bucket: 'running', label: 'At press' },
  RUNNING:               { bucket: 'running', label: 'At press' },
  COMPLETED:             { bucket: 'done',    label: 'Filed' },
  FAILED:                { bucket: 'failed',  label: 'Returned' },
}

/* Sensitivity taxonomy — editorial, not SaaS. */
const sensitivityMeta: Record<string, { label: string; marginalia: string; rail: string }> = {
  CRITICAL: { label: 'Critical', marginalia: 'crit.',  rail: 'var(--red)' },
  HIGH:     { label: 'High',     marginalia: 'high',   rail: 'var(--ink)' },
  MEDIUM:   { label: 'Medium',   marginalia: 'med.',   rail: 'var(--ink-tertiary)' },
  LOW:      { label: 'Low',      marginalia: 'low',    rail: 'transparent' },
}

export default function ProjectPage() {
  const params = useParams()
  const projectId = Number(params.id)

  const { data: project, isLoading: pLoading } = useProject(projectId)
  const { data: assumptions, isLoading: aLoading } = useAssumptions(projectId)
  const { data: simulations, isLoading: sLoading } = useSimulations(projectId)

  const assumptionList = useMemo<Assumption[]>(() => assumptions ?? [], [assumptions])
  const hiddenCount = assumptionList.filter((a) => Boolean(a.isHidden ?? a.is_hidden)).length
  const simulationCount = simulations?.length ?? 0

  /* ── Loading ──────────────────────────────────────────────────── */
  if (pLoading) {
    return (
      <div style={{ padding: '80px 48px', display: 'flex', gap: 12, alignItems: 'center', color: 'var(--ink-secondary)' }}>
        <Loader2 className="animate-spin" style={{ width: 14, height: 14 }} />
        <span className="kicker">Pulling the galley…</span>
      </div>
    )
  }

  /* ── Not found ────────────────────────────────────────────────── */
  if (!project) {
    return (
      <div style={{ padding: '80px 48px', maxWidth: 640 }}>
        <div className="kicker" style={{ color: 'var(--red)', marginBottom: 10 }}>Errata</div>
        <h1 className="font-serif" style={{ fontSize: 44, fontWeight: 900, fontStyle: 'italic', lineHeight: 1, letterSpacing: '-0.03em' }}>
          This dossier is missing from the archive.
        </h1>
        <p style={{ marginTop: 18, color: 'var(--ink-secondary)', fontSize: 14, lineHeight: 1.7 }}>
          It may have been recalled, or the number you followed was typeset in error.
          <Link href="/projects" style={{ marginLeft: 6, color: 'var(--red)', textDecoration: 'underline', textUnderlineOffset: 3 }}>
            Return to the index.
          </Link>
        </p>
      </div>
    )
  }

  const status = statusMeta[project.status] ?? { bucket: 'draft' as const, label: project.status?.toLowerCase() ?? 'in notes' }
  const filedDate = project.created_at ? new Date(project.created_at) : null
  const issueNumber = String(Number.isFinite(projectId) ? projectId : 1).padStart(3, '0')

  /* ── Page ─────────────────────────────────────────────────────── */
  return (
    <div
      className="rise"
      style={{
        padding: '40px 48px 120px',
        maxWidth: 1280,
        margin: '0 auto',
        position: 'relative',
      }}
    >
      {/* ── Title row: huge italic title + giant numeral ─────── */}
      <section
        style={{
          display: 'grid',
          gridTemplateColumns: 'minmax(0, 1fr) auto',
          gap: 40,
          alignItems: 'end',
          marginBottom: 28,
        }}
      >
        <div>
          <div className="kicker" style={{ color: 'var(--red)', marginBottom: 14, display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ width: 22, height: 0.5, background: 'var(--red)' }} />
            Galley Proof · Reader&rsquo;s Pull
          </div>

          <h1
            className="font-serif"
            style={{
              fontSize: 'clamp(44px, 6vw, 78px)',
              fontWeight: 900,
              lineHeight: 0.95,
              letterSpacing: '-0.035em',
              color: 'var(--ink)',
              marginBottom: 6,
            }}
          >
            {project.title.split(/\s+/).map((word, i, arr) => {
              const isLast = i === arr.length - 1
              const italicize = arr.length > 2 && (i === Math.floor(arr.length / 2) || i === arr.length - 2)
              return (
                <span
                  key={`${word}-${i}`}
                  style={italicize ? { fontStyle: 'italic', color: 'var(--red)' } : undefined}
                >
                  {word}
                  {!isLast ? ' ' : ''}
                </span>
              )
            })}
            <span style={{ color: 'var(--red)' }}>.</span>
          </h1>
        </div>

        {/* Right rail: giant numeral + editor's tick */}
        <div style={{ textAlign: 'right', position: 'relative', paddingLeft: 20 }}>
          <div
            className="numeral"
            style={{
              fontSize: 'clamp(120px, 14vw, 200px)',
              color: 'var(--ink)',
              lineHeight: 0.85,
              letterSpacing: '-0.06em',
            }}
          >
            {issueNumber}
          </div>
          <div
            style={{
              position: 'absolute',
              top: 6,
              right: -4,
              transform: 'rotate(-14deg)',
              color: 'var(--red)',
              fontFamily: 'var(--font-serif)',
              fontStyle: 'italic',
              fontSize: 22,
              fontWeight: 600,
              opacity: 0.75,
              letterSpacing: '-0.01em',
              userSelect: 'none',
            }}
            aria-hidden
          >
            ✓ ed.
          </div>
        </div>
      </section>

      {/* ── Ink rule under title ─────────────────────────────── */}
      <div style={{ height: 3, background: 'var(--ink)', marginBottom: 4 }} />
      <div style={{ height: 0.5, background: 'var(--border-color)', marginBottom: 56 }} />

      {/* ── Body grid: précis column + readings ledger ────────── */}
      <section
        style={{
          display: 'grid',
          gridTemplateColumns: 'minmax(280px, 360px) minmax(0, 1fr)',
          gap: 56,
          alignItems: 'start',
        }}
      >
        {/* ─── Précis column ─────────────────────────────── */}
        <aside style={{ position: 'relative' }}>
          <div className="kicker" style={{ color: 'var(--ink-secondary)', marginBottom: 14 }}>
            The Précis
          </div>
          <div
            style={{
              position: 'relative',
              padding: '24px 22px 26px',
              border: '0.5px solid var(--border-strong)',
              borderTop: '2px solid var(--ink)',
              background: 'rgba(26,23,20,0.015)',
            }}
          >
            {/* Stamp */}
            <div
              style={{
                position: 'absolute',
                top: -14,
                right: 18,
                transform: 'rotate(6deg)',
                border: '1.5px solid var(--red)',
                color: 'var(--red)',
                padding: '3px 10px',
                fontSize: 9,
                letterSpacing: '0.28em',
                textTransform: 'uppercase',
                fontWeight: 700,
                background: 'var(--paper)',
                opacity: 0.9,
              }}
              aria-hidden
            >
              Filed
            </div>

            <p
              className="dropcap"
              style={{
                fontSize: 15,
                lineHeight: 1.8,
                color: 'var(--ink)',
                fontWeight: 300,
                fontFamily: 'var(--font-body)',
              }}
            >
              {project.description}
            </p>

            <div style={{ height: 0.5, background: 'var(--border-color)', margin: '22px 0 14px' }} />

            {/* Meta list */}
            <dl style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', rowGap: 8, columnGap: 12 }}>
              <Meta label="Filed" value={filedDate ? filedDate.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }) : '—'} />
              <Meta label="Section" value="Idea Review" accent="var(--red)" />
              <Meta label="Status" value={status.label} />
              <Meta label="Reader&rsquo;s mark" value={`№ ${issueNumber}`} />
            </dl>
          </div>

          {/* Footnote */}
          <p
            style={{
              marginTop: 14,
              fontSize: 11,
              lineHeight: 1.65,
              color: 'var(--ink-tertiary)',
              fontStyle: 'italic',
              fontFamily: 'var(--font-serif)',
            }}
          >
            — typeset from the submission; unedited.
          </p>
        </aside>

        {/* ─── Readings ledger ───────────────────────────── */}
        <div>
          <div
            style={{
              display: 'flex',
              alignItems: 'baseline',
              justifyContent: 'space-between',
              gap: 16,
              marginBottom: 8,
            }}
          >
            <h2
              className="font-serif"
              style={{
                fontSize: 34,
                fontWeight: 900,
                fontStyle: 'italic',
                letterSpacing: '-0.02em',
                color: 'var(--ink)',
              }}
            >
              The Readings
            </h2>
            <div className="kicker" style={{ color: 'var(--ink-secondary)' }}>
              {aLoading ? 'Being read…' : `${assumptionList.length} surfaced`}
            </div>
          </div>
          <div style={{ height: 2, background: 'var(--ink)', marginBottom: 4 }} />
          <div style={{ height: 0.5, background: 'var(--border-color)', marginBottom: 20 }} />

          <p
            style={{
              fontSize: 13,
              lineHeight: 1.75,
              color: 'var(--ink-secondary)',
              maxWidth: 620,
              marginBottom: 28,
              fontStyle: 'italic',
              fontFamily: 'var(--font-serif)',
            }}
          >
            Every dossier carries hidden assumptions. Below is what the first reading has
            brought to the surface — a marginal ledger, in the reader&rsquo;s own hand.
          </p>

          {/* Ledger */}
          {aLoading ? (
            <LedgerSkeleton />
          ) : assumptionList.length === 0 ? (
            <EmptyReadings />
          ) : (
            <ol style={{ listStyle: 'none', borderTop: '0.5px solid var(--border-color)' }}>
              {assumptionList.map((a, i) => (
                <motion.li
                  key={a.id}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.06, duration: 0.5, ease: [0.2, 0.7, 0.2, 1] }}
                >
                  <LedgerEntry assumption={a} index={i + 1} />
                </motion.li>
              ))}
            </ol>
          )}

          {/* Printer's chase — counters strip */}
          <div
            style={{
              marginTop: 40,
              padding: '16px 0',
              borderTop: '0.5px solid var(--border-color)',
              borderBottom: '0.5px solid var(--border-color)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 20,
              flexWrap: 'wrap',
            }}
          >
            <ChaseCounter label="Assumptions surfaced" value={assumptionList.length} />
            <ChaseDivider />
            <ChaseCounter label="Hidden among them" value={hiddenCount} tone="red" />
            <ChaseDivider />
            <ChaseCounter
              label="Simulations run"
              value={sLoading ? '—' : simulationCount}
            />
            <ChaseDivider />
            <ChaseCounter label="Last pull" value={filedDate ? timeAgo(filedDate) : 'just now'} mono={false} />
          </div>

          {/* Press runs — link completed simulations to results dashboard */}
          {!sLoading && simulations && simulations.length > 0 && (
            <div style={{ marginTop: 28 }}>
              <div
                className="kicker"
                style={{ color: 'var(--red)', marginBottom: 12, letterSpacing: '0.22em', textTransform: 'uppercase' }}
              >
                Press runs
              </div>
              <ul style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 8 }}>
                {simulations.map((sim, simIdx) => {
                  const sid = sim.id
                  const st = sim.status ?? ''
                  const filed = st === 'COMPLETED'
                  return (
                    <li
                      key={sid ?? `sim-${simIdx}`}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        gap: 12,
                        padding: '10px 14px',
                        border: '0.5px solid var(--border-color)',
                        background: 'var(--paper)',
                      }}
                      className="rise"
                    >
                      <span style={{ fontSize: 13, color: 'var(--ink-secondary)' }}>
                        Run <span style={{ color: 'var(--ink)', fontWeight: 600 }}>#{sid}</span>
                        <span style={{ marginLeft: 10, fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.14em' }}>
                          {st.replace(/_/g, ' ')}
                        </span>
                      </span>
                      {filed && sid != null ? (
                        <Link
                          href={`/project/${projectId}/results?sim=${sid}`}
                          style={{
                            fontSize: 11,
                            letterSpacing: '0.16em',
                            textTransform: 'uppercase',
                            color: 'var(--red)',
                            textDecoration: 'none',
                            fontWeight: 600,
                          }}
                        >
                          Results →
                        </Link>
                      ) : (
                        <span style={{ fontSize: 11, color: 'var(--ink-tertiary)' }}>—</span>
                      )}
                    </li>
                  )
                })}
              </ul>
            </div>
          )}

          {/* ─── Prototype plate ─────────────────────────── */}
          <Link
            href={`/project/${projectId}/prototype`}
            style={{ textDecoration: 'none', color: 'var(--ink)', display: 'block' }}
          >
            <div
              className="rise rise-1"
              style={{
                marginTop: 44,
                position: 'relative',
                padding: '28px 32px',
                border: '0.5px solid var(--ink)',
                background: 'var(--paper)',
                boxShadow: '12px 12px 0 rgba(26,23,20,0.12)',
                display: 'grid',
                gridTemplateColumns: '1fr auto',
                alignItems: 'center',
                gap: 24,
                transition: 'transform 260ms ease, box-shadow 260ms ease',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.transform = 'translate(-3px, -3px)'
                e.currentTarget.style.boxShadow = '15px 15px 0 var(--ink)'
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.transform = 'translate(0, 0)'
                e.currentTarget.style.boxShadow = '12px 12px 0 rgba(26,23,20,0.12)'
              }}
            >
              <div>
                <div className="kicker" style={{ color: 'var(--red)', marginBottom: 10 }}>
                  Prototype · Plate 01
                </div>
                <div
                  className="font-serif"
                  style={{
                    fontSize: 30,
                    fontWeight: 900,
                    fontStyle: 'italic',
                    lineHeight: 1,
                    letterSpacing: '-0.02em',
                    color: 'var(--ink)',
                  }}
                >
                  Read the setting in full.
                </div>
                <p style={{ marginTop: 10, color: 'var(--ink-secondary)', fontSize: 13, lineHeight: 1.6, maxWidth: 520 }}>
                  The page as the synthetic reader will see it — typeset, cast, and open for inspection before the presses roll.
                </p>
              </div>
              <div
                style={{
                  width: 58,
                  height: 58,
                  border: '0.5px solid var(--ink)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  color: 'var(--red)',
                }}
              >
                <ArrowUpRight style={{ width: 22, height: 22 }} />
              </div>
            </div>
          </Link>
        </div>
      </section>

      {/* Colophon */}
      <div style={{ marginTop: 80 }}>
        <div style={{ height: 0.5, background: 'var(--border-color)', marginBottom: 12 }} />
        <div className="kicker" style={{ color: 'var(--ink-tertiary)', textAlign: 'center' }}>
          End of galley · The editor&rsquo;s desk awaits the next pull.
        </div>
      </div>
    </div>
  )
}

/* ── Sub-components ──────────────────────────────────────────────── */

function Meta({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <>
      <dt className="kicker" style={{ color: 'var(--ink-tertiary)', paddingTop: 1 }}>{label}</dt>
      <dd style={{ fontSize: 12, color: accent ?? 'var(--ink)', fontWeight: 500, letterSpacing: '0.02em' }}>{value}</dd>
    </>
  )
}

function LedgerEntry({ assumption, index }: { assumption: Assumption; index: number }) {
  const sens = sensitivityMeta[assumption.sensitivity] ?? sensitivityMeta.MEDIUM
  const hidden = Boolean(assumption.isHidden ?? assumption.is_hidden)
  const impact = Math.max(0, Math.min(10, assumption.impactScore ?? assumption.impact_score ?? 0))

  return (
    <div
      style={{
        position: 'relative',
        display: 'grid',
        gridTemplateColumns: '56px 1fr 200px',
        gap: 24,
        padding: '22px 0 22px 12px',
        borderBottom: '0.5px solid var(--border-color)',
        borderLeft: sens.rail === 'transparent' ? '2px solid transparent' : `2px solid ${sens.rail}`,
        transition: 'background 240ms ease, padding-left 240ms ease',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.background = 'linear-gradient(90deg, rgba(192,57,43,0.04) 0%, transparent 70%)'
        e.currentTarget.style.paddingLeft = '22px'
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.background = 'transparent'
        e.currentTarget.style.paddingLeft = '12px'
      }}
    >
      {/* Marginalia: number + optional handwritten editor's note */}
      <div style={{ position: 'relative' }}>
        <div
          className="numeral"
          style={{ fontSize: 28, color: assumption.sensitivity === 'CRITICAL' ? 'var(--red)' : 'var(--ink-tertiary)' }}
        >
          {String(index).padStart(2, '0')}
        </div>
        <div
          style={{
            marginTop: 4,
            fontFamily: 'var(--font-serif)',
            fontStyle: 'italic',
            fontSize: 11,
            color: 'var(--red)',
            opacity: 0.8,
            letterSpacing: '0.02em',
          }}
          aria-hidden
        >
          {hidden ? 'hid.' : sens.marginalia}
        </div>
      </div>

      {/* The reading itself */}
      <div>
        <p
          style={{
            fontFamily: 'var(--font-serif)',
            fontSize: 17,
            lineHeight: 1.45,
            color: 'var(--ink)',
            fontWeight: 500,
            letterSpacing: '-0.005em',
          }}
        >
          {assumption.text}
        </p>
        {hidden && (
          <div
            style={{
              marginTop: 8,
              fontFamily: 'var(--font-serif)',
              fontStyle: 'italic',
              fontSize: 12,
              color: 'var(--ink-tertiary)',
            }}
          >
            — seen only by the editor
          </div>
        )}
      </div>

      {/* Impact + category */}
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 8 }}>
        <div
          className="kicker"
          style={{
            color: assumption.sensitivity === 'CRITICAL' ? 'var(--red)' : 'var(--ink-secondary)',
            fontWeight: 600,
          }}
        >
          {sens.label}
        </div>
        <TypographicMeter value={impact} />
        <div
          style={{
            fontSize: 10,
            letterSpacing: '0.2em',
            textTransform: 'uppercase',
            color: 'var(--ink-tertiary)',
            fontWeight: 500,
          }}
        >
          {assumption.category}
        </div>
      </div>
    </div>
  )
}

/* A confidence meter drawn with block glyphs, not pixels. */
function TypographicMeter({ value }: { value: number }) {
  const filled = Math.round((value / 10) * 5)
  return (
    <div
      aria-label={`Impact ${value} of 10`}
      style={{
        fontFamily: 'var(--font-serif)',
        fontSize: 18,
        letterSpacing: '0.1em',
        lineHeight: 1,
        color: 'var(--ink)',
      }}
    >
      {Array.from({ length: 5 }, (_, i) => (
        <span key={i} style={{ color: i < filled ? 'var(--ink)' : 'var(--ink-tertiary)', opacity: i < filled ? 0.95 : 0.35 }}>
          ▐
        </span>
      ))}
    </div>
  )
}

function ChaseCounter({
  label,
  value,
  tone,
}: {
  label: string
  value: number | string
  tone?: 'red'
  mono?: boolean
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, minWidth: 120 }}>
      <span
        className="kicker"
        style={{ color: 'var(--ink-tertiary)' }}
      >
        {label}
      </span>
      <span
        className="numeral"
        style={{
          fontSize: 28,
          color: tone === 'red' ? 'var(--red)' : 'var(--ink)',
          lineHeight: 1,
        }}
      >
        {value}
      </span>
    </div>
  )
}

function ChaseDivider() {
  return <span style={{ width: 0.5, height: 36, background: 'var(--border-color)' }} aria-hidden />
}

function LedgerSkeleton() {
  return (
    <div style={{ borderTop: '0.5px solid var(--border-color)' }}>
      {Array.from({ length: 3 }).map((_, i) => (
        <div
          key={i}
          style={{
            display: 'grid',
            gridTemplateColumns: '56px 1fr 200px',
            gap: 24,
            padding: '22px 0 22px 12px',
            borderBottom: '0.5px solid var(--border-color)',
            opacity: 1 - i * 0.2,
          }}
        >
          <div style={{ height: 28, background: 'rgba(26,23,20,0.05)' }} />
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div style={{ height: 14, background: 'rgba(26,23,20,0.05)', width: '92%' }} />
            <div style={{ height: 14, background: 'rgba(26,23,20,0.05)', width: '68%' }} />
          </div>
          <div style={{ height: 14, background: 'rgba(26,23,20,0.05)' }} />
        </div>
      ))}
    </div>
  )
}

function EmptyReadings() {
  return (
    <div
      style={{
        padding: '56px 0 64px',
        borderTop: '0.5px solid var(--border-color)',
        borderBottom: '0.5px solid var(--border-color)',
        textAlign: 'center',
      }}
    >
      <div
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 12,
          marginBottom: 18,
          color: 'var(--ink-secondary)',
        }}
      >
        <span className="status-dot status-dot--running" style={{ marginRight: 0 }} />
        <span className="kicker">Reading in progress</span>
      </div>
      <p
        className="font-serif"
        style={{
          fontSize: 26,
          fontStyle: 'italic',
          fontWeight: 600,
          color: 'var(--ink)',
          letterSpacing: '-0.015em',
          maxWidth: 620,
          margin: '0 auto',
          lineHeight: 1.25,
        }}
      >
        &ldquo;The readers are still turning the first page.&rdquo;
      </p>
      <p
        style={{
          marginTop: 14,
          fontSize: 13,
          color: 'var(--ink-tertiary)',
          fontStyle: 'italic',
          fontFamily: 'var(--font-serif)',
        }}
      >
        Assumptions will surface as the proof is read.
      </p>
    </div>
  )
}

/* ── Utilities ───────────────────────────────────────────────────── */
function timeAgo(d: Date): string {
  const diff = Date.now() - d.getTime()
  const s = Math.max(1, Math.floor(diff / 1000))
  if (s < 60) return 'just now'
  const m = Math.floor(s / 60)
  if (m < 60) return `${m} min ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h} h ago`
  const day = Math.floor(h / 24)
  return `${day} d ago`
}
