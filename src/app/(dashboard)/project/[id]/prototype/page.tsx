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

interface Revision {
  prompt: string
  at: Date
  version: number
  status: 'pending' | 'applied' | 'error'
  errorMsg?: string
}

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
  const [revisions, setRevisions] = useState<Revision[]>([])

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
      setRevisions(prev => prev.map((r, i) => i === 0 ? { ...r, status: 'applied' as const } : r))
      setUiPreviewPath(data.html_preview_url)
      setGeneratedUiId(data.id)
      setEditApplied(true)
      void qc.invalidateQueries({ queryKey: ['generated-uis', projectId] })
    },
    onError: (err) => {
      setRevisions(prev => prev.map((r, i) => i === 0 ? { ...r, status: 'error' as const, errorMsg: apiError(err) } : r))
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
    setRevisions([])
    refineMutation.reset()
    setEditPrompt('')
    setEditMode(true)
  }

  const handleExitEdit = () => {
    setEditMode(false)
    refineMutation.reset()
  }

  const hasRevised = revisions.length > 0

  const handleApplyEdit = () => {
    if (!editPrompt.trim() || generatedUiId == null || revisions[0]?.status === 'pending') return
    const submittedPrompt = editPrompt.trim()
    setRevisions(prev => [{
      prompt: submittedPrompt,
      at: new Date(),
      version: prev.length + 1,
      status: 'pending' as const,
    }, ...prev])
    setEditPrompt('')
    refineMutation.mutate({ generated_ui_id: generatedUiId, refinement_prompt: submittedPrompt })
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
              background: 'var(--ink)',
            }}
          >
            {/* ── Masthead bar ─────────────────────────────────────── */}
            <div
              style={{
                height: 3,
                background: 'var(--red)',
                flexShrink: 0,
              }}
            />
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '0 32px',
                height: 52,
                background: 'var(--ink)',
                borderBottom: '0.5px solid rgba(242,236,224,0.08)',
                flexShrink: 0,
              }}
            >
              {/* Left: folio label */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 20 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span
                    className="font-serif"
                    style={{
                      fontSize: 18,
                      fontWeight: 900,
                      fontStyle: 'italic',
                      color: 'var(--paper)',
                      letterSpacing: '-0.03em',
                      opacity: 0.9,
                    }}
                  >
                    Edit Room
                  </span>
                </div>
                <div style={{ width: 0.5, height: 16, background: 'rgba(242,236,224,0.15)' }} />
                <span
                  style={{
                    fontSize: 9,
                    letterSpacing: '0.3em',
                    textTransform: 'uppercase',
                    color: 'rgba(242,236,224,0.35)',
                    fontWeight: 600,
                    fontFamily: 'var(--font-body)',
                  }}
                >
                  Compositor's desk
                </span>
                <AnimatePresence>
                  {editApplied && (
                    <motion.div
                      initial={{ opacity: 0, x: -8 }}
                      animate={{ opacity: 1, x: 0 }}
                      exit={{ opacity: 0 }}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 6,
                        padding: '3px 10px',
                        border: '0.5px solid rgba(74,222,128,0.3)',
                        background: 'rgba(74,222,128,0.08)',
                      }}
                    >
                      <Check style={{ width: 9, height: 9, color: 'rgb(74,222,128)' }} />
                      <span
                        style={{
                          fontSize: 8,
                          letterSpacing: '0.22em',
                          textTransform: 'uppercase',
                          color: 'rgb(74,222,128)',
                          fontWeight: 700,
                          fontFamily: 'var(--font-body)',
                        }}
                      >
                        Plate updated
                      </span>
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>

              {/* Right: Done */}
              <button
                type="button"
                onClick={handleExitEdit}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 8,
                  padding: '9px 22px',
                  background: editApplied ? 'var(--red)' : 'rgba(242,236,224,0.08)',
                  color: editApplied ? '#fff' : 'rgba(242,236,224,0.5)',
                  border: editApplied ? 'none' : '0.5px solid rgba(242,236,224,0.15)',
                  fontFamily: 'var(--font-body)',
                  fontSize: 9,
                  fontWeight: 700,
                  letterSpacing: '0.24em',
                  textTransform: 'uppercase',
                  cursor: 'pointer',
                  transition: 'background 300ms ease, color 300ms ease, border-color 300ms ease',
                }}
              >
                {editApplied ? 'Save & close' : 'Close'}
                <Check style={{ width: 10, height: 10 }} />
              </button>
            </div>

            {/* ── Split body ───────────────────────────────────────── */}
            <div style={{ flex: 1, minHeight: 0, display: 'flex' }}>

              {/* ── Left panel ───────────────────────────────────── */}
              <div
                style={{
                  width: '36%',
                  flexShrink: 0,
                  background: 'var(--ink)',
                  display: 'flex',
                  flexDirection: 'column',
                  borderRight: '0.5px solid rgba(242,236,224,0.08)',
                  overflow: 'hidden',
                  position: 'relative',
                }}
              >
                <AnimatePresence mode="wait" initial={false}>

                  {/* ── FRESH STATE — shown before first revision ── */}
                  {!hasRevised && (
                    <motion.div
                      key="fresh"
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      exit={{ opacity: 0, y: -16 }}
                      transition={{ duration: 0.3, ease: EASE_OUT }}
                      style={{ overflowY: 'auto', scrollbarWidth: 'none', flex: 1 }}
                    >
                      {/* Section I — Brief */}
                      <div style={{ padding: '32px 32px 28px' }}>
                        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 16, marginBottom: 20 }}>
                          <span className="font-serif" style={{ fontSize: 28, fontWeight: 900, fontStyle: 'italic', color: 'rgba(242,236,224,0.12)', lineHeight: 1, flexShrink: 0, marginTop: 2, letterSpacing: '-0.02em' }}>
                            I.
                          </span>
                          <div>
                            <div style={{ fontSize: 9, letterSpacing: '0.32em', textTransform: 'uppercase', color: 'var(--red)', fontWeight: 700, fontFamily: 'var(--font-body)', marginBottom: 6 }}>
                              Revision instruction
                            </div>
                            <p className="font-serif" style={{ fontSize: 12, fontStyle: 'italic', fontWeight: 500, color: 'rgba(242,236,224,0.4)', lineHeight: 1.6, margin: 0 }}>
                              Tell the compositor what to change — copy, colours, sections, layout.
                            </p>
                          </div>
                        </div>
                        <textarea
                          value={editPrompt}
                          onChange={(e) => setEditPrompt(e.target.value)}
                          onKeyDown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); handleApplyEdit() } }}
                          placeholder="e.g. Change the hero headline to focus on price. Make the CTA button dark red. Add a testimonials section with three quotes from Indian founders…"
                          rows={6}
                          style={{ width: '100%', resize: 'none', padding: '14px 16px', background: 'rgba(242,236,224,0.04)', border: '0.5px solid rgba(242,236,224,0.12)', borderLeft: '2px solid rgba(192,57,43,0.5)', color: 'rgba(242,236,224,0.88)', fontFamily: 'var(--font-body)', fontSize: 13, lineHeight: 1.7, outline: 'none', boxSizing: 'border-box', letterSpacing: '0.01em', transition: 'border-color 200ms ease' }}
                          onFocus={(e) => { e.currentTarget.style.borderLeftColor = 'var(--red)'; e.currentTarget.style.background = 'rgba(242,236,224,0.06)' }}
                          onBlur={(e) => { e.currentTarget.style.borderLeftColor = 'rgba(192,57,43,0.5)'; e.currentTarget.style.background = 'rgba(242,236,224,0.04)' }}
                        />
                        <div style={{ marginTop: 8, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                          <span style={{ fontSize: 9, color: 'rgba(242,236,224,0.2)', fontFamily: 'var(--font-body)', letterSpacing: '0.06em' }}>⌘ Return to apply</span>
                          <span style={{ fontSize: 9, color: editPrompt.length > 400 ? 'rgba(192,57,43,0.7)' : 'rgba(242,236,224,0.18)', fontFamily: 'var(--font-body)', fontVariantNumeric: 'tabular-nums' }}>{editPrompt.length}/600</span>
                        </div>
                      </div>

                      <div style={{ height: '0.5px', background: 'rgba(242,236,224,0.07)', marginInline: 32 }} />

                      {/* Section II — Quick revisions (first-time hint) */}
                      <div style={{ padding: '24px 32px 28px' }}>
                        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 16 }}>
                          <span className="font-serif" style={{ fontSize: 28, fontWeight: 900, fontStyle: 'italic', color: 'rgba(242,236,224,0.12)', lineHeight: 1, flexShrink: 0, marginTop: 2, letterSpacing: '-0.02em' }}>
                            II.
                          </span>
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <div style={{ fontSize: 9, letterSpacing: '0.32em', textTransform: 'uppercase', color: 'rgba(242,236,224,0.35)', fontWeight: 700, fontFamily: 'var(--font-body)', marginBottom: 12 }}>
                              Quick revisions
                            </div>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
                              {EDIT_SUGGESTIONS.map((s) => (
                                <button
                                  key={s}
                                  type="button"
                                  onClick={() => setEditPrompt(s)}
                                  style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '9px 12px', background: 'transparent', border: '0.5px solid rgba(242,236,224,0.08)', color: 'rgba(242,236,224,0.45)', fontFamily: 'var(--font-body)', fontSize: 11, letterSpacing: '0.02em', cursor: 'pointer', textAlign: 'left', transition: 'all 160ms ease', lineHeight: 1.4 }}
                                  onMouseEnter={(e) => { const el = e.currentTarget as HTMLButtonElement; el.style.background = 'rgba(192,57,43,0.08)'; el.style.borderColor = 'rgba(192,57,43,0.25)'; el.style.color = 'rgba(242,236,224,0.8)' }}
                                  onMouseLeave={(e) => { const el = e.currentTarget as HTMLButtonElement; el.style.background = 'transparent'; el.style.borderColor = 'rgba(242,236,224,0.08)'; el.style.color = 'rgba(242,236,224,0.45)' }}
                                >
                                  <div style={{ width: 3, height: 3, borderRadius: '50%', background: 'var(--red)', flexShrink: 0, opacity: 0.6 }} />
                                  {s}
                                </button>
                              ))}
                            </div>
                          </div>
                        </div>
                      </div>

                      <div style={{ height: '0.5px', background: 'rgba(242,236,224,0.07)', marginInline: 32 }} />

                      {/* Section III — Apply */}
                      <div style={{ padding: '24px 32px 36px' }}>
                        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 16 }}>
                          <span className="font-serif" style={{ fontSize: 28, fontWeight: 900, fontStyle: 'italic', color: 'rgba(242,236,224,0.12)', lineHeight: 1, flexShrink: 0, marginTop: 2, letterSpacing: '-0.02em' }}>
                            III.
                          </span>
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <div style={{ fontSize: 9, letterSpacing: '0.32em', textTransform: 'uppercase', color: 'rgba(242,236,224,0.35)', fontWeight: 700, fontFamily: 'var(--font-body)', marginBottom: 14 }}>
                              Run the press
                            </div>
                            <button
                              type="button"
                              onClick={handleApplyEdit}
                              disabled={!editPrompt.trim()}
                              style={{ width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10, padding: '14px 20px', background: editPrompt.trim() ? 'var(--red)' : 'rgba(242,236,224,0.06)', color: editPrompt.trim() ? '#fff' : 'rgba(242,236,224,0.25)', border: editPrompt.trim() ? 'none' : '0.5px solid rgba(242,236,224,0.1)', fontFamily: 'var(--font-body)', fontSize: 9, fontWeight: 700, letterSpacing: '0.26em', textTransform: 'uppercase', cursor: editPrompt.trim() ? 'pointer' : 'not-allowed', transition: 'background 200ms ease, color 200ms ease' }}
                            >
                              <Pencil style={{ width: 10, height: 10 }} />
                              Apply revision
                            </button>
                            <p style={{ margin: '10px 0 0', fontSize: 9, color: 'rgba(242,236,224,0.15)', fontFamily: 'var(--font-body)', letterSpacing: '0.06em', textAlign: 'center' }}>
                              Revisions are saved automatically — iterate freely
                            </p>
                          </div>
                        </div>
                      </div>
                    </motion.div>
                  )}

                  {/* ── WORKING STATE — shown after first revision ─ */}
                  {hasRevised && (
                    <motion.div
                      key="log"
                      initial={{ opacity: 0, y: 20 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0 }}
                      transition={{ duration: 0.36, ease: EASE_IN }}
                      style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0, height: '100%' }}
                    >
                      {/* Log header */}
                      <div style={{ padding: '20px 32px 16px', borderBottom: '0.5px solid rgba(242,236,224,0.08)', flexShrink: 0 }}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                          <div>
                            <div style={{ fontSize: 8, letterSpacing: '0.35em', textTransform: 'uppercase', color: 'var(--red)', fontWeight: 700, fontFamily: 'var(--font-body)', marginBottom: 3 }}>
                              Press log
                            </div>
                            <p style={{ margin: 0, fontSize: 11, color: 'rgba(242,236,224,0.28)', fontStyle: 'italic', fontFamily: 'var(--font-serif)' }}>
                              {revisions.filter(r => r.status === 'applied').length} revision{revisions.filter(r => r.status === 'applied').length !== 1 ? 's' : ''} applied to the plate
                            </p>
                          </div>
                          <AnimatePresence>
                            {revisions[0]?.status === 'pending' && (
                              <motion.div
                                initial={{ opacity: 0 }}
                                animate={{ opacity: 1 }}
                                exit={{ opacity: 0 }}
                                style={{ display: 'flex', alignItems: 'center', gap: 6 }}
                              >
                                <Loader2 className="animate-spin" style={{ width: 8, height: 8, color: 'var(--red)', opacity: 0.85 }} />
                                <span style={{ fontSize: 7, letterSpacing: '0.28em', textTransform: 'uppercase', color: 'rgba(192,57,43,0.85)', fontWeight: 700, fontFamily: 'var(--font-body)' }}>
                                  Live
                                </span>
                              </motion.div>
                            )}
                          </AnimatePresence>
                        </div>
                      </div>

                      {/* Revision entries — newest first, scrollable */}
                      <div style={{ flex: 1, overflowY: 'auto', scrollbarWidth: 'none' }}>
                        <AnimatePresence initial={false}>
                          {revisions.map((rev) => (
                            <motion.div
                              key={`rev-${rev.version}`}
                              initial={{ opacity: 0, y: -10 }}
                              animate={{ opacity: 1, y: 0 }}
                              transition={{ duration: 0.28 }}
                              style={{ borderBottom: '0.5px solid rgba(242,236,224,0.05)', position: 'relative' }}
                            >
                              {/* Left status stripe */}
                              <div style={{
                                position: 'absolute', left: 0, top: 14, bottom: 14, width: 2,
                                background: rev.status === 'applied' ? 'rgba(74,222,128,0.45)' : rev.status === 'error' ? 'rgba(192,57,43,0.55)' : 'rgba(192,57,43,0.22)',
                                transition: 'background 500ms ease',
                              }} />
                              <div style={{ padding: '16px 32px 16px 18px' }}>
                                {/* Meta row */}
                                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
                                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                    <span style={{ fontSize: 8, letterSpacing: '0.26em', textTransform: 'uppercase', fontWeight: 700, color: 'rgba(242,236,224,0.35)', fontFamily: 'var(--font-body)' }}>
                                      Rev. {rev.version}
                                    </span>
                                    <div style={{ width: 1, height: 8, background: 'rgba(242,236,224,0.1)' }} />
                                    <span style={{ fontSize: 8, color: 'rgba(242,236,224,0.2)', fontFamily: 'var(--font-body)', letterSpacing: '0.04em' }}>
                                      {rev.at.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                                    </span>
                                  </div>
                                  {rev.status === 'pending' && (
                                    <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                                      <Loader2 className="animate-spin" style={{ width: 8, height: 8, color: 'rgba(192,57,43,0.65)' }} />
                                      <span style={{ fontSize: 7, letterSpacing: '0.22em', textTransform: 'uppercase', color: 'rgba(192,57,43,0.65)', fontWeight: 700, fontFamily: 'var(--font-body)' }}>Working</span>
                                    </div>
                                  )}
                                  {rev.status === 'applied' && (
                                    <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                                      <Check style={{ width: 8, height: 8, color: 'rgba(74,222,128,0.75)' }} />
                                      <span style={{ fontSize: 7, letterSpacing: '0.22em', textTransform: 'uppercase', color: 'rgba(74,222,128,0.75)', fontWeight: 700, fontFamily: 'var(--font-body)' }}>Applied</span>
                                    </div>
                                  )}
                                  {rev.status === 'error' && (
                                    <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                                      <X style={{ width: 8, height: 8, color: 'var(--red)' }} />
                                      <span style={{ fontSize: 7, letterSpacing: '0.22em', textTransform: 'uppercase', color: 'var(--red)', fontWeight: 700, fontFamily: 'var(--font-body)' }}>Failed</span>
                                    </div>
                                  )}
                                </div>
                                {/* Prompt text */}
                                <p style={{ margin: 0, fontSize: 12, fontStyle: 'italic', fontFamily: 'var(--font-serif)', color: rev.status === 'pending' ? 'rgba(242,236,224,0.38)' : 'rgba(242,236,224,0.62)', lineHeight: 1.6, transition: 'color 400ms ease' }}>
                                  &ldquo;{rev.prompt}&rdquo;
                                </p>
                                {rev.status === 'error' && rev.errorMsg && (
                                  <p style={{ margin: '6px 0 0', fontSize: 10, color: 'rgba(192,57,43,0.65)', fontFamily: 'var(--font-body)', lineHeight: 1.45 }}>
                                    {rev.errorMsg}
                                  </p>
                                )}
                              </div>
                            </motion.div>
                          ))}
                        </AnimatePresence>
                      </div>

                      {/* Bottom input — sticky */}
                      <div style={{ borderTop: '0.5px solid rgba(242,236,224,0.1)', padding: '18px 32px 26px', flexShrink: 0, background: 'rgba(0,0,0,0.18)' }}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
                          <div style={{ fontSize: 8, letterSpacing: '0.32em', textTransform: 'uppercase', color: 'rgba(242,236,224,0.22)', fontWeight: 700, fontFamily: 'var(--font-body)' }}>
                            New instruction
                          </div>
                          <span style={{ fontSize: 9, color: editPrompt.length > 400 ? 'rgba(192,57,43,0.7)' : 'rgba(242,236,224,0.16)', fontFamily: 'var(--font-body)', fontVariantNumeric: 'tabular-nums', transition: 'color 200ms' }}>
                            {editPrompt.length}/600
                          </span>
                        </div>
                        <textarea
                          value={editPrompt}
                          onChange={(e) => setEditPrompt(e.target.value)}
                          onKeyDown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); handleApplyEdit() } }}
                          placeholder="Another instruction for the compositor…"
                          disabled={revisions[0]?.status === 'pending'}
                          rows={3}
                          style={{ width: '100%', resize: 'none', padding: '11px 14px', background: 'rgba(242,236,224,0.04)', border: '0.5px solid rgba(242,236,224,0.1)', borderLeft: '2px solid rgba(192,57,43,0.4)', color: 'rgba(242,236,224,0.85)', fontFamily: 'var(--font-body)', fontSize: 12, lineHeight: 1.65, outline: 'none', boxSizing: 'border-box', transition: 'border-color 200ms ease, background 200ms ease', opacity: revisions[0]?.status === 'pending' ? 0.45 : 1 }}
                          onFocus={(e) => { e.currentTarget.style.borderLeftColor = 'var(--red)'; e.currentTarget.style.background = 'rgba(242,236,224,0.06)' }}
                          onBlur={(e) => { e.currentTarget.style.borderLeftColor = 'rgba(192,57,43,0.4)'; e.currentTarget.style.background = 'rgba(242,236,224,0.04)' }}
                        />
                        <div style={{ marginTop: 10, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                          <span style={{ fontSize: 9, color: 'rgba(242,236,224,0.16)', fontFamily: 'var(--font-body)', letterSpacing: '0.06em' }}>⌘ Return to apply</span>
                          <button
                            type="button"
                            onClick={handleApplyEdit}
                            disabled={!editPrompt.trim() || revisions[0]?.status === 'pending'}
                            style={{ display: 'inline-flex', alignItems: 'center', gap: 8, padding: '9px 18px', background: editPrompt.trim() && revisions[0]?.status !== 'pending' ? 'var(--red)' : 'rgba(242,236,224,0.06)', color: editPrompt.trim() && revisions[0]?.status !== 'pending' ? '#fff' : 'rgba(242,236,224,0.2)', border: editPrompt.trim() && revisions[0]?.status !== 'pending' ? 'none' : '0.5px solid rgba(242,236,224,0.1)', fontFamily: 'var(--font-body)', fontSize: 8, fontWeight: 700, letterSpacing: '0.24em', textTransform: 'uppercase', cursor: editPrompt.trim() && revisions[0]?.status !== 'pending' ? 'pointer' : 'not-allowed', transition: 'all 200ms ease' }}
                          >
                            {revisions[0]?.status === 'pending' ? (
                              <><Loader2 className="animate-spin" style={{ width: 9, height: 9 }} /> Working…</>
                            ) : (
                              <><Pencil style={{ width: 9, height: 9 }} /> Apply</>
                            )}
                          </button>
                        </div>
                      </div>
                    </motion.div>
                  )}

                </AnimatePresence>
              </div>

              {/* ── Right panel — live preview ──────────────────── */}
              <div
                style={{
                  flex: 1,
                  minWidth: 0,
                  display: 'flex',
                  flexDirection: 'column',
                  position: 'relative',
                  background: 'var(--paper-dark)',
                }}
              >
                {/* Preview bar */}
                <div
                  style={{
                    padding: '10px 20px',
                    borderBottom: '0.5px solid rgba(26,23,20,0.1)',
                    background: 'var(--paper)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    flexShrink: 0,
                    height: 40,
                    boxSizing: 'border-box',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    {/* Traffic-light dots matching the chrome bar */}
                    {['var(--red)', '#b88a3a', '#3d7a4a'].map((c) => (
                      <span key={c} style={{ width: 8, height: 8, borderRadius: '50%', background: c, opacity: 0.7 }} />
                    ))}
                    <div style={{ width: 0.5, height: 12, background: 'var(--border-color)', marginLeft: 4 }} />
                    <span
                      style={{
                        fontSize: 9,
                        letterSpacing: '0.24em',
                        textTransform: 'uppercase',
                        color: 'var(--ink-tertiary)',
                        fontWeight: 600,
                        fontFamily: 'var(--font-body)',
                      }}
                    >
                      Reader's view
                    </span>
                  </div>

                  <AnimatePresence>
                    {editApplied && (
                      <motion.div
                        initial={{ opacity: 0, scale: 0.92 }}
                        animate={{ opacity: 1, scale: 1 }}
                        exit={{ opacity: 0 }}
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: 5,
                          padding: '3px 10px',
                          background: 'rgba(192,57,43,0.08)',
                          border: '0.5px solid rgba(192,57,43,0.2)',
                        }}
                      >
                        <div style={{ width: 5, height: 5, borderRadius: '50%', background: 'var(--red)' }} />
                        <span
                          style={{
                            fontSize: 8,
                            letterSpacing: '0.22em',
                            textTransform: 'uppercase',
                            color: 'var(--red)',
                            fontWeight: 700,
                            fontFamily: 'var(--font-body)',
                          }}
                        >
                          Revised proof
                        </span>
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>

                {/* Refine loading overlay */}
                {refineMutation.isPending && (
                  <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    style={{
                      position: 'absolute',
                      inset: 0,
                      top: 40,
                      zIndex: 2,
                      display: 'flex',
                      flexDirection: 'column',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: 18,
                      background: 'rgba(242,236,224,0.9)',
                      backdropFilter: 'blur(4px)',
                    }}
                  >
                    <Loader2 className="animate-spin" style={{ width: 28, height: 28, color: 'var(--red)' }} />
                    <div style={{ textAlign: 'center' }}>
                      <p
                        className="font-serif"
                        style={{
                          fontSize: 16,
                          fontStyle: 'italic',
                          fontWeight: 700,
                          color: 'var(--ink)',
                          marginBottom: 6,
                        }}
                      >
                        Resetting the type…
                      </p>
                      <p
                        style={{
                          fontSize: 11,
                          letterSpacing: '0.18em',
                          textTransform: 'uppercase',
                          color: 'var(--ink-secondary)',
                          fontFamily: 'var(--font-body)',
                          fontWeight: 600,
                        }}
                      >
                        Compositor is working
                      </p>
                    </div>
                  </motion.div>
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
