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
  Download,
  Hexagon,
  Loader2,
  Pencil,
  Play,
  RotateCcw,
  Sparkles,
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

const STEPS: Array<{ key: Tab; numeral: string; label: string; subline: string }> = [
  { key: 'spec', numeral: 'I', label: 'Geometry', subline: 'Define the solid' },
  { key: 'tests', numeral: 'II', label: 'Stress', subline: 'Prove the assembly' },
  { key: 'cost', numeral: 'III', label: 'Landed cost', subline: 'BOM to shelf' },
  { key: 'simulation', numeral: 'IV', label: 'Gauge room', subline: '52 cohorts' },
  { key: 'competitive', numeral: 'V', label: 'Shelf map', subline: 'Position & gap' },
  { key: 'report', numeral: 'VI', label: 'Release pack', subline: 'One PDF' },
]

const STEP_HERO: Record<Tab, { titleA: string; titleEm: string; titleB: string; sub: string }> = {
  spec: {
    titleA: 'Give the ',
    titleEm: 'object',
    titleB: ' a name and a spine.',
    sub: 'Four inputs — geometry, category, target price, intent. The model returns a spec you can rotate, measure, and hand to a toolmaker.',
  },
  tests: {
    titleA: 'Stress it ',
    titleEm: 'before',
    titleB: ' metal meets mold.',
    sub: 'Eight regimes across structure, thermal, RF, and supply. Failures pin to parts on the diagram so you know what to redesign.',
  },
  cost: {
    titleA: 'Know the ',
    titleEm: 'margin',
    titleB: ' before you cut steel.',
    sub: 'BOM, freight, duties, and yield — rolled into a landed number against your shelf price.',
  },
  simulation: {
    titleA: 'Let ',
    titleEm: 'fifty-two',
    titleB: ' reader clusters vote.',
    sub: 'Each cohort behaves differently on price, trust, and novelty. You see who converts and why — not a single average score.',
  },
  competitive: {
    titleA: 'See where you ',
    titleEm: 'sit',
    titleB: ' in the aisle.',
    sub: 'Whitespace, threats, and a positioning line you can actually ship — not generic SWOT filler.',
  },
  report: {
    titleA: 'One ',
    titleEm: 'release pack',
    titleB: ' for the room that funds you.',
    sub: 'Physics, cost, room behaviour, shelf story, and next moves — bound for investors or a CM.',
  },
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
function PaperField() {
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

// ── 3D Product Spec Viewer (SVG isometric) ────────────────────────────────
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
      className="relative flex h-full min-h-[520px] w-full select-none flex-col items-center justify-center"
      style={{ perspective: '900px' }}
      onMouseMove={onMouseMove}
      onMouseUp={onMouseUp}
      onMouseLeave={onMouseUp}
    >
      <PaperField />

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
        <svg viewBox="0 0 360 280" width={520} xmlns="http://www.w3.org/2000/svg" className="max-w-full">
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

      <div className="relative z-10 mt-6 flex items-center gap-4 text-[11px] text-[var(--ink-secondary)]">
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
        className="relative z-10 mt-3 flex items-center gap-1.5 text-[10px] uppercase tracking-[0.22em] text-[var(--ink-tertiary)] transition-colors hover:text-[var(--red)]"
      >
        <RotateCcw size={10} />
        drag · double-click to reset
      </button>
    </div>
  )
}

const CATEGORIES = [
  { value: 'consumer_hardware', label: 'Consumer hardware' },
  { value: 'health_hardware', label: 'Health hardware' },
  { value: 'wearable', label: 'Wearable' },
  { value: 'iot_hardware', label: 'IoT hardware' },
  { value: 'b2b_hardware', label: 'B2B hardware' },
] as const

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
  const [selectedHwId, setSelectedHwId] = useState<number | null>(null)
  const [generating, setGenerating] = useState(false)
  const [runningTests, setRunningTests] = useState(false)
  const [runningSim, setRunningSim] = useState(false)
  const [competitiveReport, setCompetitiveReport] = useState<CompetitiveReport | null>(null)
  const [pdfBusy, setPdfBusy] = useState(false)
  const [editingSpec, setEditingSpec] = useState(false)

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

  const hasPlate = Boolean(mergedSpec && Object.keys(mergedSpec).length > 0)

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
      setEditingSpec(false)
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

  const verdictTone = (v: string) =>
    v === 'VIABLE'
      ? 'text-emerald-800'
      : v === 'MARGINAL'
        ? 'text-amber-800'
        : v === 'NOT_VIABLE'
          ? 'text-red-800'
          : 'text-[var(--ink-tertiary)]'

  const verdictBg = (v: string) =>
    v === 'VIABLE'
      ? 'border-emerald-700/25 bg-emerald-500/[0.06]'
      : v === 'MARGINAL'
        ? 'border-amber-700/25 bg-amber-500/[0.07]'
        : 'border-red-700/25 bg-red-500/[0.06]'

  const statusColor = (s: string) =>
    s === 'PASS'
      ? 'text-emerald-800'
      : s === 'PARTIAL'
        ? 'text-amber-800'
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

  // ── Step navigation logic ────────────────────────────────────────────
  const stepIdx = STEPS.findIndex((s) => s.key === activeTab)
  const prevStep = STEPS[stepIdx - 1] ?? null
  const hero = STEP_HERO[activeTab]

  // The single dedicated forward CTA per step
  const primaryCta = (() => {
    if (activeTab === 'spec') {
      if (!hasPlate) return null // primary action lives in the build sheet (Generate build sheet)
      return { label: 'Run physics', icon: ArrowRight, onClick: () => setActiveTab('tests') }
    }
    if (activeTab === 'tests') {
      return testResults.length > 0
        ? { label: 'Land the price', icon: ArrowRight, onClick: () => setActiveTab('cost') }
        : { label: runningTests ? 'Running…' : 'Run physics', icon: Play, onClick: () => void handleRunTests(), disabled: !hwId || runningTests }
    }
    if (activeTab === 'cost') {
      return costView.hasData
        ? { label: 'Cast the room', icon: ArrowRight, onClick: () => setActiveTab('simulation') }
        : { label: runCostMutation.isPending ? 'Running…' : 'Run analysis', icon: Play, onClick: () => runCostMutation.mutate(), disabled: !hwId || runCostMutation.isPending }
    }
    if (activeTab === 'simulation') {
      return hasSimulation
        ? { label: 'Find the shelf', icon: ArrowRight, onClick: () => setActiveTab('competitive') }
        : { label: runningSim ? 'Queuing…' : 'Run simulation', icon: Play, onClick: () => void handleRunSim(), disabled: !hwId || runningSim }
    }
    if (activeTab === 'competitive') {
      return compDisplay?.price_position
        ? { label: 'Open release pack', icon: ArrowRight, onClick: () => setActiveTab('report') }
        : { label: runCompetitiveMutation.isPending ? 'Running…' : 'Run analysis', icon: Play, onClick: () => runCompetitiveMutation.mutate(), disabled: !hwId || runCompetitiveMutation.isPending }
    }
    return {
      label: pdfBusy ? 'Preparing…' : 'Download PDF',
      icon: Download,
      onClick: () => void downloadPdf(),
      disabled: !hwId || pdfBusy,
    }
  })()

  const showSpecForm = activeTab === 'spec' && (!hasPlate || editingSpec)

  return (
    <div className="hw-workshop relative min-h-screen text-[var(--ink)]">
      <div className="mx-auto w-full max-w-[1200px] px-8 pt-6 pb-32 lg:px-12">
        <div
          className="mt-3 h-px w-full opacity-70"
          style={{
            background:
              'linear-gradient(90deg, transparent, var(--workshop) 12%, var(--workshop) 88%, transparent)',
          }}
        />

        {/* ── HERO ──────────────────────────────────────────────────── */}
        <AnimatePresence mode="wait">
          <motion.header
            key={activeTab + '-hero'}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.25 }}
            className="mt-8"
          >
            <h1
              className="max-w-[22ch] font-serif italic text-[var(--ink)]"
              style={{
                fontSize: 'clamp(34px, 4.5vw, 56px)',
                fontWeight: 900,
                letterSpacing: '-0.032em',
                lineHeight: 1.02,
              }}
            >
              {hero.titleA}
              <span style={{ color: 'var(--red)' }}>{hero.titleEm}</span>
              {hero.titleB}
            </h1>
            <p className="mt-5 max-w-[56ch] text-[15px] font-light leading-[1.75] text-[var(--ink-secondary)]">
              {hero.sub}
            </p>
          </motion.header>
        </AnimatePresence>

        {/* ── DRAFTING CARD ─────────────────────────────────────────── */}
        <div className="relative mt-9">
          <div
            className="relative overflow-hidden border border-[var(--ink)]/18 bg-[color-mix(in_srgb,var(--paper)_92%,white)]"
            style={{
              boxShadow:
                '0 1px 0 rgba(45,69,86,0.06), 0 22px 48px -28px rgba(26,23,20,0.22), 10px 10px 0 rgba(45,69,86,0.04)',
            }}
          >
            {/* Card chrome — registration marks (drafting sheet, not OS window) */}
            <div className="flex flex-wrap items-center gap-3 border-b border-[var(--ink)]/12 bg-[color-mix(in_srgb,var(--paper-dark)_55%,transparent)] px-5 py-3.5">
              <div className="relative h-5 w-9 shrink-0 text-[var(--workshop)]" aria-hidden>
                <span className="absolute left-0 top-0 h-2 w-2 border-l border-t border-current opacity-55" />
                <span className="absolute right-0 top-0 h-2 w-2 border-r border-t border-current opacity-55" />
                <span className="absolute bottom-0 left-0 h-2 w-2 border-b border-l border-current opacity-55" />
                <span className="absolute bottom-0 right-0 h-2 w-2 border-b border-r border-current opacity-55" />
              </div>
              <span
                className="border border-[var(--workshop)]/25 bg-[var(--paper)] px-2.5 py-1 font-mono text-[10px] uppercase tracking-[0.16em] text-[var(--workshop)]"
                style={{ letterSpacing: '0.12em' }}
              >
                {STEPS[stepIdx].numeral} · {STEPS[stepIdx].label}
              </span>

              {/* Step-specific chrome row */}
              <div className="ml-auto flex flex-1 items-center justify-end gap-3">
                <CardChrome
                  step={activeTab}
                  selectedHw={selectedHw}
                  hwList={hwList}
                  onSelectHw={(id) => setSelectedHwId(id)}
                  hasPlate={hasPlate}
                  editing={editingSpec}
                  onToggleEdit={() => setEditingSpec((v) => !v)}
                  onRunTests={() => void handleRunTests()}
                  runningTests={runningTests}
                  onRerunCost={() => runCostMutation.mutate()}
                  costPending={runCostMutation.isPending}
                  onRunSim={() => void handleRunSim()}
                  runningSim={runningSim}
                  onRunCompetitive={() => runCompetitiveMutation.mutate()}
                  competitivePending={runCompetitiveMutation.isPending}
                />
              </div>
            </div>

            {/* Card body */}
            <AnimatePresence mode="wait">
              <motion.div
                key={activeTab + '-body'}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -4 }}
                transition={{ duration: 0.22 }}
                className="relative"
              >
                {/* SPEC */}
                {activeTab === 'spec' && (
                  <div className="relative">
                    {showSpecForm ? (
                      <PressDispatchForm
                        form={genForm}
                        onChange={setGenForm}
                        onSubmit={() => void handleGenerate()}
                        generating={generating}
                        canCancel={hasPlate}
                        onCancel={() => setEditingSpec(false)}
                      />
                    ) : hasPlate ? (
                      <div className="px-6 py-10">
                        <SpecViewer spec={mergedSpec} hwProduct={selectedHw} />
                      </div>
                    ) : (
                      <div className="relative flex min-h-[520px] flex-col items-center justify-center px-8 py-20">
                        <PaperField />
                        <div className="relative z-10 max-w-md text-center">
                          <p className="kicker mb-5" style={{ color: 'var(--red)' }}>
                            No solid on file · Geometry idle
                          </p>
                          <div className="mx-auto mb-7 flex h-24 w-24 items-center justify-center border-[0.5px] border-[var(--workshop)]/35 bg-[var(--paper)]">
                            <Hexagon size={42} className="text-[var(--workshop)]" strokeWidth={1.2} />
                          </div>
                          <h3
                            className="font-serif italic text-[var(--ink)]"
                            style={{ fontSize: 36, fontWeight: 900, letterSpacing: '-0.025em' }}
                          >
                            Awaiting <span style={{ color: 'var(--red)' }}>geometry</span>.
                          </h3>
                          <p className="mt-3 text-[14px] leading-relaxed text-[var(--ink-secondary)]">
                            When this bench is on Geometry without a saved solid, the build sheet
                            appears in this same frame. Complete it to generate the 3D plate,
                            dimensions, and part list.
                          </p>
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {/* TESTS */}
                {activeTab === 'tests' && (
                  <div className="px-8 py-10">
                    {testResults.length > 0 ? (
                      <>
                        <div className="grid grid-cols-2 gap-px border-[0.5px] border-[var(--border-color)] bg-[var(--border-color)] sm:grid-cols-4">
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

                        <div className="mt-6 space-y-3">
                          {testResults.map((r) => (
                            <div
                              key={r.test_type}
                              className="border-[0.5px] border-[var(--border-color)] bg-[var(--paper)]/85 p-5"
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
                          <div className="mt-6">
                            <HardwareFailureMap spec={hardwareSpec} testResults={testResults} />
                          </div>
                        ) : null}
                      </>
                    ) : (
                      <EmptyStage
                        kicker="No tests on file"
                        title="The room is quiet."
                        body="Use the bench control below to run eight load cases on the current solid."
                      />
                    )}
                  </div>
                )}

                {/* COST */}
                {activeTab === 'cost' && (
                  <div className="px-8 py-10">
                    {costView.hasData ? (
                      <>
                        <div className={`border-[0.5px] p-7 ${verdictBg(costView.verdict)}`}>
                          <p className="kicker mb-2" style={{ color: 'var(--ink-secondary)' }}>
                            Margin verdict
                          </p>
                          <p
                            className={`font-serif italic ${verdictTone(costView.verdict)}`}
                            style={{ fontSize: 44, fontWeight: 900, letterSpacing: '-0.02em', lineHeight: 1 }}
                          >
                            {costView.verdict.replace(/_/g, ' ')}
                          </p>
                          <p className="mt-3 max-w-[60ch] text-sm leading-relaxed text-[var(--ink-secondary)]">
                            {costView.verdict_reason}
                          </p>
                        </div>

                        <div className="mt-6 grid grid-cols-2 gap-px border-[0.5px] border-[var(--border-color)] bg-[var(--border-color)] lg:grid-cols-4">
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
                          <div className="mt-7">
                            <p className="kicker mb-3" style={{ color: 'var(--ink-secondary)' }}>
                              Bill of materials
                            </p>
                            <div className="table-mobile-scroll overflow-hidden border-[0.5px] border-[var(--border-color)] bg-[var(--paper)]/90">
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
                                  <tr className="bg-[var(--paper-dark)]/45">
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
                      <EmptyStage
                        kicker="No analysis on file"
                        title={costView.message ?? 'No verdict yet.'}
                        body="Run landed-cost analysis from the bench control below."
                      />
                    )}
                  </div>
                )}

                {/* SIMULATION */}
                {activeTab === 'simulation' && (
                  <div className="px-8 py-10">
                    {hasSimulation ? (
                      <>
                        <div className="grid grid-cols-1 gap-px border-[0.5px] border-[var(--border-color)] bg-[var(--border-color)] sm:grid-cols-3">
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

                        <div className="mt-7">
                          {Object.keys(simClusters).length > 0 && simFindings.length > 0 ? (
                            <KeyPersonReport
                              findings={simFindings}
                              clusterBreakdown={simClusters}
                              primaryFailure={String(simData?.primary_failure_domain ?? 'unknown')}
                            />
                          ) : (
                            <EmptyStage
                              kicker="Half-filed"
                              title="The room is still arriving."
                              body="Cluster results and findings populate moments after the run completes."
                            />
                          )}
                        </div>
                      </>
                    ) : (
                      <EmptyStage
                        kicker="No simulation on file"
                        title="An empty room awaits."
                        body="Queue the gauge-room run from the bench control — fifty-two cohorts evaluate the solid."
                      />
                    )}
                  </div>
                )}

                {/* COMPETITIVE */}
                {activeTab === 'competitive' && (
                  <div className="px-8 py-10">
                    {compDisplay?.price_position ? (
                      <>
                        <div className="grid grid-cols-1 gap-px border-[0.5px] border-[var(--border-color)] bg-[var(--border-color)] sm:grid-cols-3">
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

                        <div className="mt-6 border-[0.5px] border-[var(--workshop)]/30 bg-[var(--workshop-dim)] p-7">
                          <p className="kicker mb-2" style={{ color: 'var(--workshop)' }}>
                            Recommended positioning
                          </p>
                          <p
                            className="font-serif italic leading-snug text-[var(--ink)]"
                            style={{ fontSize: 26, fontWeight: 700, letterSpacing: '-0.015em' }}
                          >
                            &ldquo;{compDisplay.recommended_positioning}&rdquo;
                          </p>
                        </div>

                        <div className="mt-6 grid grid-cols-1 gap-px border-[0.5px] border-[var(--border-color)] bg-[var(--border-color)] md:grid-cols-2">
                          <div className="space-y-2 bg-[var(--paper)] p-6">
                            <p className="kicker" style={{ color: 'var(--red)' }}>
                              Top threats
                            </p>
                            {compDisplay.top_threats?.map((t, i) => (
                              <p key={i} className="font-serif text-sm italic text-[var(--ink-secondary)]">
                                → {t}
                              </p>
                            ))}
                          </div>
                          <div className="space-y-2 bg-[var(--paper)] p-6">
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
                      <EmptyStage
                        kicker="No analysis filed"
                        title="The shelf is unread."
                        body="Run shelf mapping from the bench control to derive positioning, threats, and whitespace."
                        footer={
                          runCompetitiveMutation.isError ? (
                            <p className="font-mono text-xs text-red-700">
                              {(runCompetitiveMutation.error as Error).message}
                            </p>
                          ) : null
                        }
                      />
                    )}
                  </div>
                )}

                {/* REPORT */}
                {activeTab === 'report' && (
                  <div className="grid grid-cols-1 gap-10 px-8 py-10 md:grid-cols-[1fr_320px]">
                    <div>
                      <p className="lead-para">
                        Seven sections, one filed envelope: viability verdict, key-person report,
                        physics, manufacturing cost, the room&rsquo;s 52-cluster behaviour,
                        competitive positioning, and a ranked list of next moves.
                      </p>
                      {!hwId ? (
                        <p className="mt-6 text-sm italic text-[var(--ink-tertiary)]">
                          Generate a hardware spec first to unlock the report.
                        </p>
                      ) : null}
                    </div>
                    <aside className="border-[0.5px] border-[var(--border-color)] bg-[var(--paper)]/90">
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
                            className="flex items-baseline gap-4 px-5 py-3 text-[13px] text-[var(--ink)]"
                          >
                            <span
                              className="font-serif text-xs italic text-[var(--red)]"
                              style={{ minWidth: 22 }}
                            >
                              {String(i + 1).padStart(2, '0')}.
                            </span>
                            <span>{s}</span>
                          </li>
                        ))}
                      </ol>
                    </aside>
                  </div>
                )}
              </motion.div>
            </AnimatePresence>
          </div>
        </div>
      </div>

      {/* ── Bench rail: back / quiet stage / forward only (no step picker) ── */}
      <nav
        className="fixed right-0 bottom-0 left-0 z-40 border-t border-[var(--ink)]/10 bg-[color-mix(in_srgb,var(--paper)_88%,var(--paper-dark))]/95 backdrop-blur-md"
        style={{ boxShadow: '0 -12px 40px -24px rgba(26,23,20,0.2)' }}
        aria-label="Bench navigation"
      >
        <div className="mx-auto flex w-full max-w-[1200px] flex-col items-stretch gap-3 px-6 py-3.5 sm:flex-row sm:items-center sm:justify-between sm:gap-8 lg:px-12">
          <div className="flex shrink-0 justify-start sm:min-w-[9rem]">
            {prevStep ? (
              <button
                type="button"
                onClick={() => setActiveTab(prevStep.key)}
                className="group text-left text-[11px] font-medium tracking-[0.06em] text-[var(--ink-secondary)] transition-colors hover:text-[var(--workshop)]"
              >
                <span className="inline-flex items-center gap-2">
                  <ArrowLeft size={12} className="opacity-70 transition-transform group-hover:-translate-x-0.5" />
                  <span>
                    <span className="block font-mono text-[9px] uppercase tracking-[0.2em] text-[var(--ink-tertiary)]">
                      Prior bench
                    </span>
                    {prevStep.label}
                  </span>
                </span>
              </button>
            ) : (
              <Link
                href={`/project/${projectId}`}
                className="group text-[11px] font-medium tracking-[0.06em] text-[var(--ink-secondary)] transition-colors hover:text-[var(--workshop)]"
              >
                <span className="inline-flex items-center gap-2">
                  <ArrowLeft size={12} className="opacity-70 transition-transform group-hover:-translate-x-0.5" />
                  Back to dossier
                </span>
              </Link>
            )}
          </div>

          <div
            className="flex min-w-0 flex-1 flex-col items-center justify-center gap-0.5 text-center"
            aria-live="polite"
          >
            <p className="font-mono text-[9px] uppercase tracking-[0.28em] text-[var(--ink-tertiary)]">
              {String(stepIdx + 1).padStart(2, '0')} / 06
            </p>
            <p className="font-serif text-[15px] italic leading-tight text-[var(--ink)]">
              {STEPS[stepIdx].numeral} — {STEPS[stepIdx].label}
            </p>
            <p className="max-w-[36ch] text-[10px] font-normal normal-case tracking-normal text-[var(--ink-tertiary)]">
              {STEPS[stepIdx].subline}
            </p>
          </div>

          <div className="flex min-h-[44px] shrink-0 items-center justify-end sm:min-w-[11rem]">
            {primaryCta ? (
              <button
                type="button"
                onClick={primaryCta.onClick}
                disabled={primaryCta.disabled}
                className="group inline-flex w-full items-center justify-center gap-2.5 border border-[var(--ink)] bg-[var(--ink)] px-5 py-2.5 text-[10px] font-medium uppercase tracking-[0.22em] text-[var(--paper)] transition-all hover:border-[var(--red)] hover:bg-[var(--red)] disabled:cursor-not-allowed disabled:opacity-40 sm:w-auto"
              >
                {primaryCta.icon === Play ? (
                  primaryCta.disabled ? (
                    <Loader2 size={12} className="animate-spin" />
                  ) : (
                    <Play size={12} />
                  )
                ) : null}
                {primaryCta.label}
                {primaryCta.icon === ArrowRight ? (
                  <ArrowRight size={12} className="transition-transform group-hover:translate-x-0.5" />
                ) : null}
                {primaryCta.icon === Download ? <Download size={12} /> : null}
              </button>
            ) : null}
          </div>
        </div>
      </nav>
    </div>
  )
}

/* ── Card chrome row — step-specific controls ────────────────────────── */

function CardChrome({
  step,
  selectedHw,
  hwList,
  onSelectHw,
  hasPlate,
  editing,
  onToggleEdit,
  onRunTests,
  runningTests,
  onRerunCost,
  costPending,
  onRunSim,
  runningSim,
  onRunCompetitive,
  competitivePending,
}: {
  step: Tab
  selectedHw: HwListItem | null
  hwList: HwListItem[]
  onSelectHw: (id: number) => void
  hasPlate: boolean
  editing: boolean
  onToggleEdit: () => void
  onRunTests: () => void
  runningTests: boolean
  onRerunCost: () => void
  costPending: boolean
  onRunSim: () => void
  runningSim: boolean
  onRunCompetitive: () => void
  competitivePending: boolean
}) {
  if (step === 'spec') {
    if (!hasPlate) {
      return (
        <span className="max-w-[28ch] text-right font-mono text-[10px] leading-snug tracking-[0.04em] text-[var(--ink-tertiary)]">
          Build sheet open — four fields required before the model runs.
        </span>
      )
    }
    return (
      <>
        {hwList.length > 1 ? (
          <select
            value={selectedHw?.id ?? ''}
            onChange={(e) => onSelectHw(Number(e.target.value))}
            className="border-0 border-b border-[var(--ink)]/40 bg-transparent px-1 py-0.5 font-serif text-[13px] italic text-[var(--ink)] focus:border-[var(--red)] focus:outline-none"
          >
            {hwList.map((h) => (
              <option key={h.id} value={h.id}>
                {h.name}
              </option>
            ))}
          </select>
        ) : selectedHw ? (
          <span className="font-serif text-[13px] italic text-[var(--ink)]">{selectedHw.name}</span>
        ) : null}
        <button
          type="button"
          onClick={onToggleEdit}
          className="inline-flex items-center gap-1.5 border-[0.5px] border-[var(--ink)]/30 bg-[var(--paper)] px-2.5 py-1 text-[10px] uppercase tracking-[0.22em] text-[var(--ink-secondary)] transition-colors hover:border-[var(--ink)] hover:text-[var(--ink)]"
        >
          <Pencil size={10} />
          {editing ? 'Cancel' : 'Re-configure'}
        </button>
      </>
    )
  }
  if (step === 'tests') {
    return (
      <button
        type="button"
        onClick={onRunTests}
        disabled={runningTests}
        className="inline-flex items-center gap-2 border-[0.5px] border-[var(--ink)]/30 bg-[var(--paper)] px-3 py-1.5 text-[10px] uppercase tracking-[0.22em] text-[var(--ink-secondary)] transition-colors hover:border-[var(--ink)] hover:text-[var(--ink)] disabled:opacity-40"
      >
        {runningTests ? <Loader2 size={11} className="animate-spin" /> : <Play size={11} />}
        Re-run tests
      </button>
    )
  }
  if (step === 'cost') {
    return (
      <button
        type="button"
        onClick={onRerunCost}
        disabled={costPending}
        className="inline-flex items-center gap-2 border-[0.5px] border-[var(--ink)]/30 bg-[var(--paper)] px-3 py-1.5 text-[10px] uppercase tracking-[0.22em] text-[var(--ink-secondary)] transition-colors hover:border-[var(--ink)] hover:text-[var(--ink)] disabled:opacity-40"
      >
        {costPending ? <Loader2 size={11} className="animate-spin" /> : <RotateCcw size={11} />}
        Re-run analysis
      </button>
    )
  }
  if (step === 'simulation') {
    return (
      <button
        type="button"
        onClick={onRunSim}
        disabled={runningSim}
        className="inline-flex items-center gap-2 border-[0.5px] border-[var(--ink)]/30 bg-[var(--paper)] px-3 py-1.5 text-[10px] uppercase tracking-[0.22em] text-[var(--ink-secondary)] transition-colors hover:border-[var(--ink)] hover:text-[var(--ink)] disabled:opacity-40"
      >
        {runningSim ? <Loader2 size={11} className="animate-spin" /> : <RotateCcw size={11} />}
        Re-cast room
      </button>
    )
  }
  if (step === 'competitive') {
    return (
      <button
        type="button"
        onClick={onRunCompetitive}
        disabled={competitivePending}
        className="inline-flex items-center gap-2 border-[0.5px] border-[var(--ink)]/30 bg-[var(--paper)] px-3 py-1.5 text-[10px] uppercase tracking-[0.22em] text-[var(--ink-secondary)] transition-colors hover:border-[var(--ink)] hover:text-[var(--ink)] disabled:opacity-40"
      >
        {competitivePending ? <Loader2 size={11} className="animate-spin" /> : <RotateCcw size={11} />}
        Re-run analysis
      </button>
    )
  }
  return null
}

/* ── Build sheet (spec step — hardware intake, not “press” metaphor) ─── */

function BuildSheetDatumLine() {
  return (
    <div
      className="mt-7 h-px w-full max-w-xl opacity-50"
      style={{
        backgroundImage:
          'repeating-linear-gradient(90deg, var(--workshop) 0, var(--workshop) 1px, transparent 1px, transparent 10px)',
      }}
      aria-hidden
    />
  )
}

function PressDispatchForm({
  form,
  onChange,
  onSubmit,
  generating,
  canCancel,
  onCancel,
}: {
  form: { name: string; description: string; category: string; target_price_inr: number; product_type: string }
  onChange: React.Dispatch<
    React.SetStateAction<{
      name: string
      description: string
      category: string
      target_price_inr: number
      product_type: string
    }>
  >
  onSubmit: () => void
  generating: boolean
  canCancel: boolean
  onCancel: () => void
}) {
  const canSubmit = form.name.trim() && form.description.trim() && !generating
  return (
    <div className="relative">
      <PaperField />
      <div className="relative z-10 mx-auto max-w-3xl px-8 py-12">
        <p className="font-mono text-[10px] uppercase tracking-[0.22em]" style={{ color: 'var(--workshop)' }}>
          Build specification · intake
        </p>
        <h2
          className="mt-3 font-serif italic text-[var(--ink)]"
          style={{ fontSize: 34, fontWeight: 900, letterSpacing: '-0.028em', lineHeight: 1.05 }}
        >
          Name the <span style={{ color: 'var(--red)' }}>solid</span> you want to prove.
        </h2>
        <p className="mt-4 max-w-[52ch] text-[14px] font-light leading-relaxed text-[var(--ink-secondary)]">
          Identity, category, shelf price, and a short engineering note. The bench returns a
          dimensioned solid, a part tree, and a diagram you can interrogate — not a slide deck.
        </p>
        <BuildSheetDatumLine />

        <div className="mt-10 grid grid-cols-1 gap-8 sm:grid-cols-[2fr_1fr_1fr] sm:gap-6">
          <FormField label="i. Product name">
            <input
              type="text"
              placeholder="e.g. Daybreak SmartWatch"
              value={form.name}
              onChange={(e) => onChange((f) => ({ ...f, name: e.target.value }))}
              className="w-full border-0 border-b border-[var(--ink)]/35 bg-transparent px-0 py-2 font-serif text-[18px] italic text-[var(--ink)] placeholder-[var(--ink-tertiary)] focus:border-[var(--red)] focus:outline-none"
            />
          </FormField>
          <FormField label="ii. Category">
            <select
              value={form.category}
              onChange={(e) =>
                onChange((f) => ({ ...f, category: e.target.value, product_type: e.target.value }))
              }
              className="w-full border-0 border-b border-[var(--ink)]/35 bg-transparent px-0 py-2 font-serif text-[16px] italic text-[var(--ink)] focus:border-[var(--red)] focus:outline-none"
            >
              {CATEGORIES.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </select>
          </FormField>
          <FormField label="iii. Target price (₹)">
            <input
              type="number"
              placeholder="4999"
              value={form.target_price_inr}
              onChange={(e) =>
                onChange((f) => ({ ...f, target_price_inr: Number(e.target.value) || 0 }))
              }
              className="w-full border-0 border-b border-[var(--ink)]/35 bg-transparent px-0 py-2 font-mono text-[18px] text-[var(--ink)] placeholder-[var(--ink-tertiary)] focus:border-[var(--red)] focus:outline-none"
            />
          </FormField>
        </div>

        <div className="mt-8">
          <FormField label="iv. Engineering note">
            <textarea
              rows={4}
              placeholder="Materials, stack-up, ingress rating, radios — what a CM would need in the first call."
              value={form.description}
              onChange={(e) => onChange((f) => ({ ...f, description: e.target.value }))}
              className="w-full resize-none border-0 border-b border-[var(--ink)]/35 bg-transparent px-0 py-2 font-serif text-[16px] leading-relaxed italic text-[var(--ink)] placeholder-[var(--ink-tertiary)] focus:border-[var(--red)] focus:outline-none"
            />
          </FormField>
        </div>

        <div className="mt-10 flex flex-col gap-4 border-t border-[var(--ink)]/10 pt-8 sm:flex-row sm:items-end sm:justify-between">
          <p className="max-w-[40ch] text-[12px] font-light leading-relaxed text-[var(--ink-tertiary)]">
            Spec generation runs on the server; keep this tab open. You can iterate the note and
            re-issue without leaving the bench.
          </p>
          <div className="flex shrink-0 flex-wrap items-center justify-end gap-3">
            {canCancel ? (
              <button
                type="button"
                onClick={onCancel}
                className="border border-[var(--ink)]/25 bg-transparent px-4 py-2.5 text-[10px] uppercase tracking-[0.2em] text-[var(--ink-secondary)] transition-colors hover:border-[var(--ink)] hover:text-[var(--ink)]"
              >
                Cancel
              </button>
            ) : null}
            <button
              type="button"
              onClick={onSubmit}
              disabled={!canSubmit}
              className="group inline-flex items-center gap-2.5 border border-[var(--ink)] bg-[var(--ink)] px-6 py-2.5 text-[10px] font-medium uppercase tracking-[0.22em] text-[var(--paper)] transition-all hover:border-[var(--red)] hover:bg-[var(--red)] disabled:cursor-not-allowed disabled:opacity-40"
            >
              {generating ? (
                <>
                  <Loader2 size={13} className="animate-spin" />
                  Generating solid…
                </>
              ) : (
                <>
                  <Sparkles size={13} />
                  Generate build sheet
                  <ArrowRight size={13} className="transition-transform group-hover:translate-x-0.5" />
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

function FormField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="text-[10px] font-medium uppercase tracking-[0.22em] text-[var(--ink-tertiary)]">
        {label}
      </p>
      {children}
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
        style={{ fontSize: 28, fontWeight: 800, letterSpacing: '-0.02em' }}
      >
        {value}
      </p>
    </div>
  )
}

function EmptyStage({
  kicker,
  title,
  body,
  footer,
}: {
  kicker: string
  title: string
  body: React.ReactNode
  footer?: React.ReactNode
}) {
  return (
    <div className="relative flex min-h-[440px] flex-col items-center justify-center px-8 py-16 text-center">
      <PaperField />
      <div className="relative z-10 max-w-[44ch]">
        <p className="kicker mb-4" style={{ color: 'var(--ink-tertiary)' }}>
          {kicker}
        </p>
        <h3
          className="font-serif italic text-[var(--ink)]"
          style={{ fontSize: 32, fontWeight: 800, letterSpacing: '-0.02em', lineHeight: 1.05 }}
        >
          {title}
        </h3>
        <p className="mt-3 text-[14px] leading-relaxed text-[var(--ink-secondary)]">{body}</p>
        {footer ? <div className="mt-4">{footer}</div> : null}
      </div>
    </div>
  )
}
