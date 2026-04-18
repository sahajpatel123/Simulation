'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import { ArrowUpRight, BookOpen, Compass, Keyboard, LifeBuoy, PencilLine, Printer, Sparkles } from 'lucide-react'
import Link from 'next/link'

type ChapterKey = 'welcome' | 'workflow' | 'glossary' | 'shortcuts' | 'typography' | 'faq'

const chapters: {
  key: ChapterKey
  num: string
  title: string
  note: string
  icon: React.ComponentType<{ style?: React.CSSProperties }>
}[] = [
  { key: 'welcome',    num: 'I',   title: 'Welcome',          note: 'What this paper is for',            icon: BookOpen },
  { key: 'workflow',   num: 'II',  title: 'The workflow',     note: 'Idea → proof → press → filing',     icon: Compass },
  { key: 'glossary',   num: 'III', title: 'Editorial glossary', note: 'Our words, decoded',              icon: PencilLine },
  { key: 'shortcuts',  num: 'IV',  title: 'Keyboard shortcuts', note: 'For the quick hand',              icon: Keyboard },
  { key: 'typography', num: 'V',   title: 'House typography',  note: 'How this paper is set',            icon: Printer },
  { key: 'faq',        num: 'VI',  title: 'Frequently asked',   note: 'Questions the editor gets most',  icon: LifeBuoy },
]

export default function HelpPage() {
  const [active, setActive] = useState<ChapterKey>('welcome')
  const refs = useRef<Record<ChapterKey, HTMLDivElement | null>>({
    welcome: null,
    workflow: null,
    glossary: null,
    shortcuts: null,
    typography: null,
    faq: null,
  })

  const scrollTo = (key: ChapterKey) => {
    setActive(key)
    const el = refs.current[key]
    if (el) {
      const y = el.getBoundingClientRect().top + window.scrollY - 140
      window.scrollTo({ top: y, behavior: 'smooth' })
    }
  }

  // Observe scroll to highlight active chapter
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0]
        if (visible) {
          const key = visible.target.getAttribute('data-chapter') as ChapterKey | null
          if (key) setActive(key)
        }
      },
      { rootMargin: '-140px 0px -55% 0px', threshold: [0.2, 0.5] },
    )
    Object.values(refs.current).forEach((el) => el && observer.observe(el))
    return () => observer.disconnect()
  }, [])

  return (
    <div className="rise" style={{ padding: '48px 48px 160px', maxWidth: 1280, margin: '0 auto' }}>
      {/* Masthead */}
      <header style={{ marginBottom: 28 }}>
        <div
          className="kicker"
          style={{ color: 'var(--red)', marginBottom: 18, display: 'flex', alignItems: 'center', gap: 12 }}
        >
          <span style={{ width: 24, height: 0.5, background: 'var(--red)' }} />
          Style & Method
          <span style={{ color: 'var(--ink-secondary)' }}>·</span>
          <span style={{ color: 'var(--ink-secondary)' }}>A manual for the room</span>
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
          A house<span style={{ fontStyle: 'italic', color: 'var(--red)' }}> style guide</span>.
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
          Every paper keeps a manual beside the typesetter. This is ours. It explains how the press
          reads your ideas, what each column on the desk means, and which keys to press when the
          deadline is close and the coffee is cold.
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
        {/* Table of contents */}
        <nav
          aria-label="Manual index"
          style={{
            position: 'sticky',
            top: 140,
            alignSelf: 'start',
            paddingRight: 16,
            borderRight: '0.5px solid var(--border-color)',
          }}
        >
          <div className="kicker" style={{ color: 'var(--red)', marginBottom: 16 }}>
            Chapters
          </div>
          <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: 2 }}>
            {chapters.map((c) => {
              const isActive = active === c.key
              const Icon = c.icon
              return (
                <li key={c.key}>
                  <button
                    type="button"
                    onClick={() => scrollTo(c.key)}
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
                      {c.num}
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
                        {c.title}
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
                        {c.note}
                      </span>
                    </span>
                  </button>
                </li>
              )
            })}
          </ul>
        </nav>

        {/* Body */}
        <article style={{ display: 'flex', flexDirection: 'column', gap: 72 }}>
          <Chapter refCb={(el) => (refs.current.welcome = el)} keyName="welcome" kicker="Chapter I" title="Welcome to the room.">
            <p className="lead-para dropcap">
              TheCee is a small paper with one obsession: to read your ideas as a stranger would. You
              file a dossier, the press draws a room of synthetic readers, and the impression comes
              back measured — not flattered. What you do with the measurement is the real work.
            </p>
            <p className="lead-para">
              Nothing you file is lost. Every draft, every proof, every filed outcome stays in your
              archive. Come back to it a month later and the page will be exactly where you left it,
              a little dustier, still readable.
            </p>
            <div
              style={{
                display: 'flex',
                gap: 12,
                marginTop: 20,
                flexWrap: 'wrap',
              }}
            >
              <Link href="/projects" className="btn-ink">
                <Sparkles style={{ width: 13, height: 13 }} /> File your first dossier
              </Link>
              <Link href="/dashboard" className="btn-ghost">
                Open the front page
              </Link>
            </div>
          </Chapter>

          <Chapter refCb={(el) => (refs.current.workflow = el)} keyName="workflow" kicker="Chapter II" title="The workflow, in four movements.">
            <p className="lead-para">
              A dossier moves through the desk in four steps. Each step is its own page, with its own
              voice. You can stop at any one of them and come back later.
            </p>
            <ol
              style={{
                listStyle: 'none',
                counterReset: 'step',
                padding: 0,
                margin: '28px 0 0',
                display: 'flex',
                flexDirection: 'column',
                gap: 18,
              }}
            >
              {[
                {
                  t: 'File the dossier',
                  d: 'Describe your idea in a paragraph. The press pulls the assumptions hiding inside it and shows them back to you as an outline you can argue with.',
                },
                {
                  t: 'Assemble the cast',
                  d: 'Choose the market your synthetic readers live in: a base case, a recession, a viral moment, a rival walking in through the door.',
                },
                {
                  t: 'Run the press',
                  d: 'Ten thousand agents step through your draft like any reader would. You see the work in progress, not a spinner — profile, markov, funnel, aggregate.',
                },
                {
                  t: 'Read the proofs',
                  d: 'The impression comes back with a conversion rate, a confidence interval, funnel bleed, sensitivity, and interventions you can actually try. When you try them, record the outcome and the next run gets smarter.',
                },
              ].map((step, i) => (
                <li
                  key={step.t}
                  style={{
                    display: 'grid',
                    gridTemplateColumns: '56px 1fr',
                    gap: 20,
                    alignItems: 'start',
                    paddingTop: 16,
                    borderTop: '0.5px solid var(--border-color)',
                  }}
                >
                  <span
                    className="numeral"
                    style={{
                      fontSize: 42,
                      fontWeight: 800,
                      color: 'var(--red)',
                      letterSpacing: '-0.04em',
                      lineHeight: 0.9,
                    }}
                  >
                    {String(i + 1).padStart(2, '0')}
                  </span>
                  <div>
                    <h4
                      className="font-serif"
                      style={{
                        fontSize: 22,
                        fontWeight: 800,
                        fontStyle: 'italic',
                        letterSpacing: '-0.01em',
                        color: 'var(--ink)',
                        marginBottom: 6,
                        lineHeight: 1.1,
                      }}
                    >
                      {step.t}
                    </h4>
                    <p style={{ fontSize: 14, lineHeight: 1.75, color: 'var(--ink-secondary)', fontWeight: 300, maxWidth: 620 }}>
                      {step.d}
                    </p>
                  </div>
                </li>
              ))}
            </ol>
          </Chapter>

          <Chapter refCb={(el) => (refs.current.glossary = el)} keyName="glossary" kicker="Chapter III" title="A short glossary.">
            <p className="lead-para">
              The paper uses a few words in a specific way. If a term confuses you in a report, its
              definition is likely here.
            </p>
            <GlossaryList
              items={[
                { term: 'Dossier', def: 'A single idea on file. Every project in your archive is a dossier.' },
                { term: 'The press', def: 'The simulation engine. It draws the cast, runs the agents, and returns the impression.' },
                { term: 'Cast', def: 'The set of synthetic readers used for a run — their scenario, volume and demographic shape.' },
                { term: 'Proof', def: 'The readable report returned by a completed run. Proofs are filed back into the dossier.' },
                { term: 'Impression', def: 'One full pass of agents through a dossier. A run with ten thousand readers is one impression.' },
                { term: 'Funnel bleed', def: 'Where readers drop off along your conversion path. Shown as a negative percentage per stage.' },
                { term: 'Sensitivity', def: 'How much each assumption moves the outcome. Higher means the run is more fragile to that input.' },
                { term: 'Intervention', def: 'A concrete action the press recommends to shift the outcome upward. Rated by effort.' },
                { term: 'Errata', def: 'The column for failed runs, returned drafts, and decisions that cannot be taken back.' },
                { term: 'Filing', def: 'A recorded outcome from the real world, compared against the proof. Each filing tightens the next run.' },
              ]}
            />
          </Chapter>

          <Chapter refCb={(el) => (refs.current.shortcuts = el)} keyName="shortcuts" kicker="Chapter IV" title="Keys for the quick hand.">
            <p className="lead-para">
              A small keyboard vocabulary, shared across the site. These work anywhere in the
              workspace.
            </p>
            <ShortcutGrid
              rows={[
                { keys: ['G', 'D'], what: 'Go to the front page' },
                { keys: ['G', 'I'], what: 'Open the dossier index' },
                { keys: ['N'],      what: 'File a new dossier' },
                { keys: ['/'],      what: 'Focus the search on the archive' },
                { keys: ['['],      what: 'Collapse the side rail' },
                { keys: [']'],      what: 'Expand the side rail' },
                { keys: ['⌘', 'K'], what: 'Open the command palette (coming soon)' },
                { keys: ['Esc'],    what: 'Close any open modal or sheet' },
              ]}
            />
            <p style={{ fontSize: 12, color: 'var(--ink-tertiary)', marginTop: 16, fontStyle: 'italic' }}>
              These bindings are advisory — the implementation rolls out one by one as the paper
              grows. If a key is silent, it has not been set yet.
            </p>
          </Chapter>

          <Chapter refCb={(el) => (refs.current.typography = el)} keyName="typography" kicker="Chapter V" title="How this paper is set.">
            <p className="lead-para">
              The house typography is deliberately narrow: a single serif for display and body,
              sharpened with italic for accent, and a small sans for kickers and captions.
            </p>

            <TypographySpecimen
              kicker="Serif display · 900 italic"
              sample="Your ideas, under review."
              styleProps={{
                fontFamily: 'var(--font-serif)',
                fontSize: 'clamp(42px, 5vw, 72px)',
                fontWeight: 900,
                fontStyle: 'italic',
                letterSpacing: '-0.035em',
                lineHeight: 0.98,
                color: 'var(--ink)',
              }}
            />
            <TypographySpecimen
              kicker="Serif body · 300 roman"
              sample="A brief description of the reader, typeset as the audience would encounter it on the page."
              styleProps={{
                fontFamily: 'var(--font-serif)',
                fontSize: 18,
                fontWeight: 300,
                letterSpacing: '-0.005em',
                lineHeight: 1.55,
                color: 'var(--ink)',
              }}
            />
            <TypographySpecimen
              kicker="Kicker · sans, 0.22em tracking"
              sample="THE DAILY IMPRESSION · VOL. II NO. 288"
              styleProps={{
                fontFamily: 'var(--font-body)',
                fontSize: 11,
                fontWeight: 600,
                letterSpacing: '0.22em',
                textTransform: 'uppercase',
                color: 'var(--red)',
              }}
            />

            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(3, 1fr)',
                gap: 18,
                marginTop: 28,
              }}
            >
              {[
                { name: 'Paper', hex: '#f2ece0' },
                { name: 'Ink',   hex: '#1a1714' },
                { name: 'Red',   hex: '#c0392b' },
              ].map((sw) => (
                <div key={sw.name} style={{ border: '0.5px solid var(--border-strong)' }}>
                  <div style={{ height: 88, background: sw.hex, borderBottom: '0.5px solid var(--border-strong)' }} />
                  <div style={{ padding: '10px 12px', display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
                    <span className="font-serif" style={{ fontSize: 16, fontWeight: 800, fontStyle: 'italic' }}>{sw.name}</span>
                    <span className="kicker" style={{ color: 'var(--ink-tertiary)' }}>{sw.hex}</span>
                  </div>
                </div>
              ))}
            </div>
          </Chapter>

          <Chapter refCb={(el) => (refs.current.faq = el)} keyName="faq" kicker="Chapter VI" title="The editor’s postbag.">
            <FAQList
              items={[
                {
                  q: 'Are the synthetic readers real people?',
                  a: 'No. They are statistical agents drawn to behave the way a given market segment tends to. The press uses them to stress-test assumptions before you spend a real user’s attention.',
                },
                {
                  q: 'How accurate is a single impression?',
                  a: 'One run is a reading, not a verdict. The confidence interval printed on every proof tells you how much to trust it. Record real outcomes in the tracker and the calibration sharpens.',
                },
                {
                  q: 'Can I run the same dossier more than once?',
                  a: 'Yes, with different casts. Running the same idea against a base case, a recession, and a viral scenario is how you find where it is fragile.',
                },
                {
                  q: 'Where is my data kept?',
                  a: 'Every dossier, proof and filing is yours. You can export the entire archive as JSON from the Press Office at any time.',
                },
                {
                  q: 'Is there a mobile edition?',
                  a: 'A small pocket edition is in typesetting. For now the paper reads best on a wide desk.',
                },
              ]}
            />
          </Chapter>

          {/* Final colophon */}
          <div
            style={{
              borderTop: '2px solid var(--ink)',
              paddingTop: 24,
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'baseline',
              gap: 16,
              flexWrap: 'wrap',
            }}
          >
            <div className="kicker" style={{ color: 'var(--ink-tertiary)' }}>
              — End of the style guide. Thank you for reading closely.
            </div>
            <Link href="/projects" className="btn-ink" style={{ marginLeft: 'auto' }}>
              Return to the archive <ArrowUpRight style={{ width: 13, height: 13 }} />
            </Link>
          </div>
        </article>
      </div>
    </div>
  )
}

/* ── Chapter wrapper ─────────────────────────────────────────────── */
function Chapter({
  kicker,
  title,
  keyName,
  children,
  refCb,
}: {
  kicker: string
  title: string
  keyName: ChapterKey
  children: React.ReactNode
  refCb: (el: HTMLDivElement | null) => void
}) {
  return (
    <section ref={refCb} data-chapter={keyName} style={{ scrollMarginTop: 140 }}>
      <motion.header
        initial={{ opacity: 0, y: 8 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true, amount: 0.3 }}
        transition={{ duration: 0.4 }}
        style={{ marginBottom: 22 }}
      >
        <div className="kicker" style={{ color: 'var(--red)', marginBottom: 12 }}>
          {kicker}
        </div>
        <h2
          className="font-serif"
          style={{
            fontSize: 'clamp(32px, 3.8vw, 48px)',
            fontWeight: 900,
            fontStyle: 'italic',
            lineHeight: 1,
            letterSpacing: '-0.03em',
            color: 'var(--ink)',
            marginBottom: 14,
            maxWidth: 620,
          }}
        >
          {title}
        </h2>
        <div style={{ height: 2, background: 'var(--red)', width: 56 }} />
      </motion.header>
      <div className="help-body" style={{ maxWidth: 680 }}>
        {children}
      </div>
    </section>
  )
}

/* ── Glossary ────────────────────────────────────────────────────── */
function GlossaryList({ items }: { items: { term: string; def: string }[] }) {
  return (
    <dl
      style={{
        margin: '24px 0 0',
        display: 'grid',
        gridTemplateColumns: '180px 1fr',
        columnGap: 32,
        rowGap: 0,
      }}
    >
      {items.map((it, i) => (
        <div
          key={it.term}
          style={{
            display: 'contents',
          }}
        >
          <dt
            className="font-serif"
            style={{
              gridColumn: 1,
              fontSize: 20,
              fontWeight: 800,
              fontStyle: 'italic',
              color: 'var(--red)',
              letterSpacing: '-0.01em',
              padding: '18px 0',
              borderTop: i === 0 ? '0.5px solid var(--border-color)' : 'none',
              borderBottom: '0.5px solid var(--border-color)',
              lineHeight: 1.1,
            }}
          >
            {it.term}
          </dt>
          <dd
            style={{
              gridColumn: 2,
              fontSize: 14,
              lineHeight: 1.75,
              color: 'var(--ink-secondary)',
              fontWeight: 300,
              padding: '18px 0',
              margin: 0,
              borderTop: i === 0 ? '0.5px solid var(--border-color)' : 'none',
              borderBottom: '0.5px solid var(--border-color)',
            }}
          >
            {it.def}
          </dd>
        </div>
      ))}
    </dl>
  )
}

/* ── Shortcut grid ───────────────────────────────────────────────── */
function ShortcutGrid({ rows }: { rows: { keys: string[]; what: string }[] }) {
  return (
    <div
      style={{
        marginTop: 24,
        display: 'grid',
        gridTemplateColumns: '220px 1fr',
        rowGap: 0,
        columnGap: 24,
      }}
    >
      {rows.map((r, i) => (
        <div key={r.what} style={{ display: 'contents' }}>
          <div
            style={{
              display: 'flex',
              gap: 6,
              alignItems: 'center',
              padding: '14px 0',
              borderTop: i === 0 ? '0.5px solid var(--border-color)' : 'none',
              borderBottom: '0.5px solid var(--border-color)',
            }}
          >
            {r.keys.map((k) => (
              <kbd
                key={k + Math.random()}
                style={{
                  fontFamily: 'var(--font-body)',
                  fontSize: 11,
                  fontWeight: 700,
                  letterSpacing: '0.04em',
                  padding: '6px 10px',
                  border: '0.5px solid var(--ink)',
                  borderBottom: '2px solid var(--ink)',
                  background: 'var(--paper)',
                  color: 'var(--ink)',
                  minWidth: 24,
                  textAlign: 'center',
                }}
              >
                {k}
              </kbd>
            ))}
          </div>
          <div
            style={{
              padding: '14px 0',
              borderTop: i === 0 ? '0.5px solid var(--border-color)' : 'none',
              borderBottom: '0.5px solid var(--border-color)',
              fontSize: 14,
              color: 'var(--ink-secondary)',
              fontWeight: 300,
              lineHeight: 1.6,
            }}
          >
            {r.what}
          </div>
        </div>
      ))}
    </div>
  )
}

/* ── Typography specimen block ───────────────────────────────────── */
function TypographySpecimen({
  kicker,
  sample,
  styleProps,
}: {
  kicker: string
  sample: string
  styleProps: React.CSSProperties
}) {
  return (
    <figure
      style={{
        margin: '24px 0 0',
        padding: '22px 24px 26px',
        border: '0.5px solid var(--border-strong)',
        background: 'var(--paper)',
      }}
    >
      <figcaption className="kicker" style={{ color: 'var(--red)', marginBottom: 14 }}>
        {kicker}
      </figcaption>
      <div style={styleProps}>{sample}</div>
    </figure>
  )
}

/* ── FAQ ─────────────────────────────────────────────────────────── */
function FAQList({ items }: { items: { q: string; a: string }[] }) {
  // Each row knows its own open state
  const initial = useMemo(() => items.map((_, i) => i === 0), [items])
  const [open, setOpen] = useState<boolean[]>(initial)
  const toggle = (i: number) => setOpen((prev) => prev.map((v, j) => (i === j ? !v : v)))
  return (
    <div style={{ marginTop: 24 }}>
      {items.map((it, i) => {
        const isOpen = open[i]
        return (
          <div
            key={it.q}
            style={{
              borderTop: i === 0 ? '0.5px solid var(--border-color)' : 'none',
              borderBottom: '0.5px solid var(--border-color)',
            }}
          >
            <button
              type="button"
              onClick={() => toggle(i)}
              aria-expanded={isOpen}
              style={{
                width: '100%',
                background: 'none',
                border: 'none',
                cursor: 'pointer',
                padding: '18px 0',
                textAlign: 'left',
                display: 'grid',
                gridTemplateColumns: '1fr auto',
                gap: 20,
                alignItems: 'baseline',
                color: 'var(--ink)',
              }}
            >
              <span
                className="font-serif"
                style={{
                  fontSize: 20,
                  fontWeight: 800,
                  fontStyle: 'italic',
                  letterSpacing: '-0.01em',
                  lineHeight: 1.25,
                  color: isOpen ? 'var(--red)' : 'var(--ink)',
                }}
              >
                {it.q}
              </span>
              <span
                className="kicker"
                style={{
                  color: 'var(--ink-tertiary)',
                  transform: isOpen ? 'rotate(90deg)' : 'rotate(0)',
                  transition: 'transform 200ms ease',
                  display: 'inline-block',
                }}
              >
                +
              </span>
            </button>
            {isOpen && (
              <motion.p
                initial={{ opacity: 0, y: -4 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.2 }}
                style={{
                  padding: '0 0 20px',
                  fontSize: 14,
                  lineHeight: 1.8,
                  color: 'var(--ink-secondary)',
                  fontWeight: 300,
                  maxWidth: 600,
                }}
              >
                {it.a}
              </motion.p>
            )}
          </div>
        )
      })}
    </div>
  )
}
