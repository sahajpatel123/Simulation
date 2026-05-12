'use client'

import type { Dispatch, SetStateAction } from 'react'

import { SOFTWARE_TYPES, formatProductTypeLabel } from './constants'

type Props = {
  productType: string
  setProductType: Dispatch<SetStateAction<string>>
  prompt: string
  setPrompt: Dispatch<SetStateAction<string>>
  pricePoint: string
  setPricePoint: Dispatch<SetStateAction<string>>
  targetDemo: string
  setTargetDemo: Dispatch<SetStateAction<string>>
  onGenerate: () => void
  generatePending: boolean
  generateError: boolean
  generatedUI: { id: number } | null
  onSimulate: () => void
  simulatePending: boolean
  simStatus: string | null
}

export default function UIBuilderConfigPanel(props: Props) {
  const {
    productType,
    setProductType,
    prompt,
    setPrompt,
    pricePoint,
    setPricePoint,
    targetDemo,
    setTargetDemo,
    onGenerate,
    generatePending,
    generateError,
    generatedUI,
    onSimulate,
    simulatePending,
    simStatus,
  } = props

  return (
    <div className="flex w-full max-w-none flex-col border-slate-800/90 bg-[#060a12] md:w-96 md:max-w-96 md:border-r">
      <div className="flex-1 space-y-5 overflow-y-auto p-6">
        <div>
          <label className="mb-2 block text-[10px] font-medium uppercase tracking-[0.28em] text-slate-500">
            Product type
          </label>
          <select
            value={productType}
            onChange={(e) => setProductType(e.target.value)}
            className="w-full rounded border border-slate-700/80 bg-slate-950 px-3 py-2 text-sm text-slate-200 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500/40"
          >
            {SOFTWARE_TYPES.map((pt) => (
              <option key={pt} value={pt}>
                {formatProductTypeLabel(pt)}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="mb-2 block text-[10px] font-medium uppercase tracking-[0.28em] text-slate-500">
            Product description
          </label>
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            rows={5}
            placeholder="Describe your product, its core value proposition, key features, and target audience…"
            className="w-full resize-none rounded border border-slate-700/80 bg-slate-950 px-3 py-2 text-sm leading-relaxed text-slate-200 placeholder:text-slate-600 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500/40"
          />
        </div>

        <div>
          <label className="mb-2 block text-[10px] font-medium uppercase tracking-[0.28em] text-slate-500">
            Price point <span className="text-slate-600">(optional)</span>
          </label>
          <input
            value={pricePoint}
            onChange={(e) => setPricePoint(e.target.value)}
            placeholder="e.g. ₹999/month"
            className="w-full rounded border border-slate-700/80 bg-slate-950 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500/40"
          />
        </div>

        <div>
          <label className="mb-2 block text-[10px] font-medium uppercase tracking-[0.28em] text-slate-500">
            Target segment <span className="text-slate-600">(optional)</span>
          </label>
          <input
            value={targetDemo}
            onChange={(e) => setTargetDemo(e.target.value)}
            placeholder="e.g. metro professionals, Tier-2 founders"
            className="w-full rounded border border-slate-700/80 bg-slate-950 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500/40"
          />
        </div>
      </div>

      <div className="space-y-3 border-t border-slate-800/90 bg-[#04070d] p-6">
        <button
          type="button"
          onClick={onGenerate}
          disabled={!prompt.trim() || generatePending}
          className="relative w-full overflow-hidden rounded bg-blue-600 py-3 text-sm font-bold uppercase tracking-widest text-white transition-all hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {generatePending ? (
            <span className="flex items-center justify-center gap-2">
              <span className="h-3 w-3 animate-spin rounded-full border-2 border-white border-t-transparent" />
              Generating…
            </span>
          ) : (
            '✨ Generate Lovable UI'
          )}
        </button>

        {generateError && (
          <p className="text-center text-xs text-red-400">Generation failed — check API connection</p>
        )}

        {generatedUI && (
          <button
            type="button"
            onClick={onSimulate}
            disabled={simulatePending}
            className="w-full rounded border border-blue-500 py-2.5 text-sm font-bold uppercase tracking-widest text-blue-400 transition-all hover:bg-blue-600 hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
          >
            {simulatePending ? 'Queuing…' : '▶ Run 52-Cluster Simulation'}
          </button>
        )}

        {simStatus && <p className="text-center text-xs text-emerald-400">{simStatus}</p>}
      </div>
    </div>
  )
}
