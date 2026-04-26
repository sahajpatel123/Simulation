'use client'

import type { MouseEvent } from 'react'
import Link from 'next/link'
import { useParams, useRouter } from 'next/navigation'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AnimatePresence, motion } from 'framer-motion'
import {
  ArrowLeft,
  ArrowRight,
  Cpu,
  Download,
  FileText,
  FlaskConical,
  Hexagon,
  Loader2,
  Play,
  RotateCcw,
  Scale,
  Sparkles,
  Target,
  Users,
} from 'lucide-react'

import {
  HardwareFailureMap,
  type FailurePoint,
  type HardwareSpec,
  type TestResult,
} from '@/components/HardwareFailureMap'
import { KeyPersonReport } from '@/components/KeyPersonReport'
import type { DomainFindingRow } from '@/components/simulation-results/types'
import { getApiV1Base } from '@/lib/api-v1-base'
import { useIsMobile } from '@/hooks/useIsMobile'
import { useProject } from '@/hooks/useProjects'

function authHeaders(): HeadersInit {
  const token = typeof window !== 'undefined' ? localStorage.getItem('access_token') : null
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  }
}

type Tab = 'spec' | 'tests' | 'cost' | 'simulation' | 'competitive' | 'report'

type HwListItem = {
  id: number
  name: string
  category: string | null
  product_type: string
  target_price_inr: number | null
  created_at: string
}

type HwDetail = {
  id: number
  project_id: number
  name: string
  description: string | null
  category: string | null
  product_type: string
  target_price_inr: number | null
  weight_grams: number | null
  spec: Record<string, unknown>
  render_hints: {
    primary_shape: string
    dominant_material: string
    color_hex: string
    highlight_zones: string[]
  }
}

type CompetitiveReport = {
  price_position?: string
  overall_differentiation?: number
  whitespace_clusters?: string[]
  recommended_positioning?: string
  top_threats?: string[]
  top_opportunities?: string[]
}

function verdictFromMargin(marginPct: number): 'VIABLE' | 'MARGINAL' | 'NOT_VIABLE' {
  if (marginPct >= 35) return 'VIABLE'
  if (marginPct >= 20) return 'MARGINAL'
  return 'NOT_VIABLE'
}

function normalizeCostView(
  raw: Record<string, unknown> | undefined,
  targetPriceInr: number,
): {
  hasData: boolean
  message?: string
  verdict: string
  verdict_reason: string
  landed_cost_inr: number
  target_price_inr: number
  margin_pct: number
  margin_inr: number
  break_even_moq: number | null
  bom: Array<Record<string, unknown>>
  bom_total_inr: number
} {
  if (!raw || typeof raw !== 'object') {
    return {
      hasData: false,
      verdict: '—',
      verdict_reason: '',
      landed_cost_inr: 0,
      target_price_inr: targetPriceInr,
      margin_pct: 0,
      margin_inr: 0,
      break_even_moq: null,
      bom: [],
      bom_total_inr: 0,
    }
  }
  if ('message' in raw && raw.message && !raw.bom) {
    return {
      hasData: false,
      message: String(raw.message),
      verdict: '—',
      verdict_reason: '',
      landed_cost_inr: 0,
      target_price_inr: targetPriceInr,
      margin_pct: 0,
      margin_inr: 0,
      break_even_moq: null,
      bom: [],
      bom_total_inr: 0,
    }
  }
  const bom = Array.isArray(raw.bom) ? (raw.bom as Array<Record<string, unknown>>) : []
  const bomTotal = bom.reduce((acc, b) => acc + Number(b.unit_cost_inr ?? 0), 0)
  const landed = Number(raw.landed_cost_inr ?? 0)
  const marginPct =
    typeof raw.margin_pct === 'number' ? raw.margin_pct : Number(raw.margin_pct ?? 0)
  const target = Number(raw.target_price_inr ?? targetPriceInr)
  const marginInr =
    typeof raw.margin_inr === 'number'
      ? raw.margin_inr
      : Math.max(0, target - landed)
  const verdict =
    typeof raw.verdict === 'string' && raw.verdict.length > 0
      ? raw.verdict
      : verdictFromMargin(marginPct)
  const verdictReason =
    typeof raw.verdict_reason === 'string'
      ? raw.verdict_reason
      : `Margin ${marginPct.toFixed(1)}% (from manufacturing estimate)`
  const be =
    raw.break_even_moq === undefined || raw.break_even_moq === null
      ? null
      : Number(raw.break_even_moq)

  return {
    hasData: true,
    verdict,
    verdict_reason: verdictReason,
    landed_cost_inr: landed,
    target_price_inr: target,
    margin_pct: marginPct,
    margin_inr: marginInr,
    break_even_moq: Number.isFinite(be) ? be : null,
    bom,
    bom_total_inr: typeof raw.bom_total_inr === 'number' ? raw.bom_total_inr : bomTotal,
  }
}

// ── Editorial paper field — warm grain, faint blueprint diagonals ────────
function EditorialBlueprintGrid() {
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden">
      <div
        className="absolute inset-0"
        style={{
          backgroundImage: `radial-gradient(circle at 1px 1px, rgba(45, 69, 86, 0.08) 1px, transparent 0)`,
          backgroundSize: '24px 24px',
        }}
      />
      <div
        className="absolute inset-0 opacity-40"
        style={{
          backgroundImage: `
            linear-gradient(105deg, transparent 48.5%, rgba(45, 69, 86, 0.05) 49.5%, rgba(45, 69, 86, 0.05) 50.5%, transparent 51.5%),
            linear-gradient(-15deg, transparent 48.5%, rgba(45, 69, 86, 0.04) 49.5%, rgba(45, 69, 86, 0.04) 50.5%, transparent 51.5%)
          `,
          backgroundSize: '88px 88px, 120px 120px',
        }}
      />
      <div
        className="absolute inset-0"
        style={{
          background:
            'radial-gradient(ellipse 78% 62% at 50% 48%, rgba(242, 236, 224, 0.92) 0%, transparent 64%)',
        }}
      />
    </div>
  )
}

// ── 3D Product Spec Viewer (kept; trim refined) ─────────────────────────
function SpecViewer({ spec, hwProduct }: { spec: Record<string, unknown>; hwProduct: HwListItem | null }) {
  const [rotateY, setRotateY] = useState(-25)
  const [rotateX, setRotateX] = useState(15)
  const [dragging, setDragging] = useState(false)
  const lastPos = useRef({ x: 0, y: 0 })

  const hints = (spec?.render_hints ?? {}) as Record<string, unknown>
  const shape = String(hints.primary_shape ?? 'box')
  const color = String(hints.color_hex ?? '#1e293b')
  const material = String(hints.dominant_material ?? 'ABS')
  const components = Array.isArray(spec?.components) ? (spec.components as Array<Record<string, unknown>>) : []
  const dims = (spec?.dimensions ?? {}) as Record<string, unknown>

  const onMouseDown = (e: MouseEvent) => {
    setDragging(true)
    lastPos.current = { x: e.clientX, y: e.clientY }
  }
  const onMouseMove = (e: MouseEvent) => {
    if (!dragging) return
    const dx = e.clientX - lastPos.current.x
    const dy = e.clientY - lastPos.current.y
    setRotateY((prev) => prev + dx * 0.5)
    setRotateX((prev) => Math.max(-30, Math.min(30, prev - dy * 0.3)))
    lastPos.current = { x: e.clientX, y: e.clientY }
  }
  const onMouseUp = () => setDragging(false)
  const onReset = () => {
    setRotateY(-25)
    setRotateX(15)
  }

  const ZONE_COLORS: Record<string, string> = {
    shell: '#1e3a5f',
    core: '#1e4d3f',
    top: '#2d3b55',
    bottom: '#1a2d3f',
    left: '#2a3f5f',
    right: '#2a3f5f',
  }

  return (
    <div
      className="relative flex min-h-[520px] flex-1 select-none flex-col items-center justify-center"
      style={{ perspective: '900px' }}
      onMouseMove={onMouseMove}
      onMouseUp={onMouseUp}
      onMouseLeave={onMouseUp}
    >
      <EditorialBlueprintGrid />

      {/* Plate corner registration marks */}
      <div className="pointer-events-none absolute inset-6 z-0">
        {(['tl', 'tr', 'bl', 'br'] as const).map((c) => (
          <span
            key={c}
            aria-hidden
            className="absolute h-3 w-3 border-[var(--workshop)]/35"
            style={{
              top: c.startsWith('t') ? 0 : 'auto',
              bottom: c.startsWith('b') ? 0 : 'auto',
              left: c.endsWith('l') ? 0 : 'auto',
              right: c.endsWith('r') ? 0 : 'auto',
              borderTopWidth: c.startsWith('t') ? 1 : 0,
              borderBottomWidth: c.startsWith('b') ? 1 : 0,
              borderLeftWidth: c.endsWith('l') ? 1 : 0,
              borderRightWidth: c.endsWith('r') ? 1 : 0,
            }}
          />
        ))}
      </div>

      <div className="relative z-10 mb-3 text-center">
        <p className="kicker" style={{ color: 'var(--workshop)' }}>
          Plate · Component diagram
        </p>
      </div>

      <div
        className="relative z-10 cursor-grab active:cursor-grabbing"
        style={{
          transform: `rotateX(${rotateX}deg) rotateY(${rotateY}deg)`,
          transformStyle: 'preserve-3d',
          transition: dragging ? 'none' : 'transform 0.3s ease-out',
          filter: 'drop-shadow(0 28px 40px rgba(26, 23, 20, 0.18))',
        }}
        onMouseDown={onMouseDown}
        onDoubleClick={onReset}
        role="presentation"
      >
        <svg viewBox="0 0 360 280" width={460} xmlns="http://www.w3.org/2000/svg" className="max-w-full">
          <ellipse cx="180" cy="270" rx="120" ry="12" fill="var(--workshop)" opacity="0.1" />

          {shape === 'flat' ? (
            <>
              <rect x="40" y="100" width="280" height="80" rx="8" fill={color} stroke="#3b82f620" strokeWidth="1" />
              <rect x="50" y="104" width="100" height="6" rx="3" fill="white" opacity="0.08" />
            </>
          ) : shape === 'cylinder' ? (
            <>
              <ellipse cx="180" cy="80" rx="120" ry="30" fill={color} stroke="#3b82f630" strokeWidth="1" />
              <rect x="60" y="80" width="240" height="140" fill={color} stroke="#3b82f620" strokeWidth="1" />
              <ellipse cx="180" cy="220" rx="120" ry="30" fill={color} stroke="#3b82f630" strokeWidth="1" />
            </>
          ) : (
            <>
              <rect x="30" y="70" width="240" height="170" rx="6" fill={color} stroke="#3b82f625" strokeWidth="1.5" />
              <polygon
                points="30,70 100,30 340,30 270,70"
                fill={color}
                style={{ filter: 'brightness(1.3)' }}
                stroke="#3b82f625"
                strokeWidth="1.5"
              />
              <polygon
                points="270,70 340,30 340,200 270,240"
                fill={color}
                style={{ filter: 'brightness(0.7)' }}
                stroke="#3b82f620"
                strokeWidth="1.5"
              />
              <polygon points="35,68 85,35 200,35 150,68" fill="white" opacity="0.04" />
              <line x1="30" y1="70" x2="270" y2="70" stroke="#3b82f6" strokeWidth="0.8" opacity="0.6" />
              <line x1="30" y1="70" x2="100" y2="30" stroke="#3b82f6" strokeWidth="0.8" opacity="0.4" />
            </>
          )}

          {components.slice(0, 4).map((comp, i) => {
            const offsets = [
              { x: 45, y: 85 },
              { x: 45, y: 125 },
              { x: 45, y: 165 },
              { x: 45, y: 205 },
            ]
            const pos = offsets[i] ?? { x: 45, y: 85 + i * 40 }
            const zone = String(comp.zone ?? 'core')
            const zoneColor = ZONE_COLORS[zone] ?? '#1e293b'
            const cid = String(comp.id ?? i)
            return (
              <g key={cid}>
                <rect
                  x={pos.x}
                  y={pos.y}
                  width={220}
                  height={28}
                  rx="3"
                  fill={zoneColor}
                  stroke="#3b82f630"
                  strokeWidth="0.8"
                  strokeDasharray="4 2"
                />
                <text x={pos.x + 8} y={pos.y + 17} fontSize="8" fontFamily="monospace" fill="#5c564e">
                  {String(comp.name ?? '')} · {String(comp.material ?? '')}
                </text>
                <circle cx={pos.x + 212} cy={pos.y + 14} r="3" fill="var(--workshop)" opacity="0.75" />
              </g>
            )
          })}

          {dims.length_mm != null && (
            <>
              <line x1="30" y1="255" x2="270" y2="255" stroke="var(--workshop)" strokeOpacity="0.25" strokeWidth="0.7" />
              <text x="150" y="268" textAnchor="middle" fontSize="7" fontFamily="monospace" fill="#6b6560">
                {String(dims.length_mm)}mm × {String(dims.width_mm ?? '—')}mm
                {dims.weight_grams != null ? ` · ${String(dims.weight_grams)}g` : ''}
              </text>
            </>
          )}
        </svg>
      </div>

      <div className="relative z-10 mt-5 flex items-center gap-4 text-[11px] text-[var(--ink-secondary)]">
        <span className="flex items-center gap-1.5">
          <Hexagon size={11} className="text-[var(--workshop)]" />
          {material}
        </span>
        <span className="h-3 w-px bg-[var(--border-color)]" />
        <span>{components.length} components</span>
        {hwProduct?.name ? (
          <>
            <span className="h-3 w-px bg-[var(--border-color)]" />
            <span className="font-serif italic text-[var(--ink)]">{hwProduct.name}</span>
          </>
        ) : null}
      </div>

      <button
        type="button"
        onClick={onReset}
        className="relative z-10 mt-4 flex items-center gap-1.5 text-[10px] uppercase tracking-[0.22em] text-[var(--ink-tertiary)] transition-colors hover:text-[var(--red)]"
      >
        <RotateCcw size={10} />
        drag to rotate · double-click to reset
      </button>
    </div>
  )
}

const CATEGORIES = [
  { value: 'consumer_hardware', label: 'Consumer Hardware' },
  { value: 'health_hardware', label: 'Health Hardware' },
  { value: 'wearable', label: 'Wearable' },
  { value: 'iot_hardware', label: 'IoT Hardware' },
  { value: 'b2b_hardware', label: 'B2B Hardware' },
] as const

const ROMAN = ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII']

export default function HardwareBuilderPage() {
  const params = useParams()
  const router = useRouter()
  const projectId = String(params.id ?? '')
  const projectIdNum = Number(projectId)
  const { data: project } = useProject(
    projectId && Number.isFinite(projectIdNum) ? projectIdNum : null
  )
  const queryClient = useQueryClient()

  useEffect(() => {
    if (!project) return
    if (project.dossier_axis === 'software') {
      router.replace(`/project/${projectId}/prototype`)
    }
  }, [project, router, projectId])

  const [activeTab, setActiveTab] = useState<Tab>('spec')
  const isMobile = useIsMobile()
  const [selectedHwId, setSelectedHwId] = useState<number | null>(null)
  const [generating, setGenerating] = useState(false)
  const [runningTests, setRunningTests] = useState(false)
  const [runningSim, setRunningSim] = useState(false)
  const [competitiveReport, setCompetitiveReport] = useState<CompetitiveReport | null>(null)
  const [pdfBusy, setPdfBusy] = useState(false)
  const [configOpen, setConfigOpen] = useState(true)

  const [genForm, setGenForm] = useState({
    name: '',
    description: '',
    category: 'wearable',
    target_price_inr: 4999,
    product_type: 'wearable',
  })

  const api = getApiV1Base()

  const { data: hwList = [], refetch: refetchHw } = useQuery<HwListItem[]>({
    queryKey: ['hardware', projectId],
    queryFn: async (): Promise<HwListItem[]> => {
      const r = await fetch(`${api}/projects/${projectId}/hardware`, { headers: authHeaders() })
      if (!r.ok) throw new Error(await r.text())
      return (await r.json()) as HwListItem[]
    },
    enabled: Boolean(projectId),
  })

  useEffect(() => {
    if (hwList.length === 0) {
      setSelectedHwId(null)
      return
    }
    setSelectedHwId((prev) => {
      if (prev != null && hwList.some((h) => h.id === prev)) return prev
      return hwList[0].id
    })
  }, [hwList])

  useEffect(() => {
    setCompetitiveReport(null)
  }, [selectedHwId])

  const hwId = selectedHwId

  const { data: specData } = useQuery<HwDetail | null>({
    queryKey: ['hw-spec', projectId, hwId],
    queryFn: async (): Promise<HwDetail | null> => {
      const r = await fetch(`${api}/projects/${projectId}/hardware/${hwId}`, { headers: authHeaders() })
      if (!r.ok) throw new Error(await r.text())
      return (await r.json()) as HwDetail
    },
    enabled: Boolean(projectId && hwId),
  })

  const mergedSpec = useMemo(() => {
    if (!specData) return {}
    return {
      ...(specData.spec ?? {}),
      render_hints: specData.render_hints,
    } as Record<string, unknown>
  }, [specData])

  const hardwareSpec: HardwareSpec | null = useMemo(() => {
    if (!specData) return null
    const s = specData.spec ?? {}
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
        ...(cluster != null && cluster !== '' ? { cluster_id: String(cluster) } : {}),
      }
    })
    const d = s.dimensions as Record<string, unknown> | undefined
    const dimensions =
      d && typeof d === 'object'
        ? {
            length_mm: Number(d.length_mm ?? 0),
            width_mm: Number(d.width_mm ?? 0),
            height_mm: Number(d.height_mm ?? 0),
            weight_grams: Number(d.weight_grams ?? specData.weight_grams ?? 0),
          }
        : undefined
    return {
      product_name: (s.product_name as string) || specData.name,
      dimensions,
      components,
      render_hints: specData.render_hints,
    }
  }, [specData])

  type TestResultsPayload = {
    results: TestResult[]
    total_tests: number
    passed: number
    failed: number
    overall_pass_rate: number
  }

  const { data: testResultsPayload, refetch: refetchTests } = useQuery<TestResultsPayload>({
    queryKey: ['hw-tests', projectId, hwId],
    queryFn: async (): Promise<TestResultsPayload> => {
      const r = await fetch(`${api}/projects/${projectId}/hardware/${hwId}/test-results`, {
        headers: authHeaders(),
      })
      if (!r.ok) throw new Error(await r.text())
      return (await r.json()) as TestResultsPayload
    },
    enabled: Boolean(projectId && hwId && activeTab === 'tests'),
  })

  const { data: costRaw } = useQuery<Record<string, unknown>>({
    queryKey: ['hw-cost', projectId, hwId],
    queryFn: async (): Promise<Record<string, unknown>> => {
      const r = await fetch(`${api}/projects/${projectId}/hardware/${hwId}/cost-analysis`, {
        headers: authHeaders(),
      })
      return (await r.json()) as Record<string, unknown>
    },
    enabled: Boolean(projectId && hwId),
  })

  const selectedHw = hwList.find((h) => h.id === hwId) ?? null
  const targetFromProduct = Number(selectedHw?.target_price_inr ?? specData?.target_price_inr ?? 1999)

  const costView = useMemo(
    () => normalizeCostView(costRaw, targetFromProduct),
    [costRaw, targetFromProduct],
  )

  const { data: simData, refetch: refetchSim } = useQuery<Record<string, unknown>>({
    queryKey: ['hw-sim', projectId, hwId],
    queryFn: async (): Promise<Record<string, unknown>> => {
      const r = await fetch(`${api}/projects/${projectId}/hardware/${hwId}/consumer-simulation`, {
        headers: authHeaders(),
      })
      return (await r.json()) as Record<string, unknown>
    },
    enabled: Boolean(projectId && hwId && activeTab === 'simulation'),
  })

  const hasSimulation = Boolean(simData && 'hardware_product_id' in simData)

  const runCostMutation = useMutation({
    mutationFn: async () => {
      const r = await fetch(`${api}/projects/${projectId}/hardware/${hwId}/cost-analysis`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({
          target_price_inr: selectedHw?.target_price_inr ?? 1999,
          moq: 500,
        }),
      })
      if (!r.ok) throw new Error(await r.text())
      return (await r.json()) as Record<string, unknown>
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['hw-cost', projectId, hwId] })
    },
  })

  const headerCostVerdict = costView.hasData ? costView.verdict : null

  const runCompetitiveMutation = useMutation({
    mutationFn: async () => {
      const r = await fetch(`${api}/projects/${projectId}/hardware/${hwId}/competitive-analysis`, {
        method: 'POST',
        headers: authHeaders(),
      })
      if (!r.ok) throw new Error(await r.text())
      return (await r.json()) as CompetitiveReport
    },
    onSuccess: (data: CompetitiveReport) => {
      setCompetitiveReport(data)
    },
  })

  const handleGenerate = async () => {
    setGenerating(true)
    try {
      const r = await fetch(`${api}/projects/${projectId}/hardware/generate-spec`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({
          name: genForm.name.trim(),
          description: genForm.description.trim(),
          category: genForm.category,
          product_type: genForm.product_type,
          target_price_inr: genForm.target_price_inr,
        }),
      })
      if (!r.ok) throw new Error(await r.text())
      const created = (await r.json()) as { id: number }
      await refetchHw()
      setSelectedHwId(created.id)
      void queryClient.invalidateQueries({ queryKey: ['hw-spec', projectId, created.id] })
      setActiveTab('spec')
    } finally {
      setGenerating(false)
    }
  }

  const handleRunTests = useCallback(async () => {
    if (!hwId) return
    setRunningTests(true)
    try {
      const r = await fetch(`${api}/projects/${projectId}/hardware/${hwId}/run-tests`, {
        method: 'POST',
        headers: authHeaders(),
      })
      if (!r.ok) throw new Error(await r.text())
      window.setTimeout(() => {
        void refetchTests()
        void queryClient.invalidateQueries({ queryKey: ['hw-tests', projectId, hwId] })
        setRunningTests(false)
      }, 3000)
    } catch {
      setRunningTests(false)
    }
  }, [api, hwId, projectId, queryClient, refetchTests])

  const handleRunSim = async () => {
    if (!hwId) return
    setRunningSim(true)
    try {
      const r = await fetch(`${api}/projects/${projectId}/hardware/${hwId}/consumer-simulation`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({}),
      })
      if (!r.ok) throw new Error(await r.text())
      window.setTimeout(() => {
        void refetchSim()
        void queryClient.invalidateQueries({ queryKey: ['hw-sim', projectId, hwId] })
        setRunningSim(false)
      }, 2500)
    } catch {
      setRunningSim(false)
    }
  }

  const downloadPdf = async () => {
    if (!hwId) return
    setPdfBusy(true)
    try {
      const r = await fetch(`${api}/projects/${projectId}/hardware/${hwId}/report.pdf`, {
        headers: authHeaders(),
      })
      if (!r.ok) throw new Error(await r.text())
      const blob = await r.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `thecee-hardware-${hwId}.pdf`
      a.click()
      URL.revokeObjectURL(url)
    } finally {
      setPdfBusy(false)
    }
  }

  const TABS: { key: Tab; label: string; sub: string; Icon: typeof Cpu }[] = [
    { key: 'spec', label: 'Spec', sub: 'Blueprint', Icon: Hexagon },
    { key: 'tests', label: 'Tests', sub: 'Physics', Icon: FlaskConical },
    { key: 'cost', label: 'Cost', sub: 'Margin', Icon: Scale },
    { key: 'simulation', label: 'Simulation', sub: '52 clusters', Icon: Users },
    { key: 'competitive', label: 'Competitive', sub: 'Position', Icon: Target },
    { key: 'report', label: 'Report', sub: 'Filed PDF', Icon: FileText },
  ]

  const verdictColor = (v: string) =>
    v === 'VIABLE'
      ? 'text-emerald-900 border-emerald-700/35'
      : v === 'MARGINAL'
        ? 'text-amber-900 border-amber-700/35'
        : v === 'NOT_VIABLE'
          ? 'text-red-900 border-red-700/40'
          : 'text-[var(--ink-tertiary)] border-[var(--border-color)]'

  const verdictBorderBg = (v: string) =>
    v === 'VIABLE'
      ? 'border-emerald-700/25 bg-emerald-500/[0.07]'
      : v === 'MARGINAL'
        ? 'border-amber-700/25 bg-amber-500/[0.08]'
        : 'border-red-700/25 bg-red-500/[0.06]'

  const statusColor = (s: string) =>
    s === 'PASS'
      ? 'text-emerald-800'
      : s === 'PARTIAL'
        ? 'text-amber-900'
        : s === 'FAIL'
          ? 'text-red-800'
          : 'text-[var(--ink-tertiary)]'

  const testResults = testResultsPayload?.results ?? []
  const compDisplay = competitiveReport

  const simFindings = (simData?.domain_findings ?? []) as DomainFindingRow[]
  const simClusters = (simData?.cluster_results ?? {}) as Record<
    string,
    { conversion_rate?: number; population_fraction?: number }
  >

  const issueLine = `Folio ${String(hwId ?? '—').padStart(3, '0')} · Workshop edition`

  return (
    <div className="hw-workshop min-h-screen bg-[var(--paper)] text-[var(--ink)]">
      {/* ── EDITORIAL MASTHEAD ────────────────────────────────────── */}
      <section
        className="relative z-20 border-b border-[var(--border-color)] px-10 pt-9 pb-6"
        style={{ background: 'linear-gradient(180deg, #faf7f0 0%, var(--paper) 100%)' }}
      >
        <div className="flex items-center justify-between text-[10px] uppercase tracking-[0.28em] text-[var(--ink-secondary)]">
          <span style={{ color: 'var(--red)', fontWeight: 600 }}>The Workshop</span>
          <span>{issueLine}</span>
          <Link
            href={`/project/${projectId}`}
            className="flex items-center gap-2 transition-colors hover:text-[var(--red)]"
          >
            <ArrowLeft size={11} />
            Back to dossier
          </Link>
        </div>

        <div className="mt-5 flex items-end justify-between gap-8">
          <div className="min-w-0 flex-1">
            <p className="kicker mb-2" style={{ color: 'var(--workshop)' }}>
              <span className="status-dot status-dot--running" />
              {selectedHw ? (selectedHw.category ?? 'hardware').replace(/_/g, ' ') : 'Awaiting first plate'}
            </p>
            <h1
              className="font-serif italic leading-[0.96] tracking-tight text-[var(--ink)]"
              style={{ fontSize: 'clamp(36px, 4.5vw, 56px)', fontWeight: 900, letterSpacing: '-0.035em' }}
            >
              {selectedHw?.name ?? (
                <>
                  An <span style={{ color: 'var(--red)' }}>idea</span> on the press.
                </>
              )}
            </h1>
            <p className="mt-3 max-w-[58ch] text-[13px] leading-[1.7] text-[var(--ink-secondary)]">
              Blueprint, physics, margin, and the room&rsquo;s verdict — typeset like the rest of
              the magazine. Configure on the left, watch the plate set itself on the right.
            </p>
          </div>

          <div className="flex shrink-0 flex-col items-end gap-3">
            {hwList.length > 1 ? (
              <label className="text-[10px] uppercase tracking-[0.22em] text-[var(--ink-tertiary)]">
                Filed under
                <select
                  value={hwId ?? ''}
                  onChange={(e) => setSelectedHwId(Number(e.target.value))}
                  className="ml-2 rounded-none border-0 border-b border-[var(--ink)] bg-transparent px-1 py-1 font-serif text-sm italic text-[var(--ink)] focus:outline-none"
                >
                  {hwList.map((h) => (
                    <option key={h.id} value={h.id}>
                      {h.name}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
            {headerCostVerdict && headerCostVerdict !== '—' ? (
              <span
                className={`inline-flex items-center gap-2 border px-3 py-1.5 text-[10px] font-medium uppercase tracking-[0.22em] ${verdictColor(headerCostVerdict)}`}
              >
                <span className="h-1.5 w-1.5 rounded-full bg-current" />
                Verdict · {headerCostVerdict}
              </span>
            ) : null}
          </div>
        </div>

        <div className="mt-6 h-[2px] bg-[var(--red)]" />
      </section>

      {/* ── SECTION TABS — editorial nav with roman numerals ────── */}
      {!isMobile && (
        <nav className="relative z-20 border-b border-[var(--border-color)] bg-[var(--paper)]/85 backdrop-blur-sm">
          <ul className="flex">
            {TABS.map((t, i) => {
              const active = activeTab === t.key
              const Icon = t.Icon
              return (
                <li key={t.key} className="flex-1">
                  <button
                    type="button"
                    onClick={() => setActiveTab(t.key)}
                    className={`group relative flex w-full items-center gap-3 px-5 py-4 text-left transition-colors ${
                      active ? 'text-[var(--ink)]' : 'text-[var(--ink-tertiary)] hover:text-[var(--ink-secondary)]'
                    }`}
                  >
                    <span
                      className={`font-serif text-xs italic transition-colors ${
                        active ? 'text-[var(--red)]' : 'text-[var(--ink-tertiary)]'
                      }`}
                      style={{ letterSpacing: 0 }}
                    >
                      {ROMAN[i]}.
                    </span>
                    <Icon size={14} className={active ? 'text-[var(--red)]' : 'text-[var(--ink-tertiary)]'} />
                    <span className="flex flex-col leading-tight">
                      <span className="text-[12px] font-medium uppercase tracking-[0.18em]">{t.label}</span>
                      <span className="text-[9.5px] uppercase tracking-[0.22em] text-[var(--ink-tertiary)]">
                        {t.sub}
                      </span>
                    </span>
                    {active && (
                      <motion.span
                        layoutId="hw-tab-rule"
                        className="absolute right-0 bottom-0 left-0 h-[2px] bg-[var(--red)]"
                      />
                    )}
                  </button>
                </li>
              )
            })}
          </ul>
        </nav>
      )}

      {/* ── CONTENT ───────────────────────────────────────────────── */}
      <div className={`relative ${isMobile ? 'pb-24' : ''}`}>
        <AnimatePresence mode="wait">
          {activeTab === 'spec' && (
            <motion.div
              key="spec"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="flex min-h-[calc(100vh-260px)]"
            >
              {/* ── Left ledger: Configuration sheet ─────────── */}
              <aside
                className={`relative z-10 flex flex-col border-r border-[var(--border-color)] bg-[var(--paper)]/96 transition-[width] duration-300 ${
                  configOpen ? 'w-[360px]' : 'w-12'
                }`}
              >
                <button
                  type="button"
                  onClick={() => setConfigOpen((v) => !v)}
                  className="absolute -right-3 top-8 z-20 flex h-6 w-6 items-center justify-center rounded-full border border-[var(--border-strong)] bg-[var(--paper)] text-[var(--ink-secondary)] shadow-sm transition-colors hover:border-[var(--red)] hover:text-[var(--red)]"
                  aria-label={configOpen ? 'Collapse configuration' : 'Expand configuration'}
                >
                  {configOpen ? <ArrowLeft size={12} /> : <ArrowRight size={12} />}
                </button>

                {configOpen ? (
                  <>
                    <div className="border-b border-[var(--border-color)] px-7 pt-8 pb-5">
                      <p className="kicker" style={{ color: 'var(--workshop)' }}>
                        Configuration sheet
                      </p>
                      <h2
                        className="mt-2 font-serif italic leading-tight tracking-tight text-[var(--ink)]"
                        style={{ fontSize: 22, fontWeight: 800, letterSpacing: '-0.02em' }}
                      >
                        File a new <span style={{ color: 'var(--red)' }}>plate</span>.
                      </h2>
                      <p className="mt-2 text-[12px] leading-relaxed text-[var(--ink-secondary)]">
                        Four fields. Set the parameters, press the press, and the workshop returns
                        a typeset specification.
                      </p>
                    </div>

                    <div className="flex-1 space-y-5 overflow-y-auto px-7 py-6">
                      <Field label="Product name" numeral="i.">
                        <input
                          type="text"
                          placeholder="e.g. Daybreak SmartWatch"
                          value={genForm.name}
                          onChange={(e) => setGenForm((f) => ({ ...f, name: e.target.value }))}
                          className="w-full border-0 border-b border-[var(--ink)]/35 bg-transparent px-0 py-2 font-serif text-base italic text-[var(--ink)] placeholder-[var(--ink-tertiary)] focus:border-[var(--red)] focus:outline-none"
                        />
                      </Field>

                      <Field label="Target price (₹)" numeral="ii.">
                        <input
                          type="number"
                          placeholder="4999"
                          value={genForm.target_price_inr}
                          onChange={(e) =>
                            setGenForm((f) => ({ ...f, target_price_inr: Number(e.target.value) || 0 }))
                          }
                          className="w-full border-0 border-b border-[var(--ink)]/35 bg-transparent px-0 py-2 font-mono text-base text-[var(--ink)] placeholder-[var(--ink-tertiary)] focus:border-[var(--red)] focus:outline-none"
                        />
                      </Field>

                      <Field label="Category" numeral="iii.">
                        <select
                          value={genForm.category}
                          onChange={(e) =>
                            setGenForm((f) => ({
                              ...f,
                              category: e.target.value,
                              product_type: e.target.value,
                            }))
                          }
                          className="w-full border-0 border-b border-[var(--ink)]/35 bg-transparent px-0 py-2 font-serif text-base italic text-[var(--ink)] focus:border-[var(--red)] focus:outline-none"
                        >
                          {CATEGORIES.map((c) => (
                            <option key={c.value} value={c.value}>
                              {c.label}
                            </option>
                          ))}
                        </select>
                      </Field>

                      <Field label="Marginalia" numeral="iv.">
                        <textarea
                          rows={5}
                          placeholder="Materials, key features, form factor — the editor's note."
                          value={genForm.description}
                          onChange={(e) => setGenForm((f) => ({ ...f, description: e.target.value }))}
                          className="w-full resize-none border-0 border-b border-[var(--ink)]/35 bg-transparent px-0 py-2 font-serif text-[15px] leading-relaxed italic text-[var(--ink)] placeholder-[var(--ink-tertiary)] focus:border-[var(--red)] focus:outline-none"
                        />
                      </Field>
                    </div>

                    <div className="space-y-2.5 border-t border-[var(--border-color)] px-7 py-6">
                      <button
                        type="button"
                        onClick={() => void handleGenerate()}
                        disabled={!genForm.name || !genForm.description || generating}
                        className="flex w-full items-center justify-center gap-2.5 bg-[var(--ink)] py-3 text-[11px] font-medium uppercase tracking-[0.22em] text-[var(--paper)] transition-all hover:bg-[var(--red)] disabled:cursor-not-allowed disabled:opacity-40"
                      >
                        {generating ? (
                          <>
                            <Loader2 size={13} className="animate-spin" />
                            Setting type…
                          </>
                        ) : (
                          <>
                            <Sparkles size={13} />
                            Send to press
                          </>
                        )}
                      </button>
                      {hwId ? (
                        <button
                          type="button"
                          onClick={() => void handleRunTests()}
                          disabled={runningTests}
                          className="flex w-full items-center justify-center gap-2.5 border border-[var(--workshop)]/45 py-2.5 text-[11px] font-medium uppercase tracking-[0.22em] text-[var(--workshop)] transition-all hover:bg-[var(--workshop)] hover:text-[var(--paper)] disabled:opacity-40"
                        >
                          {runningTests ? (
                            <>
                              <Loader2 size={12} className="animate-spin" />
                              Running…
                            </>
                          ) : (
                            <>
                              <Play size={12} />
                              Run physics tests
                            </>
                          )}
                        </button>
                      ) : null}
                    </div>
                  </>
                ) : (
                  <div className="flex flex-1 flex-col items-center pt-10">
                    <span
                      className="kicker rotate-180 text-[var(--ink-tertiary)]"
                      style={{ writingMode: 'vertical-rl' }}
                    >
                      Configuration sheet
                    </span>
                  </div>
                )}
              </aside>

              {/* ── Right plate: 3D viewer or empty editorial state ─ */}
              {mergedSpec && Object.keys(mergedSpec).length > 0 ? (
                <SpecViewer spec={mergedSpec} hwProduct={selectedHw} />
              ) : (
                <div className="relative flex flex-1 flex-col items-center justify-center px-10 py-16">
                  <EditorialBlueprintGrid />
                  <div className="relative z-10 max-w-md text-center">
                    <p className="kicker mb-5" style={{ color: 'var(--red)' }}>
                      Standing type · Plate not yet filed
                    </p>
                    <div className="mx-auto mb-7 flex h-20 w-20 items-center justify-center border border-[var(--workshop)]/35 bg-[var(--paper)]">
                      <Hexagon size={36} className="text-[var(--workshop)]" strokeWidth={1.2} />
                    </div>
                    <h3
                      className="font-serif italic leading-tight text-[var(--ink)]"
                      style={{ fontSize: 30, fontWeight: 900, letterSpacing: '-0.025em' }}
                    >
                      Awaiting <span style={{ color: 'var(--red)' }}>impression</span>.
                    </h3>
                    <p className="mt-4 text-sm leading-relaxed text-[var(--ink-secondary)]">
                      File the four-line configuration on the left and the workshop will set a
                      blueprint, dimensions, and a component diagram on this plate.
                    </p>
                    <div className="mt-8 flex items-center justify-center gap-3 text-[10px] uppercase tracking-[0.28em] text-[var(--ink-tertiary)]">
                      <span className="h-px w-8 bg-[var(--border-strong)]" />
                      drag to rotate
                      <span className="h-px w-8 bg-[var(--border-strong)]" />
                    </div>
                  </div>
                </div>
              )}
            </motion.div>
          )}

          {activeTab === 'tests' && (
            <motion.div
              key="tests"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="space-y-7 px-10 py-9"
            >
              <SectionHead
                kicker="Section II · Physics"
                title="The room shakes the prototype."
                description="Eight stress regimes, every component scored. The press returns a pass-rate per axis."
                action={
                  <button
                    type="button"
                    onClick={() => void handleRunTests()}
                    disabled={!hwId || runningTests}
                    className="flex items-center gap-2 bg-[var(--ink)] px-4 py-2.5 text-[11px] font-medium uppercase tracking-[0.22em] text-[var(--paper)] transition-all hover:bg-[var(--red)] disabled:opacity-40"
                  >
                    {runningTests ? (
                      <>
                        <Loader2 size={12} className="animate-spin" /> Running…
                      </>
                    ) : (
                      <>
                        <Play size={12} /> Re-run tests
                      </>
                    )}
                  </button>
                }
              />

              {testResults.length > 0 ? (
                <>
                  <div className="grid grid-cols-2 gap-px bg-[var(--border-color)] sm:grid-cols-4">
                    {(
                      [
                        { label: 'Tests run', value: testResultsPayload?.total_tests, tone: 'ink' as const },
                        { label: 'Passed', value: testResultsPayload?.passed, tone: 'green' as const },
                        { label: 'Failed', value: testResultsPayload?.failed, tone: 'red' as const },
                        {
                          label: 'Pass rate',
                          value: `${((testResultsPayload?.overall_pass_rate ?? 0) * 100).toFixed(0)}%`,
                          tone: 'workshop' as const,
                        },
                      ] as const
                    ).map((k) => (
                      <Stat key={k.label} label={k.label} value={String(k.value ?? '—')} tone={k.tone} />
                    ))}
                  </div>

                  <div className="space-y-3">
                    {testResults.map((r) => (
                      <div
                        key={r.test_type}
                        className="border border-[var(--border-color)] bg-[var(--paper)]/85 p-5"
                      >
                        <div className="mb-3 flex items-center justify-between">
                          <div className="flex items-center gap-3">
                            <span className={`font-serif text-base italic ${statusColor(r.status)}`}>
                              {r.status === 'PASS' ? '✓' : r.status === 'FAIL' ? '✗' : '~'}
                            </span>
                            <span className="text-sm capitalize text-[var(--ink)]">
                              {r.test_type?.replace(/_/g, ' ')}
                            </span>
                          </div>
                          <div className="flex items-center gap-3">
                            <div className="h-1 w-36 overflow-hidden bg-[var(--border-color)]">
                              <div
                                className={`h-full ${
                                  r.pass_rate > 0.7
                                    ? 'bg-emerald-700'
                                    : r.pass_rate > 0.4
                                      ? 'bg-amber-600'
                                      : 'bg-red-700'
                                }`}
                                style={{ width: `${Math.min(100, r.pass_rate * 100)}%` }}
                              />
                            </div>
                            <span className="w-10 font-mono text-xs text-[var(--ink-secondary)]">
                              {(r.pass_rate * 100).toFixed(0)}%
                            </span>
                          </div>
                        </div>
                        {r.failure_points?.length ? (
                          <div className="space-y-1 border-t border-[var(--border-color)] pt-3">
                            {r.failure_points.slice(0, 2).map((fp: FailurePoint, i: number) => (
                              <p key={i} className="font-mono text-xs text-red-700">
                                → {fp.reason}
                              </p>
                            ))}
                          </div>
                        ) : null}
                      </div>
                    ))}
                  </div>

                  {hardwareSpec ? (
                    <HardwareFailureMap spec={hardwareSpec} testResults={testResults} />
                  ) : null}
                </>
              ) : (
                <EmptySection
                  title="No tests on file."
                  body="Generate a spec first, then send the prototype to the press for physical regimes."
                />
              )}
            </motion.div>
          )}

          {activeTab === 'cost' && (
            <motion.div
              key="cost"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="space-y-7 px-10 py-9"
            >
              <SectionHead
                kicker="Section III · Margin"
                title="What it costs to land on a desk."
                description="Bill of materials, freight, duties, factory overhead — distilled to one verdict."
                action={
                  hwId ? (
                    <button
                      type="button"
                      onClick={() => runCostMutation.mutate()}
                      disabled={runCostMutation.isPending}
                      className="flex items-center gap-2 border border-[var(--border-strong)] px-4 py-2.5 text-[11px] font-medium uppercase tracking-[0.22em] text-[var(--ink)] transition-all hover:border-[var(--ink)] hover:text-[var(--red)] disabled:opacity-40"
                    >
                      {runCostMutation.isPending ? (
                        <>
                          <Loader2 size={12} className="animate-spin" /> Running…
                        </>
                      ) : (
                        <>Re-run analysis</>
                      )}
                    </button>
                  ) : null
                }
              />

              {costView.hasData ? (
                <>
                  <div className={`border p-6 ${verdictBorderBg(costView.verdict)}`}>
                    <p className="kicker mb-2" style={{ color: 'var(--ink-secondary)' }}>
                      Editor&rsquo;s verdict
                    </p>
                    <p
                      className={`font-serif italic ${verdictColor(costView.verdict).split(' ')[0]}`}
                      style={{ fontSize: 32, fontWeight: 900, letterSpacing: '-0.02em' }}
                    >
                      {costView.verdict.replace(/_/g, ' ')}
                    </p>
                    <p className="mt-2 text-sm leading-relaxed text-[var(--ink-secondary)]">
                      {costView.verdict_reason}
                    </p>
                  </div>

                  <div className="grid grid-cols-2 gap-px bg-[var(--border-color)] lg:grid-cols-4">
                    {(
                      [
                        { label: 'Landed cost', value: `₹${costView.landed_cost_inr.toLocaleString('en-IN')}`, tone: 'workshop' as const },
                        { label: 'Target price', value: `₹${costView.target_price_inr.toLocaleString('en-IN')}`, tone: 'ink' as const },
                        { label: 'Gross margin', value: `${costView.margin_pct.toFixed(1)}%`, tone: 'workshop' as const },
                        {
                          label: 'Break-even',
                          value:
                            costView.break_even_moq != null
                              ? `${costView.break_even_moq.toLocaleString('en-IN')} units`
                              : '—',
                          tone: 'ink' as const,
                        },
                      ] as const
                    ).map((k) => (
                      <Stat key={k.label} label={k.label} value={k.value} tone={k.tone} />
                    ))}
                  </div>

                  {costView.bom.length > 0 ? (
                    <div>
                      <p className="kicker mb-3" style={{ color: 'var(--ink-secondary)' }}>
                        Bill of materials
                      </p>
                      <div className="table-mobile-scroll overflow-hidden border border-[var(--border-color)] bg-[var(--paper)]/90">
                        <table className="w-full min-w-[560px] text-sm">
                          <thead>
                            <tr className="border-b border-[var(--border-color)]">
                              {(['Component', 'Material', 'Volume (cm³)', 'Unit cost'] as const).map((h) => (
                                <th
                                  key={h}
                                  className="px-5 py-3 text-left text-[10px] font-medium uppercase tracking-[0.22em] text-[var(--ink-tertiary)]"
                                >
                                  {h}
                                </th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {costView.bom.map((item, idx) => (
                              <tr
                                key={String(item.component_id ?? item.component_name ?? idx)}
                                className="border-b border-[var(--border-color)] transition-colors hover:bg-[var(--paper-dark)]/35"
                              >
                                <td className="px-5 py-3 font-serif italic text-[var(--ink)]">
                                  {String(item.component_name ?? '—')}
                                </td>
                                <td className="px-5 py-3 text-[var(--ink-secondary)]">{String(item.material ?? '—')}</td>
                                <td className="px-5 py-3 font-mono text-[var(--ink-secondary)]">
                                  {item.volume_cm3 != null ? Number(item.volume_cm3).toFixed(1) : '—'}
                                </td>
                                <td className="px-5 py-3 font-mono text-[var(--workshop)]">
                                  ₹{Number(item.unit_cost_inr ?? 0).toFixed(2)}
                                </td>
                              </tr>
                            ))}
                            <tr className="bg-[var(--paper-dark)]/50">
                              <td colSpan={3} className="px-5 py-3 text-[10px] uppercase tracking-[0.22em] text-[var(--ink-tertiary)]">
                                Total BOM
                              </td>
                              <td className="px-5 py-3 font-mono font-bold text-[var(--workshop)]">
                                ₹{costView.bom_total_inr.toFixed(2)}
                              </td>
                            </tr>
                          </tbody>
                        </table>
                      </div>
                    </div>
                  ) : null}
                </>
              ) : (
                <EmptySection
                  title={costView.message ?? 'No cost analysis yet.'}
                  body="Run the manufacturing pass to estimate landed cost and margin."
                  action={
                    hwId ? (
                      <button
                        type="button"
                        onClick={() => runCostMutation.mutate()}
                        className="bg-[var(--ink)] px-5 py-2.5 text-[11px] uppercase tracking-[0.22em] text-[var(--paper)]"
                      >
                        Run cost analysis
                      </button>
                    ) : null
                  }
                />
              )}
            </motion.div>
          )}

          {activeTab === 'simulation' && (
            <motion.div
              key="simulation"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="space-y-7 px-10 py-9"
            >
              <SectionHead
                kicker="Section IV · The room"
                title="52 clusters meet the prototype."
                description="Synthetic readers walk past the shelf, pick it up, and decide. The press records who buys, and who hesitates."
                action={
                  <button
                    type="button"
                    onClick={() => void handleRunSim()}
                    disabled={!hwId || runningSim}
                    className="flex items-center gap-2 bg-[var(--ink)] px-4 py-2.5 text-[11px] font-medium uppercase tracking-[0.22em] text-[var(--paper)] transition-all hover:bg-[var(--red)] disabled:opacity-40"
                  >
                    {runningSim ? (
                      <>
                        <Loader2 size={12} className="animate-spin" /> Queuing…
                      </>
                    ) : (
                      <>
                        <Play size={12} /> Run simulation
                      </>
                    )}
                  </button>
                }
              />

              {hasSimulation ? (
                <>
                  <div className="grid grid-cols-1 gap-px bg-[var(--border-color)] sm:grid-cols-3">
                    {(
                      [
                        {
                          label: 'Overall conversion',
                          value: `${((Number(simData?.overall_conversion_rate) || 0) * 100).toFixed(1)}%`,
                          tone: 'workshop' as const,
                        },
                        {
                          label: 'Total agents',
                          value: (Number(simData?.agent_count ?? simData?.total_agents) || 0).toLocaleString('en-IN'),
                          tone: 'ink' as const,
                        },
                        {
                          label: 'Prototype wired',
                          value: simData?.prototype_wired ? 'Yes' : 'No',
                          tone: 'workshop' as const,
                        },
                      ] as const
                    ).map((k) => (
                      <Stat key={k.label} label={k.label} value={k.value} tone={k.tone} />
                    ))}
                  </div>

                  {Object.keys(simClusters).length > 0 && simFindings.length > 0 ? (
                    <KeyPersonReport
                      findings={simFindings}
                      clusterBreakdown={simClusters}
                      primaryFailure={String(simData?.primary_failure_domain ?? 'unknown')}
                    />
                  ) : (
                    <EmptySection
                      title="The room is still arriving."
                      body="Cluster results and findings populate moments after the run completes — check back when both are filed."
                    />
                  )}
                </>
              ) : (
                <EmptySection
                  title="No simulation on file."
                  body="Run physics first, then put the prototype in front of the room."
                />
              )}
            </motion.div>
          )}

          {activeTab === 'competitive' && (
            <motion.div
              key="competitive"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="space-y-7 px-10 py-9"
            >
              <SectionHead
                kicker="Section V · Position"
                title="Where this lands on the shelf."
                description="Price band, differentiation score, the whitespace nobody owns yet — distilled from the simulated room."
                action={
                  hwId ? (
                    <button
                      type="button"
                      onClick={() => runCompetitiveMutation.mutate()}
                      disabled={runCompetitiveMutation.isPending}
                      className="flex items-center gap-2 bg-[var(--ink)] px-4 py-2.5 text-[11px] font-medium uppercase tracking-[0.22em] text-[var(--paper)] transition-all hover:bg-[var(--red)] disabled:opacity-40"
                    >
                      {runCompetitiveMutation.isPending ? (
                        <>
                          <Loader2 size={12} className="animate-spin" /> Running…
                        </>
                      ) : (
                        <>Run analysis</>
                      )}
                    </button>
                  ) : null
                }
              />

              {compDisplay?.price_position ? (
                <>
                  <div className="grid grid-cols-1 gap-px bg-[var(--border-color)] sm:grid-cols-3">
                    {(
                      [
                        { label: 'Price position', value: String(compDisplay.price_position), tone: 'ink' as const },
                        {
                          label: 'Differentiation',
                          value: `${((compDisplay.overall_differentiation ?? 0) * 100).toFixed(0)}%`,
                          tone: 'workshop' as const,
                        },
                        {
                          label: 'Whitespace clusters',
                          value: String(compDisplay.whitespace_clusters?.length ?? 0),
                          tone: 'ink' as const,
                        },
                      ] as const
                    ).map((k) => (
                      <Stat key={k.label} label={k.label} value={k.value} tone={k.tone} />
                    ))}
                  </div>

                  <div className="border border-[var(--workshop)]/30 bg-[var(--workshop-dim)] p-6">
                    <p className="kicker mb-2" style={{ color: 'var(--workshop)' }}>
                      Recommended positioning
                    </p>
                    <p
                      className="font-serif italic leading-snug text-[var(--ink)]"
                      style={{ fontSize: 22, fontWeight: 700, letterSpacing: '-0.015em' }}
                    >
                      &ldquo;{compDisplay.recommended_positioning}&rdquo;
                    </p>
                  </div>

                  <div className="grid grid-cols-1 gap-px border border-[var(--border-color)] bg-[var(--border-color)] md:grid-cols-2">
                    <div className="space-y-2 bg-[var(--paper)] p-5">
                      <p className="kicker" style={{ color: 'var(--red)' }}>
                        Top threats
                      </p>
                      {compDisplay.top_threats?.map((t, i) => (
                        <p key={i} className="font-serif text-sm italic text-[var(--ink-secondary)]">
                          → {t}
                        </p>
                      ))}
                    </div>
                    <div className="space-y-2 bg-[var(--paper)] p-5">
                      <p className="kicker" style={{ color: 'var(--workshop)' }}>
                        Opportunities
                      </p>
                      {compDisplay.top_opportunities?.map((o, i) => (
                        <p key={i} className="font-serif text-sm italic text-[var(--ink-secondary)]">
                          → {o}
                        </p>
                      ))}
                    </div>
                  </div>
                </>
              ) : (
                <EmptySection
                  title="No analysis filed."
                  body={
                    <>
                      Run consumer simulation first, then press{' '}
                      <span className="font-medium text-[var(--red)]">Run analysis</span> to derive
                      positioning, threats, and opportunities.
                    </>
                  }
                  footer={
                    runCompetitiveMutation.isError ? (
                      <p className="font-mono text-xs text-red-700">
                        {(runCompetitiveMutation.error as Error).message}
                      </p>
                    ) : null
                  }
                />
              )}
            </motion.div>
          )}

          {activeTab === 'report' && (
            <motion.div
              key="report"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="px-10 py-12"
            >
              <div className="mx-auto grid max-w-5xl grid-cols-1 gap-12 md:grid-cols-[1fr_320px]">
                <div>
                  <p className="kicker" style={{ color: 'var(--red)' }}>
                    Section VI · Filed PDF
                  </p>
                  <h2
                    className="mt-3 font-serif italic leading-[0.96] tracking-tight text-[var(--ink)]"
                    style={{ fontSize: 'clamp(36px, 4vw, 52px)', fontWeight: 900, letterSpacing: '-0.03em' }}
                  >
                    The whole <span style={{ color: 'var(--red)' }}>folio</span>, in one envelope.
                  </h2>
                  <p className="lead-para mt-5">
                    Seven sections, one filed envelope: viability verdict, key-person report,
                    physics, manufacturing cost, the room&rsquo;s 52-cluster behaviour, competitive
                    positioning, and a ranked list of next moves.
                  </p>

                  <div className="mt-8 flex items-center gap-4">
                    {hwId ? (
                      <button
                        type="button"
                        onClick={() => void downloadPdf()}
                        disabled={pdfBusy}
                        className="flex items-center gap-3 bg-[var(--ink)] px-7 py-4 text-[11px] font-medium uppercase tracking-[0.24em] text-[var(--paper)] transition-all hover:bg-[var(--red)] disabled:opacity-50"
                      >
                        {pdfBusy ? (
                          <>
                            <Loader2 size={14} className="animate-spin" /> Preparing…
                          </>
                        ) : (
                          <>
                            <Download size={14} />
                            Download the folio
                          </>
                        )}
                      </button>
                    ) : (
                      <p className="text-sm italic text-[var(--ink-tertiary)]">
                        Generate a hardware spec first to unlock the report.
                      </p>
                    )}
                  </div>
                </div>

                <aside className="border border-[var(--border-color)] bg-[var(--paper)]/90">
                  <div className="border-b border-[var(--border-color)] px-5 py-3">
                    <p className="kicker" style={{ color: 'var(--ink-secondary)' }}>
                      Contents
                    </p>
                  </div>
                  <ol className="divide-y divide-[var(--border-color)]">
                    {[
                      'Executive summary',
                      'Key-person report',
                      'Physics test results',
                      'Manufacturing cost & BOM',
                      '52-cluster behaviour',
                      'Competitive positioning',
                      'Recommended actions',
                    ].map((s, i) => (
                      <li
                        key={s}
                        className="flex items-baseline gap-4 px-5 py-3.5 text-[13px] text-[var(--ink)]"
                      >
                        <span className="font-serif text-xs italic text-[var(--red)]" style={{ minWidth: 22 }}>
                          {ROMAN[i]}.
                        </span>
                        <span>{s}</span>
                      </li>
                    ))}
                  </ol>
                </aside>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {isMobile && (
        <nav className="safe-area-inset-bottom fixed right-0 bottom-0 left-0 z-50 flex items-center justify-around border-t border-[var(--border-color)] bg-[var(--paper)]/95 px-2 py-2 backdrop-blur-sm">
          {TABS.map((t) => {
            const Icon = t.Icon
            const active = activeTab === t.key
            return (
              <button
                key={t.key}
                type="button"
                onClick={() => setActiveTab(t.key)}
                className={`flex flex-1 flex-col items-center gap-0.5 px-2 py-1.5 transition-all ${
                  active ? 'text-[var(--red)]' : 'text-[var(--ink-tertiary)]'
                }`}
              >
                <Icon size={14} />
                <span className="text-[10px] uppercase tracking-[0.16em]">{t.label}</span>
              </button>
            )
          })}
        </nav>
      )}
    </div>
  )
}

/* ── Editorial atoms ──────────────────────────────────────────────── */

function Field({
  label,
  numeral,
  children,
}: {
  label: string
  numeral: string
  children: React.ReactNode
}) {
  return (
    <div>
      <div className="mb-1 flex items-baseline gap-2">
        <span className="font-serif text-[11px] italic text-[var(--red)]">{numeral}</span>
        <label className="text-[10px] font-medium uppercase tracking-[0.22em] text-[var(--ink-tertiary)]">
          {label}
        </label>
      </div>
      {children}
    </div>
  )
}

function SectionHead({
  kicker,
  title,
  description,
  action,
}: {
  kicker: string
  title: string
  description: string
  action?: React.ReactNode
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-6 border-b border-[var(--border-color)] pb-5">
      <div className="max-w-3xl">
        <p className="kicker" style={{ color: 'var(--red)' }}>
          {kicker}
        </p>
        <h2
          className="mt-2 font-serif italic leading-tight tracking-tight text-[var(--ink)]"
          style={{ fontSize: 28, fontWeight: 800, letterSpacing: '-0.02em' }}
        >
          {title}
        </h2>
        <p className="mt-2 max-w-[60ch] text-[13px] leading-relaxed text-[var(--ink-secondary)]">
          {description}
        </p>
      </div>
      {action}
    </div>
  )
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string
  value: string | number
  tone: 'ink' | 'workshop' | 'green' | 'red'
}) {
  const color =
    tone === 'workshop'
      ? 'text-[var(--workshop)]'
      : tone === 'green'
        ? 'text-emerald-800'
        : tone === 'red'
          ? 'text-red-800'
          : 'text-[var(--ink)]'
  return (
    <div className="bg-[var(--paper)] p-5">
      <p className="kicker mb-2" style={{ color: 'var(--ink-tertiary)' }}>
        {label}
      </p>
      <p
        className={`font-serif italic ${color}`}
        style={{ fontSize: 26, fontWeight: 800, letterSpacing: '-0.02em' }}
      >
        {value}
      </p>
    </div>
  )
}

function EmptySection({
  title,
  body,
  action,
  footer,
}: {
  title: string
  body: React.ReactNode
  action?: React.ReactNode
  footer?: React.ReactNode
}) {
  return (
    <div className="border border-dashed border-[var(--border-color)] bg-[var(--paper)]/60 px-8 py-14 text-center">
      <p className="kicker" style={{ color: 'var(--ink-tertiary)' }}>
        Standing type
      </p>
      <h3
        className="mt-3 font-serif italic text-[var(--ink)]"
        style={{ fontSize: 22, fontWeight: 700, letterSpacing: '-0.015em' }}
      >
        {title}
      </h3>
      <p className="mx-auto mt-2 max-w-[52ch] text-sm leading-relaxed text-[var(--ink-secondary)]">
        {body}
      </p>
      {action ? <div className="mt-5 flex justify-center">{action}</div> : null}
      {footer ? <div className="mt-3">{footer}</div> : null}
    </div>
  )
}
