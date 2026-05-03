'use client'

import type { CSSProperties, Dispatch, FocusEvent, ReactNode, SetStateAction } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'

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

const inputStyle: CSSProperties = {
  width: '100%',
  background: '#f5f0e8',
  backgroundColor: '#f5f0e8',
  border: 'none',
  borderBottom: '1px solid #1a1a1a',
  fontFamily: 'Georgia, serif',
  fontStyle: 'italic',
  fontSize: 18,
  color: '#1a1a1a',
  padding: '12px 4px',
  outline: 'none',
  borderRadius: 0,
  transition: 'border-color 0.2s ease, background 0.2s ease, background-color 0.2s ease',
}

const SELECT_CHEVRON =
  "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath fill='%231a1a1a' d='M2.5 4.5L6 8l3.5-3.5z'/%3E%3C/svg%3E\")"

const selectStyle: CSSProperties = {
  ...inputStyle,
  cursor: 'pointer',
  appearance: 'none',
  WebkitAppearance: 'none',
  MozAppearance: 'none',
  backgroundColor: '#f5f0e8',
  backgroundImage: SELECT_CHEVRON,
  backgroundRepeat: 'no-repeat',
  backgroundPosition: 'right 6px center',
  paddingRight: 28,
}

/** Number inputs ignore `background` in some WebKit builds; reinforce + textfield chrome. */
const numberInputStyle: CSSProperties = {
  ...inputStyle,
  backgroundColor: '#f5f0e8',
  MozAppearance: 'textfield',
  WebkitAppearance: 'textfield',
}

const inputFocusHandlers = {
  onFocus: (e: FocusEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => {
    e.currentTarget.style.borderBottomColor = '#c0392b'
    if (e.currentTarget instanceof HTMLSelectElement || e.currentTarget instanceof HTMLInputElement) {
      e.currentTarget.style.backgroundColor = '#fff'
    } else {
      e.currentTarget.style.background = '#fff'
    }
  },
  onBlur: (e: FocusEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => {
    e.currentTarget.style.borderBottomColor = '#1a1a1a'
    if (e.currentTarget instanceof HTMLSelectElement || e.currentTarget instanceof HTMLInputElement) {
      e.currentTarget.style.backgroundColor = '#f5f0e8'
    } else {
      e.currentTarget.style.background = '#f5f0e8'
    }
  },
}

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
      }}
    >
      <PressDispatchForm
        form={genForm}
        onChange={setGenForm}
        onSubmit={() => void handleGenerate()}
        generating={generating}
      />

      <TechnicalPlate
        productName={productNameForPlate}
        category={categoryForPlate}
        hasSpec={!!specData}
        onBack={() => router.push(`/project/${projectId}`)}
        onRunPhysics={() => {}}
      />
    </div>
  )
}

function PressDispatchForm({
  form,
  onChange,
  onSubmit,
  generating,
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
}) {
  const canSubmit = form.name.trim() && form.description.trim() && !generating
  return (
    <div style={{
      width: '38%',
      minWidth: 460,
      padding: '56px 48px 96px 56px',
      background: '#f5f0e8',
      display: 'flex',
      flexDirection: 'column',
      gap: 32,
      overflowY: 'auto',
    }}>

      {/* HEADING */}
      <div>
        <div style={{
          fontFamily: "'Courier New', monospace",
          fontSize: 10,
          letterSpacing: '0.22em',
          color: '#c0392b',
          marginBottom: 16,
        }}>
          BUILD SPECIFICATION · INTAKE
        </div>
        <h1 style={{
          fontFamily: 'Georgia, serif',
          fontWeight: 700,
          fontSize: 42,
          lineHeight: 1.08,
          letterSpacing: '-0.02em',
          color: '#1a1a1a',
          margin: 0,
        }}>
          Name the{' '}
          <em style={{ color: '#c0392b', fontStyle: 'italic' }}>
            solid
          </em>{' '}
          you want to prove.
        </h1>
      </div>

      {/* FIELD: PRODUCT NAME */}
      <FormField label="I. PRODUCT NAME">
        <input
          type="text"
          placeholder="e.g. Daybreak SmartWatch"
          style={inputStyle}
          {...inputFocusHandlers}
          value={form.name}
          onChange={(e) => onChange((f) => ({ ...f, name: e.target.value }))}
        />
      </FormField>

      {/* TWO-COLUMN ROW: CATEGORY + PRICE */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: '1fr 1fr',
        gap: 20,
      }}>
        <FormField label="II. CATEGORY">
          <select
            style={selectStyle}
            {...inputFocusHandlers}
            value={form.category}
            onChange={(e) => onChange((f) => ({ ...f, category: e.target.value, product_type: e.target.value }))}
          >
            {CATEGORIES.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </select>
        </FormField>

        <FormField label="III. TARGET PRICE (₹)">
          <input
            type="number"
            style={numberInputStyle}
            {...inputFocusHandlers}
            value={form.target_price_inr}
            onChange={(e) => onChange((f) => ({ ...f, target_price_inr: Number(e.target.value) || 0 }))}
          />
        </FormField>
      </div>

      {/* FIELD: ENGINEERING NOTE */}
      <FormField label="IV. ENGINEERING NOTE">
        <textarea
          placeholder="Materials, stack-up, ingress rating, radios — what a CM would need in the first call."
          rows={4}
          style={{
            ...inputStyle,
            border: '0.5px solid #1a1a1a',
            borderBottom: '0.5px solid #1a1a1a',
            padding: '14px 16px',
            resize: 'none',
            minHeight: 110,
            fontSize: 15,
            lineHeight: 1.6,
            fontStyle: 'italic',
            background: '#f5f0e8',
          }}
          onFocus={(e) => {
            e.currentTarget.style.borderColor = '#c0392b'
            e.currentTarget.style.background = '#fff'
          }}
          onBlur={(e) => {
            e.currentTarget.style.borderColor = '#1a1a1a'
            e.currentTarget.style.background = '#f5f0e8'
          }}
          value={form.description}
          onChange={(e) => onChange((f) => ({ ...f, description: e.target.value }))}
        />
      </FormField>

      {/* HELP TEXT */}
      <div style={{
        fontFamily: 'Georgia, serif',
        fontSize: 13,
        fontStyle: 'italic',
        color: '#888',
        lineHeight: 1.6,
        paddingTop: 8,
        borderTop: '0.5px solid #c4bfb4',
      }}>
        Spec generation runs on the server; keep this
        tab open. You can iterate the note and re-issue
        without leaving the bench.
      </div>

      {/* GENERATE BUTTON */}
      <button
        type="button"
        className="hw-build-sheet-cta"
        disabled={!canSubmit || generating}
        aria-busy={generating}
        onClick={onSubmit}
        style={{
          position: 'relative',
          background:
            'linear-gradient(180deg, rgba(255,255,255,0.1) 0%, rgba(255,255,255,0) 42%), #c0392b',
          color: '#f5f0e8',
          border: '1px solid rgba(255,255,255,0.14)',
          padding: '18px 24px',
          fontFamily: "'Courier New', monospace",
          fontSize: 12,
          letterSpacing: '0.2em',
          fontWeight: 600,
          cursor: !canSubmit || generating ? 'not-allowed' : 'pointer',
          display: 'grid',
          gridTemplateColumns: 'minmax(0,1fr) auto minmax(0,1fr)',
          alignItems: 'center',
          columnGap: 12,
          width: '100%',
          borderRadius: 2,
          marginTop: 12,
          textTransform: 'uppercase',
          WebkitFontSmoothing: 'antialiased',
          boxShadow:
            'inset 0 1px 0 rgba(255,255,255,0.12), 0 1px 0 rgba(0,0,0,0.06), 0 10px 28px -6px rgba(192,57,43,0.45)',
          opacity: !canSubmit || generating ? 0.45 : 1,
          transition:
            'background 0.22s ease, border-color 0.22s ease, box-shadow 0.22s ease, transform 0.12s ease, opacity 0.2s ease',
        }}
        onMouseEnter={(e) => {
          if (!canSubmit || generating) return
          e.currentTarget.style.background =
            'linear-gradient(180deg, rgba(255,255,255,0.08) 0%, rgba(255,255,255,0) 45%), #1a1a1a'
          e.currentTarget.style.borderColor = 'rgba(255,255,255,0.12)'
          e.currentTarget.style.boxShadow =
            'inset 0 1px 0 rgba(255,255,255,0.06), 0 1px 0 rgba(0,0,0,0.12), 0 12px 32px -8px rgba(0,0,0,0.35)'
        }}
        onMouseLeave={(e) => {
          if (!canSubmit || generating) return
          e.currentTarget.style.background =
            'linear-gradient(180deg, rgba(255,255,255,0.1) 0%, rgba(255,255,255,0) 42%), #c0392b'
          e.currentTarget.style.borderColor = 'rgba(255,255,255,0.14)'
          e.currentTarget.style.boxShadow =
            'inset 0 1px 0 rgba(255,255,255,0.12), 0 1px 0 rgba(0,0,0,0.06), 0 10px 28px -6px rgba(192,57,43,0.45)'
        }}
      >
        <span
          style={{
            justifySelf: 'end',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: 22,
          }}
        >
          <span
            style={{
              display: 'block',
              width: 7,
              height: 7,
              borderRadius: '50%',
              background: '#f5f0e8',
              boxShadow: '0 0 0 1px rgba(26,26,26,0.12), inset 0 1px 0 rgba(255,255,255,0.35)',
            }}
          />
        </span>
        <span
          style={{
            textAlign: 'center',
            textShadow: '0 1px 0 rgba(0,0,0,0.12)',
            whiteSpace: 'nowrap',
          }}
        >
          {generating ? 'GENERATING SOLID…' : 'GENERATE BUILD SHEET'}
        </span>
        <span
          style={{
            justifySelf: 'start',
            fontSize: 15,
            lineHeight: 1,
            fontWeight: 500,
            opacity: 0.92,
            letterSpacing: '0.02em',
            textShadow: '0 1px 0 rgba(0,0,0,0.12)',
          }}
        >
          →
        </span>
      </button>

    </div>
  )
}

function FormField({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <label style={{
        fontFamily: "'Courier New', monospace",
        fontSize: 10,
        letterSpacing: '0.18em',
        color: '#1a1a1a',
        fontWeight: 500,
      }}>
        {label}
      </label>
      {children}
    </div>
  );
}
