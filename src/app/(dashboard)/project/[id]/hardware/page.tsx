'use client'

import type { Dispatch, ReactNode, SetStateAction } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, Loader2, Sparkles } from 'lucide-react'

import { TechnicalPlate } from '@/components/hardware/TechnicalPlate'
import { getApiV1Base } from '@/lib/api-v1-base'
import { useProject } from '@/hooks/useProjects'

function authHeaders(): HeadersInit {
  const token = typeof window !== 'undefined' ? localStorage.getItem('access_token') : null
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  }
}

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

  const [selectedHwId, setSelectedHwId] = useState<number | null>(null)
  const [generating, setGenerating] = useState(false)

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

  const mergedSpec = (() => {
    if (!specData) return {} as Record<string, unknown>
    return {
      ...(specData.spec ?? {}),
      render_hints: specData.render_hints,
    } as Record<string, unknown>
  })()

  const selectedHw = hwList.find((h) => h.id === hwId) ?? null

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
    } finally {
      setGenerating(false)
    }
  }

  const specProductName =
    (mergedSpec?.product_name as string | undefined) || specData?.name || selectedHw?.name
  const productNameForPlate = specProductName || project?.title || '—'
  const categoryForPlate =
    selectedHw?.category || genForm.category || project?.dossier_axis || '—'

  return (
    <div
      style={{
        display: 'flex',
        height: 'calc(100vh - 120px)',
        background: '#f5f0e8',
        overflow: 'hidden',
        marginLeft: 32,
      }}
    >
      <div
        style={{
          flex: '0 0 35%',
          minWidth: 280,
          maxWidth: '40%',
          overflowY: 'auto',
          borderRight: '1px solid rgba(45, 69, 86, 0.12)',
        }}
      >
        <PressDispatchForm
          form={genForm}
          onChange={setGenForm}
          onSubmit={() => void handleGenerate()}
          generating={generating}
          canCancel={false}
          onCancel={() => {}}
        />
      </div>

      <TechnicalPlate productName={productNameForPlate} category={categoryForPlate} />
    </div>
  )
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
  onChange: Dispatch<
    SetStateAction<{
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

function FormField({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <p className="text-[10px] font-medium uppercase tracking-[0.22em] text-[var(--ink-tertiary)]">
        {label}
      </p>
      {children}
    </div>
  )
}
