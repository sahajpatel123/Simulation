'use client'

import { useRef, useState } from 'react'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AnimatePresence, motion } from 'framer-motion'

import UIBuilderConfigPanel from '@/components/ui-builder/UIBuilderConfigPanel'
import UIBuilderHistory from '@/components/ui-builder/UIBuilderHistory'
import UIBuilderPreview from '@/components/ui-builder/UIBuilderPreview'
import type {
  GeneratedUI,
  GeneratedUIHistoryResponse,
  UIGenerateRequest,
} from '@/components/ui-builder/types'
import { getApiV1Base } from '@/lib/api-v1-base'

function authHeaders(): HeadersInit {
  const token = typeof window !== 'undefined' ? localStorage.getItem('access_token') : null
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  }
}

export default function UIBuilderPage() {
  const params = useParams()
  const projectIdRaw = Array.isArray(params?.id) ? params?.id[0] : params?.id
  const projectId = Number(projectIdRaw)
  const qc = useQueryClient()

  const [prompt, setPrompt] = useState('')
  const [productType, setProductType] = useState('saas')
  const [pricePoint, setPricePoint] = useState('')
  const [targetDemo, setTargetDemo] = useState('')
  const [generatedUI, setGeneratedUI] = useState<GeneratedUI | null>(null)
  const [activeTab, setActiveTab] = useState<'builder' | 'history'>('builder')
  const [simStatus, setSimStatus] = useState<string | null>(null)
  const iframeRef = useRef<HTMLIFrameElement>(null)

  const generateMutation = useMutation({
    mutationFn: async (body: UIGenerateRequest) => {
      const res = await fetch(`${getApiV1Base()}/projects/${projectId}/generate-ui`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify(body),
      })
      if (!res.ok) throw new Error(await res.text())
      const data = (await res.json()) as GeneratedUI & { project_id?: number }
      return data
    },
    onSuccess: (data: GeneratedUI & { project_id?: number }) => {
      setGeneratedUI({
        ...data,
        product_type: data.product_type ?? productType,
      })
      void qc.invalidateQueries({ queryKey: ['generated-uis', projectId] })
    },
  })

  const { data: uiHistory } = useQuery({
    queryKey: ['generated-uis', projectId],
    queryFn: async (): Promise<GeneratedUIHistoryResponse> => {
      const res = await fetch(`${getApiV1Base()}/projects/${projectId}/generated-uis`, { headers: authHeaders() })
      if (!res.ok) throw new Error(await res.text())
      return (await res.json()) as GeneratedUIHistoryResponse
    },
    enabled: Number.isFinite(projectId) && activeTab === 'history',
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
    onSuccess: (data: { ui_simulation_run_id: number }) => {
      setSimStatus(`Simulation queued — Run ID: ${data.ui_simulation_run_id}`)
      void qc.invalidateQueries({ queryKey: ['generated-uis', projectId] })
    },
  })

  const handleGenerate = () => {
    if (!prompt.trim()) return
    generateMutation.mutate({
      prompt,
      product_type: productType,
      pages_required: ['home', 'product', 'checkout'],
      target_demographic: targetDemo || undefined,
      price_point: pricePoint || undefined,
    })
  }

  if (!Number.isFinite(projectId)) {
    return (
      <div className="min-h-screen bg-[#04070d] px-8 py-16 font-mono text-slate-300">
        <p className="text-xs uppercase tracking-[0.2em] text-red-400">Err</p>
        <h1 className="mt-2 text-lg text-white">Invalid project id</h1>
        <Link href="/projects" className="mt-6 inline-block text-sm text-blue-400 hover:text-blue-300">
          ← Back to dossiers
        </Link>
      </div>
    )
  }

  return (
    <div
      className="min-h-screen bg-[#04070d] font-mono text-slate-100"
      style={{
        backgroundImage:
          'radial-gradient(ellipse 120% 80% at 50% -20%, rgba(37,99,235,0.12), transparent 50%)',
      }}
    >
      <div className="flex items-center justify-between border-b border-slate-800/90 px-8 py-5">
        <div>
          <p className="mb-1 text-[10px] uppercase tracking-[0.35em] text-blue-400/90">TheCee / UI Builder</p>
          <h1 className="text-xl font-semibold tracking-tight text-white">Generate &amp; simulate UI</h1>
          <p className="mt-1 text-[11px] text-slate-600">Project #{String(projectId).padStart(4, '0')}</p>
        </div>
        <div className="flex gap-2">
          {(['builder', 'history'] as const).map((tab) => (
            <button
              key={tab}
              type="button"
              onClick={() => setActiveTab(tab)}
              className={`rounded px-4 py-1.5 text-[10px] font-medium uppercase tracking-[0.22em] transition-all ${
                activeTab === tab ? 'bg-blue-600 text-white' : 'text-slate-500 hover:text-slate-200'
              }`}
            >
              {tab}
            </button>
          ))}
        </div>
      </div>

      <div className="flex h-[calc(100dvh-88px)] min-h-[480px]">
        <UIBuilderConfigPanel
          productType={productType}
          setProductType={setProductType}
          prompt={prompt}
          setPrompt={setPrompt}
          pricePoint={pricePoint}
          setPricePoint={setPricePoint}
          targetDemo={targetDemo}
          setTargetDemo={setTargetDemo}
          onGenerate={handleGenerate}
          generatePending={generateMutation.isPending}
          generateError={generateMutation.isError}
          generatedUI={generatedUI}
          onSimulate={() => generatedUI && simulateMutation.mutate(generatedUI.id)}
          simulatePending={simulateMutation.isPending}
          simStatus={simStatus}
        />

        <div className="flex flex-1 flex-col">
          <AnimatePresence mode="wait">
            {activeTab === 'builder' && (
              <motion.div
                key="builder"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="flex flex-1 flex-col"
              >
                <UIBuilderPreview
                  generatedUI={generatedUI}
                  generatePending={generateMutation.isPending}
                  iframeRef={iframeRef}
                />
              </motion.div>
            )}

            {activeTab === 'history' && (
              <motion.div
                key="history"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="flex flex-1 flex-col bg-[#04070d]"
              >
                <UIBuilderHistory
                  rows={uiHistory?.uis ?? []}
                  onPreview={(ui) => {
                    setGeneratedUI(ui)
                    setActiveTab('builder')
                  }}
                  onSimulate={(id) => simulateMutation.mutate(id)}
                  simulatePending={simulateMutation.isPending}
                />
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </div>
  )
}
