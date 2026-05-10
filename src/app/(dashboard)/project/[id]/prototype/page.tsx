'use client'

import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { Monitor, Smartphone, ArrowRight, ArrowLeft, Loader2, Pencil, Check, X } from 'lucide-react'
import Link from 'next/link'
import { useParams, useRouter } from 'next/navigation'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { formatProductTypeLabel, SOFTWARE_TYPES } from '@/components/ui-builder/constants'
import type { GeneratedUI, GeneratedUIHistoryResponse, UIGenerateRequest, UIRefineRequest } from '@/components/ui-builder/types'
import { previewAbsoluteUrl } from '@/components/ui-builder/preview-absolute-url'
import { useProject } from '@/hooks/useProjects'
import { apiError, apiLong } from '@/lib/api'

type PrototypeGenerateResponse = GeneratedUI & { project_id?: number }
type UISimulationStartResponse = { ui_simulation_run_id: number }

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

/* ── Shared animation props ─────────────────────────────────────── */
const PAGE_ENTER = { opacity: 1, y: 0 }
const PAGE_HIDDEN = { opacity: 0, y: 10 }
const PAGE_GONE = { opacity: 0, y: -10 }
const EASE_IN: [number, number, number, number] = [0.22, 1, 0.36, 1]
const EASE_OUT: [number, number, number, number] = [0.4, 0, 1, 1]

const EDIT_SUGGESTIONS = [
  'Make the hero headline bolder and more compelling',
  'Add a testimonials section with 3 quotes',
  'Change colour scheme to dark/midnight theme',
  'Add a FAQ accordion section at the bottom',
  'Make the CTA button more prominent',
]

export default function PrototypePage() {
  const params = useParams()
  const router = useRouter()
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

  /* Edit mode state */
  const [editMode, setEditMode] = useState(false)
  const [editPrompt, setEditPrompt] = useState('')
  const [editApplied, setEditApplied] = useState(false)

  const { data: uiHistory, isLoading: isLoadingUiHistory } = useQuery({
    queryKey: ['generated-uis', projectId],
    queryFn: async (): Promise<GeneratedUIHistoryResponse> => {
      const { data } = await apiLong.get<GeneratedUIHistoryResponse>(`/projects/${projectId}/generated-uis`)
      return data
    },
    enabled: Number.isFinite(projectId),
  })

  useEffect(() => {
    const latest = uiHistory?.uis?.[0]
    if (!latest || uiPreviewPath) return
    setUiPreviewPath(latest.html_preview_url)
    setGeneratedUiId(latest.id)
  }, [uiHistory, uiPreviewPath])

  useEffect(() => {
    promptSeededRef.current = false
    setPrompt('')
  }, [projectId])

  useEffect(() => {
    if (!project || isLoading) return
    if (project.dossier_axis === 'hardware') {
      router.replace(`/project/${projectId}/hardware`)
    }
  }, [project, isLoading, router, projectId])

  const generateMutation = useMutation({
    mutationFn: async (body: UIGenerateRequest): Promise<PrototypeGenerateResponse> => {
      const { data } = await apiLong.post<PrototypeGenerateResponse>(`/projects/${projectId}/generate-ui`, body)
      return data
    },
    onSuccess: (data) => {
      setUiPreviewPath(data.html_preview_url)
      setGeneratedUiId(data.id)
      setSimStatus(null)
      void qc.invalidateQueries({ queryKey: ['generated-uis', projectId] })
    },
  })

  const refineMutation = useMutation({
    mutationFn: async (body: UIRefineRequest): Promise<PrototypeGenerateResponse> => {
      const { data } = await apiLong.post<PrototypeGenerateResponse>(
        `/projects/${projectId}/generate-ui/refine`,
        body,
      )
      return data
    },
    onSuccess: (data) => {
      setUiPreviewPath(data.html_preview_url)
      setGeneratedUiId(data.id)
      setEditApplied(true)
      setEditPrompt('')
      void qc.invalidateQueries({ queryKey: ['generated-uis', projectId] })
    },
  })

  const simulateMutation = useMutation({
    mutationFn: async (uiId: number): Promise<UISimulationStartResponse> => {
      const { data } = await apiLong.post<UISimulationStartResponse>(`/projects/${projectId}/generated-uis/${uiId}/simulate`)
      return data
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
  const generateError = generateMutation.isError ? apiError(generateMutation.error) : null
  const refineError = refineMutation.isError ? apiError(refineMutation.error) : null

  const handlePullProof = () => {
    if (!prompt.trim() || !Number.isFinite(projectId)) return
    generateMutation.mutate({
      prompt: prompt.trim(),
      product_type: productType,
      pages_required: ['home', 'product', 'checkout'],
    })
  }

  const handleEnterEdit = () => {
    setEditApplied(false)
    refineMutation.reset()
    setEditPrompt('')
    setEditMode(true)
  }

  const handleExitEdit = () => {
    setEditMode(false)
    refineMutation.reset()
  }

  const handleApplyEdit = () => {
    if (!editPrompt.trim() || generatedUiId == null || refineMutation.isPending) return
    refineMutation.mutate({ generated_ui_id: generatedUiId, refinement_prompt: editPrompt.trim() })
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

  /* ── Shared iframe renderer ─────────────────────────────────────── */
  const previewIframe = (
    iframeServeUrl ? (
      <iframe
        key={iframeServeUrl}
        src={iframeServeUrl}
        title="Generated prototype preview"
        sandbox="allow-scripts allow-forms allow-same-origin"
        style={{ flex: 1, width: '100%', border: 'none', minHeight: 0, background: 'var(--paper)' }}
      />
    ) : (
      <iframe
        srcDoc={legacyPrototypeHtml || MOCK_HTML}
        title="Prototype preview"
        sandbox="allow-scripts allow-forms allow-same-origin"
        style={{ flex: 1, width: '100%', border: 'none', minHeight: 0, background: 'var(--paper)' }}
      />
    )
  )

  return (
    <div
      style={{
        position: 'relative',
        minHeight: 'calc(100dvh - 60px)',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
      }}
    >
      <AnimatePresence mode="wait" initial={false}>

        {/* ═══ VIEW MODE ════════════════════════════════════════════ */}
        {!editMode && (
          <motion.div
            key="view"
            initial={PAGE_HIDDEN}
            animate={PAGE_ENTER}
            exit={PAGE_GONE}
            transition={{ duration: 0.42, ease: EASE_IN }}
            style={{
              flex: 1,
              display: 'flex',
              flexDirection: 'column',
              padding: '12px 48px 16px',
              maxWidth: 1200,
              margin: '0 auto',
              width: '100%',
              boxSizing: 'border-box',
              minHeight: 'calc(100dvh - 60px)',
            }}
          >
            <header style={{ flexShrink: 0, marginBottom: 6, paddingTop: 4 }}>
              <div style={{ height: 0.5, background: 'var(--border-color)' }} />
            </header>

            {/* Press window */}
            <motion.div
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ opacity: { duration: 0.45, delay: 0.05 }, y: { duration: 0.45, delay: 0.05 } }}
              style={{
                flex: 1,
                minHeight: 0,
                display: 'flex',
                flexDirection: 'column',
                alignItems: view === 'desktop' ? 'stretch' : 'center',
                width: '100%',
                marginBottom: 28,
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
                {/* Chrome */}
                <div style={{ borderBottom: '0.5px solid var(--border-strong)', background: 'var(--paper-dark)', flexShrink: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 14px 12px' }}>
                    <div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
                      {['var(--red)', '#b88a3a', '#3d7a4a'].map((c) => (
                        <span key={c} style={{ width: 8, height: 8, borderRadius: '50%', background: c, opacity: 0.85 }} />
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
                        onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); handlePullProof() } }}
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
                        {SOFTWARE_TYPES.map((pt) => (
                          <option key={pt} value={pt}>{formatProductTypeLabel(pt)}</option>
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
                  {generateError && (
                    <p style={{ padding: '0 14px 10px', margin: 0, fontSize: 11, color: 'var(--red)' }}>
                      The presses jammed — {generateError}
                    </p>
                  )}
                </div>

                {/* Preview area */}
                <div style={{ position: 'relative', flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
                  {(generateMutation.isPending || isLoadingUiHistory) && (
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
                        {generateMutation.isPending ? 'Compositor is setting your line…' : 'Checking saved plates…'}
                      </span>
                    </div>
                  )}
                  {previewIframe}
                </div>

                {/* Press tools */}
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
                          onClick={handleEnterEdit}
                          className="btn-ink"
                          style={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: 8,
                            padding: '8px 14px',
                            fontSize: 10,
                            letterSpacing: '0.16em',
                            textTransform: 'uppercase',
                          }}
                        >
                          <Pencil style={{ width: 11, height: 11 }} />
                          Edit site
                        </button>
                      ) : (
                        <p style={{ margin: 0, fontSize: 12, color: 'var(--ink-secondary)', maxWidth: 520 }}>
                          Pull a fresh proof from the line above to enable site editing.
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

            {/* Footer */}
            <footer
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 16,
                marginTop: 'auto',
                paddingTop: 22,
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
          </motion.div>
        )}

        {/* ═══ EDIT MODE ════════════════════════════════════════════ */}
        {editMode && (
          <motion.div
            key="edit"
            initial={PAGE_HIDDEN}
            animate={PAGE_ENTER}
            exit={PAGE_GONE}
            transition={{ duration: 0.42, ease: EASE_IN }}
            style={{
              position: 'fixed',
              inset: 0,
              top: 60,
              display: 'flex',
              flexDirection: 'column',
              zIndex: 40,
              background: 'var(--paper)',
            }}
          >
            {/* Edit mode header bar */}
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '0 24px',
                height: 48,
                background: 'var(--ink)',
                borderBottom: '0.5px solid rgba(242,236,224,0.1)',
                flexShrink: 0,
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
                <div style={{ width: 2, height: 14, background: 'var(--red)' }} />
                <span
                  style={{
                    fontSize: 9,
                    letterSpacing: '0.32em',
                    textTransform: 'uppercase',
                    color: 'rgba(242,236,224,0.55)',
                    fontWeight: 600,
                    fontFamily: 'var(--font-body)',
                  }}
                >
                  Edit room
                </span>
                {editApplied && (
                  <motion.span
                    initial={{ opacity: 0, x: -6 }}
                    animate={{ opacity: 1, x: 0 }}
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: 5,
                      fontSize: 9,
                      letterSpacing: '0.18em',
                      textTransform: 'uppercase',
                      color: '#4caf50',
                      fontWeight: 600,
                      fontFamily: 'var(--font-body)',
                    }}
                  >
                    <Check style={{ width: 10, height: 10 }} />
                    Changes applied
                  </motion.span>
                )}
              </div>
              <button
                type="button"
                onClick={handleExitEdit}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 8,
                  padding: '7px 18px',
                  background: 'var(--red)',
                  color: '#fff',
                  border: 'none',
                  fontFamily: 'var(--font-body)',
                  fontSize: 9,
                  fontWeight: 700,
                  letterSpacing: '0.22em',
                  textTransform: 'uppercase',
                  cursor: 'pointer',
                }}
              >
                Done <Check style={{ width: 11, height: 11 }} />
              </button>
            </div>

            {/* Split body */}
            <div style={{ flex: 1, minHeight: 0, display: 'flex' }}>

              {/* Left — edit panel */}
              <div
                style={{
                  width: '38%',
                  flexShrink: 0,
                  background: 'var(--ink)',
                  display: 'flex',
                  flexDirection: 'column',
                  borderRight: '0.5px solid rgba(242,236,224,0.08)',
                  overflowY: 'auto',
                }}
              >
                <div style={{ padding: '28px 28px 0' }}>
                  <div
                    style={{
                      fontSize: 9,
                      letterSpacing: '0.3em',
                      textTransform: 'uppercase',
                      color: 'var(--red)',
                      fontWeight: 600,
                      fontFamily: 'var(--font-body)',
                      marginBottom: 12,
                    }}
                  >
                    Revision instruction
                  </div>
                  <p
                    className="font-serif"
                    style={{
                      fontSize: 13,
                      fontStyle: 'italic',
                      fontWeight: 600,
                      color: 'rgba(242,236,224,0.55)',
                      lineHeight: 1.55,
                      marginBottom: 20,
                    }}
                  >
                    Tell the compositor what to change — section, copy, colours, layout, anything.
                  </p>
                </div>

                <div style={{ padding: '0 28px', flex: 1, display: 'flex', flexDirection: 'column', gap: 14, paddingBottom: 28 }}>
                  <textarea
                    value={editPrompt}
                    onChange={(e) => setEditPrompt(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                        e.preventDefault()
                        handleApplyEdit()
                      }
                    }}
                    placeholder="e.g. Change the hero headline to focus on price. Make the CTA button red. Add a testimonials section with three quotes from Indian founders."
                    disabled={refineMutation.isPending}
                    rows={7}
                    style={{
                      width: '100%',
                      resize: 'vertical',
                      padding: '12px 14px',
                      background: 'rgba(242,236,224,0.06)',
                      border: '0.5px solid rgba(242,236,224,0.15)',
                      color: 'var(--paper)',
                      fontFamily: 'var(--font-body)',
                      fontSize: 13,
                      lineHeight: 1.65,
                      outline: 'none',
                      boxSizing: 'border-box',
                    }}
                  />

                  {/* Quick suggestion chips */}
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    <div
                      style={{
                        fontSize: 8,
                        letterSpacing: '0.28em',
                        textTransform: 'uppercase',
                        color: 'rgba(242,236,224,0.3)',
                        fontWeight: 600,
                        fontFamily: 'var(--font-body)',
                      }}
                    >
                      Quick edits
                    </div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                      {EDIT_SUGGESTIONS.map((s) => (
                        <button
                          key={s}
                          type="button"
                          onClick={() => setEditPrompt(s)}
                          disabled={refineMutation.isPending}
                          style={{
                            padding: '5px 10px',
                            background: 'rgba(242,236,224,0.06)',
                            border: '0.5px solid rgba(242,236,224,0.12)',
                            color: 'rgba(242,236,224,0.5)',
                            fontFamily: 'var(--font-body)',
                            fontSize: 10,
                            letterSpacing: '0.06em',
                            cursor: refineMutation.isPending ? 'not-allowed' : 'pointer',
                            textAlign: 'left',
                          }}
                          onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.borderColor = 'rgba(192,57,43,0.5)'; (e.currentTarget as HTMLButtonElement).style.color = 'rgba(242,236,224,0.8)' }}
                          onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.borderColor = 'rgba(242,236,224,0.12)'; (e.currentTarget as HTMLButtonElement).style.color = 'rgba(242,236,224,0.5)' }}
                        >
                          {s}
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* Error */}
                  {refineError && (
                    <div
                      style={{
                        padding: '10px 12px',
                        background: 'rgba(192,57,43,0.12)',
                        border: '0.5px solid rgba(192,57,43,0.3)',
                        display: 'flex',
                        alignItems: 'flex-start',
                        gap: 8,
                      }}
                    >
                      <X style={{ width: 12, height: 12, color: 'var(--red)', flexShrink: 0, marginTop: 1 }} />
                      <span style={{ fontSize: 11, color: 'rgba(242,236,224,0.7)', fontFamily: 'var(--font-body)', lineHeight: 1.55 }}>
                        {refineError}
                      </span>
                    </div>
                  )}

                  {/* Apply button */}
                  <button
                    type="button"
                    onClick={handleApplyEdit}
                    disabled={!editPrompt.trim() || refineMutation.isPending}
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: 8,
                      padding: '12px 20px',
                      background: !editPrompt.trim() || refineMutation.isPending ? 'rgba(242,236,224,0.08)' : 'var(--red)',
                      color: !editPrompt.trim() || refineMutation.isPending ? 'rgba(242,236,224,0.3)' : '#fff',
                      border: 'none',
                      fontFamily: 'var(--font-body)',
                      fontSize: 10,
                      fontWeight: 700,
                      letterSpacing: '0.2em',
                      textTransform: 'uppercase',
                      cursor: !editPrompt.trim() || refineMutation.isPending ? 'not-allowed' : 'pointer',
                      transition: 'background 200ms ease, color 200ms ease',
                    }}
                  >
                    {refineMutation.isPending ? (
                      <>
                        <Loader2 className="animate-spin" style={{ width: 12, height: 12 }} />
                        Compositor working…
                      </>
                    ) : (
                      <>Apply changes</>
                    )}
                  </button>

                  <p style={{ margin: 0, fontSize: 10, color: 'rgba(242,236,224,0.2)', fontFamily: 'var(--font-body)', letterSpacing: '0.04em' }}>
                    ⌘ + Enter to apply · Changes are saved automatically
                  </p>
                </div>
              </div>

              {/* Right — live preview */}
              <div
                style={{
                  flex: 1,
                  minWidth: 0,
                  display: 'flex',
                  flexDirection: 'column',
                  position: 'relative',
                  background: '#e8e2d8',
                }}
              >
                {/* Preview label */}
                <div
                  style={{
                    padding: '8px 16px',
                    borderBottom: '0.5px solid rgba(26,23,20,0.12)',
                    background: 'var(--paper-dark)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    flexShrink: 0,
                  }}
                >
                  <span
                    style={{
                      fontSize: 9,
                      letterSpacing: '0.28em',
                      textTransform: 'uppercase',
                      color: 'var(--ink-secondary)',
                      fontWeight: 600,
                      fontFamily: 'var(--font-body)',
                    }}
                  >
                    Live preview
                  </span>
                  {editApplied && (
                    <motion.span
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      style={{
                        fontSize: 9,
                        letterSpacing: '0.18em',
                        textTransform: 'uppercase',
                        color: 'var(--red)',
                        fontWeight: 600,
                        fontFamily: 'var(--font-body)',
                      }}
                    >
                      Updated
                    </motion.span>
                  )}
                </div>

                {/* Refine loading overlay */}
                {refineMutation.isPending && (
                  <div
                    style={{
                      position: 'absolute',
                      inset: 0,
                      top: 37,
                      zIndex: 2,
                      display: 'flex',
                      flexDirection: 'column',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: 14,
                      background: 'rgba(242,236,224,0.88)',
                    }}
                  >
                    <Loader2 className="animate-spin" style={{ width: 24, height: 24, color: 'var(--red)' }} />
                    <span
                      style={{
                        fontSize: 11,
                        letterSpacing: '0.22em',
                        textTransform: 'uppercase',
                        color: 'var(--ink-secondary)',
                        fontWeight: 600,
                        fontFamily: 'var(--font-body)',
                      }}
                    >
                      Setting new type…
                    </span>
                  </div>
                )}

                {/* iframe */}
                <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
                  {previewIframe}
                </div>
              </div>
            </div>
          </motion.div>
        )}

      </AnimatePresence>
    </div>
  )
}
