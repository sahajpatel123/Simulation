'use client'

import { Suspense, useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { ArrowUpRight, Loader2, Plus, X } from 'lucide-react'
import Link from 'next/link'
import { useRouter, useSearchParams } from 'next/navigation'

import { apiError } from '@/lib/api'
import { useCreateProject, useProjects } from '@/hooks/useProjects'
import type { Project } from '@/types'

/* ── Status taxonomy — editorial labels, not SaaS tags. ──────────── */
type StatusBucket = 'draft' | 'ready' | 'running' | 'done' | 'failed'

const statusMeta: Record<string, { bucket: StatusBucket; label: string }> = {
  DRAFT:                 { bucket: 'draft',   label: 'In notes' },
  ASSUMPTIONS_EXTRACTED: { bucket: 'ready',   label: 'Outline ready' },
  PROTOTYPE_GENERATED:   { bucket: 'ready',   label: 'Draft typeset' },
  ENVIRONMENT_SET:       { bucket: 'ready',   label: 'Cast assembled' },
  QUEUED:                { bucket: 'running', label: 'At press' },
  RUNNING:               { bucket: 'running', label: 'At press' },
  COMPLETED:             { bucket: 'done',    label: 'Filed' },
  FAILED:                { bucket: 'failed',  label: 'Returned' },
}

function resolveStatus(s: string) {
  return statusMeta[s] ?? { bucket: 'draft' as StatusBucket, label: s.toLowerCase().replace(/_/g, ' ') }
}

/* ── Filter taxonomy ─────────────────────────────────────────────── */
type Filter = 'all' | 'draft' | 'ready' | 'running' | 'done' | 'failed'

const filterTabs: { id: Filter; label: string; note: string }[] = [
  { id: 'all',     label: 'All dossiers',    note: 'The complete index' },
  { id: 'draft',   label: 'Drafts',          note: 'Still in your handwriting' },
  { id: 'ready',   label: 'Ready for press', note: 'Outlines, casts, proofs set' },
  { id: 'running', label: 'In simulation',   note: 'At press now' },
  { id: 'done',    label: 'Archived',        note: 'Filed, with proofs on record' },
  { id: 'failed',  label: 'Returned',        note: 'Sent back by the press' },
]

const headlineForFilter: Record<Filter, { kicker: string; headline: React.ReactNode; lede: string }> = {
  all: {
    kicker: 'The Dossier Index',
    headline: (
      <>
        Your<span style={{ fontStyle: 'italic', color: 'var(--red)' }}> ideas</span>,
        <br />
        under review.
      </>
    ),
    lede:
      'Every entry below is a hypothesis in your hand — drafted, cast with synthetic readers, and run against a market that doesn’t flatter you. Open one to read its report.',
  },
  draft: {
    kicker: 'Field Work · Drafts',
    headline: (
      <>
        Still in your<span style={{ fontStyle: 'italic', color: 'var(--red)' }}> handwriting</span>.
      </>
    ),
    lede:
      'Notes that have not yet been set in type. The margins are wide, the punctuation is ugly, and that is the point.',
  },
  ready: {
    kicker: 'Field Work · Ready',
    headline: (
      <>
        <span style={{ fontStyle: 'italic', color: 'var(--red)' }}>Proofs</span> on the bench.
      </>
    ),
    lede:
      'Outlines drawn, casts assembled, type laid out. One more pass and these are ready to go under the press.',
  },
  running: {
    kicker: 'Field Work · In Simulation',
    headline: (
      <>
        Running through the<span style={{ fontStyle: 'italic', color: 'var(--red)' }}> press</span>.
      </>
    ),
    lede:
      'Agents are moving through the plate now. The room is loud, the edition is coming. You can leave this page — we’ll keep count.',
  },
  done: {
    kicker: 'Field Work · Archived',
    headline: (
      <>
        <span style={{ fontStyle: 'italic', color: 'var(--red)' }}>Filed</span>, with proofs on record.
      </>
    ),
    lede:
      'Dossiers that have been read, measured and filed. Their impressions are on the ledger and their interventions are on the desk.',
  },
  failed: {
    kicker: 'Errata · Returned',
    headline: (
      <>
        Sent back from the<span style={{ fontStyle: 'italic', color: 'var(--red)' }}> press</span>.
      </>
    ),
    lede:
      'These dossiers did not complete their impression. Open one to see what the press objected to, and set it again when it is ready.',
  },
}

/* ── Page ─────────────────────────────────────────────────────────── */
export default function ProjectsPageRoute() {
  return (
    <Suspense fallback={null}>
      <ProjectsPage />
    </Suspense>
  )
}

function ProjectsPage() {
  const [showModal, setShowModal] = useState(false)
  const [idea, setIdea] = useState('')

  const router = useRouter()
  const searchParams = useSearchParams()
  const rawFilter = (searchParams.get('filter') || 'all').toLowerCase()
  const activeFilter: Filter =
    (['all', 'draft', 'ready', 'running', 'done', 'failed'] as Filter[]).includes(rawFilter as Filter)
      ? (rawFilter as Filter)
      : 'all'

  const { data: projects, isLoading, isError, error } = useProjects()
  const createProject = useCreateProject()

  const sortedList = useMemo(() => {
    const list = projects ?? []
    return [...list].sort((a, b) => {
      const ad = a.created_at ? new Date(a.created_at).getTime() : 0
      const bd = b.created_at ? new Date(b.created_at).getTime() : 0
      return bd - ad
    })
  }, [projects])

  const countsByBucket = useMemo(() => {
    const c: Record<Filter, number> = { all: 0, draft: 0, ready: 0, running: 0, done: 0, failed: 0 }
    sortedList.forEach((p) => {
      c.all += 1
      c[resolveStatus(p.status).bucket] += 1
    })
    return c
  }, [sortedList])

  const filteredList = useMemo(() => {
    if (activeFilter === 'all') return sortedList
    return sortedList.filter((p) => resolveStatus(p.status).bucket === activeFilter)
  }, [sortedList, activeFilter])

  const handleCreate = async () => {
    const description = idea.trim()
    if (!description) return
    await createProject.mutateAsync({ description })
    setShowModal(false)
    setIdea('')
  }

  const setFilter = (f: Filter) => {
    const url = f === 'all' ? '/projects' : `/projects?filter=${f}`
    router.replace(url, { scroll: false })
  }

  /* ── Loading ────────────────────────────────────────────────────── */
  if (isLoading) {
    return (
      <div style={{ padding: '80px 48px', display: 'flex', gap: 12, alignItems: 'center', color: 'var(--ink-secondary)' }}>
        <Loader2 className="animate-spin" style={{ width: 14, height: 14 }} />
        <span style={{ fontSize: 10, letterSpacing: '0.24em', textTransform: 'uppercase' }}>Pulling the archive…</span>
      </div>
    )
  }

  /* ── Error ──────────────────────────────────────────────────────── */
  if (isError) {
    return (
      <div style={{ padding: '80px 48px' }}>
        <div className="kicker" style={{ color: 'var(--red)', marginBottom: 12 }}>Errata</div>
        <h1 className="font-serif" style={{ fontSize: 40, fontWeight: 800, fontStyle: 'italic', color: 'var(--ink)' }}>
          The press is silent.
        </h1>
        <p style={{ marginTop: 16, color: 'var(--ink-secondary)', maxWidth: 520 }}>{apiError(error)}</p>
      </div>
    )
  }

  const totalCount = sortedList.length
  const count = filteredList.length
  const [featured, ...rest] = filteredList as [Project | undefined, ...Project[]]
  const meta = headlineForFilter[activeFilter]
  const isFiltered = activeFilter !== 'all'

  return (
    <div
      className="rise"
      style={{
        padding: '48px 48px 120px',
        maxWidth: 1280,
        margin: '0 auto',
        position: 'relative',
      }}
    >
      {/* ─── Page header ──────────────────────────────────────── */}
      <section style={{ display: 'grid', gridTemplateColumns: '1fr auto', alignItems: 'end', gap: 40, marginBottom: 28 }}>
        <div>
          <div
            className="kicker"
            style={{ color: 'var(--red)', marginBottom: 18, display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}
          >
            <span style={{ width: 24, height: 0.5, background: 'var(--red)' }} />
            {meta.kicker}
            <span style={{ color: 'var(--ink-secondary)' }}>·</span>
            <span style={{ color: 'var(--ink-secondary)' }}>
              {count} {count === 1 ? 'entry' : 'entries'}
              {isFiltered && ` of ${totalCount}`}
            </span>
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
            {meta.headline}
          </h1>

          <p
            style={{
              fontFamily: 'var(--font-body)',
              fontSize: 15,
              lineHeight: 1.7,
              color: 'var(--ink-secondary)',
              maxWidth: 560,
              marginTop: 18,
              fontWeight: 300,
            }}
          >
            {meta.lede}
          </p>
        </div>

        <button onClick={() => setShowModal(true)} className="btn-ink" style={{ whiteSpace: 'nowrap' }}>
          <Plus style={{ width: 13, height: 13 }} /> File New Dossier
        </button>
      </section>

      {/* ─── Filter ribbon ──────────────────────────────────────── */}
      <FilterRibbon active={activeFilter} counts={countsByBucket} onChange={setFilter} />

      <div style={{ height: 3, background: 'var(--ink)', marginBottom: 4 }} />
      <div style={{ height: 0.5, background: 'var(--border-color)', marginBottom: 48 }} />

      {/* ─── Empty states ───────────────────────────────────────── */}
      {totalCount === 0 && <EmptyArchive onOpen={() => setShowModal(true)} />}

      {totalCount > 0 && count === 0 && (
        <EmptyForFilter filter={activeFilter} onClear={() => setFilter('all')} />
      )}

      {/* ─── Featured (lead) + index ──────────────────────────── */}
      {count > 0 && featured && (
        <>
          <FeaturedDossier project={featured} index={count} />
          <div style={{ height: 0.5, background: 'var(--border-color)', margin: '56px 0 40px' }} />

          {/* Index header */}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '96px minmax(0,1fr) 180px 140px 32px',
              gap: 32,
              paddingBottom: 16,
              borderBottom: '2px solid var(--ink)',
              marginBottom: 0,
            }}
          >
            <span className="kicker" style={{ color: 'var(--ink-secondary)' }}>№</span>
            <span className="kicker" style={{ color: 'var(--ink-secondary)' }}>Title / Précis</span>
            <span className="kicker" style={{ color: 'var(--ink-secondary)' }}>Filed</span>
            <span className="kicker" style={{ color: 'var(--ink-secondary)' }}>Status</span>
            <span />
          </div>

          {/* Index rows */}
          <div>
            {rest.map((project, i) => (
              <DossierRow key={project.id} project={project} number={count - 1 - i} />
            ))}
            {rest.length === 0 && (
              <p
                style={{
                  padding: '36px 0',
                  color: 'var(--ink-tertiary)',
                  fontSize: 13,
                  fontStyle: 'italic',
                  borderTop: '0.5px solid var(--border-color)',
                  borderBottom: '0.5px solid var(--border-color)',
                }}
              >
                No further entries in this volume.
              </p>
            )}
          </div>
        </>
      )}

      {/* ─── Modal ─────────────────────────────────────────────── */}
      <AnimatePresence>
        {showModal && (
          <FileDossierModal
            idea={idea}
            setIdea={setIdea}
            onClose={() => setShowModal(false)}
            onSubmit={handleCreate}
            pending={createProject.isPending}
          />
        )}
      </AnimatePresence>
    </div>
  )
}

/* ── Filter ribbon ─────────────────────────────────────────────── */
function FilterRibbon({
  active,
  counts,
  onChange,
}: {
  active: Filter
  counts: Record<Filter, number>
  onChange: (f: Filter) => void
}) {
  return (
    <div
      role="tablist"
      aria-label="Filter dossiers"
      style={{
        display: 'flex',
        flexWrap: 'wrap',
        alignItems: 'stretch',
        gap: 0,
        marginBottom: 24,
        borderTop: '0.5px solid var(--border-strong)',
        borderBottom: '0.5px solid var(--border-strong)',
        padding: '6px 0',
      }}
    >
      {filterTabs.map((tab, i) => {
        const isActive = active === tab.id
        const n = counts[tab.id] ?? 0
        const isLast = i === filterTabs.length - 1
        return (
          <button
            key={tab.id}
            role="tab"
            aria-selected={isActive}
            onClick={() => onChange(tab.id)}
            style={{
              flex: '1 1 160px',
              minWidth: 160,
              background: isActive ? 'var(--ink)' : 'transparent',
              color: isActive ? 'var(--paper)' : 'var(--ink)',
              border: 'none',
              borderRight: isLast ? 'none' : '0.5px solid var(--border-color)',
              padding: '14px 18px 12px',
              cursor: 'pointer',
              textAlign: 'left',
              transition: 'background 180ms ease, color 180ms ease',
              display: 'flex',
              flexDirection: 'column',
              gap: 4,
            }}
            className={`filter-tab ${isActive ? 'filter-tab--active' : ''}`}
          >
            <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 10 }}>
              <span
                className="font-serif"
                style={{
                  fontSize: 18,
                  fontWeight: 800,
                  fontStyle: isActive ? 'italic' : 'normal',
                  letterSpacing: '-0.01em',
                  lineHeight: 1,
                }}
              >
                {tab.label}
              </span>
              <span
                className="numeral"
                style={{
                  fontSize: 12,
                  fontWeight: 700,
                  color: isActive ? 'var(--paper)' : 'var(--red)',
                  opacity: isActive ? 0.75 : 1,
                }}
              >
                {String(n).padStart(2, '0')}
              </span>
            </div>
            <span
              className="kicker"
              style={{
                color: isActive ? 'rgba(242, 236, 224, 0.65)' : 'var(--ink-secondary)',
                fontSize: 9,
              }}
            >
              {tab.note}
            </span>
          </button>
        )
      })}
    </div>
  )
}

/* ── Empty for filter ──────────────────────────────────────────── */
function EmptyForFilter({ filter, onClear }: { filter: Filter; onClear: () => void }) {
  const copy: Record<Exclude<Filter, 'all'>, { title: string; body: string }> = {
    draft: {
      title: 'No drafts on the desk.',
      body: 'Every dossier has already moved past the first reading. Start a new idea, or look elsewhere in the archive.',
    },
    ready: {
      title: 'Nothing queued for press.',
      body: 'No outlines are sitting typeset and waiting. Open a draft and take it through the room.',
    },
    running: {
      title: 'The press is quiet.',
      body: 'No runs are in motion right now. File a dossier and send it under the plate to fill this column.',
    },
    done: {
      title: 'The archive room is empty.',
      body: 'Nothing has been filed with proofs yet. Once a dossier finishes its run, it lives here.',
    },
    failed: {
      title: 'No errata on file.',
      body: 'No run has been returned by the press. Good news — that is how you want it.',
    },
  }
  const c = filter === 'all' ? null : copy[filter]
  if (!c) return null

  return (
    <div
      style={{
        padding: '48px 0 40px',
        borderTop: '0.5px solid var(--border-color)',
        borderBottom: '0.5px solid var(--border-color)',
        display: 'grid',
        gridTemplateColumns: '1fr auto',
        gap: 32,
        alignItems: 'center',
        marginBottom: 40,
      }}
    >
      <div>
        <div className="kicker" style={{ color: 'var(--red)', marginBottom: 10 }}>
          Editor&rsquo;s note
        </div>
        <h2
          className="font-serif"
          style={{
            fontSize: 'clamp(28px, 3.2vw, 40px)',
            fontWeight: 900,
            fontStyle: 'italic',
            lineHeight: 1,
            letterSpacing: '-0.03em',
            color: 'var(--ink)',
            marginBottom: 12,
          }}
        >
          {c.title}
        </h2>
        <p style={{ fontSize: 14, lineHeight: 1.7, color: 'var(--ink-secondary)', maxWidth: 520, fontWeight: 300 }}>
          {c.body}
        </p>
      </div>
      <button onClick={onClear} className="btn-ghost" style={{ whiteSpace: 'nowrap' }}>
        Show full index
      </button>
    </div>
  )
}

/* ── Empty state (no projects at all) ───────────────────────────── */
function EmptyArchive({ onOpen }: { onOpen: () => void }) {
  return (
    <section
      style={{
        display: 'grid',
        gridTemplateColumns: '1fr 1fr',
        gap: 64,
        alignItems: 'start',
        paddingTop: 32,
        minHeight: 420,
      }}
    >
      <div>
        <div className="kicker" style={{ color: 'var(--red)', marginBottom: 20 }}>
          Editor&rsquo;s Note &nbsp;·&nbsp; No. 001
        </div>

        <h2
          className="font-serif"
          style={{
            fontSize: 'clamp(36px, 5vw, 60px)',
            fontWeight: 900,
            fontStyle: 'italic',
            lineHeight: 1,
            letterSpacing: '-0.03em',
            color: 'var(--ink)',
            marginBottom: 24,
          }}
        >
          &ldquo;The archive<br />is empty —<br />for now.&rdquo;
        </h2>

        <div style={{ height: 2, background: 'var(--red)', width: 80, marginBottom: 24 }} />

        <p
          className="dropcap"
          style={{
            fontSize: 15,
            lineHeight: 1.75,
            color: 'var(--ink)',
            maxWidth: 440,
            marginBottom: 28,
            fontWeight: 300,
          }}
        >
          Every issue begins with a single dossier. Describe the idea you cannot stop thinking about —
          a product, a pivot, a suspicion — and the press will cast it against a room of synthetic
          readers who have no reason to be kind. What returns is not a verdict. It is material.
        </p>

        <button onClick={onOpen} className="btn-ink">
          <Plus style={{ width: 13, height: 13 }} /> Begin The First Dossier
        </button>
      </div>

      <div style={{ paddingTop: 12 }}>
        <Folio />
      </div>
    </section>
  )
}

function Folio() {
  return (
    <div
      style={{
        position: 'relative',
        aspectRatio: '4 / 5',
        maxWidth: 420,
        marginLeft: 'auto',
        border: '0.5px solid var(--border-strong)',
        background:
          'repeating-linear-gradient(0deg, rgba(26,23,20,0.035) 0 0.5px, transparent 0.5px 28px)',
        padding: 28,
      }}
    >
      <div
        style={{
          position: 'absolute',
          top: -16,
          left: 28,
          padding: '4px 14px',
          background: 'var(--paper)',
          border: '0.5px solid var(--border-strong)',
          borderBottom: 'none',
          fontSize: 9,
          letterSpacing: '0.3em',
          textTransform: 'uppercase',
          color: 'var(--ink-secondary)',
          fontWeight: 600,
        }}
      >
        File · Vacant
      </div>

      <div
        style={{
          position: 'absolute',
          top: 36,
          right: 28,
          transform: 'rotate(-12deg)',
          border: '1.5px solid var(--red)',
          color: 'var(--red)',
          padding: '6px 14px',
          fontSize: 10,
          letterSpacing: '0.26em',
          textTransform: 'uppercase',
          fontWeight: 700,
          opacity: 0.85,
        }}
      >
        Awaiting Material
      </div>

      <div style={{ marginTop: 88, display: 'flex', flexDirection: 'column', gap: 18 }}>
        {[92, 78, 85, 62, 0, 70, 55].map((w, i) => (
          <div
            key={i}
            style={{
              height: 0.5,
              width: `${w}%`,
              background: w === 0 ? 'transparent' : 'var(--border-strong)',
              minHeight: 0.5,
            }}
          />
        ))}
      </div>

      <div
        className="numeral"
        style={{
          position: 'absolute',
          bottom: 18,
          right: 24,
          fontSize: 120,
          color: 'var(--ink)',
          opacity: 0.05,
          lineHeight: 0.8,
        }}
      >
        00
      </div>
    </div>
  )
}

/* ── Featured dossier (lead story) ───────────────────────────────── */
function FeaturedDossier({ project, index }: { project: Project; index: number }) {
  const status = resolveStatus(project.status)
  const date = project.created_at ? new Date(project.created_at) : null
  const num = String(index).padStart(3, '0')

  return (
    <Link
      href={`/project/${project.id}`}
      className="rise rise-1"
      style={{
        textDecoration: 'none',
        color: 'var(--ink)',
        display: 'grid',
        gridTemplateColumns: '1.5fr 1fr',
        gap: 48,
        alignItems: 'start',
        padding: '8px 0',
      }}
    >
      <div>
        <div className="kicker" style={{ color: 'var(--red)', marginBottom: 16, display: 'flex', alignItems: 'center', gap: 10 }}>
          Lead Dossier · This Issue
          <span className={`status-dot status-dot--${status.bucket}`} />
          <span>{status.label}</span>
        </div>

        <h2
          className="font-serif"
          style={{
            fontSize: 'clamp(38px, 4.8vw, 64px)',
            fontWeight: 900,
            lineHeight: 1,
            letterSpacing: '-0.03em',
            color: 'var(--ink)',
            marginBottom: 20,
          }}
        >
          {project.title}
        </h2>

        <p
          style={{
            fontFamily: 'var(--font-body)',
            fontSize: 15,
            lineHeight: 1.75,
            color: 'var(--ink-secondary)',
            maxWidth: 640,
            marginBottom: 28,
            fontWeight: 300,
            display: '-webkit-box',
            WebkitLineClamp: 4,
            WebkitBoxOrient: 'vertical',
            overflow: 'hidden',
          }}
        >
          {project.description}
        </p>

        <div style={{ display: 'flex', alignItems: 'center', gap: 14, color: 'var(--ink)' }}>
          <span
            style={{
              fontSize: 10,
              letterSpacing: '0.26em',
              textTransform: 'uppercase',
              fontWeight: 600,
              borderBottom: '1.5px solid var(--ink)',
              paddingBottom: 3,
            }}
          >
            Open the full report
          </span>
          <ArrowUpRight style={{ width: 18, height: 18 }} />
        </div>
      </div>

      <div style={{ textAlign: 'right', position: 'relative', paddingTop: 8 }}>
        <div
          className="numeral"
          style={{
            fontSize: 'clamp(140px, 16vw, 220px)',
            color: 'var(--ink)',
            lineHeight: 0.85,
            letterSpacing: '-0.06em',
          }}
        >
          {num}
        </div>

        <div
          style={{
            marginTop: 16,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'flex-end',
            gap: 8,
            fontSize: 10,
            letterSpacing: '0.22em',
            textTransform: 'uppercase',
            color: 'var(--ink-secondary)',
            fontWeight: 500,
          }}
        >
          <div>
            Filed ·{' '}
            <span style={{ color: 'var(--ink)' }}>
              {date
                ? date.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
                : '—'}
            </span>
          </div>
          <div>
            Section · <span style={{ color: 'var(--red)' }}>Idea Review</span>
          </div>
          <div style={{ width: 60, height: 2, background: 'var(--red)', marginTop: 4 }} />
        </div>
      </div>
    </Link>
  )
}

/* ── Index row ───────────────────────────────────────────────────── */
function DossierRow({ project, number }: { project: Project; number: number }) {
  const status = resolveStatus(project.status)
  const date = project.created_at ? new Date(project.created_at) : null
  const num = String(number).padStart(3, '0')

  return (
    <Link href={`/project/${project.id}`} style={{ textDecoration: 'none', color: 'var(--ink)', display: 'block' }}>
      <div className="dossier-row">
        <span className="dossier-rule" />

        <div className="numeral dossier-numeral" style={{ fontSize: 44, color: 'var(--ink)' }}>
          {num}
        </div>

        <div style={{ minWidth: 0 }}>
          <h3
            className="font-serif"
            style={{
              fontSize: 26,
              fontWeight: 800,
              lineHeight: 1.1,
              letterSpacing: '-0.02em',
              color: 'var(--ink)',
              marginBottom: 8,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {project.title}
          </h3>
          <p
            style={{
              fontSize: 13.5,
              lineHeight: 1.65,
              color: 'var(--ink-secondary)',
              fontWeight: 300,
              display: '-webkit-box',
              WebkitLineClamp: 2,
              WebkitBoxOrient: 'vertical',
              overflow: 'hidden',
            }}
          >
            {project.description}
          </p>
        </div>

        <div
          style={{
            fontSize: 11,
            letterSpacing: '0.18em',
            textTransform: 'uppercase',
            color: 'var(--ink-secondary)',
            fontWeight: 500,
            paddingTop: 8,
          }}
        >
          {date ? (
            <>
              <div style={{ color: 'var(--ink)', fontWeight: 600 }}>
                {date.toLocaleDateString('en-GB', { day: '2-digit', month: 'short' })}
              </div>
              <div style={{ marginTop: 3 }}>{date.getFullYear()}</div>
            </>
          ) : (
            '—'
          )}
        </div>

        <div
          style={{
            fontSize: 10,
            letterSpacing: '0.22em',
            textTransform: 'uppercase',
            fontWeight: 600,
            color: status.bucket === 'failed' ? 'var(--red)' : 'var(--ink)',
            paddingTop: 10,
            display: 'flex',
            alignItems: 'center',
          }}
        >
          <span className={`status-dot status-dot--${status.bucket}`} />
          {status.label}
        </div>

        <div className="dossier-arrow" style={{ paddingTop: 10, color: 'var(--ink-tertiary)' }}>
          <ArrowUpRight style={{ width: 18, height: 18 }} />
        </div>
      </div>
    </Link>
  )
}

/* ── Modal: File New Dossier ─────────────────────────────────────── */
function FileDossierModal({
  idea,
  setIdea,
  onClose,
  onSubmit,
  pending,
}: {
  idea: string
  setIdea: (s: string) => void
  onClose: () => void
  onSubmit: () => void
  pending: boolean
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
        style={{
          position: 'fixed',
          inset: 0,
          background: 'rgba(26,23,20,0.08)',
          zIndex: 100,
        }}
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
          style={{
            width: 'min(640px, 100%)',
            maxHeight: 'calc(100vh - 48px)',
            background: 'var(--paper)',
            border: '0.5px solid var(--ink)',
            boxShadow: '24px 24px 0 rgba(26,23,20,0.12)',
            padding: '28px 36px 24px',
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden',
            pointerEvents: 'auto',
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              paddingBottom: 12,
              borderBottom: '2px solid var(--ink)',
              marginBottom: 6,
              flexShrink: 0,
            }}
          >
            <div className="kicker" style={{ color: 'var(--red)' }}>
              Submission · Editor&rsquo;s Desk
            </div>
            <button
              onClick={onClose}
              aria-label="Close"
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
          <div style={{ height: 0.5, background: 'var(--border-color)', marginBottom: 18, flexShrink: 0 }} />

          <div style={{ overflowY: 'auto', minHeight: 0, paddingRight: 2 }}>
            <h2
              className="font-serif"
              style={{
                fontSize: 'clamp(28px, 3vw, 40px)',
                fontWeight: 900,
                lineHeight: 1,
                letterSpacing: '-0.03em',
                color: 'var(--ink)',
                marginBottom: 12,
              }}
            >
              File a new<span style={{ fontStyle: 'italic', color: 'var(--red)' }}> dossier.</span>
            </h2>
            <p style={{ fontSize: 13.5, lineHeight: 1.65, color: 'var(--ink-secondary)', marginBottom: 18, fontWeight: 300 }}>
              Describe your idea in plain language — one paragraph. The press will read it as if a
              stranger handed it across a café table.
            </p>

            <label className="kicker" style={{ color: 'var(--ink-secondary)', display: 'block', marginBottom: 8 }}>
              The Idea
            </label>
            <textarea
              value={idea}
              onChange={(e) => setIdea(e.target.value)}
              placeholder="We&rsquo;re building a&nbsp;…"
              rows={5}
              autoFocus
              style={{
                width: '100%',
                padding: '14px 16px',
                background: 'rgba(26,23,20,0.03)',
                border: '0.5px solid var(--border-strong)',
                borderRadius: 0,
                fontFamily: 'var(--font-serif)',
                fontSize: 18,
                fontStyle: 'italic',
                lineHeight: 1.55,
                color: 'var(--ink)',
                outline: 'none',
                resize: 'none',
                fontWeight: 500,
              }}
              onFocus={(e) => (e.currentTarget.style.borderColor = 'var(--ink)')}
              onBlur={(e) => (e.currentTarget.style.borderColor = 'var(--border-strong)')}
            />
          </div>

          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              marginTop: 18,
              gap: 16,
              flexShrink: 0,
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
              {idea.trim().length} characters
            </div>
            <div style={{ display: 'flex', gap: 12 }}>
              <button onClick={onClose} className="btn-ghost" type="button">
                Withdraw
              </button>
              <button
                onClick={onSubmit}
                disabled={!idea.trim() || pending}
                className="btn-ink"
                type="button"
              >
                {pending ? (
                  <>
                    <Loader2 className="animate-spin" style={{ width: 12, height: 12 }} /> Filing…
                  </>
                ) : (
                  <>
                    Send to Press <ArrowUpRight style={{ width: 13, height: 13 }} />
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      </motion.div>
    </>,
    document.body,
  )
}
