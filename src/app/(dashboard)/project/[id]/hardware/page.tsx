'use client'

import type { ReactNode } from 'react'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Loader2, RotateCcw, Cpu, Ruler, AlertTriangle } from 'lucide-react'

import { HardwareFailureMap, type HardwareSpec, type TestResult } from '@/components/HardwareFailureMap'
import { getApiV1Base } from '@/lib/api-v1-base'

function authHeaders(): HeadersInit {
  const token = typeof window !== 'undefined' ? localStorage.getItem('access_token') : null
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  }
}

const BG = '#0a0a0f'
const GRID_A = '#1e3a5f'
const GRID_B = '#1a3a6e'
const ACCENT = '#38bdf8'

const HARDWARE_PRODUCT_TYPES = [
  { value: 'consumer_hardware', label: 'Consumer hardware' },
  { value: 'health_hardware', label: 'Health hardware' },
  { value: 'iot_hardware', label: 'IoT hardware' },
  { value: 'wearable', label: 'Wearable' },
  { value: 'b2b_hardware', label: 'B2B hardware' },
] as const

type HwListItem = {
  id: number
  name: string
  category: string | null
  product_type: string
  target_price_inr: number | null
  created_at: string
}

type RenderHints = {
  primary_shape: string
  dominant_material: string
  color_hex: string
  highlight_zones: string[]
}

type HwDetail = {
  id: number
  project_id: number
  name: string
  description: string | null
  category: string | null
  product_type: string
  target_price_inr: number | null
  material_spec: string | null
  dimensions_json: Record<string, unknown> | null
  weight_grams: number | null
  created_at: string
  spec: Record<string, unknown>
  render_hints: RenderHints
}

function stressColor(severity: number): string {
  const s = Math.max(0, Math.min(1, severity))
  const hue = 125 - s * 125
  return `hsl(${hue}, 72%, ${48 + s * 12}%)`
}

function ProductDiagramSvg(props: {
  shape: string
  fill: string
  highlightIds: Set<string>
  dominantMaterial: string
  rotX: number
  rotY: number
  dragging: boolean
  components: Array<{ id: string; name: string; zone: string }>
}) {
  const { shape, fill, highlightIds, dominantMaterial, rotX, rotY, dragging, components } = props
  const safeFill = /^#[0-9A-Fa-f]{6}$/i.test(fill) ? fill : '#2d4a6e'
  const sh = (shape || 'box').toLowerCase().replace(/_/g, '-')

  let body: ReactNode
  if (sh === 'cylinder') {
    body = (
      <g>
        <ellipse cx="100" cy="58" rx="44" ry="14" fill="url(#hw-metal)" stroke={GRID_A} strokeWidth={1} />
        <rect x="56" y="58" width="88" height="92" fill="url(#hw-metal)" stroke={GRID_A} strokeWidth={1} />
        <ellipse cx="100" cy="150" rx="44" ry="14" fill="#0b1220" stroke={GRID_A} strokeWidth={1} />
      </g>
    )
  } else if (sh === 'flat') {
    body = (
      <rect x="28" y="88" width="144" height="36" rx="4" fill="url(#hw-metal)" stroke={GRID_A} strokeWidth={1} />
    )
  } else if (sh === 'l-shape') {
    body = (
      <path
        d="M 52 52 L 52 148 L 100 148 L 100 100 L 148 100 L 148 52 Z"
        fill="url(#hw-metal)"
        stroke={GRID_A}
        strokeWidth={1.2}
      />
    )
  } else {
    body = (
      <g>
        <rect x="48" y="48" width="104" height="104" rx="10" fill="url(#hw-metal)" stroke={GRID_A} strokeWidth={1.2} />
        <line x1="48" y1="88" x2="152" y2="88" stroke={GRID_B} strokeWidth={0.5} opacity={0.5} />
        <line x1="88" y1="48" x2="88" y2="152" stroke={GRID_B} strokeWidth={0.5} opacity={0.5} />
      </g>
    )
  }

  const transition = dragging ? 'none' : 'transform 0.1s ease-out'

  return (
    <svg
      viewBox="0 0 200 200"
      className="mx-auto h-[min(52vw,420px)] w-full max-w-[480px] select-none"
      style={{
        transform: `rotateX(${rotX}deg) rotateY(${rotY}deg)`,
        transformStyle: 'preserve-3d' as const,
        transition,
        filter: 'drop-shadow(0 28px 48px rgba(0,0,0,0.65)) drop-shadow(0 12px 24px rgba(30,58,95,0.35))',
      }}
    >
      <defs>
        <linearGradient id="hw-metal" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor={safeFill} stopOpacity={0.95} />
          <stop offset="100%" stopColor="#0f172a" stopOpacity={0.9} />
        </linearGradient>
      </defs>
      <rect x="4" y="4" width="192" height="192" fill="none" stroke={GRID_A} strokeWidth={0.4} strokeDasharray="3 4" opacity={0.45} />
      <text x="100" y="22" textAnchor="middle" fill={GRID_B} fontSize="8" letterSpacing="0.14em">
        {dominantMaterial.toUpperCase()}
      </text>
      {body}
      {components.slice(0, 6).map((c, i) => {
        const px = 58 + (i % 3) * 42
        const py = 118 + Math.floor(i / 3) * 22
        const hi = highlightIds.has(c.id)
        return (
          <g key={c.id} style={hi ? { filter: `drop-shadow(0 0 8px ${ACCENT})` } : undefined}>
            <circle cx={px} cy={py} r={7} fill={hi ? ACCENT : '#132337'} stroke={GRID_A} strokeWidth={0.8} opacity={0.95} />
            <text x={px + 12} y={py + 4} fill="#94a3b8" fontSize="7">
              {c.id}
            </text>
          </g>
        )
      })}
    </svg>
  )
}

function PerspectiveGrid() {
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden>
      <div
        className="absolute"
        style={{
          inset: '-45% -25% -35% -25%',
          transform: 'perspective(500px) rotateX(60deg)',
          transformOrigin: '50% 40%',
          background: `
            repeating-linear-gradient(90deg, transparent 0, transparent 39px, ${GRID_A} 39px, ${GRID_A} 40px),
            repeating-linear-gradient(0deg, transparent 0, transparent 39px, ${GRID_B} 39px, ${GRID_B} 40px)
          `,
          opacity: 0.55,
          maskImage: 'radial-gradient(ellipse 68% 58% at 50% 42%, black 18%, transparent 72%)',
          WebkitMaskImage: 'radial-gradient(ellipse 68% 58% at 50% 42%, black 18%, transparent 72%)',
        }}
      />
      <div
        className="absolute"
        style={{
          inset: '-40% -20% -30% -20%',
          transform: 'perspective(500px) rotateX(60deg) translateZ(-24px)',
          transformOrigin: '50% 40%',
          background: `
            repeating-linear-gradient(90deg, transparent 0, transparent 79px, ${GRID_B} 79px, ${GRID_B} 80px),
            repeating-linear-gradient(0deg, transparent 0, transparent 79px, ${GRID_A} 79px, ${GRID_A} 80px)
          `,
          opacity: 0.22,
          maskImage: 'radial-gradient(ellipse 72% 62% at 50% 44%, black 12%, transparent 78%)',
          WebkitMaskImage: 'radial-gradient(ellipse 72% 62% at 50% 44%, black 12%, transparent 78%)',
        }}
      />
    </div>
  )
}

export default function HardwareViewerPage() {
  const params = useParams()
  const projectId = Number(params.id)

  const [list, setList] = useState<HwListItem[]>([])
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [detail, setDetail] = useState<HwDetail | null>(null)
  const [loadingList, setLoadingList] = useState(true)
  const [loadingDetail, setLoadingDetail] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [testsMsg, setTestsMsg] = useState<string | null>(null)
  const [testResults, setTestResults] = useState<TestResult[]>([])

  const [showGenerate, setShowGenerate] = useState(false)
  const [genBusy, setGenBusy] = useState(false)
  const [genName, setGenName] = useState('')
  const [genDesc, setGenDesc] = useState('')
  const [genCategory, setGenCategory] = useState('')
  const [genProductType, setGenProductType] = useState('consumer_hardware')
  const [genPrice, setGenPrice] = useState('4999')
  const [genMaterial, setGenMaterial] = useState('')
  const [genDimsRough, setGenDimsRough] = useState('')

  const [rotX, setRotX] = useState(-8)
  const [rotY, setRotY] = useState(22)
  const [dragging, setDragging] = useState(false)
  const dragRef = useRef({ active: false, lx: 0, ly: 0 })

  const loadList = useCallback(async () => {
    if (!Number.isFinite(projectId)) return
    setLoadingList(true)
    setError(null)
    try {
      const res = await fetch(`${getApiV1Base()}/projects/${projectId}/hardware`, {
        headers: authHeaders(),
      })
      if (!res.ok) throw new Error(await res.text())
      const data = (await res.json()) as HwListItem[]
      setList(data)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load hardware')
    } finally {
      setLoadingList(false)
    }
  }, [projectId])

  const loadDetail = useCallback(async () => {
    if (!Number.isFinite(projectId) || selectedId === null) {
      setDetail(null)
      return
    }
    setLoadingDetail(true)
    setError(null)
    try {
      const res = await fetch(`${getApiV1Base()}/projects/${projectId}/hardware/${selectedId}`, {
        headers: authHeaders(),
      })
      if (!res.ok) throw new Error(await res.text())
      setDetail((await res.json()) as HwDetail)
    } catch (e) {
      setDetail(null)
      setError(e instanceof Error ? e.message : 'Failed to load product')
    } finally {
      setLoadingDetail(false)
    }
  }, [projectId, selectedId])

  const loadTestResults = useCallback(async () => {
    if (!Number.isFinite(projectId) || selectedId === null) {
      setTestResults([])
      return
    }
    try {
      const res = await fetch(
        `${getApiV1Base()}/projects/${projectId}/hardware/${selectedId}/test-results`,
        { headers: authHeaders() },
      )
      if (!res.ok) {
        setTestResults([])
        return
      }
      const data = (await res.json()) as { results?: TestResult[] }
      setTestResults(Array.isArray(data.results) ? data.results : [])
    } catch {
      setTestResults([])
    }
  }, [projectId, selectedId])

  useEffect(() => {
    void loadList()
  }, [loadList])

  useEffect(() => {
    if (list.length === 0) return
    setSelectedId((prev) => (prev === null ? list[0].id : prev))
  }, [list])

  useEffect(() => {
    void loadDetail()
  }, [loadDetail])

  useEffect(() => {
    void loadTestResults()
  }, [loadTestResults])

  const spec = detail?.spec as Record<string, unknown> | undefined
  const dims = spec?.dimensions as Record<string, number> | undefined
  const components = useMemo(() => {
    const raw = spec?.components
    if (!Array.isArray(raw)) return [] as Array<{ id: string; name: string; material: string; zone: string; stress_rating: number }>
    return raw as Array<{ id: string; name: string; material: string; zone: string; stress_rating: number }>
  }, [spec])
  const stressMap = useMemo(() => {
    const raw = spec?.stress_point_map
    if (!Array.isArray(raw)) return [] as Array<{ component_id: string; stress_type: string; severity: number }>
    return raw as Array<{ component_id: string; stress_type: string; severity: number }>
  }, [spec])
  const rh = detail?.render_hints

  const highlightSet = useMemo(() => new Set(rh?.highlight_zones ?? []), [rh])

  const hardwareSpec: HardwareSpec | null = useMemo(() => {
    if (!detail) return null
    const s = detail.spec as Record<string, unknown>
    const raw = s.components
    if (!Array.isArray(raw)) return null
    const components = raw.map((c: Record<string, unknown>) => {
      const cluster = c.cluster_id
      return {
        id: String(c.id ?? ''),
        name: String(c.name ?? ''),
        material: String(c.material ?? ''),
        zone: String(c.zone ?? 'core'),
        volume_cm3: Number(c.volume_cm3 ?? 0),
        stress_rating: Number(c.stress_rating ?? 0),
        ...(cluster != null && cluster !== ''
          ? { cluster_id: String(cluster) }
          : {}),
      }
    })
    const d = s.dimensions as Record<string, unknown> | undefined
    const dimensions =
      d && typeof d === 'object'
        ? {
            length_mm: Number(d.length_mm ?? 0),
            width_mm: Number(d.width_mm ?? 0),
            height_mm: Number(d.height_mm ?? 0),
            weight_grams: Number(
              d.weight_grams ?? detail.weight_grams ?? 0,
            ),
          }
        : detail.weight_grams != null
          ? {
              length_mm: 0,
              width_mm: 0,
              height_mm: 0,
              weight_grams: detail.weight_grams,
            }
          : undefined
    return {
      product_name: (s.product_name as string) || detail.name,
      dimensions,
      components,
      render_hints: detail.render_hints,
    }
  }, [detail])

  const onPointerDown = (e: React.MouseEvent) => {
    dragRef.current = { active: true, lx: e.clientX, ly: e.clientY }
    setDragging(true)
  }
  const onPointerMove = (e: React.MouseEvent) => {
    if (!dragRef.current.active) return
    const dx = e.clientX - dragRef.current.lx
    const dy = e.clientY - dragRef.current.ly
    dragRef.current.lx = e.clientX
    dragRef.current.ly = e.clientY
    setRotY((y) => y + dx * 0.35)
    setRotX((x) => Math.max(-30, Math.min(30, x - dy * 0.35)))
  }
  const endDrag = () => {
    dragRef.current.active = false
    setDragging(false)
  }

  const resetView = () => {
    setRotX(-8)
    setRotY(22)
  }

  const runTests = async () => {
    if (!Number.isFinite(projectId) || selectedId === null) return
    setTestsMsg(null)
    try {
      const res = await fetch(`${getApiV1Base()}/projects/${projectId}/hardware/${selectedId}/run-tests`, {
        method: 'POST',
        headers: authHeaders(),
      })
      const text = await res.text()
      let body: { detail?: string; message?: string } = {}
      try {
        body = JSON.parse(text) as { detail?: string; message?: string }
      } catch {
        /* non-JSON error body */
      }
      if (!res.ok) throw new Error(body.detail || text.slice(0, 280))
      setTestsMsg(body.message || 'Tests queued.')
      window.setTimeout(() => void loadTestResults(), 3000)
    } catch (e) {
      setTestsMsg(e instanceof Error ? e.message : 'Could not queue tests')
    }
  }

  const generateSpec = async () => {
    if (!Number.isFinite(projectId)) return
    setGenBusy(true)
    setError(null)
    let dimsRough: string | Record<string, unknown> | null = genDimsRough.trim() || null
    if (dimsRough && typeof dimsRough === 'string' && dimsRough.startsWith('{')) {
      try {
        dimsRough = JSON.parse(dimsRough) as Record<string, unknown>
      } catch {
        /* keep string */
      }
    }
    try {
      const res = await fetch(`${getApiV1Base()}/projects/${projectId}/hardware/generate-spec`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({
          name: genName.trim(),
          description: genDesc.trim(),
          category: genCategory.trim(),
          product_type: genProductType,
          target_price_inr: Number(genPrice),
          material_preference: genMaterial.trim() || null,
          dimensions_rough: dimsRough,
        }),
      })
      if (!res.ok) throw new Error(await res.text())
      const created = (await res.json()) as { id: number }
      setShowGenerate(false)
      setSelectedId(created.id)
      await loadList()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Generate failed')
    } finally {
      setGenBusy(false)
    }
  }

  if (!Number.isFinite(projectId)) {
    return (
      <div className="p-10 font-mono text-sm" style={{ background: BG, color: '#94a3b8' }}>
        Invalid project id.
      </div>
    )
  }

  return (
    <div
      className="relative min-h-[calc(100dvh-72px)] overflow-x-hidden font-mono text-[13px] leading-relaxed"
      style={{ background: BG, color: '#b8c5db' }}
      onMouseMove={onPointerMove}
      onMouseUp={endDrag}
      onMouseLeave={endDrag}
    >
      <PerspectiveGrid />

      <div className="relative z-10 mx-auto max-w-7xl px-4 py-6 pb-24 sm:px-6">
        <div className="mb-6 flex flex-wrap items-center justify-between gap-4 border-b border-[#1e3a5f]/60 pb-4">
          <div>
            <div className="mb-1 text-[10px] uppercase tracking-[0.2em]" style={{ color: ACCENT }}>
              Prototype plate · Hardware
            </div>
            <h1 className="text-lg font-semibold tracking-tight text-slate-100 sm:text-xl">Semantic 3D viewer</h1>
            <p className="mt-1 max-w-xl text-[12px] text-slate-500">
              Blueprint view of the locked spec JSON — grid, stress map, and render hints from Step 70. Drag the assembly
              to orbit; double-click to reset.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Link
              href={`/project/${projectId}`}
              className="rounded border border-[#1e3a5f] bg-[#0f1629] px-3 py-1.5 text-[11px] uppercase tracking-wider text-slate-400 hover:border-[#38bdf8]/50 hover:text-slate-200"
            >
              ← Dossier
            </Link>
            <button
              type="button"
              onClick={() => setShowGenerate((s) => !s)}
              className="rounded border border-[#38bdf8]/40 bg-[#0c4a6e]/40 px-3 py-1.5 text-[11px] font-medium uppercase tracking-wider text-sky-200 hover:bg-[#0c4a6e]/70"
            >
              Generate spec
            </button>
            <button
              type="button"
              disabled={selectedId === null}
              onClick={() => void runTests()}
              className="rounded border border-[#1e3a5f] bg-[#111827] px-3 py-1.5 text-[11px] uppercase tracking-wider text-slate-300 hover:border-amber-500/50 disabled:opacity-40"
            >
              Run tests
            </button>
          </div>
        </div>

        {error ? (
          <div className="mb-4 rounded border border-red-900/60 bg-red-950/30 px-3 py-2 text-[12px] text-red-200">{error}</div>
        ) : null}
        {testsMsg ? (
          <div className="mb-4 rounded border border-amber-900/50 bg-amber-950/20 px-3 py-2 text-[12px] text-amber-100">{testsMsg}</div>
        ) : null}

        {showGenerate ? (
          <div
            className="mb-8 rounded-lg border border-[#1e3a5f] bg-[#0c101c]/95 p-4 shadow-xl backdrop-blur-sm sm:p-6"
            style={{ boxShadow: '0 0 0 1px rgba(56,189,248,0.06)' }}
          >
            <div className="mb-3 text-[10px] uppercase tracking-[0.18em] text-sky-400/90">Generate semantic spec (Step 71)</div>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="block sm:col-span-2">
                <span className="mb-1 block text-[10px] uppercase tracking-wider text-slate-500">Name</span>
                <input
                  value={genName}
                  onChange={(e) => setGenName(e.target.value)}
                  className="w-full rounded border border-[#1e3a5f] bg-[#0a0f18] px-2 py-1.5 text-slate-200 outline-none focus:border-sky-500/50"
                />
              </label>
              <label className="block sm:col-span-2">
                <span className="mb-1 block text-[10px] uppercase tracking-wider text-slate-500">Description</span>
                <textarea
                  value={genDesc}
                  onChange={(e) => setGenDesc(e.target.value)}
                  rows={3}
                  className="w-full rounded border border-[#1e3a5f] bg-[#0a0f18] px-2 py-1.5 text-slate-200 outline-none focus:border-sky-500/50"
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-[10px] uppercase tracking-wider text-slate-500">Category</span>
                <input
                  value={genCategory}
                  onChange={(e) => setGenCategory(e.target.value)}
                  className="w-full rounded border border-[#1e3a5f] bg-[#0a0f18] px-2 py-1.5 text-slate-200 outline-none focus:border-sky-500/50"
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-[10px] uppercase tracking-wider text-slate-500">Product type</span>
                <select
                  value={genProductType}
                  onChange={(e) => setGenProductType(e.target.value)}
                  className="w-full rounded border border-[#1e3a5f] bg-[#0a0f18] px-2 py-1.5 text-slate-200 outline-none focus:border-sky-500/50"
                >
                  {HARDWARE_PRODUCT_TYPES.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="mb-1 block text-[10px] uppercase tracking-wider text-slate-500">Target price (INR)</span>
                <input
                  value={genPrice}
                  onChange={(e) => setGenPrice(e.target.value)}
                  className="w-full rounded border border-[#1e3a5f] bg-[#0a0f18] px-2 py-1.5 text-slate-200 outline-none focus:border-sky-500/50"
                />
              </label>
              <label className="block sm:col-span-2">
                <span className="mb-1 block text-[10px] uppercase tracking-wider text-slate-500">Material preference (optional)</span>
                <input
                  value={genMaterial}
                  onChange={(e) => setGenMaterial(e.target.value)}
                  className="w-full rounded border border-[#1e3a5f] bg-[#0a0f18] px-2 py-1.5 text-slate-200 outline-none focus:border-sky-500/50"
                />
              </label>
              <label className="block sm:col-span-2">
                <span className="mb-1 block text-[10px] uppercase tracking-wider text-slate-500">Dimensions rough (text or JSON)</span>
                <textarea
                  value={genDimsRough}
                  onChange={(e) => setGenDimsRough(e.target.value)}
                  rows={2}
                  className="w-full rounded border border-[#1e3a5f] bg-[#0a0f18] px-2 py-1.5 text-slate-200 outline-none focus:border-sky-500/50"
                />
              </label>
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              <button
                type="button"
                disabled={genBusy}
                onClick={() => void generateSpec()}
                className="inline-flex items-center gap-2 rounded bg-sky-600 px-4 py-2 text-[12px] font-medium text-white hover:bg-sky-500 disabled:opacity-50"
              >
                {genBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Cpu className="h-4 w-4" />}
                Submit to Claude
              </button>
              <button
                type="button"
                onClick={() => setShowGenerate(false)}
                className="rounded border border-[#1e3a5f] px-3 py-2 text-[12px] text-slate-400 hover:text-slate-200"
              >
                Cancel
              </button>
            </div>
          </div>
        ) : null}

        <div className="grid gap-8 lg:grid-cols-[minmax(0,1.1fr)_minmax(260px,0.45fr)]">
          <div>
            <div
              className="relative flex min-h-[420px] flex-col items-center justify-center rounded-xl border border-[#1e3a5f]/70 bg-[#060910]/80 px-4 py-10"
              style={{ perspective: '800px' }}
              onDoubleClick={resetView}
            >
              <div className="pointer-events-none absolute left-3 top-3 flex items-center gap-2 text-[10px] uppercase tracking-widest text-slate-500">
                <RotateCcw className="h-3 w-3" />
                Double-click reset
              </div>
              {loadingDetail ? (
                <div className="flex items-center gap-2 text-slate-500">
                  <Loader2 className="h-5 w-5 animate-spin" />
                  Loading spec…
                </div>
              ) : detail && rh ? (
                <div
                  className="cursor-grab active:cursor-grabbing"
                  style={{ transformStyle: 'preserve-3d' }}
                  onMouseDown={onPointerDown}
                >
                  <ProductDiagramSvg
                    shape={rh.primary_shape}
                    fill={rh.color_hex}
                    highlightIds={highlightSet}
                    dominantMaterial={rh.dominant_material}
                    rotX={rotX}
                    rotY={rotY}
                    dragging={dragging}
                    components={components}
                  />
                </div>
              ) : (
                <div className="max-w-sm text-center text-[13px] text-slate-500">
                  Select a hardware product or generate a new spec. The diagram uses{' '}
                  <code className="text-sky-300/90">render_hints</code> from the API.
                </div>
              )}
            </div>

            {detail && dims ? (
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                <div className="flex items-start gap-2 rounded border border-[#1e3a5f]/60 bg-[#0a0f18]/80 p-3">
                  <Ruler className="mt-0.5 h-4 w-4 shrink-0 text-sky-400/80" />
                  <div>
                    <div className="text-[10px] uppercase tracking-wider text-slate-500">Envelope</div>
                    <div className="text-[12px] text-slate-200">
                      {dims.length_mm} × {dims.width_mm} × {dims.height_mm} mm
                    </div>
                    <div className="text-[11px] text-slate-500">{dims.weight_grams} g (spec)</div>
                  </div>
                </div>
                <div className="rounded border border-[#1e3a5f]/60 bg-[#0a0f18]/80 p-3">
                  <div className="text-[10px] uppercase tracking-wider text-slate-500">Render hints</div>
                  <div className="mt-1 space-y-0.5 text-[11px] text-slate-400">
                    <div>
                      <span className="text-slate-600">shape</span> {rh?.primary_shape}
                    </div>
                    <div>
                      <span className="text-slate-600">material</span> {rh?.dominant_material}
                    </div>
                    <div>
                      <span className="text-slate-600">highlight</span> {(rh?.highlight_zones ?? []).join(', ') || '—'}
                    </div>
                  </div>
                </div>
              </div>
            ) : null}

            {hardwareSpec && testResults.length > 0 ? (
              <HardwareFailureMap
                spec={hardwareSpec}
                testResults={testResults}
                className="mt-6"
              />
            ) : null}
          </div>

          <aside className="space-y-4">
            <div className="rounded-lg border border-[#1e3a5f]/70 bg-[#060910]/85 p-3">
              <div className="mb-2 text-[10px] uppercase tracking-[0.2em] text-sky-400/80">Products</div>
              {loadingList ? (
                <div className="flex items-center gap-2 text-slate-500">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Loading…
                </div>
              ) : list.length === 0 ? (
                <p className="text-[12px] text-slate-500">No hardware rows yet. Generate a spec to populate this list.</p>
              ) : (
                <ul className="max-h-[220px] space-y-1 overflow-y-auto pr-1">
                  {list.map((p) => (
                    <li key={p.id}>
                      <button
                        type="button"
                        onClick={() => setSelectedId(p.id)}
                        className={`w-full rounded border px-2 py-2 text-left text-[12px] transition ${
                          selectedId === p.id
                            ? 'border-sky-500/50 bg-sky-950/40 text-sky-100'
                            : 'border-transparent bg-transparent text-slate-400 hover:border-[#1e3a5f] hover:bg-[#0a0f18]'
                        }`}
                      >
                        <div className="font-medium text-slate-200">{p.name}</div>
                        <div className="text-[10px] text-slate-500">
                          {p.product_type} · ₹{p.target_price_inr ?? '—'}
                        </div>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {detail ? (
              <>
                <div className="rounded-lg border border-[#1e3a5f]/70 bg-[#060910]/85 p-3">
                  <div className="text-[10px] uppercase tracking-[0.2em] text-sky-400/80">Title block</div>
                  <div className="mt-2 text-[15px] font-semibold tracking-tight text-slate-100">
                    {(spec?.product_name as string) || detail.name}
                  </div>
                  <div className="mt-1 text-[11px] text-slate-500">
                    {(spec?.category as string) || detail.category || '—'} · {detail.product_type}
                  </div>
                  <div className="mt-2 text-[12px] text-sky-200/90">
                    Target ₹{detail.target_price_inr ?? '—'} <span className="text-slate-600">·</span> sheet #{detail.id}
                  </div>
                </div>

                <div className="rounded-lg border border-[#1e3a5f]/70 bg-[#060910]/85 p-3">
                  <div className="mb-2 text-[10px] uppercase tracking-[0.2em] text-sky-400/80">Components</div>
                  <ul className="max-h-[240px] space-y-2 overflow-y-auto pr-1 text-[11px]">
                    {components.map((c) => (
                      <li
                        key={c.id}
                        className={`rounded border px-2 py-1.5 ${
                          highlightSet.has(c.id) ? 'border-sky-500/40 bg-sky-950/25' : 'border-[#1e3a5f]/40 bg-[#0a0f18]/60'
                        }`}
                      >
                        <div className="font-medium text-slate-200">{c.name}</div>
                        <div className="text-slate-500">
                          <span className="text-sky-300/70">{c.material}</span> · {c.zone} · stress {c.stress_rating?.toFixed?.(2) ?? c.stress_rating}
                        </div>
                      </li>
                    ))}
                  </ul>
                </div>

                <div className="rounded-lg border border-[#1e3a5f]/70 bg-[#060910]/85 p-3">
                  <div className="mb-2 flex items-center gap-2 text-[10px] uppercase tracking-[0.2em] text-sky-400/80">
                    <AlertTriangle className="h-3 w-3" />
                    Stress map
                  </div>
                  <ul className="max-h-[200px] space-y-1.5 overflow-y-auto text-[11px]">
                    {stressMap.map((s, i) => (
                      <li
                        key={`${s.component_id}-${i}`}
                        className="flex items-center justify-between gap-2 rounded border border-[#1e3a5f]/35 px-2 py-1"
                        style={{ borderLeftColor: stressColor(s.severity), borderLeftWidth: 3 }}
                      >
                        <span className="truncate text-slate-300">{s.component_id}</span>
                        <span className="shrink-0 text-slate-500">{s.stress_type}</span>
                        <span className="shrink-0 font-mono text-[10px]" style={{ color: stressColor(s.severity) }}>
                          {(s.severity * 100).toFixed(0)}%
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              </>
            ) : null}
          </aside>
        </div>
      </div>
    </div>
  )
}
