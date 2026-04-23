'use client'

import type { MouseEvent } from 'react'
import Link from 'next/link'
import { useParams, useRouter } from 'next/navigation'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AnimatePresence, motion } from 'framer-motion'

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
    typeof raw.margin_pct === 'number'
      ? raw.margin_pct
      : Number(raw.margin_pct ?? 0)
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

// ── Editorial “blueprint” field — warm paper, steel rule, no dark-lab chrome ──
function EditorialBlueprintGrid() {
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden">
      <div
        className="absolute inset-0"
        style={{
          backgroundImage: `radial-gradient(circle at 1px 1px, rgba(45, 69, 86, 0.1) 1px, transparent 0)`,
          backgroundSize: '22px 22px',
        }}
      />
      <div
        className="absolute inset-0 opacity-50"
        style={{
          backgroundImage: `
            linear-gradient(105deg, transparent 48.5%, rgba(45, 69, 86, 0.04) 49.5%, rgba(45, 69, 86, 0.04) 50.5%, transparent 51.5%),
            linear-gradient(-15deg, transparent 48.5%, rgba(45, 69, 86, 0.03) 49.5%, rgba(45, 69, 86, 0.03) 50.5%, transparent 51.5%)
          `,
          backgroundSize: '72px 72px, 96px 96px',
        }}
      />
      <div
        className="absolute inset-0"
        style={{
          background:
            'radial-gradient(ellipse 75% 60% at 50% 48%, rgba(242, 236, 224, 0.9) 0%, transparent 62%)',
        }}
      />
    </div>
  )
}

// ── 3D Product Spec Viewer ──
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
      className="relative flex min-h-96 flex-1 select-none flex-col items-center justify-center"
      style={{ perspective: '900px' }}
      onMouseMove={onMouseMove}
      onMouseUp={onMouseUp}
      onMouseLeave={onMouseUp}
    >
      <EditorialBlueprintGrid />

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
        <svg viewBox="0 0 360 280" width={420} xmlns="http://www.w3.org/2000/svg" className="max-w-full">
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

      <p className="relative z-10 mt-3 text-xs text-[var(--ink-tertiary)]" style={{ letterSpacing: '0.12em' }}>
        drag to rotate · double-click to reset
      </p>

      <div className="relative z-10 mt-2 flex items-center gap-2">
        <div className="h-2 w-2 rounded-full bg-[var(--workshop)]" />
        <span className="text-xs text-[var(--ink-secondary)]">
          {material} · {components.length} components
          {hwProduct?.name ? ` · ${hwProduct.name}` : ''}
        </span>
      </div>
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

  const TABS: { key: Tab; label: string }[] = [
    { key: 'spec', label: 'Spec' },
    { key: 'tests', label: 'Tests' },
    { key: 'cost', label: 'Cost' },
    { key: 'simulation', label: 'Simulation' },
    { key: 'competitive', label: 'Competitive' },
    { key: 'report', label: 'Report' },
  ]

  const verdictColor = (v: string) =>
    v === 'VIABLE'
      ? 'text-emerald-900 border-emerald-600/35'
      : v === 'MARGINAL'
        ? 'text-amber-900 border-amber-700/35'
        : v === 'NOT_VIABLE'
          ? 'text-red-900 border-red-600/40'
          : 'text-[var(--ink-tertiary)] border-[var(--border-color)]'

  const verdictBorderBg = (v: string) =>
    v === 'VIABLE'
      ? 'border-emerald-600/25 bg-emerald-500/[0.07]'
      : v === 'MARGINAL'
        ? 'border-amber-700/25 bg-amber-500/[0.08]'
        : 'border-red-600/25 bg-red-500/[0.06]'

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

  return (
    <div className="hw-workshop min-h-screen bg-[var(--paper)] text-[var(--ink)]">
      {/* ── HEADER — workshop masthead, not devtools chrome ── */}
      <div
        className="relative z-20 flex items-center justify-between border-b border-[var(--border-color)] px-8 py-6"
        style={{
          background: 'linear-gradient(180deg, #faf7f0 0%, var(--paper) 100%)',
        }}
      >
        <div className="flex flex-wrap items-end gap-5">
          <div>
            <p
              className="kicker mb-1"
              style={{ color: 'var(--workshop)', letterSpacing: '0.2em' }}
            >
              TheCee / Workshop
            </p>
            <h1 className="font-serif text-2xl font-bold italic leading-tight tracking-tight text-[var(--ink)]">
              {selectedHw?.name ?? 'Hardware atelier'}
            </h1>
            <p className="mt-1 max-w-xl text-xs text-[var(--ink-tertiary)]" style={{ letterSpacing: '0.06em' }}>
              Blueprint, physics, and margin — filed like the rest of the magazine.
            </p>
          </div>
          {hwList.length > 1 ? (
            <label className="text-[10px] uppercase tracking-[0.16em] text-[var(--ink-tertiary)]">
              Product
              <select
                value={hwId ?? ''}
                onChange={(e) => setSelectedHwId(Number(e.target.value))}
                className="ml-2 rounded border border-[var(--border-strong)] bg-white/80 px-2.5 py-1.5 text-xs text-[var(--ink)] shadow-sm"
              >
                {hwList.map((h) => (
                  <option key={h.id} value={h.id}>
                    {h.name}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          <Link
            href={`/project/${projectId}`}
            className="rounded border border-[var(--border-strong)] bg-white/50 px-3.5 py-1.5 text-[10px] font-medium uppercase tracking-[0.18em] text-[var(--ink-secondary)] transition-all hover:border-[var(--ink)] hover:text-[var(--red)]"
          >
            ← Dossier
          </Link>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {selectedHw ? (
            <span
              className="rounded border border-[var(--workshop)]/35 bg-[var(--workshop-dim)] px-3 py-1.5 text-[10px] font-medium uppercase tracking-[0.16em] text-[var(--workshop)]"
            >
              {(selectedHw.category ?? 'hardware').replace(/_/g, ' ')}
            </span>
          ) : null}
          {headerCostVerdict && headerCostVerdict !== '—' ? (
            <span
              className={`rounded border px-3 py-1.5 text-[10px] font-medium uppercase tracking-[0.16em] ${verdictColor(headerCostVerdict)}`}
            >
              {headerCostVerdict}
            </span>
          ) : null}
        </div>
      </div>

      {/* ── TABS — desktop: top bar ── */}
      {!isMobile && (
        <div className="relative z-20 flex gap-1 border-b border-[var(--border-color)] bg-[var(--paper-dark)]/40 px-8 backdrop-blur-sm">
          {TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              onClick={() => setActiveTab(t.key)}
              className={`px-4 py-3.5 text-xs uppercase tracking-[0.2em] transition-all ${
                activeTab === t.key
                  ? 'border-b-2 border-[var(--red)] text-[var(--ink)]'
                  : 'text-[var(--ink-tertiary)] hover:text-[var(--ink-secondary)]'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      )}

      {/* ── CONTENT ── */}
      <div className={`relative ${isMobile ? 'pb-24' : ''}`}>
        <AnimatePresence mode="wait">
          {activeTab === 'spec' && (
            <motion.div
              key="spec"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="flex h-[calc(100vh-130px)]"
            >
              <div className="relative z-10 flex w-80 flex-col border-r border-[var(--border-color)] bg-[var(--paper)]/95 backdrop-blur-sm">
                <div className="flex-1 space-y-4 overflow-y-auto p-6">
                  <p className="text-xs tracking-widest text-[var(--ink-tertiary)] uppercase">Hardware Configuration</p>

                  {(
                    [
                      { label: 'Product Name', key: 'name' as const, type: 'text', placeholder: 'e.g. SmartWatch Pro' },
                      {
                        label: 'Target Price (₹)',
                        key: 'target_price_inr' as const,
                        type: 'number',
                        placeholder: 'e.g. 4999',
                      },
                    ] as const
                  ).map((field) => (
                    <div key={field.key}>
                      <label className="mb-1.5 block text-xs tracking-widest text-[var(--ink-tertiary)] uppercase">
                        {field.label}
                      </label>
                      <input
                        type={field.type}
                        placeholder={field.placeholder}
                        value={field.key === 'target_price_inr' ? genForm.target_price_inr : genForm[field.key]}
                        onChange={(e) =>
                          setGenForm((f) => ({
                            ...f,
                            [field.key]:
                              field.key === 'target_price_inr' ? Number(e.target.value) || 0 : e.target.value,
                          }))
                        }
                        className="w-full rounded border border-[var(--border-color)] bg-white/90 px-3 py-2 font-mono text-sm text-[var(--ink)] placeholder-[var(--ink-tertiary)] focus:border-[var(--workshop)] focus:outline-none"
                      />
                    </div>
                  ))}

                  <div>
                    <label className="mb-1.5 block text-xs tracking-widest text-[var(--ink-tertiary)] uppercase">Category</label>
                    <select
                      value={genForm.category}
                      onChange={(e) =>
                        setGenForm((f) => ({
                          ...f,
                          category: e.target.value,
                          product_type: e.target.value,
                        }))
                      }
                      className="w-full rounded border border-[var(--border-color)] bg-white/90 px-3 py-2 font-mono text-sm text-[var(--ink)] focus:border-[var(--workshop)] focus:outline-none"
                    >
                      {CATEGORIES.map((c) => (
                        <option key={c.value} value={c.value}>
                          {c.label}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div>
                    <label className="mb-1.5 block text-xs tracking-widest text-[var(--ink-tertiary)] uppercase">
                      Description
                    </label>
                    <textarea
                      rows={4}
                      placeholder="Describe materials, key features, form factor..."
                      value={genForm.description}
                      onChange={(e) => setGenForm((f) => ({ ...f, description: e.target.value }))}
                      className="w-full resize-none rounded border border-[var(--border-color)] bg-white/90 px-3 py-2 font-mono text-sm text-[var(--ink)] placeholder-[var(--ink-tertiary)] focus:border-[var(--workshop)] focus:outline-none"
                    />
                  </div>
                </div>

                <div className="space-y-2 border-t border-[var(--border-color)] p-6">
                  <button
                    type="button"
                    onClick={() => void handleGenerate()}
                    disabled={!genForm.name || !genForm.description || generating}
                    className="w-full rounded bg-[var(--ink)] py-3 text-sm font-bold tracking-widest text-[var(--paper)] uppercase transition-all hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    {generating ? (
                      <span className="flex items-center justify-center gap-2">
                        <span className="h-3 w-3 animate-spin rounded-full border-2 border-[var(--paper)] border-t-transparent" />
                        Generating Spec...
                      </span>
                    ) : (
                      'Generate Spec'
                    )}
                  </button>
                  {hwId ? (
                    <button
                      type="button"
                      onClick={() => void handleRunTests()}
                      disabled={runningTests}
                      className="w-full rounded border border-[var(--workshop)]/45 py-2.5 text-sm font-bold tracking-widest text-[var(--workshop)] uppercase transition-all hover:bg-[var(--workshop)] hover:text-[var(--paper)] disabled:opacity-40"
                    >
                      {runningTests ? 'Running Tests...' : '▶ Run Physics Tests'}
                    </button>
                  ) : null}
                </div>
              </div>

              {mergedSpec && Object.keys(mergedSpec).length > 0 ? (
                <SpecViewer spec={mergedSpec} hwProduct={selectedHw} />
              ) : (
                <div className="relative flex flex-1 flex-col items-center justify-center">
                  <EditorialBlueprintGrid />
                  <div className="relative z-10 space-y-3 text-center">
                    <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-2xl border border-[var(--border-color)] text-3xl">
                      ⬡
                    </div>
                    <p className="text-sm text-[var(--ink-tertiary)]">Configure your hardware and generate the spec</p>
                    <p className="text-xs text-[var(--ink-secondary)]">A 3D component diagram will appear here</p>
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
              className="space-y-6 p-8"
            >
              <div className="flex items-center justify-between">
                <p className="text-xs tracking-widest text-[var(--ink-tertiary)] uppercase">Physics Test Results</p>
                <button
                  type="button"
                  onClick={() => void handleRunTests()}
                  disabled={!hwId || runningTests}
                  className="rounded bg-[var(--ink)] px-4 py-2 text-xs font-bold tracking-widest text-[var(--paper)] uppercase transition-all hover:opacity-90 disabled:opacity-40"
                >
                  {runningTests ? 'Running...' : 'Re-run Tests'}
                </button>
              </div>

              {testResults.length > 0 ? (
                <>
                  <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                    {(
                      [
                        { label: 'Tests Run', value: testResultsPayload?.total_tests, color: undefined },
                        { label: 'Passed', value: testResultsPayload?.passed, color: 'text-green-400' },
                        { label: 'Failed', value: testResultsPayload?.failed, color: 'text-red-400' },
                        {
                          label: 'Pass Rate',
                          value: `${((testResultsPayload?.overall_pass_rate ?? 0) * 100).toFixed(0)}%`,
                          color: undefined,
                        },
                      ] as const
                    ).map((k) => (
                      <div key={k.label} className="rounded-xl border border-[var(--border-color)] bg-[var(--paper)]/90 p-4">
                        <p className="mb-1 text-xs tracking-widest text-[var(--ink-tertiary)] uppercase">{k.label}</p>
                        <p className={`text-2xl font-bold ${k.color ?? 'text-[var(--workshop)]'}`}>{k.value}</p>
                      </div>
                    ))}
                  </div>

                  <div className="space-y-3">
                    {testResults.map((r) => (
                      <div key={r.test_type} className="rounded-xl border border-[var(--border-color)] bg-[var(--paper-dark)]/35 p-5">
                        <div className="mb-3 flex items-center justify-between">
                          <div className="flex items-center gap-3">
                            <span className={`text-sm font-bold ${statusColor(r.status)}`}>
                              {r.status === 'PASS' ? '✓' : r.status === 'FAIL' ? '✗' : '~'}
                            </span>
                            <span className="text-sm text-[var(--ink)]">{r.test_type?.replace(/_/g, ' ')}</span>
                          </div>
                          <div className="flex items-center gap-3">
                            <div className="h-1.5 w-32 overflow-hidden rounded-full bg-[var(--border-color)]">
                              <div
                                className={`h-full rounded-full ${
                                  r.pass_rate > 0.7 ? 'bg-green-500' : r.pass_rate > 0.4 ? 'bg-amber-500' : 'bg-red-500'
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
                          <div className="space-y-1">
                            {r.failure_points.slice(0, 2).map((fp: FailurePoint, i: number) => (
                              <p key={i} className="font-mono text-xs text-red-400">
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
                <div className="py-20 text-center text-[var(--ink-tertiary)]">
                  <p className="text-sm">No test results yet.</p>
                  <p className="mt-1 text-xs">Generate a spec first, then run physics tests.</p>
                </div>
              )}
            </motion.div>
          )}

          {activeTab === 'cost' && (
            <motion.div
              key="cost"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="space-y-6 p-8"
            >
              <div className="flex items-center justify-between">
                <p className="text-xs tracking-widest text-[var(--ink-tertiary)] uppercase">Manufacturing Cost Analysis</p>
                {hwId ? (
                  <button
                    type="button"
                    onClick={() => runCostMutation.mutate()}
                    disabled={runCostMutation.isPending}
                    className="rounded border border-[var(--border-strong)] px-4 py-2 text-xs font-bold tracking-widest uppercase transition-all hover:border-[var(--ink)] hover:text-[var(--red)] disabled:opacity-40"
                  >
                    {runCostMutation.isPending ? 'Running…' : 'Re-run Analysis'}
                  </button>
                ) : null}
              </div>

              {costView.hasData ? (
                <>
                  <div className={`rounded-2xl border p-6 ${verdictBorderBg(costView.verdict)}`}>
                    <p className={`mb-1 text-lg font-bold ${verdictColor(costView.verdict).split(' ')[0]}`}>
                      {costView.verdict}
                    </p>
                    <p className="text-sm text-[var(--ink-secondary)]">{costView.verdict_reason}</p>
                  </div>

                  <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
                    {(
                      [
                        {
                          label: 'Landed Cost',
                          value: `₹${costView.landed_cost_inr.toLocaleString('en-IN')}`,
                        },
                        {
                          label: 'Target Price',
                          value: `₹${costView.target_price_inr.toLocaleString('en-IN')}`,
                        },
                        { label: 'Gross Margin', value: `${costView.margin_pct.toFixed(1)}%` },
                        {
                          label: 'Break-even',
                          value:
                            costView.break_even_moq != null
                              ? `${costView.break_even_moq.toLocaleString('en-IN')} units`
                              : '—',
                        },
                      ] as const
                    ).map((k) => (
                      <div key={k.label} className="rounded-xl border border-[var(--border-color)] bg-[var(--paper)]/90 p-4">
                        <p className="mb-1 text-xs tracking-widest text-[var(--ink-tertiary)] uppercase">{k.label}</p>
                        <p className="text-xl font-bold text-[var(--workshop)]">{k.value}</p>
                      </div>
                    ))}
                  </div>

                  {costView.bom.length > 0 ? (
                    <div>
                      <p className="mb-3 text-xs tracking-widest text-[var(--ink-tertiary)] uppercase">Bill of Materials</p>
                      <div className="table-mobile-scroll overflow-hidden rounded-xl border border-[var(--border-color)]">
                        <table className="w-full min-w-[500px] text-sm">
                          <thead>
                            <tr className="border-b border-[var(--border-color)] bg-white/90">
                              {(['Component', 'Material', 'Volume (cm³)', 'Unit Cost'] as const).map((h) => (
                                <th
                                  key={h}
                                  className="px-4 py-3 text-left text-xs font-normal tracking-widest text-[var(--ink-tertiary)] uppercase"
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
                                className="border-b border-[var(--border-color)] hover:bg-[var(--paper-dark)]/35"
                              >
                                <td className="px-4 py-3 text-[var(--ink)]">{String(item.component_name ?? '—')}</td>
                                <td className="px-4 py-3 text-[var(--ink-secondary)]">{String(item.material ?? '—')}</td>
                                <td className="px-4 py-3 font-mono text-[var(--ink-secondary)]">
                                  {item.volume_cm3 != null ? Number(item.volume_cm3).toFixed(1) : '—'}
                                </td>
                                <td className="px-4 py-3 font-mono text-[var(--workshop)]">
                                  ₹{Number(item.unit_cost_inr ?? 0).toFixed(2)}
                                </td>
                              </tr>
                            ))}
                            <tr className="bg-white/90">
                              <td colSpan={3} className="px-4 py-3 text-xs tracking-widest text-[var(--ink-tertiary)] uppercase">
                                Total BOM
                              </td>
                              <td className="px-4 py-3 font-mono font-bold text-[var(--workshop)]">
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
                <div className="py-20 text-center text-[var(--ink-tertiary)]">
                  <p className="text-sm">{costView.message ?? 'No cost analysis yet.'}</p>
                  {hwId ? (
                    <button
                      type="button"
                      onClick={() => runCostMutation.mutate()}
                      className="mt-3 rounded bg-[var(--ink)] px-4 py-2 text-xs text-[var(--paper)]"
                    >
                      Run Cost Analysis
                    </button>
                  ) : null}
                </div>
              )}
            </motion.div>
          )}

          {activeTab === 'simulation' && (
            <motion.div
              key="simulation"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="space-y-6 p-8"
            >
              <div className="flex items-center justify-between">
                <p className="text-xs tracking-widest text-[var(--ink-tertiary)] uppercase">Consumer Simulation — 52 Clusters</p>
                <button
                  type="button"
                  onClick={() => void handleRunSim()}
                  disabled={!hwId || runningSim}
                  className="rounded bg-[var(--ink)] px-4 py-2 text-xs font-bold tracking-widest text-[var(--paper)] uppercase transition-all hover:opacity-90 disabled:opacity-40"
                >
                  {runningSim ? 'Queuing...' : '▶ Run Simulation'}
                </button>
              </div>

              {hasSimulation ? (
                <>
                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                    {(
                      [
                        {
                          label: 'Overall Conversion',
                          value: `${((Number(simData?.overall_conversion_rate) || 0) * 100).toFixed(1)}%`,
                        },
                        {
                          label: 'Total Agents',
                          value: (Number(simData?.agent_count ?? simData?.total_agents) || 0).toLocaleString('en-IN'),
                        },
                        {
                          label: 'Prototype Wired',
                          value: simData?.prototype_wired ? 'Yes' : 'No',
                        },
                      ] as const
                    ).map((k) => (
                      <div key={k.label} className="rounded-xl border border-[var(--border-color)] bg-[var(--paper)]/90 p-4">
                        <p className="mb-1 text-xs tracking-widest text-[var(--ink-tertiary)] uppercase">{k.label}</p>
                        <p className="text-2xl font-bold text-[var(--workshop)]">{k.value}</p>
                      </div>
                    ))}
                  </div>

                  {Object.keys(simClusters).length > 0 && simFindings.length > 0 ? (
                    <KeyPersonReport
                      findings={simFindings}
                      clusterBreakdown={simClusters}
                      primaryFailure={String(simData?.primary_failure_domain ?? 'unknown')}
                    />
                  ) : (
                    <p className="text-sm text-[var(--ink-tertiary)]">
                      Simulation is running or results are still sparse — check back when `cluster_results` and findings
                      are populated.
                    </p>
                  )}
                </>
              ) : (
                <div className="py-20 text-center text-[var(--ink-tertiary)]">
                  <p className="text-sm">No simulation run yet.</p>
                  <p className="mt-1 text-xs">Run physics tests first, then simulate consumer behaviour.</p>
                </div>
              )}
            </motion.div>
          )}

          {activeTab === 'competitive' && (
            <motion.div
              key="competitive"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="space-y-6 p-8"
            >
              <div className="flex items-center justify-between">
                <p className="text-xs tracking-widest text-[var(--ink-tertiary)] uppercase">Competitive Analysis</p>
                {hwId ? (
                  <button
                    type="button"
                    onClick={() => runCompetitiveMutation.mutate()}
                    disabled={runCompetitiveMutation.isPending}
                    className="rounded bg-[var(--ink)] px-4 py-2 text-xs font-bold tracking-widest text-[var(--paper)] uppercase transition-all hover:opacity-90 disabled:opacity-40"
                  >
                    {runCompetitiveMutation.isPending ? 'Running…' : 'Run Analysis'}
                  </button>
                ) : null}
              </div>

              {compDisplay?.price_position ? (
                <>
                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                    {(
                      [
                        { label: 'Price Position', value: compDisplay.price_position },
                        {
                          label: 'Differentiation Score',
                          value: `${((compDisplay.overall_differentiation ?? 0) * 100).toFixed(0)}%`,
                        },
                        {
                          label: 'Whitespace Clusters',
                          value: compDisplay.whitespace_clusters?.length ?? 0,
                        },
                      ] as const
                    ).map((k) => (
                      <div key={k.label} className="rounded-xl border border-[var(--border-color)] bg-[var(--paper)]/90 p-4">
                        <p className="mb-1 text-xs tracking-widest text-[var(--ink-tertiary)] uppercase">{k.label}</p>
                        <p className="text-xl font-bold text-[var(--workshop)]">{k.value}</p>
                      </div>
                    ))}
                  </div>

                  <div className="rounded-xl border border-[var(--workshop)]/25 bg-[var(--workshop-dim)] p-5">
                    <p className="kicker mb-2 text-[var(--workshop)]">Recommended Positioning</p>
                    <p className="text-sm text-[var(--ink)]">{compDisplay.recommended_positioning}</p>
                  </div>

                  <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                    <div className="space-y-2">
                      <p className="text-xs tracking-widest text-red-400 uppercase">Top Threats</p>
                      {compDisplay.top_threats?.map((t, i) => (
                        <p key={i} className="font-mono text-xs text-[var(--ink-secondary)]">
                          → {t}
                        </p>
                      ))}
                    </div>
                    <div className="space-y-2">
                      <p className="text-xs tracking-widest text-green-400 uppercase">Opportunities</p>
                      {compDisplay.top_opportunities?.map((o, i) => (
                        <p key={i} className="font-mono text-xs text-[var(--ink-secondary)]">
                          → {o}
                        </p>
                      ))}
                    </div>
                  </div>
                </>
              ) : (
                <div className="py-20 text-center text-[var(--ink-tertiary)]">
                  <p className="text-sm">
                    Run consumer simulation first, then press{' '}
                    <span className="font-medium text-[var(--red)]">Run Analysis</span> to
                    generate positioning, threats, and opportunities (results are returned from the POST endpoint).
                  </p>
                  {runCompetitiveMutation.isError ? (
                    <p className="mt-2 font-mono text-xs text-red-400">
                      {(runCompetitiveMutation.error as Error).message}
                    </p>
                  ) : null}
                </div>
              )}
            </motion.div>
          )}

          {activeTab === 'report' && (
            <motion.div
              key="report"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="p-8"
            >
              <div className="mx-auto max-w-lg space-y-8 pt-16 text-center">
                <div className="mx-auto flex h-20 w-20 items-center justify-center rounded-2xl border border-[var(--workshop)]/30 bg-[var(--workshop-dim)] text-4xl">
                  📋
                </div>
                <div>
                  <h2 className="mb-2 font-serif text-2xl font-bold italic text-[var(--ink)]">Hardware intelligence report</h2>
                  <p className="text-sm text-[var(--ink-tertiary)]">
                    7-section PDF covering product viability, physics tests, manufacturing cost, cluster behavioral
                    analysis, and competitive positioning.
                  </p>
                </div>
                {hwId ? (
                  <button
                    type="button"
                    onClick={() => void downloadPdf()}
                    disabled={pdfBusy}
                    className="inline-block rounded-xl bg-[var(--ink)] px-8 py-4 text-sm font-bold tracking-widest text-[var(--paper)] uppercase transition-all hover:opacity-90 disabled:opacity-50"
                  >
                    {pdfBusy ? 'Preparing…' : '↓ Download PDF Report'}
                  </button>
                ) : (
                  <p className="text-sm text-[var(--ink-tertiary)]">Generate a hardware spec first to unlock the report.</p>
                )}
                <div className="space-y-2 rounded-xl border border-[var(--border-color)] p-5 text-left">
                  {[
                    'Executive Summary — viability verdict',
                    'Key Person Report — blocker and champion personas',
                    'Physics Test Results — all 8 test types',
                    'Manufacturing Cost — BOM, margin, break-even',
                    'Cluster Behavioral Analysis — 52-segment breakdown',
                    'Competitive Analysis — positioning and displacement',
                    'Recommended Actions — ranked by impact',
                  ].map((s, i) => (
                    <p key={s} className="font-mono text-xs text-[var(--ink-secondary)]">
                      {i + 1}. {s}
                    </p>
                  ))}
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {isMobile && (
        <nav className="safe-area-inset-bottom fixed right-0 bottom-0 left-0 z-50 flex items-center justify-around border-t border-slate-800 bg-slate-950/95 px-2 py-2 backdrop-blur-sm">
          {TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              onClick={() => setActiveTab(t.key)}
              className={`flex flex-1 flex-col items-center gap-0.5 rounded-lg px-2 py-1.5 transition-all ${
                activeTab === t.key ? 'bg-blue-500/10 text-blue-400' : 'text-slate-600'
              }`}
            >
              <span className="text-xs tracking-wide">{t.label}</span>
            </button>
          ))}
        </nav>
      )}
    </div>
  )
}
