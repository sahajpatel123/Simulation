'use client'

import { useEffect, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import { Monitor, Smartphone, ArrowRight, ArrowLeft, Loader2 } from 'lucide-react'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import { useMutation, useQueryClient } from '@tanstack/react-query'

import { formatProductTypeLabel, PRODUCT_TYPES } from '@/components/ui-builder/constants'
import type { GeneratedUI, UIGenerateRequest } from '@/components/ui-builder/types'
import { previewAbsoluteUrl } from '@/components/ui-builder/preview-absolute-url'
import { useProject } from '@/hooks/useProjects'
import { getApiV1Base } from '@/lib/api-v1-base'

function authHeaders(): HeadersInit {
  const token = typeof window !== 'undefined' ? localStorage.getItem('access_token') : null
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  }
}

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
  const idStr = String(projectId)

  const { data: project, isLoading, isError } = useProject(Number.isFinite(projectId) ? projectId : null)
  const qc = useQueryClient()
  const [view, setView] = useState<'desktop' | 'mobile'>('desktop')
  const [prompt, setPrompt] = useState('')
  const [productType, setProductType] = useState('saas')
  const [uiPreviewPath, setUiPreviewPath] = useState<string | null>(null)
  const [generatedUiId, setGeneratedUiId] = useState<number | null>(null)
  const [simStatus, setSimStatus] = useState<string | null>(null)
  const promptSeededRef = useRef(false)

  useEffect(() => {
    promptSeededRef.current = false
    setPrompt('')
  }, [projectId])

  const generateMutation = useMutation({
    mutationFn: async (body: UIGenerateRequest) => {
      const res = await fetch(`${getApiV1Base()}/projects/${projectId}/generate-ui`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify(body),
      })
      if (!res.ok) throw new Error(await res.text())
      return (await res.json()) as GeneratedUI & { project_id?: number }
    },
    onSuccess: (data) => {
      setUiPreviewPath(data.html_preview_url)
      setGeneratedUiId(data.id)
      setSimStatus(null)
      void qc.invalidateQueries({ queryKey: ['project', projectId] })
    },
  })

  const simulateMutation = useMutation({
    mutationFn: async (uiId: number) => {
      const res = await fetch(`${getApiV1Base()}/projects/${projectId}/generated-uis/${uiId}/simulate`, {
        method: 'POST',
        headers: authHeaders(),
      })
      if (!res.ok) throw new Error(await res.text())
      return (await res.json()) as { ui_simulation_run_id: number }
    },
    onSuccess: (data) => {
      setSimStatus(`Simulation queued — run #${data.ui_simulation_run_id}`)
    },
  })

  useEffect(() => {
    if (!project?.description?.trim() || promptSeededRef.current) return
    setPrompt(project.description.trim().slice(0, 500))
    promptSeededRef.current = true
  }, [project?.description])

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

  const legacyPrototypeHtml = project.prototypeHtml?.trim() ?? ''
  const hasBuiltOnce = Boolean(legacyPrototypeHtml) || Boolean(uiPreviewPath)
  const iframeServeUrl = uiPreviewPath ? previewAbsoluteUrl(uiPreviewPath) : null

  const handlePullProof = () => {
    if (!prompt.trim() || !Number.isFinite(projectId)) return
    generateMutation.mutate({
      prompt: prompt.trim(),
      product_type: productType,
      pages_required: ['home', 'product', 'checkout'],
    })
  }

  const viewToggle = (
    <div
      role="group"
      aria-label="Preview width"
      style={{
        display: 'inline-flex',
        border: '0.5px solid var(--ink)',
        background: 'var(--paper-dark)',
        flexShrink: 0,
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
  )

  return (
    <div
      className="rise"
      style={{
        padding: '12px 48px 16px',
        maxWidth: 1200,
        margin: '0 auto',
        width: '100%',
        boxSizing: 'border-box',
        minHeight: 'calc(100dvh - 120px)',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
        <header style={{ flexShrink: 0, marginBottom: 6, paddingTop: 4 }}>
          <div style={{ height: 0.5, background: 'var(--border-color)', marginTop: 0 }} />
        </header>

        {/* Press window */}
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{
            opacity: { duration: 0.45, delay: 0.05 },
            y: { duration: 0.45, delay: 0.05 },
          }}
          style={{
            flex: 1,
            minHeight: 0,
            display: 'flex',
            flexDirection: 'column',
            alignItems: view === 'desktop' ? 'stretch' : 'center',
            width: '100%',
          }}
        >
        <div
          style={{
            width: view === 'desktop' ? '100%' : 390,
            maxWidth: '100%',
            flex: 1,
            minHeight: 0,
            display: 'flex',
            flexDirection: 'column',
            border: '0.5px solid var(--ink)',
            background: 'var(--paper)',
            boxShadow: '16px 16px 0 rgba(26,23,20,0.1)',
            overflow: 'hidden',
            transition: 'width 420ms cubic-bezier(0.2, 0.7, 0.2, 1)',
          }}
        >
          {/* Chrome — prompt as the compositor’s line; not a browser URL bar */}
          <div
            style={{
              borderBottom: '0.5px solid var(--border-strong)',
              background: 'var(--paper-dark)',
              flexShrink: 0,
            }}
          >
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 12,
                padding: '10px 14px 12px',
              }}
            >
              <div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
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
              <label htmlFor="prototype-prompt" className="sr-only">
                Describe the site or page you want the presses to pull
              </label>
              <div
                style={{
                  flex: 1,
                  minWidth: 0,
                  display: 'flex',
                  alignItems: 'stretch',
                  border: '0.5px solid var(--border-color)',
                  background: 'rgba(26,23,20,0.03)',
                  overflow: 'hidden',
                }}
              >
                <input
                  id="prototype-prompt"
                  type="text"
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault()
                      handlePullProof()
                    }
                  }}
                  placeholder="Describe the site you want pulled — product, audience, what must be true on the page…"
                  disabled={generateMutation.isPending}
                  style={{
                    flex: 1,
                    minWidth: 0,
                    border: 'none',
                    padding: '8px 12px',
                    background: 'transparent',
                    fontFamily: 'var(--font-body)',
                    fontSize: 12,
                    letterSpacing: '0.04em',
                    color: 'var(--ink)',
                    outline: 'none',
                  }}
                />
                <select
                  value={productType}
                  onChange={(e) => setProductType(e.target.value)}
                  disabled={generateMutation.isPending}
                  aria-label="Product type"
                  style={{
                    flexShrink: 0,
                    alignSelf: 'stretch',
                    width: 'auto',
                    minWidth: 112,
                    maxWidth: 200,
                    padding: '6px 8px',
                    border: 'none',
                    borderLeft: '0.5px solid var(--border-color)',
                    borderRadius: 0,
                    background: 'var(--paper)',
                    fontSize: 10,
                    fontFamily: 'var(--font-body)',
                    color: 'var(--ink-secondary)',
                    cursor: generateMutation.isPending ? 'not-allowed' : 'pointer',
                  }}
                >
                  {PRODUCT_TYPES.map((pt) => (
                    <option key={pt} value={pt}>
                      {formatProductTypeLabel(pt)}
                    </option>
                  ))}
                </select>
              </div>
              <button
                type="button"
                onClick={handlePullProof}
                disabled={!prompt.trim() || generateMutation.isPending}
                style={{
                  flexShrink: 0,
                  padding: '8px 14px',
                  border: '0.5px solid var(--ink)',
                  background: !prompt.trim() || generateMutation.isPending ? 'transparent' : 'var(--ink)',
                  color: !prompt.trim() || generateMutation.isPending ? 'var(--ink-tertiary)' : 'var(--paper)',
                  fontFamily: 'var(--font-body)',
                  fontSize: 9,
                  fontWeight: 700,
                  letterSpacing: '0.2em',
                  textTransform: 'uppercase',
                  cursor: !prompt.trim() || generateMutation.isPending ? 'not-allowed' : 'pointer',
                  opacity: !prompt.trim() || generateMutation.isPending ? 0.45 : 1,
                }}
              >
                {generateMutation.isPending ? 'Building…' : 'Build'}
              </button>
            </div>
            {generateMutation.isError && (
              <p style={{ padding: '0 14px 10px', margin: 0, fontSize: 11, color: 'var(--red)' }}>
                The presses jammed — check your connection and try again.
              </p>
            )}
          </div>

          <div style={{ position: 'relative', flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
            {generateMutation.isPending && (
              <div
                style={{
                  position: 'absolute',
                  inset: 0,
                  zIndex: 2,
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: 12,
                  background: 'rgba(242,236,224,0.92)',
                }}
              >
                <Loader2 className="animate-spin" style={{ width: 22, height: 22, color: 'var(--red)' }} />
                <span className="kicker" style={{ color: 'var(--ink-secondary)' }}>
                  Compositor is setting your line…
                </span>
              </div>
            )}
            {iframeServeUrl ? (
              <iframe
                key={iframeServeUrl}
                src={iframeServeUrl}
                title="Generated prototype preview"
                sandbox="allow-scripts allow-same-origin"
                style={{
                  flex: 1,
                  width: '100%',
                  border: 'none',
                  minHeight: 0,
                  background: 'var(--paper)',
                }}
              />
            ) : (
              <iframe
                srcDoc={legacyPrototypeHtml || MOCK_HTML}
                title="Prototype preview"
                sandbox="allow-scripts"
                style={{
                  flex: 1,
                  width: '100%',
                  border: 'none',
                  minHeight: 0,
                  background: 'var(--paper)',
                }}
              />
            )}
          </div>

          {hasBuiltOnce && (
            <div
              style={{
                borderTop: '0.5px solid var(--border-color)',
                padding: '12px 14px',
                background: 'rgba(26,23,20,0.02)',
                flexShrink: 0,
              }}
            >
              <div className="kicker" style={{ color: 'var(--red)', marginBottom: 8, letterSpacing: '0.22em' }}>
                Press tools
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 12 }}>
                {generatedUiId != null ? (
                  <button
                    type="button"
                    onClick={() => simulateMutation.mutate(generatedUiId)}
                    disabled={simulateMutation.isPending}
                    className="btn-ink"
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: 8,
                      padding: '8px 14px',
                      fontSize: 10,
                      letterSpacing: '0.16em',
                      textTransform: 'uppercase',
                      opacity: simulateMutation.isPending ? 0.6 : 1,
                    }}
                  >
                    {simulateMutation.isPending ? 'Queuing…' : 'Run 52-cluster simulation'}
                  </button>
                ) : (
                  <p style={{ margin: 0, fontSize: 12, color: 'var(--ink-secondary)', maxWidth: 520 }}>
                    Pull a fresh proof from the line above to enable cluster simulation on this sheet.
                  </p>
                )}
                {simStatus && (
                  <span className="kicker" style={{ color: 'var(--ink)', letterSpacing: '0.12em' }}>
                    {simStatus}
                  </span>
                )}
              </div>
            </div>
          )}
        </div>
      </motion.div>

      {/* Footer — Broadsheet / Folio centered between nav actions */}
      <footer
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 16,
          marginTop: 'auto',
          paddingTop: 16,
          paddingBottom: 4,
          borderTop: '0.5px solid var(--border-color)',
          flexShrink: 0,
          flexWrap: 'wrap',
          rowGap: 14,
          minWidth: 0,
        }}
      >
        <div style={{ flex: '1 1 140px', minWidth: 0, display: 'flex', justifyContent: 'flex-start' }}>
          <Link href={`/project/${idStr}`} className="btn-ghost" style={{ display: 'inline-flex', alignItems: 'center', gap: 10 }}>
            <ArrowLeft style={{ width: 14, height: 14 }} /> Back to dossier
          </Link>
        </div>
        <div style={{ flex: '0 0 auto', display: 'flex', justifyContent: 'center' }}>{viewToggle}</div>
        <div style={{ flex: '1 1 140px', minWidth: 0, display: 'flex', justifyContent: 'flex-end' }}>
          <Link href={`/project/${idStr}/environment`} className="btn-ink" style={{ display: 'inline-flex', alignItems: 'center', gap: 10 }}>
            Cast the room <ArrowRight style={{ width: 14, height: 14 }} />
          </Link>
        </div>
      </footer>
    </div>
  )
}
