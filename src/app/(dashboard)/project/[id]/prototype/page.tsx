'use client'

import { useState } from 'react'
import { motion } from 'framer-motion'
import { Monitor, Smartphone, ArrowRight, ArrowLeft, Loader2 } from 'lucide-react'
import Link from 'next/link'
import { useParams } from 'next/navigation'

import { useProject } from '@/hooks/useProjects'

/**
 * Editorial fallback when the API has not yet typeset a prototype HTML.
 * Matches the workspace "Archive" paper / ink / red rule language.
 */
const MOCK_HTML = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Reader's proof — TheCee</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: Georgia, 'Times New Roman', serif;
    background: #f2ece0;
    color: #1a1714;
    min-height: 100vh;
  }
  .mast { border-bottom: 2px solid #1a1714; padding: 18px 28px 14px; }
  .kicker {
    font-family: system-ui, sans-serif;
    font-size: 9px;
    letter-spacing: 0.28em;
    text-transform: uppercase;
    color: #c0392b;
    font-weight: 600;
    margin-bottom: 10px;
  }
  .wordmark { font-size: 26px; font-weight: 900; letter-spacing: -0.03em; }
  .wordmark span { color: #c0392b; }
  .rule-red { height: 2px; background: #c0392b; margin-top: 12px; }
  main { max-width: 720px; margin: 0 auto; padding: 48px 28px 80px; }
  h1 {
    font-size: clamp(32px, 5vw, 52px);
    font-weight: 900;
    line-height: 0.98;
    letter-spacing: -0.035em;
    margin-bottom: 18px;
  }
  h1 em { font-style: italic; color: #c0392b; }
  .lead {
    font-family: system-ui, sans-serif;
    font-weight: 300;
    font-size: 15px;
    line-height: 1.75;
    color: #6b6560;
    max-width: 48ch;
    margin-bottom: 32px;
  }
  .lead::first-letter {
    float: left;
    font-family: Georgia, serif;
    font-size: 3.4em;
    line-height: 0.85;
    padding-right: 10px;
    font-weight: 800;
    color: #1a1714;
  }
  .folio {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 1px;
    background: rgba(26,23,20,0.18);
    border: 0.5px solid rgba(26,23,20,0.25);
    margin-top: 40px;
  }
  .folio article {
    background: #f2ece0;
    padding: 22px 18px;
  }
  .folio h3 {
    font-size: 11px;
    letter-spacing: 0.2em;
    text-transform: uppercase;
    font-family: system-ui, sans-serif;
    color: #c0392b;
    margin-bottom: 10px;
    font-weight: 600;
  }
  .folio p { font-size: 14px; line-height: 1.55; color: #4a4540; }
  .stamp {
    display: inline-block;
    margin-top: 36px;
    border: 1.5px solid #c0392b;
    color: #c0392b;
    padding: 6px 14px;
    font-family: system-ui, sans-serif;
    font-size: 9px;
    letter-spacing: 0.26em;
    text-transform: uppercase;
    font-weight: 700;
    transform: rotate(-3deg);
    opacity: 0.9;
  }
</style>
</head>
<body>
  <header class="mast">
    <div class="kicker">Reader's proof · Plate not yet filed</div>
    <div class="wordmark">TheCee<span>.</span></div>
    <div class="rule-red"></div>
  </header>
  <main>
    <h1>Your headline <em>still</em> goes here.</h1>
    <p class="lead">
      This is a standing type block — a placeholder until the press returns your real page.
      When the prototype is generated, this entire sheet is replaced with your idea as the synthetic reader sees it.
    </p>
    <div class="folio">
      <article><h3>Column I</h3><p>First argument in favour — crisp, declarative, no decoration.</p></article>
      <article><h3>Column II</h3><p>Second tension — what the room might doubt before they buy.</p></article>
      <article><h3>Column III</h3><p>Third move — the line that turns a browser into a believer.</p></article>
    </div>
    <div class="stamp">Awaiting impression</div>
  </main>
</body>
</html>`

export default function PrototypePage() {
  const params = useParams()
  const projectId = Number(params.id)

  const { data: project, isLoading, isError } = useProject(Number.isFinite(projectId) ? projectId : null)
  const [view, setView] = useState<'desktop' | 'mobile'>('desktop')

  const idStr = String(projectId)

  if (!Number.isFinite(projectId)) {
    return (
      <div style={{ padding: '80px 48px', maxWidth: 640 }}>
        <div className="kicker" style={{ color: 'var(--red)', marginBottom: 10 }}>Errata</div>
        <h1 className="font-serif" style={{ fontSize: 36, fontWeight: 900, fontStyle: 'italic', color: 'var(--ink)' }}>
          Invalid dossier number.
        </h1>
        <Link href="/projects" style={{ marginTop: 16, display: 'inline-block', color: 'var(--red)', fontSize: 14 }}>
          Return to the index.
        </Link>
      </div>
    )
  }

  if (isLoading) {
    return (
      <div style={{ padding: '80px 48px', display: 'flex', gap: 12, alignItems: 'center', color: 'var(--ink-secondary)' }}>
        <Loader2 className="animate-spin" style={{ width: 14, height: 14 }} />
        <span className="kicker">Opening the plate…</span>
      </div>
    )
  }

  if (isError || !project) {
    return (
      <div style={{ padding: '80px 48px', maxWidth: 640 }}>
        <div className="kicker" style={{ color: 'var(--red)', marginBottom: 10 }}>Errata</div>
        <h1 className="font-serif" style={{ fontSize: 36, fontWeight: 900, fontStyle: 'italic', color: 'var(--ink)' }}>
          This dossier is missing from the archive.
        </h1>
        <p style={{ marginTop: 14, color: 'var(--ink-secondary)', fontSize: 14, lineHeight: 1.7 }}>
          The plate could not be found. It may have been recalled or the link was misprinted.
        </p>
        <Link href="/projects" style={{ marginTop: 18, display: 'inline-block', color: 'var(--red)', fontSize: 14 }}>
          Return to the index.
        </Link>
      </div>
    )
  }

  return (
    <div
      className="rise"
      style={{
        padding: '36px 48px 48px',
        maxWidth: 1200,
        margin: '0 auto',
        minHeight: 'calc(100vh - 120px)',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {/* Masthead */}
      <header style={{ flexShrink: 0, marginBottom: 20 }}>
        <div
          className="kicker"
          style={{
            color: 'var(--red)',
            marginBottom: 12,
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            flexWrap: 'wrap',
          }}
        >
          <Link href={`/project/${idStr}`} style={{ color: 'inherit', textDecoration: 'none' }}>
            Dossier
          </Link>
          <span style={{ color: 'var(--ink-tertiary)' }}>·</span>
          <span style={{ color: 'var(--ink-secondary)' }}>Press room</span>
          <span style={{ color: 'var(--ink-tertiary)' }}>·</span>
          <span>Reader&rsquo;s proof</span>
        </div>

        <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', gap: 24, flexWrap: 'wrap' }}>
          <div>
            <h1
              className="font-serif"
              style={{
                fontSize: 'clamp(32px, 4vw, 48px)',
                fontWeight: 900,
                fontStyle: 'italic',
                lineHeight: 1,
                letterSpacing: '-0.03em',
                color: 'var(--ink)',
                marginBottom: 8,
              }}
            >
              The <span style={{ color: 'var(--red)' }}>setting</span> in full.
            </h1>
            <p
              style={{
                fontSize: 13,
                lineHeight: 1.65,
                color: 'var(--ink-secondary)',
                maxWidth: 520,
                fontWeight: 300,
              }}
            >
              Preview the page as it will appear to synthetic readers — desktop measure or narrow folio. This is not the
              final edition until the presses run.
            </p>
          </div>

          {/* View toggle — letterpress segmented control */}
          <div
            role="group"
            aria-label="Preview width"
            style={{
              display: 'inline-flex',
              border: '0.5px solid var(--ink)',
              background: 'var(--paper-dark)',
            }}
          >
            {(
              [
                { mode: 'desktop' as const, icon: Monitor, label: 'Broadsheet' },
                { mode: 'mobile' as const, icon: Smartphone, label: 'Folio' },
              ] as const
            ).map(({ mode, icon: Icon, label }) => {
              const active = view === mode
              return (
                <button
                  key={mode}
                  type="button"
                  onClick={() => setView(mode)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    padding: '10px 16px',
                    border: 'none',
                    cursor: 'pointer',
                    fontFamily: 'var(--font-body)',
                    fontSize: 10,
                    fontWeight: 600,
                    letterSpacing: '0.18em',
                    textTransform: 'uppercase',
                    color: active ? 'var(--paper)' : 'var(--ink-secondary)',
                    background: active ? 'var(--ink)' : 'transparent',
                    transition: 'background 180ms ease, color 180ms ease',
                  }}
                >
                  <Icon style={{ width: 14, height: 14 }} />
                  {label}
                </button>
              )
            })}
          </div>
        </div>

        <motion.div
          initial={{ scaleX: 0, transformOrigin: 'left' }}
          animate={{ scaleX: 1 }}
          transition={{ duration: 0.35, ease: [0.2, 0.7, 0.2, 1] }}
          style={{ height: 2, background: 'var(--red)', marginTop: 16 }}
        />
        <div style={{ height: 0.5, background: 'var(--border-color)', marginTop: 4 }} />
      </header>

      {/* Press window */}
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.45, delay: 0.05 }}
        style={{
          flex: 1,
          minHeight: 0,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
        }}
      >
        <div
          style={{
            width: view === 'desktop' ? '100%' : 390,
            maxWidth: '100%',
            flex: 1,
            minHeight: 420,
            display: 'flex',
            flexDirection: 'column',
            border: '0.5px solid var(--ink)',
            background: 'var(--paper)',
            boxShadow: '16px 16px 0 rgba(26,23,20,0.1)',
            overflow: 'hidden',
            transition: 'width 420ms cubic-bezier(0.2, 0.7, 0.2, 1)',
          }}
        >
          {/* Chrome bar — editorial, not macOS glass */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 12,
              padding: '10px 14px',
              borderBottom: '0.5px solid var(--border-strong)',
              background: 'var(--paper-dark)',
              flexShrink: 0,
            }}
          >
            <div style={{ display: 'flex', gap: 6 }}>
              {['var(--red)', '#b88a3a', '#3d7a4a'].map((c) => (
                <span
                  key={c}
                  style={{
                    width: 8,
                    height: 8,
                    borderRadius: '50%',
                    background: c,
                    opacity: 0.85,
                  }}
                />
              ))}
            </div>
            <div
              className="kicker"
              style={{
                flex: 1,
                textAlign: 'center',
                color: 'var(--ink-tertiary)',
                letterSpacing: '0.14em',
                border: '0.5px solid var(--border-color)',
                padding: '6px 10px',
                background: 'rgba(26,23,20,0.03)',
              }}
            >
              proof.thecee.app · {project.title.slice(0, 42)}
              {project.title.length > 42 ? '…' : ''}
            </div>
          </div>

          <iframe
            srcDoc={project.prototypeHtml || MOCK_HTML}
            title="Prototype preview"
            sandbox="allow-scripts"
            style={{
              flex: 1,
              width: '100%',
              border: 'none',
              minHeight: 360,
              background: 'var(--paper)',
            }}
          />
        </div>
      </motion.div>

      {/* Footer */}
      <footer
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 16,
          marginTop: 28,
          paddingTop: 20,
          borderTop: '0.5px solid var(--border-color)',
          flexShrink: 0,
          flexWrap: 'wrap',
        }}
      >
        <Link href={`/project/${idStr}`} className="btn-ghost" style={{ display: 'inline-flex', alignItems: 'center', gap: 10 }}>
          <ArrowLeft style={{ width: 14, height: 14 }} /> Back to dossier
        </Link>
        <Link href={`/project/${idStr}/environment`} className="btn-ink" style={{ display: 'inline-flex', alignItems: 'center', gap: 10 }}>
          Cast the room <ArrowRight style={{ width: 14, height: 14 }} />
        </Link>
      </footer>
    </div>
  )
}
