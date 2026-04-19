'use client'

import type { GeneratedUI, GeneratedUIHistoryRow } from './types'
import { formatProductTypeLabel } from './constants'

type Props = {
  rows: GeneratedUIHistoryRow[]
  onPreview: (ui: GeneratedUI) => void
  onSimulate: (id: number) => void
  simulatePending: boolean
}

export default function UIBuilderHistory({ rows, onPreview, onSimulate, simulatePending }: Props) {
  return (
    <div className="flex-1 overflow-y-auto p-6">
      <h2 className="mb-4 font-mono text-[10px] font-medium uppercase tracking-[0.28em] text-slate-500">
        Generated UI history
      </h2>
      {!rows.length ? (
        <p className="text-sm text-slate-600">No UIs generated yet.</p>
      ) : (
        <ul className="space-y-3">
          {rows.map((ui) => (
            <li
              key={ui.id}
              className="flex items-center justify-between gap-4 rounded-lg border border-slate-800/90 bg-[#060a12] p-4 transition-all hover:border-slate-700"
            >
              <div>
                <p className="text-sm text-slate-200">
                  Version {ui.version}
                  <span className="ml-2 font-mono text-xs text-slate-500">{formatProductTypeLabel(ui.product_type)}</span>
                </p>
                <p className="mt-0.5 font-mono text-xs text-slate-600">
                  {ui.created_at ? new Date(ui.created_at).toLocaleString() : '—'}
                </p>
              </div>
              <div className="flex shrink-0 gap-2">
                <button
                  type="button"
                  onClick={() =>
                    onPreview({
                      id: ui.id,
                      version: ui.version,
                      product_type: ui.product_type,
                      html_preview_url: ui.html_preview_url,
                      pages_detected: [],
                    })
                  }
                  className="rounded border border-slate-700 px-3 py-1.5 font-mono text-xs transition-all hover:border-blue-500 hover:text-blue-400"
                >
                  Preview
                </button>
                <button
                  type="button"
                  onClick={() => onSimulate(ui.id)}
                  disabled={simulatePending}
                  className="rounded bg-blue-600 px-3 py-1.5 font-mono text-xs text-white transition-all hover:bg-blue-500 disabled:opacity-40"
                >
                  Simulate
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
