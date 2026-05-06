'use client'

import { useEffect, useMemo, useState } from 'react'
import { motion } from 'framer-motion'
import { ArrowUpRight, FileText, Hourglass, Layers, Loader2, Plus, Radio } from 'lucide-react'
import Link from 'next/link'

import { FolioAxisChip } from '@/components/FolioAxisChip'
import { useProjects } from '@/hooks/useProjects'
import { editorialTruncate } from '@/lib/typography'
import { useAuthStore } from '@/store/auth.store'
import type { Project } from '@/types'

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

const resolveStatus = (s: string) =>
  statusMeta[s] ?? { bucket: 'draft' as StatusBucket, label: s.toLowerCase().replace(/_/g, ' ') }

/** Local wall-clock hour (0–23); `Date` in the browser uses the user’s timezone. */
function salutationForHour(hour: number): string {
  if (hour >= 5 && hour < 12) return 'Good morning'
  if (hour >= 12 && hour < 17) return 'Good afternoon'
  if (hour >= 17 && hour < 21) return 'Good evening'
  return 'Good night' /* 21:00–04:59 */
}

export default function DashboardPage() {
  const { data: projects, isLoading } = useProjects()
  const user = useAuthStore((s) => s.user)

  /* Same string on server + first client paint avoids hydration mismatch; then snap to local time. */
  const [salutation, setSalutation] = useState('Good morning')
  useEffect(() => {
    setSalutation(salutationForHour(new Date().getHours()))
  }, [])

  const todayLong = new Date().toLocaleDateString('en-GB', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  })

  const { counts, featured, running, recent } = useMemo(() => {
    const list = [...(projects ?? [])].sort((a, b) => {
      const ad = a.created_at ? new Date(a.created_at).getTime() : 0
      const bd = b.created_at ? new Date(b.created_at).getTime() : 0
      return bd - ad
    })
    const counts: Record<StatusBucket | 'total', number> = {
      total: list.length,
      draft: 0,
      ready: 0,
      running: 0,
      done: 0,
      failed: 0,
    }
    list.forEach((p) => {
      counts[resolveStatus(p.status).bucket] += 1
    })
    const featured = list.find((p) => resolveStatus(p.status).bucket !== 'draft') ?? list[0]
    const running = list.filter((p) => resolveStatus(p.status).bucket === 'running').slice(0, 4)
    /* Rank reflects creation order (oldest = 1) so the dashboard № matches the
       dossier's own identity used elsewhere — not its position in the newest-first feed. */
    const recent = list.slice(0, 5).map((project, i) => ({ project, rank: list.length - i }))
    return { counts, featured, running, recent }
  }, [projects])

  if (isLoading) {
    return (
      <div
        style={{
          padding: '80px 48px',
          display: 'flex',
          gap: 12,
          alignItems: 'center',
          color: 'var(--ink-secondary)',
        }}
      >
        <Loader2 className="animate-spin" style={{ width: 14, height: 14 }} />
        <span className="kicker">Assembling the front page…</span>
      </div>
    )
  }

  const firstName = user?.full_name?.split(' ')[0] || 'Editor'

  return (
    <div className="rise" style={{ padding: '48px 48px 120px', maxWidth: 1280, margin: '0 auto' }}>
      {/* ─── Masthead for the dashboard (front page) ─────────────────── */}
      <section
        style={{
          display: 'grid',
          gridTemplateColumns: '1fr auto',
          alignItems: 'end',
          gap: 32,
          marginBottom: 28,
        }}
      >
        <div>
          <div
            className="kicker"
            style={{
              color: 'var(--red)',
              marginBottom: 18,
              display: 'flex',
              alignItems: 'center',
              gap: 12,
              flexWrap: 'wrap',
            }}
          >
            <span style={{ width: 24, height: 0.5, background: 'var(--red)' }} />
            The Daily Impression
            <span style={{ color: 'var(--ink-secondary)' }}>·</span>
            <span style={{ color: 'var(--ink-secondary)' }}>{todayLong}</span>
          </div>

          <h1
            className="font-serif"
            style={{
              fontSize: 'clamp(48px, 6.4vw, 80px)',
              fontWeight: 900,
              lineHeight: 0.95,
              letterSpacing: '-0.035em',
              color: 'var(--ink)',
              marginBottom: 8,
            }}
          >
            {salutation},{' '}
            <span style={{ fontStyle: 'italic', color: 'var(--red)' }}>{firstName}</span>.
          </h1>
          <p
            style={{
              fontFamily: 'var(--font-body)',
              fontSize: 15,
              lineHeight: 1.7,
              color: 'var(--ink-secondary)',
              maxWidth: 560,
              marginTop: 16,
              fontWeight: 300,
            }}
          >
            A summary of the desk: what is on your bench, what is running at the press, and what has
            just come back filed. Pick up where yesterday left a mark.
          </p>
        </div>
        <Link
          href="/projects"
          className="btn-ink"
          style={{ whiteSpace: 'nowrap', alignItems: 'center', display: 'inline-flex', gap: 10 }}
        >
          <Plus style={{ width: 13, height: 13 }} /> File new dossier
        </Link>
      </section>

      <div style={{ height: 3, background: 'var(--ink)', marginBottom: 4 }} />
      <div style={{ height: 0.5, background: 'var(--border-color)', marginBottom: 40 }} />

      {/* ─── Stat strip ─────────────────────────────────────────────── */}
      <StatsStrip
        total={counts.total}
        drafts={counts.draft + counts.ready}
        running={counts.running}
        done={counts.done}
      />

      {/* ─── Two column body: lead + side rail ─────────────────────── */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'minmax(0, 2fr) minmax(0, 1fr)',
          gap: 56,
          marginTop: 48,
          minWidth: 0,
        }}
      >
        {/* Lead — minWidth:0 so long headlines wrap instead of clipping (grid + body overflow-x) */}
        <div style={{ minWidth: 0 }}>
          <SectionTitle kicker="Lead dossier" title="The one on the press today." />
          {featured ? (
            <FeaturedLead project={featured} />
          ) : (
            <EmptyFeatured />
          )}

          <div style={{ height: 0.5, background: 'var(--border-color)', margin: '48px 0 28px' }} />

          <SectionTitle kicker="Recent filings" title="What you left on the desk." />
          {recent.length === 0 ? (
            <p
              style={{
                fontSize: 13,
                fontStyle: 'italic',
                color: 'var(--ink-tertiary)',
                padding: '24px 0',
              }}
            >
              Nothing yet. The page is wide open.
            </p>
          ) : (
            <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
              {recent.map(({ project, rank }) => (
                <RecentLine key={project.id} project={project} rank={rank} />
              ))}
            </ul>
          )}
        </div>

        {/* Side rail */}
        <aside style={{ display: 'flex', flexDirection: 'column', gap: 40 }}>
          <AtPressCard running={running} />
          <BreakdownCard counts={counts} />
          <QuickLinks />
        </aside>
      </div>
    </div>
  )
}

/* ── Small section header ────────────────────────────────────────── */
function SectionTitle({ kicker, title }: { kicker: string; title: string }) {
  return (
    <header style={{ marginBottom: 20 }}>
      <div className="kicker" style={{ color: 'var(--red)', marginBottom: 10 }}>
        {kicker}
      </div>
      <h2
        className="font-serif"
        style={{
          fontSize: 'clamp(22px, 2.4vw, 30px)',
          fontWeight: 900,
          fontStyle: 'italic',
          lineHeight: 1,
          letterSpacing: '-0.02em',
          color: 'var(--ink)',
        }}
      >
        {title}
      </h2>
      <div style={{ height: 2, background: 'var(--red)', width: 40, marginTop: 10 }} />
    </header>
  )
}

/* ── Stats strip (big editorial numbers) ─────────────────────────── */
function StatsStrip({
  total,
  drafts,
  running,
  done,
}: {
  total: number
  drafts: number
  running: number
  done: number
}) {
  const cells: { label: string; value: number; hint: string; href: string; icon: React.ComponentType<{ style?: React.CSSProperties }> }[] =
    [
      { label: 'On file', value: total, hint: 'Dossiers in the archive', href: '/projects', icon: FileText },
      { label: 'On the bench', value: drafts, hint: 'Drafts and proofs waiting', href: '/projects?filter=draft', icon: Layers },
      { label: 'At press', value: running, hint: 'Currently running', href: '/projects?filter=running', icon: Radio },
      { label: 'Filed', value: done, hint: 'Complete with proofs', href: '/projects?filter=done', icon: Hourglass },
    ]
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(4, 1fr)',
        borderTop: '0.5px solid var(--border-strong)',
        borderBottom: '0.5px solid var(--border-strong)',
      }}
    >
      {cells.map((c, i) => {
        const Icon = c.icon
        return (
          <Link
            key={c.label}
            href={c.href}
            className="stat-cell"
            style={{
              padding: '22px 24px 20px',
              display: 'flex',
              flexDirection: 'column',
              gap: 8,
              borderRight: i < cells.length - 1 ? '0.5px solid var(--border-color)' : 'none',
              textDecoration: 'none',
              color: 'var(--ink)',
              transition: 'background 180ms ease',
              position: 'relative',
            }}
          >
            <div className="kicker" style={{ color: 'var(--ink-secondary)', display: 'flex', alignItems: 'center', gap: 8 }}>
              <Icon style={{ width: 12, height: 12, color: 'var(--red)' }} />
              {c.label}
            </div>
            <div
              className="numeral"
              style={{
                fontSize: 'clamp(40px, 5vw, 64px)',
                fontWeight: 800,
                color: 'var(--ink)',
                lineHeight: 1,
                letterSpacing: '-0.04em',
              }}
            >
              {String(c.value).padStart(2, '0')}
            </div>
            <div style={{ fontSize: 12, color: 'var(--ink-tertiary)' }}>{c.hint}</div>
          </Link>
        )
      })}
    </div>
  )
}

/* ── Featured lead card ──────────────────────────────────────────── */
function FeaturedLead({ project }: { project: Project }) {
  const status = resolveStatus(project.status)
  const date = project.created_at ? new Date(project.created_at) : null

  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }}>
      <Link
        href={`/project/${project.id}`}
        style={{
          display: 'block',
          minWidth: 0,
          textDecoration: 'none',
          color: 'var(--ink)',
          border: '0.5px solid var(--border-strong)',
          background: 'var(--paper)',
          padding: 32,
          boxShadow: '16px 16px 0 rgba(26,23,20,0.08)',
          transition: 'transform 260ms ease, box-shadow 260ms ease',
          overflow: 'visible',
        }}
        className="rise rise-1"
        onMouseEnter={(e) => {
          e.currentTarget.style.transform = 'translate(-3px, -3px)'
          e.currentTarget.style.boxShadow = '15px 15px 0 var(--ink)'
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.transform = 'translate(0, 0)'
          e.currentTarget.style.boxShadow = '16px 16px 0 rgba(26,23,20,0.08)'
        }}
      >
        <div className="kicker" style={{ color: 'var(--red)', marginBottom: 10, display: 'flex', gap: 10, alignItems: 'center' }}>
          This Issue
          <span className={`status-dot status-dot--${status.bucket}`} />
          <span>{status.label}</span>
        </div>
        <div style={{ marginBottom: 12 }}>
          <FolioAxisChip axis={project.dossier_axis} />
        </div>
        <h3
          className="font-serif overflow-hidden break-words leading-tight"
          style={{
            fontSize: 'clamp(28px, 3.4vw, 44px)',
            fontWeight: 900,
            letterSpacing: '-0.03em',
            color: 'var(--ink)',
            marginBottom: 16,
            maxWidth: '100%',
          }}
        >
          {editorialTruncate(project.title, 10)}
        </h3>
        <p
          style={{
            fontSize: 14.5,
            lineHeight: 1.75,
            color: 'var(--ink-secondary)',
            fontWeight: 300,
            display: '-webkit-box',
            WebkitLineClamp: 3,
            WebkitBoxOrient: 'vertical',
            overflow: 'hidden',
            marginBottom: 22,
          }}
        >
          {project.description}
        </p>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            paddingTop: 16,
            borderTop: '0.5px solid var(--border-color)',
          }}
        >
          <span
            className="kicker"
            style={{
              color: 'var(--ink-tertiary)',
            }}
          >
            {date ? date.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }) : '—'}
          </span>
          <span
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 8,
              fontSize: 11,
              fontWeight: 600,
              letterSpacing: '0.22em',
              textTransform: 'uppercase',
              color: 'var(--ink)',
              borderBottom: '1.5px solid var(--ink)',
              paddingBottom: 3,
            }}
          >
            Open report
            <ArrowUpRight style={{ width: 14, height: 14 }} />
          </span>
        </div>
      </Link>
    </motion.div>
  )
}

/* ── Empty featured ──────────────────────────────────────────────── */
function EmptyFeatured() {
  return (
    <div
      style={{
        border: '0.5px dashed var(--border-strong)',
        padding: 36,
        display: 'flex',
        flexDirection: 'column',
        gap: 14,
        alignItems: 'flex-start',
        background:
          'repeating-linear-gradient(0deg, rgba(26,23,20,0.025) 0 0.5px, transparent 0.5px 28px)',
      }}
    >
      <div className="kicker" style={{ color: 'var(--red)' }}>Nothing filed yet</div>
      <h3
        className="font-serif"
        style={{
          fontSize: 28,
          fontWeight: 900,
          fontStyle: 'italic',
          color: 'var(--ink)',
          letterSpacing: '-0.02em',
          lineHeight: 1,
        }}
      >
        The page is wide open.
      </h3>
      <p style={{ fontSize: 14, color: 'var(--ink-secondary)', lineHeight: 1.6, maxWidth: 420 }}>
        Start with any idea you cannot stop turning over. One paragraph is enough to begin.
      </p>
      <Link href="/projects" className="btn-ink" style={{ marginTop: 4 }}>
        <Plus style={{ width: 13, height: 13 }} /> File the first dossier
      </Link>
    </div>
  )
}

/* ── Recent line ─────────────────────────────────────────────────── */
function RecentLine({ project, rank }: { project: Project; rank: number }) {
  const status = resolveStatus(project.status)
  const date = project.created_at ? new Date(project.created_at) : null
  const num = String(rank).padStart(2, '0')
  return (
    <li>
      <Link
        href={`/project/${project.id}`}
        style={{
          display: 'grid',
          gridTemplateColumns: '3rem minmax(0,1fr) 110px 120px 24px',
          gap: 16,
          alignItems: 'start',
          padding: '14px 0',
          borderBottom: '0.5px solid var(--border-color)',
          textDecoration: 'none',
          color: 'var(--ink)',
        }}
        className="recent-line"
      >
        <span
          className="numeral"
          aria-hidden
          style={{
            fontSize: 18,
            fontWeight: 800,
            color: 'var(--ink)',
            lineHeight: 1.2,
            paddingTop: 2,
            fontFeatureSettings: "'lnum' 1, 'tnum' 1",
          }}
        >
          {num}
        </span>
        <span
          className="font-serif"
          style={{
            fontSize: 17,
            fontWeight: 700,
            letterSpacing: '-0.01em',
            lineHeight: 1.4,
            display: '-webkit-box',
            WebkitLineClamp: 2,
            WebkitBoxOrient: 'vertical',
            overflow: 'hidden',
            overflowWrap: 'anywhere',
            minWidth: 0,
          }}
        >
          {project.title}
        </span>
        <span
          className="kicker"
          style={{ color: 'var(--ink-tertiary)', fontSize: 10 }}
        >
          {date ? date.toLocaleDateString('en-GB', { day: '2-digit', month: 'short' }) : '—'}
        </span>
        <span
          style={{
            fontSize: 10,
            letterSpacing: '0.2em',
            textTransform: 'uppercase',
            fontWeight: 600,
            color: status.bucket === 'failed' ? 'var(--red)' : 'var(--ink)',
            display: 'flex',
            alignItems: 'center',
          }}
        >
          <span className={`status-dot status-dot--${status.bucket}`} />
          {status.label}
        </span>
        <ArrowUpRight style={{ width: 14, height: 14, color: 'var(--ink-tertiary)' }} />
      </Link>
    </li>
  )
}

/* ── Side rail: At press card ────────────────────────────────────── */
function AtPressCard({ running }: { running: Project[] }) {
  return (
    <div
      style={{
        border: '0.5px solid var(--ink)',
        background: 'var(--paper-dark)',
        padding: '20px 20px 18px',
      }}
      className="rise rise-2"
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          paddingBottom: 12,
          borderBottom: '0.5px solid var(--border-strong)',
          marginBottom: 14,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Radio style={{ width: 14, height: 14, color: 'var(--red)' }} />
          <span className="kicker" style={{ color: 'var(--ink)', letterSpacing: '0.22em' }}>
            At press
          </span>
        </div>
        <Link
          href="/projects?filter=running"
          className="kicker"
          style={{ color: 'var(--ink-tertiary)', textDecoration: 'none' }}
        >
          All →
        </Link>
      </div>

      {running.length === 0 ? (
        <p
          style={{
            fontSize: 13,
            fontStyle: 'italic',
            color: 'var(--ink-tertiary)',
            lineHeight: 1.6,
            paddingBottom: 6,
          }}
        >
          The press is idle. No runs moving through the plate right now.
        </p>
      ) : (
        <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: 10 }}>
          {running.map((p) => (
            <li key={p.id}>
              <Link
                href={`/project/${p.id}/simulation`}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                  textDecoration: 'none',
                  color: 'var(--ink)',
                }}
              >
                <span
                  style={{
                    width: 6,
                    height: 6,
                    borderRadius: '50%',
                    background: 'var(--red)',
                    flexShrink: 0,
                    boxShadow: '0 0 0 3px rgba(192,57,43,0.15)',
                    animation: 'pulse-red 1.6s ease-in-out infinite',
                  }}
                />
                <span
                  className="font-serif"
                  style={{
                    fontSize: 15,
                    fontWeight: 700,
                    fontStyle: 'italic',
                    lineHeight: 1.2,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                    flex: 1,
                    minWidth: 0,
                  }}
                >
                  {p.title}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/* ── Side rail: Breakdown card ───────────────────────────────────── */
function BreakdownCard({ counts }: { counts: Record<StatusBucket | 'total', number> }) {
  const rows: { label: string; count: number; href: string; color: string }[] = [
    { label: 'Drafts',       count: counts.draft,   href: '/projects?filter=draft',   color: 'var(--ink)' },
    { label: 'Ready',        count: counts.ready,   href: '/projects?filter=ready',   color: 'var(--ink)' },
    { label: 'In simulation',count: counts.running, href: '/projects?filter=running', color: 'var(--red)' },
    { label: 'Archived',     count: counts.done,    href: '/projects?filter=done',    color: 'var(--ink)' },
    { label: 'Returned',     count: counts.failed,  href: '/projects?filter=failed',  color: 'var(--red)' },
  ]
  const max = Math.max(1, ...rows.map((r) => r.count))
  return (
    <div style={{ borderTop: '0.5px solid var(--border-strong)', paddingTop: 18 }} className="rise rise-3">
      <div className="kicker" style={{ color: 'var(--red)', marginBottom: 14 }}>
        Breakdown
      </div>
      <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: 10 }}>
        {rows.map((r) => (
          <li key={r.label}>
            <Link
              href={r.href}
              style={{
                display: 'grid',
                gridTemplateColumns: '110px 1fr 32px',
                alignItems: 'center',
                gap: 10,
                textDecoration: 'none',
                color: 'var(--ink)',
              }}
            >
              <span
                style={{
                  fontSize: 12,
                  fontWeight: 500,
                  color: 'var(--ink-secondary)',
                }}
              >
                {r.label}
              </span>
              <span
                style={{
                  height: 3,
                  background: 'rgba(26,23,20,0.06)',
                  overflow: 'hidden',
                }}
              >
                <span
                  style={{
                    display: 'block',
                    height: '100%',
                    width: `${(r.count / max) * 100}%`,
                    background: r.color,
                    transition: 'width 400ms ease',
                  }}
                />
              </span>
              <span
                className="numeral"
                style={{
                  fontSize: 13,
                  fontWeight: 700,
                  color: r.count === 0 ? 'var(--ink-tertiary)' : r.color,
                  textAlign: 'right',
                }}
              >
                {String(r.count).padStart(2, '0')}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  )
}

/* ── Side rail: Quick links ──────────────────────────────────────── */
function QuickLinks() {
  const links: { label: string; href: string; hint: string }[] = [
    { label: 'The archive index', href: '/projects', hint: 'Every dossier you have filed' },
    { label: 'Drafts on the desk', href: '/projects?filter=draft', hint: 'Pick up where you left off' },
    { label: 'Style & Method', href: '/help', hint: 'How the press reads your ideas' },
    { label: 'Settings', href: '/settings', hint: 'The press office' },
  ]
  return (
    <div
      style={{
        borderTop: '0.5px solid var(--border-strong)',
        paddingTop: 18,
      }}
      className="rise rise-4"
    >
      <div className="kicker" style={{ color: 'var(--red)', marginBottom: 14 }}>
        Desk shortcuts
      </div>
      <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: 10 }}>
        {links.map((l) => (
          <li key={l.href}>
            <Link
              href={l.href}
              style={{
                display: 'flex',
                alignItems: 'baseline',
                justifyContent: 'space-between',
                gap: 12,
                padding: '8px 0',
                borderBottom: '0.5px dashed var(--border-color)',
                textDecoration: 'none',
                color: 'var(--ink)',
              }}
            >
              <span>
                <span
                  className="font-serif"
                  style={{ fontSize: 15, fontWeight: 700, letterSpacing: '-0.01em' }}
                >
                  {l.label}
                </span>
                <span
                  style={{
                    display: 'block',
                    fontSize: 11,
                    color: 'var(--ink-tertiary)',
                    marginTop: 2,
                    letterSpacing: '0.08em',
                    textTransform: 'uppercase',
                    fontWeight: 500,
                  }}
                >
                  {l.hint}
                </span>
              </span>
              <ArrowUpRight style={{ width: 14, height: 14, color: 'var(--ink-tertiary)' }} />
            </Link>
          </li>
        ))}
      </ul>
    </div>
  )
}
