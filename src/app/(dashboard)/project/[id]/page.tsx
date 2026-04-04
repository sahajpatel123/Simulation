'use client'
import { motion } from 'framer-motion'
import { use } from 'react'
import { getProjectById, getAssumptionsByProjectId } from '@/lib/mock-data'
import AssumptionCard from '@/components/project/AssumptionCard'
import { ArrowRight, RefreshCw, AlertCircle, Brain } from 'lucide-react'
import Link from 'next/link'

export default function ProjectPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params)
  const project = getProjectById(id)
  const assumptions = getAssumptionsByProjectId(id)

  if (!project) return (
    <div className="p-8 flex items-center justify-center min-h-screen">
      <div className="text-center">
        <AlertCircle className="w-10 h-10 text-slate-600 mx-auto mb-3" />
        <p className="text-slate-400">Project not found</p>
      </div>
    </div>
  )

  return (
    <div className="p-8 max-w-6xl">
      <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }}>
        {/* Header */}
        <div className="mb-8">
          <div className="flex items-center gap-2 text-xs text-slate-600 mb-3">
            <Link href="/dashboard" className="hover:text-slate-400 transition-colors">Dashboard</Link>
            <span>/</span>
            <span className="text-slate-400">{project.title}</span>
          </div>
          <div className="flex items-start justify-between">
            <div>
              <h1 className="font-display text-2xl font-700 text-white mb-1">{project.title}</h1>
              <p className="text-slate-400 text-sm max-w-xl">{project.description}</p>
            </div>
            <button className="flex items-center gap-2 px-3 py-2 rounded-lg glass glass-hover text-slate-400 text-sm">
              <RefreshCw className="w-3.5 h-3.5" /> Regenerate
            </button>
          </div>
        </div>

        <div className="grid lg:grid-cols-[1fr_2fr] gap-6">
          {/* Original input */}
          <div className="glass rounded-2xl p-6 h-fit">
            <div className="flex items-center gap-2 mb-4">
              <Brain className="w-4 h-4 text-indigo-400" />
              <h2 className="font-display text-sm font-600 text-white">Original idea</h2>
            </div>
            <p className="text-slate-400 text-sm leading-relaxed">{project.description}</p>
            <div className="mt-4 pt-4 border-t border-white/5">
              <div className="flex justify-between text-xs text-slate-600">
                <span>{assumptions.filter(a => a.isHidden).length} hidden assumptions found</span>
                <span>{assumptions.length} total</span>
              </div>
            </div>
          </div>

          {/* Assumptions */}
          <div>
            <div className="flex items-center justify-between mb-4">
              <h2 className="font-display text-sm font-600 text-white">
                Extracted assumptions <span className="text-slate-600 font-400">({assumptions.length})</span>
              </h2>
            </div>

            {assumptions.length === 0 ? (
              <div className="glass rounded-2xl p-10 text-center">
                <p className="text-slate-500 text-sm">No assumptions extracted yet</p>
              </div>
            ) : (
              <div className="grid sm:grid-cols-2 gap-3">
                {assumptions.map((a, i) => (
                  <motion.div key={a.id} initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: i * 0.08 }}>
                    <AssumptionCard assumption={a} />
                  </motion.div>
                ))}
              </div>
            )}

            <div className="flex justify-end mt-6">
              <Link href={`/project/${id}/prototype`}
                className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium transition-all">
                View prototype <ArrowRight className="w-4 h-4" />
              </Link>
            </div>
          </div>
        </div>
      </motion.div>
    </div>
  )
}
