'use client'

import type { RefObject } from 'react'

import type { GeneratedUI } from './types'
import { previewAbsoluteUrl } from './preview-absolute-url'

type Props = {
  generatedUI: GeneratedUI | null
  generatePending: boolean
  iframeRef: RefObject<HTMLIFrameElement | null>
}

export default function UIBuilderPreview({ generatedUI, generatePending, iframeRef }: Props) {
  const previewSrc = generatedUI ? previewAbsoluteUrl(generatedUI.html_preview_url) : null
  const openHref = previewSrc ?? undefined

  return (
    <>
      {generatedUI && (
        <div className="flex items-center justify-between border-b border-slate-800/90 bg-[#060a12] px-6 py-3">
          <div className="flex flex-wrap items-center gap-4">
            <span className="font-mono text-xs text-slate-500">
              v{generatedUI.version} · {generatedUI.product_type}
            </span>
            {generatedUI.pages_detected.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {generatedUI.pages_detected.map((p) => (
                  <span key={p} className="rounded bg-slate-800/90 px-2 py-0.5 font-mono text-[11px] text-slate-400">
                    {p}
                  </span>
                ))}
              </div>
            )}
          </div>
          {openHref && (
            <a
              href={openHref}
              target="_blank"
              rel="noopener noreferrer"
              className="font-mono text-xs text-blue-400 hover:text-blue-300"
            >
              Open full ↗
            </a>
          )}
        </div>
      )}

      <div className="relative flex-1 bg-[#0a0f1c]">
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 opacity-[0.07]"
          style={{
            backgroundImage:
              'linear-gradient(rgba(59,130,246,0.5) 1px, transparent 1px), linear-gradient(90deg, rgba(59,130,246,0.35) 1px, transparent 1px)',
            backgroundSize: '24px 24px',
          }}
        />

        {generatePending && (
          <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-4 bg-[#0a0f1c]/95">
            <div className="h-8 w-8 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
            <p className="text-sm text-slate-400">Claude is generating your UI…</p>
            <p className="font-mono text-xs text-slate-600">This takes 15–30 seconds</p>
          </div>
        )}

        {!generatePending && !generatedUI && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3">
            <div className="flex h-16 w-16 items-center justify-center rounded-2xl border border-slate-800 bg-slate-950 text-3xl text-blue-500/80">
              ⬡
            </div>
            <p className="text-sm text-slate-500">Configure your product and click Generate</p>
            <p className="font-mono text-xs text-slate-700">A complete HTML prototype will appear here</p>
          </div>
        )}

        {generatedUI && !generatePending && previewSrc && (
          <iframe
            ref={iframeRef}
            src={previewSrc}
            className="relative z-[1] h-full w-full border-0"
            title="Generated UI Preview"
            sandbox="allow-scripts allow-same-origin"
          />
        )}
      </div>
    </>
  )
}
