'use client'

import { useState } from 'react'
import { motion } from 'framer-motion'
import { Monitor, Smartphone, ArrowRight, ArrowLeft, AlertCircle, Loader2 } from 'lucide-react'
import Link from 'next/link'
import { useParams } from 'next/navigation'

import { useProject } from '@/hooks/useProjects'

const MOCK_HTML = `<!DOCTYPE html>
<html>
<head>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; font-family: system-ui, sans-serif; }
  body { background: #f8fafc; color: #1e293b; }
  nav { background: white; padding: 16px 24px; border-bottom: 1px solid #e2e8f0; display: flex; align-items: center; justify-content: space-between; }
  nav .logo { font-weight: 700; font-size: 18px; color: #4f46e5; }
  nav button { background: #4f46e5; color: white; border: none; padding: 8px 20px; border-radius: 8px; font-size: 14px; cursor: pointer; }
  .hero { text-align: center; padding: 80px 24px 60px; }
  .hero h1 { font-size: 42px; font-weight: 800; margin-bottom: 16px; line-height: 1.1; }
  .hero p { color: #64748b; font-size: 16px; max-width: 480px; margin: 0 auto 32px; }
  .hero .cta { background: #4f46e5; color: white; border: none; padding: 14px 32px; border-radius: 10px; font-size: 16px; font-weight: 600; cursor: pointer; }
  .features { display: grid; grid-template-columns: repeat(3, 1fr); gap: 24px; padding: 40px 24px; max-width: 900px; margin: 0 auto; }
  .card { background: white; border-radius: 12px; padding: 24px; border: 1px solid #e2e8f0; }
  .card h3 { font-size: 16px; font-weight: 600; margin-bottom: 8px; }
  .card p { font-size: 14px; color: #64748b; line-height: 1.5; }
</style>
</head>
<body>
  <nav>
    <div class="logo">YourBrand</div>
    <button>Get Started</button>
  </nav>
  <div class="hero">
    <h1>Your Headline<br/>Goes Here</h1>
    <p>A brief description of your product value proposition. Clear and compelling.</p>
    <button class="cta">Start for free →</button>
  </div>
  <div class="features">
    <div class="card"><h3>Feature One</h3><p>Short description of the first key feature benefit.</p></div>
    <div class="card"><h3>Feature Two</h3><p>Short description of the second key feature benefit.</p></div>
    <div class="card"><h3>Feature Three</h3><p>Short description of the third key feature benefit.</p></div>
  </div>
</body>
</html>`

export default function PrototypePage() {
  const params = useParams()
  const rawId = params.id
  const projectId = typeof rawId === 'string' ? Number(rawId) : Number(Array.isArray(rawId) ? rawId[0] : rawId)

  const { data: project, isLoading, isError } = useProject(Number.isFinite(projectId) ? projectId : null)
  const [view, setView] = useState<'desktop' | 'mobile'>('desktop')

  const idStr = String(projectId)

  if (!Number.isFinite(projectId)) {
    return (
      <div style={{ padding: '80px 48px', maxWidth: 640 }}>
        <div className="kicker" style={{ color: 'var(--red)', marginBottom: 10 }}>Errata</div>
        <h1 className="font-serif" style={{ fontSize: 36, fontWeight: 900, fontStyle: 'italic', color: 'var(--ink)' }}>
          Invalid dossier number.
        </h1>
        <Link href="/projects" style={{ marginTop: 16, display: 'inline-block', color: 'var(--red)', fontSize: 14 }}>
          Return to the index.
        </Link>
      </div>
    )
  }

  if (isLoading) {
    return (
      <div style={{ padding: '80px 48px', display: 'flex', gap: 12, alignItems: 'center', color: 'var(--ink-secondary)' }}>
        <Loader2 className="animate-spin" style={{ width: 14, height: 14 }} />
        <span className="kicker">Opening the plate…</span>
      </div>
    )
  }

  if (!isLoading && (isError || !project)) {
    return (
      <div style={{ padding: '80px 48px', maxWidth: 640 }}>
        <div className="kicker" style={{ color: 'var(--red)', marginBottom: 10 }}>Errata</div>
        <h1 className="font-serif" style={{ fontSize: 36, fontWeight: 900, fontStyle: 'italic', color: 'var(--ink)' }}>
          This dossier is missing from the archive.
        </h1>
        <p style={{ marginTop: 14, color: 'var(--ink-secondary)', fontSize: 14, lineHeight: 1.7 }}>
          The plate could not be found. It may have been recalled or the link was misprinted.
        </p>
        <Link href="/projects" style={{ marginTop: 18, display: 'inline-block', color: 'var(--red)', fontSize: 14 }}>
          Return to the index.
        </Link>
      </div>
    )
  }

  return (
    <div className="p-8 h-screen flex flex-col max-h-screen overflow-hidden">
      <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }}>
        {/* Header */}
        <div className="flex items-center justify-between mb-6 shrink-0">
          <div>
            <div className="flex items-center gap-2 text-xs text-slate-600 mb-1.5">
              <Link href={`/project/${idStr}`} className="hover:text-slate-400">
                Dossier
              </Link>
              <span>/</span>
              <span className="text-slate-400">Prototype</span>
            </div>
            <h1 className="font-display text-xl font-700 text-white">Generated prototype</h1>
          </div>

          {/* Toggle */}
          <div className="flex items-center gap-1 glass rounded-xl p-1">
            {([
              { mode: 'desktop' as const, icon: Monitor, label: 'Desktop' },
              { mode: 'mobile' as const, icon: Smartphone, label: 'Mobile' },
            ]).map(({ mode, icon: Icon, label }) => (
              <button
                key={mode}
                type="button"
                onClick={() => setView(mode)}
                className={`flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium transition-all duration-200 ${
                  view === mode ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-white'
                }`}
              >
                <Icon className="w-3.5 h-3.5" />
                {label}
              </button>
            ))}
          </div>
        </div>
      </motion.div>

      {/* Iframe container */}
      <motion.div
        initial={{ opacity: 0, scale: 0.98 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.4, delay: 0.1 }}
        className="flex-1 flex flex-col items-center min-h-0"
      >
        <div
          className={`glass rounded-2xl overflow-hidden transition-all duration-500 flex flex-col ${
            view === 'desktop' ? 'w-full' : 'w-[390px]'
          } flex-1`}
        >
          {/* Browser chrome */}
          <div className="flex items-center gap-2 px-4 py-3 border-b border-white/5 shrink-0">
            <div className="flex gap-1.5">
              {['bg-red-500', 'bg-amber-500', 'bg-emerald-500'].map((c) => (
                <div key={c} className={`w-2.5 h-2.5 rounded-full ${c} opacity-60`} />
              ))}
            </div>
            <div className="flex-1 mx-3 px-3 py-1 rounded-md bg-white/5 border border-white/5 text-xs text-slate-600 text-center">
              preview.thecee.app
            </div>
          </div>
          <iframe
            srcDoc={project.prototypeHtml || MOCK_HTML}
            className="flex-1 w-full bg-white"
            sandbox="allow-scripts"
            title="Prototype preview"
          />
        </div>
      </motion.div>

      {/* Footer nav */}
      <div className="flex items-center justify-between mt-4 shrink-0">
        <Link
          href={`/project/${idStr}`}
          className="flex items-center gap-2 px-4 py-2 rounded-lg glass glass-hover text-slate-400 text-sm"
        >
          <ArrowLeft className="w-3.5 h-3.5" /> Dossier
        </Link>
        <Link
          href={`/project/${idStr}/environment`}
          className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium transition-all"
        >
          Set environment <ArrowRight className="w-4 h-4" />
        </Link>
      </div>
    </div>
  )
}
