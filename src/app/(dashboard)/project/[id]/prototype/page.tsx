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
  const appliedRevisionCount = revisions.filter(r => r.status === 'applied').length
  const isRefining = revisions[0]?.status === 'pending'
  const canApplyEdit = editPrompt.trim().length > 0 && !isRefining
  const editCharOverSoftLimit = editPrompt.length > 400

  const handleApplyEdit = () => {
    if (!editPrompt.trim() || generatedUiId == null || isRefining) return
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

        {/* ═══ EDIT MODE (Modern Studio) ════════════════════════════ */}
        {editMode && (
          <motion.div
            key="edit"
            initial={PAGE_HIDDEN}
            animate={PAGE_ENTER}
            exit={PAGE_GONE}
            transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
            style={{
              position: 'fixed',
              inset: 0,
              top: 64,
              display: 'flex',
              flexDirection: 'column',
              zIndex: 40,
              background: '#0a0a0a',
              borderTop: '1px solid rgba(192,57,43,0.3)',
            }}
          >
            {/* ── Split body ───────────────────────────────────────── */}
            <div style={{ flex: 1, minHeight: 0, display: 'flex', background: 'linear-gradient(90deg, #0a0a0a 0%, #0a0a0a 34%, var(--paper) 34%, var(--paper) 100%)' }}>

              {/* ── Left panel (Compositor Desk) ───────────────────────────────────── */}
              <div
                style={{
                  width: '34%',
                  minWidth: 440,
                  maxWidth: 540,
                  flexShrink: 0,
                  background: '#0a0a0a',
                  display: 'flex',
                  flexDirection: 'column',
                  position: 'relative',
                  borderRight: '1px solid rgba(255,255,255,0.06)',
                  zIndex: 10,
                  boxShadow: '24px 0 60px rgba(0,0,0,0.5)',
                  overflow: 'hidden',
                }}
              >
                {/* Atmospheric Glows */}
                <div aria-hidden="true" style={{ position: 'absolute', top: -100, right: -100, width: 400, height: 400, background: 'var(--red)', filter: 'blur(140px)', opacity: 0.12, borderRadius: '50%', pointerEvents: 'none' }} />
                <div aria-hidden="true" style={{ position: 'absolute', bottom: -50, left: -50, width: 300, height: 300, background: '#4a4540', filter: 'blur(120px)', opacity: 0.15, borderRadius: '50%', pointerEvents: 'none' }} />
                
                {/* Grain overlay */}
                <div aria-hidden="true" style={{ position: 'absolute', inset: 0, opacity: 0.04, pointerEvents: 'none', backgroundImage: 'url("data:image/svg+xml,%3Csvg viewBox=%220 0 200 200%22 xmlns=%22http://www.w3.org/2000/svg%22%3E%3Cfilter id=%22noise%22%3E%3CfeTurbulence type=%22fractalNoise%22 baseFrequency=%220.85%22 numOctaves=%223%22 stitchTiles=%22stitch%22/%3E%3C/filter%3E%3Crect width=%22100%25%22 height=%22100%25%22 filter=%22url(%23noise)%22/%3E%3C/svg%3E")' }} />

                <AnimatePresence mode="wait" initial={false}>

                  {/* ── FRESH STATE ── */}
                  {!hasRevised && (
                    <motion.div
                      key="fresh"
                      initial={{ opacity: 0, x: -10 }}
                      animate={{ opacity: 1, x: 0 }}
                      exit={{ opacity: 0, x: -10 }}
                      transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
                      style={{ overflowY: 'auto', scrollbarWidth: 'none', flex: 1, position: 'relative', zIndex: 1 }}
                    >
                      {/* Desk Header */}
                      <div style={{ padding: '36px 40px 10px' }}>
                        <div style={{ fontSize: 10, letterSpacing: '0.4em', textTransform: 'uppercase', color: 'var(--red)', fontWeight: 800, fontFamily: 'var(--font-body)', marginBottom: 16, display: 'flex', alignItems: 'center', gap: 12 }}>
                          <div style={{ width: 6, height: 6, background: 'var(--red)', borderRadius: '50%', boxShadow: '0 0 10px var(--red)' }} />
                          Editor&apos;s Desk
                        </div>
                        <h2 className="font-serif" style={{ fontSize: 28, fontWeight: 500, color: 'rgba(255,255,255,0.95)', lineHeight: 1.25, margin: 0, letterSpacing: '-0.02em' }}>
                          Draft a <em style={{ color: 'var(--red)', fontStyle: 'italic' }}>directive</em> for the compositor.
                        </h2>
                      </div>

                      {/* Section I — Instruction Input Card */}
                      <div style={{ padding: '24px 40px 16px' }}>
                        <div
                          style={{
                            background: 'rgba(255,255,255,0.03)',
                            border: '1px solid',
                            borderColor: editPrompt.trim() ? 'rgba(192,57,43,0.4)' : 'rgba(255,255,255,0.08)',
                            borderRadius: 16,
                            padding: 2,
                            position: 'relative',
                            transition: 'all 0.3s cubic-bezier(0.16, 1, 0.3, 1)',
                            boxShadow: editPrompt.trim() ? '0 12px 30px rgba(192,57,43,0.15)' : '0 8px 24px rgba(0,0,0,0.2)',
                          }}
                        >
                          <textarea
                            value={editPrompt}
                            onChange={(e) => setEditPrompt(e.target.value)}
                            onKeyDown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); handleApplyEdit() } }}
                            placeholder="e.g. Turn the hero black. Make the CTA pulse. Add 3 Indian founder testimonials..."
                            rows={5}
                            style={{
                              width: '100%', resize: 'none', padding: '18px 20px',
                              background: 'transparent', border: 'none',
                              color: 'rgba(255,255,255,0.95)', fontFamily: 'var(--font-body)',
                              fontSize: 14, lineHeight: 1.6, outline: 'none',
                              letterSpacing: '0.01em', boxSizing: 'border-box'
                            }}
                          />
                          <div style={{ padding: '0 20px 16px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 6, opacity: editPrompt.trim() ? 1 : 0.4, transition: 'opacity 0.2s' }}>
                              <kbd style={{ background: 'rgba(255,255,255,0.1)', padding: '4px 8px', borderRadius: 4, fontSize: 10, fontFamily: 'var(--font-body)', color: '#fff', border: '1px solid rgba(255,255,255,0.05)' }}>⌘</kbd>
                              <kbd style={{ background: 'rgba(255,255,255,0.1)', padding: '4px 8px', borderRadius: 4, fontSize: 10, fontFamily: 'var(--font-body)', color: '#fff', border: '1px solid rgba(255,255,255,0.05)' }}>↵</kbd>
                              <span style={{ fontSize: 10, color: 'rgba(255,255,255,0.4)', marginLeft: 4, textTransform: 'uppercase', letterSpacing: '0.1em' }}>to apply</span>
                            </div>
                            <span style={{ fontSize: 10, color: editPrompt.length > 400 ? 'var(--red)' : 'rgba(255,255,255,0.3)', fontFamily: 'var(--font-mono)' }}>
                              {editPrompt.length}<span style={{ opacity: 0.5 }}>/600</span>
                            </span>
                          </div>
                        </div>
                        
                        {/* Apply Button */}
                        <motion.button
                          type="button"
                          onClick={handleApplyEdit}
                          disabled={!editPrompt.trim()}
                          initial={false}
                          animate={{ 
                            opacity: editPrompt.trim() ? 1 : 0.5,
                            y: editPrompt.trim() ? 0 : 4,
                            scale: editPrompt.trim() ? 1 : 0.98
                          }}
                          style={{
                            width: '100%', marginTop: 20, padding: '16px 24px',
                            background: editPrompt.trim() ? 'var(--red)' : 'rgba(255,255,255,0.04)',
                            color: editPrompt.trim() ? '#fff' : 'rgba(255,255,255,0.3)',
                            border: editPrompt.trim() ? '1px solid rgba(192,57,43,0.8)' : '1px solid rgba(255,255,255,0.06)',
                            borderRadius: 12, fontFamily: 'var(--font-body)', fontSize: 11,
                            fontWeight: 800, letterSpacing: '0.2em', textTransform: 'uppercase',
                            cursor: editPrompt.trim() ? 'pointer' : 'not-allowed',
                            display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10,
                            boxShadow: editPrompt.trim() ? '0 10px 24px rgba(192,57,43,0.3), inset 0 1px 0 rgba(255,255,255,0.2)' : 'none',
                            transition: 'all 0.2s',
                          }}
                        >
                          <Pencil style={{ width: 14, height: 14 }} />
                          Run the Press
                        </motion.button>
                      </div>

                      {/* Section II — Suggestion Chips */}
                      <div style={{ padding: '10px 40px 40px' }}>
                        <div style={{ fontSize: 10, letterSpacing: '0.2em', textTransform: 'uppercase', color: 'rgba(255,255,255,0.3)', fontWeight: 700, fontFamily: 'var(--font-body)', marginBottom: 16 }}>
                          Quick Marks
                        </div>
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
                          {EDIT_SUGGESTIONS.map((s) => (
                            <button
                              key={s}
                              type="button"
                              onClick={() => setEditPrompt(s)}
                              style={{
                                padding: '10px 16px', background: 'rgba(255,255,255,0.03)',
                                border: '1px solid rgba(255,255,255,0.08)', borderRadius: 20,
                                color: 'rgba(255,255,255,0.6)', fontFamily: 'var(--font-body)',
                                fontSize: 12, cursor: 'pointer', textAlign: 'left',
                                transition: 'all 0.2s cubic-bezier(0.16, 1, 0.3, 1)', display: 'flex', alignItems: 'center', gap: 8
                              }}
                              onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(192,57,43,0.1)'; e.currentTarget.style.borderColor = 'rgba(192,57,43,0.3)'; e.currentTarget.style.color = '#fff'; e.currentTarget.style.transform = 'translateY(-1px)' }}
                              onMouseLeave={(e) => { e.currentTarget.style.background = 'rgba(255,255,255,0.03)'; e.currentTarget.style.borderColor = 'rgba(255,255,255,0.08)'; e.currentTarget.style.color = 'rgba(255,255,255,0.6)'; e.currentTarget.style.transform = 'translateY(0)' }}
                            >
                              <span style={{ color: 'var(--red)', opacity: 0.8, fontSize: 14, fontWeight: 300 }}>+</span> {s}
                            </button>
                          ))}
                        </div>
                      </div>
                    </motion.div>
                  )}

                  {/* ── WORKING STATE ── */}
                  {hasRevised && (
                    <motion.div
                      key="log"
                      initial={{ opacity: 0, x: -10 }}
                      animate={{ opacity: 1, x: 0 }}
                      exit={{ opacity: 0 }}
                      transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
                      style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0, position: 'relative', zIndex: 1 }}
                    >
                      {/* Log header */}
                      <div style={{ padding: '36px 40px 20px', flexShrink: 0 }}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                          <div>
                            <div style={{ fontSize: 10, letterSpacing: '0.4em', textTransform: 'uppercase', color: 'var(--red)', fontWeight: 800, fontFamily: 'var(--font-body)', marginBottom: 8 }}>
                              Press Log
                            </div>
                            <h2 className="font-serif" style={{ fontSize: 24, fontWeight: 500, color: 'rgba(255,255,255,0.95)', lineHeight: 1.2, margin: 0, letterSpacing: '-0.01em' }}>
                              {revisions.filter(r => r.status === 'applied').length} revision{revisions.filter(r => r.status === 'applied').length !== 1 ? 's' : ''} applied
                            </h2>
                          </div>
                          <AnimatePresence>
                            {revisions[0]?.status === 'pending' && (
                              <motion.div
                                initial={{ opacity: 0, scale: 0.8 }}
                                animate={{ opacity: 1, scale: 1 }}
                                exit={{ opacity: 0, scale: 0.8 }}
                                style={{ display: 'flex', alignItems: 'center', gap: 8, background: 'rgba(192,57,43,0.15)', padding: '8px 14px', borderRadius: 20, border: '1px solid rgba(192,57,43,0.3)', boxShadow: '0 0 20px rgba(192,57,43,0.2)' }}
                              >
                                <Loader2 className="animate-spin" style={{ width: 12, height: 12, color: 'var(--red)' }} />
                                <span style={{ fontSize: 9, letterSpacing: '0.2em', textTransform: 'uppercase', color: 'var(--red)', fontWeight: 800 }}>
                                  Live
                                </span>
                              </motion.div>
                            )}
                          </AnimatePresence>
                        </div>
                      </div>

                      {/* Revision entries */}
                      <div style={{ flex: 1, overflowY: 'auto', scrollbarWidth: 'none', padding: '0 40px 20px', display: 'flex', flexDirection: 'column', gap: 16 }}>
                        <AnimatePresence initial={false}>
                          {revisions.map((rev, index) => (
                            <motion.div
                              key={`rev-${rev.version}`}
                              initial={{ opacity: 0, y: 20, scale: 0.95 }}
                              animate={{ opacity: 1, y: 0, scale: 1 }}
                              transition={{ duration: 0.4, delay: index * 0.05, ease: [0.16, 1, 0.3, 1] }}
                              style={{
                                background: rev.status === 'pending' ? 'rgba(255,255,255,0.05)' : 'rgba(255,255,255,0.02)',
                                border: '1px solid',
                                borderColor: rev.status === 'pending' ? 'rgba(192,57,43,0.4)' : 'rgba(255,255,255,0.06)',
                                borderRadius: 16,
                                padding: '20px',
                                position: 'relative',
                                overflow: 'hidden',
                                boxShadow: rev.status === 'pending' ? '0 12px 30px rgba(192,57,43,0.1)' : 'none',
                              }}
                            >
                              {rev.status === 'pending' && (
                                <motion.div 
                                  animate={{ x: ['-100%', '100%'] }} 
                                  transition={{ duration: 2, repeat: Infinity, ease: 'linear' }} 
                                  style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: 2, background: 'linear-gradient(90deg, transparent, var(--red), transparent)' }} 
                                />
                              )}
                              
                              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                                  <span style={{ background: rev.status === 'applied' ? 'rgba(255,255,255,0.1)' : 'rgba(192,57,43,0.2)', color: rev.status === 'applied' ? '#fff' : 'var(--red)', fontSize: 10, fontWeight: 800, padding: '4px 8px', borderRadius: 6, fontFamily: 'var(--font-mono)' }}>
                                    v{rev.version}
                                  </span>
                                  <span style={{ fontSize: 11, color: 'rgba(255,255,255,0.3)', fontFamily: 'var(--font-body)' }}>
                                    {rev.at.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                                  </span>
                                </div>
                                {rev.status === 'pending' && <span style={{ fontSize: 9, letterSpacing: '0.2em', textTransform: 'uppercase', color: 'var(--red)', fontWeight: 800 }}>Working</span>}
                                {rev.status === 'applied' && <Check style={{ width: 14, height: 14, color: 'rgba(74,222,128,0.8)' }} />}
                                {rev.status === 'error' && <X style={{ width: 14, height: 14, color: 'var(--red)' }} />}
                              </div>
                              <p style={{ margin: 0, fontSize: 14, fontFamily: 'var(--font-body)', color: rev.status === 'pending' ? '#fff' : 'rgba(255,255,255,0.7)', lineHeight: 1.6 }}>
                                {rev.prompt}
                              </p>
                              {rev.status === 'error' && rev.errorMsg && (
                                <div style={{ marginTop: 14, padding: '12px 16px', background: 'rgba(192,57,43,0.1)', borderRadius: 8, border: '1px solid rgba(192,57,43,0.2)' }}>
                                  <p style={{ margin: 0, fontSize: 12, color: 'var(--red)', fontFamily: 'var(--font-body)' }}>
                                    {rev.errorMsg}
                                  </p>
                                </div>
                              )}
                            </motion.div>
                          ))}
                        </AnimatePresence>
                      </div>

                      {/* Sticky input */}
                      <div style={{ padding: '20px 40px 30px', background: 'linear-gradient(0deg, #0a0a0a 80%, transparent 100%)', flexShrink: 0 }}>
                        <div
                          style={{
                            background: 'rgba(255,255,255,0.04)',
                            border: '1px solid',
                            borderColor: editPrompt.trim() ? 'rgba(192,57,43,0.4)' : 'rgba(255,255,255,0.1)',
                            borderRadius: 16,
                            padding: 2,
                            transition: 'all 0.3s ease',
                          }}
                        >
                          <textarea
                            value={editPrompt}
                            onChange={(e) => setEditPrompt(e.target.value)}
                            onKeyDown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); handleApplyEdit() } }}
                            placeholder="Next instruction..."
                            disabled={revisions[0]?.status === 'pending'}
                            rows={3}
                            style={{
                              width: '100%', resize: 'none', padding: '16px 20px',
                              background: 'transparent', border: 'none',
                              color: 'rgba(255,255,255,0.95)', fontFamily: 'var(--font-body)',
                              fontSize: 14, lineHeight: 1.6, outline: 'none',
                              opacity: revisions[0]?.status === 'pending' ? 0.5 : 1
                            }}
                          />
                          <div style={{ padding: '0 16px 12px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <button
                              type="button"
                              onClick={handleApplyEdit}
                              disabled={!editPrompt.trim() || revisions[0]?.status === 'pending'}
                              style={{
                                display: 'inline-flex', alignItems: 'center', gap: 8, padding: '10px 20px',
                                background: editPrompt.trim() && revisions[0]?.status !== 'pending' ? 'var(--red)' : 'rgba(255,255,255,0.1)',
                                color: editPrompt.trim() && revisions[0]?.status !== 'pending' ? '#fff' : 'rgba(255,255,255,0.4)',
                                border: 'none', borderRadius: 8, fontFamily: 'var(--font-body)', fontSize: 10,
                                fontWeight: 800, letterSpacing: '0.1em', textTransform: 'uppercase', cursor: 'pointer',
                                transition: 'all 0.2s',
                              }}
                            >
                              {revisions[0]?.status === 'pending' ? <><Loader2 className="animate-spin" style={{ width: 12, height: 12 }} /> Sending</> : <><Pencil style={{ width: 12, height: 12 }} /> Apply</>}
                            </button>
                            <span style={{ fontSize: 10, color: 'rgba(255,255,255,0.3)', fontFamily: 'var(--font-mono)' }}>{editPrompt.length}/600</span>
                          </div>
                        </div>
                      </div>
                    </motion.div>
                  )}

                </AnimatePresence>
              </div>

              {/* ── Right panel (The Proofing Mat) ──────────────────── */}
              <div
                style={{
                  flex: 1,
                  minWidth: 0,
                  display: 'flex',
                  flexDirection: 'column',
                  position: 'relative',
                  background: 'var(--paper)',
                  overflow: 'hidden',
                }}
              >
                {/* Cutting Mat Grain */}
                <div
                  aria-hidden="true"
                  style={{
                    position: 'absolute',
                    inset: 0,
                    pointerEvents: 'none',
                    backgroundImage: 'radial-gradient(var(--archive-grain-dot-a) 1px, transparent 1px)',
                    backgroundSize: '24px 24px',
                    opacity: 0.8,
                    zIndex: 0
                  }}
                />

                {/* Floating Header */}
                <div
                  style={{
                    position: 'absolute',
                    top: 24,
                    left: '50%',
                    transform: 'translateX(-50%)',
                    zIndex: 20,
                    display: 'flex',
                    alignItems: 'center',
                    gap: 16,
                    background: 'rgba(255,255,255,0.95)',
                    backdropFilter: 'blur(8px)',
                    padding: '6px 6px 6px 24px',
                    borderRadius: 40,
                    boxShadow: '0 12px 32px rgba(0,0,0,0.08), 0 2px 8px rgba(0,0,0,0.04)',
                    border: '1px solid rgba(0,0,0,0.05)',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                    {/* Pulsing live dot */}
                    <div style={{ position: 'relative', width: 8, height: 8 }}>
                      {refineMutation.isPending ? (
                        <>
                          <motion.div animate={{ scale: [1, 2.5], opacity: [0.6, 0] }} transition={{ duration: 1.5, repeat: Infinity }} style={{ position: 'absolute', inset: 0, background: 'var(--red)', borderRadius: '50%' }} />
                          <div style={{ position: 'absolute', inset: 0, background: 'var(--red)', borderRadius: '50%' }} />
                        </>
                      ) : (
                        <div style={{ position: 'absolute', inset: 0, background: 'var(--ink)', borderRadius: '50%', opacity: 0.5 }} />
                      )}
                    </div>
                    <span className="font-serif" style={{ fontSize: 16, fontWeight: 700, fontStyle: 'italic', color: 'var(--ink)' }}>
                      Reader&apos;s View
                    </span>
                  </div>

                  <div style={{ width: 1, height: 20, background: 'var(--border-color)' }} />

                  <button
                    type="button"
                    onClick={handleExitEdit}
                    style={{
                      display: 'inline-flex', alignItems: 'center', gap: 8,
                      padding: '10px 24px', borderRadius: 30,
                      background: editApplied ? 'var(--red)' : '#1a1714',
                      color: '#fff', border: 'none', fontFamily: 'var(--font-body)',
                      fontSize: 10, fontWeight: 800, letterSpacing: '0.15em',
                      textTransform: 'uppercase', cursor: 'pointer',
                      transition: 'all 0.3s ease',
                    }}
                  >
                    {editApplied ? 'Save & Close' : 'Close'}
                    <Check style={{ width: 12, height: 12 }} />
                  </button>
                </div>

                {/* Magical Compositor Glow (Stitch inspired) */}
                <AnimatePresence>
                  {refineMutation.isPending && (
                    <motion.div
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      exit={{ opacity: 0 }}
                      style={{
                        position: 'absolute', inset: 0, zIndex: 10,
                        background: 'radial-gradient(circle at center, rgba(255,255,255,0.7) 0%, rgba(242,236,224,0.4) 100%)',
                        backdropFilter: 'blur(4px)',
                        display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
                      }}
                    >
                      <motion.div
                        animate={{ scale: [0.9, 1.1, 0.9], opacity: [0.4, 0.8, 0.4], rotate: [0, 90, 180] }}
                        transition={{ duration: 3, repeat: Infinity, ease: "easeInOut" }}
                        style={{ width: 180, height: 180, background: 'conic-gradient(from 0deg, transparent, rgba(192,57,43,0.2), transparent)', borderRadius: '50%', filter: 'blur(10px)', position: 'absolute' }}
                      />
                      <Loader2 className="animate-spin" style={{ width: 36, height: 36, color: 'var(--red)', position: 'relative', zIndex: 2 }} />
                      <h3 className="font-serif" style={{ fontSize: 26, fontStyle: 'italic', fontWeight: 500, color: 'var(--ink)', marginTop: 28, position: 'relative', zIndex: 2 }}>
                        Stitching layout...
                      </h3>
                      <p style={{ fontSize: 11, letterSpacing: '0.24em', textTransform: 'uppercase', color: 'var(--ink-secondary)', fontWeight: 800, fontFamily: 'var(--font-body)', marginTop: 10, position: 'relative', zIndex: 2 }}>
                        Compositor active
                      </p>
                    </motion.div>
                  )}
                </AnimatePresence>

                {/* The Floating iFrame */}
                <div style={{ flex: 1, padding: '100px 48px 48px', display: 'flex', alignItems: 'center', justifyContent: 'center', position: 'relative', zIndex: 5 }}>
                  <motion.div
                    animate={{ scale: refineMutation.isPending ? 0.97 : 1, y: refineMutation.isPending ? 10 : 0 }}
                    transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
                    style={{
                      width: '100%', height: '100%', maxWidth: 1200,
                      background: '#fff', borderRadius: 16, overflow: 'hidden',
                      boxShadow: refineMutation.isPending ? '0 12px 30px rgba(0,0,0,0.05)' : '0 30px 80px rgba(0,0,0,0.1), 0 4px 16px rgba(0,0,0,0.06)',
                      border: '1px solid rgba(0,0,0,0.08)',
                      display: 'flex', flexDirection: 'column',
                    }}
                  >
                    {previewIframe}
                  </motion.div>
                </div>

              </div>
            </div>
          </motion.div>
        )}

      </AnimatePresence>
    </div>
  )
}
