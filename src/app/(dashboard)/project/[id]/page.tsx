'use client'

import { motion } from 'framer-motion'
import { AlertCircle, ArrowRight, Brain, Loader2, RefreshCw } from 'lucide-react'
import Link from 'next/link'
import { useParams } from 'next/navigation'

import AssumptionCard from '@/components/project/AssumptionCard'
import { useAssumptions } from '@/hooks/useAssumptions'
import { useProject } from '@/hooks/useProjects'
import { useSimulations } from '@/hooks/useSimulation'

export default function ProjectPage() {
  const params = useParams()
  const projectId = Number(params.id)

  const { data: project, isLoading: pLoading } = useProject(projectId)
  const { data: assumptions, isLoading: aLoading } = useAssumptions(projectId)
  const { data: simulations, isLoading: sLoading } = useSimulations(projectId)

  if (pLoading) {
    return (
      <div className="p-8 flex items-center gap-2 text-slate-400">
        <Loader2 className="w-4 h-4 animate-spin" />
        Loading project...
      </div>
    )
  }

  if (!project) {
    return (
      <div className="p-8 flex items-center justify-center min-h-screen">
        <div className="text-center">
          <AlertCircle className="w-10 h-10 text-slate-600 mx-auto mb-3" />
          <p className="text-slate-400">Project not found</p>
        </div>
      </div>
    )
  }

  const assumptionList = assumptions ?? []
  const hiddenCount = assumptionList.filter((a) => Boolean(a.isHidden ?? a.is_hidden)).length
  const simulationCount = simulations?.length ?? 0

  return (
    <div className="p-8 max-w-6xl">
      <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }}>
        <div className="mb-8">
          <div className="flex items-center gap-2 text-xs text-slate-600 mb-3">
            <Link href="/dashboard" className="hover:text-slate-400 transition-colors">
              Dashboard
            </Link>
            <span>/</span>
            <span className="text-slate-400">{project.title}</span>
          </div>
          <div className="flex items-start justify-between">
            <div>
              <h1 className="font-display text-2xl font-700 text-white mb-1">{project.title}</h1>
              <p className="text-slate-400 text-sm max-w-xl">{project.description}</p>
            </div>
            <button className="flex items-center gap-2 px-3 py-2 rounded-lg glass glass-hover text-slate-400 text-sm">
              <RefreshCw className="w-3.5 h-3.5" /> Refresh
            </button>
          </div>
        </div>

        <div className="grid lg:grid-cols-[1fr_2fr] gap-6">
          <div className="glass rounded-2xl p-6 h-fit">
            <div className="flex items-center gap-2 mb-4">
              <Brain className="w-4 h-4 text-indigo-400" />
              <h2 className="font-display text-sm font-600 text-white">Original idea</h2>
            </div>
            <p className="text-slate-400 text-sm leading-relaxed">{project.description}</p>
            <div className="mt-4 pt-4 border-t border-white/5">
              <div className="flex justify-between text-xs text-slate-600">
                <span>{hiddenCount} hidden assumptions found</span>
                <span>{assumptionList.length} total</span>
              </div>
              <div className="flex justify-between text-xs text-slate-600 mt-2">
                <span>Simulations</span>
                <span>{sLoading ? 'Loading...' : simulationCount}</span>
              </div>
            </div>
          </div>

          <div>
            <div className="flex items-center justify-between mb-4">
              <h2 className="font-display text-sm font-600 text-white">
                Extracted assumptions <span className="text-slate-600 font-400">({aLoading ? '...' : assumptionList.length})</span>
              </h2>
            </div>

            {aLoading ? (
              <div className="glass rounded-2xl p-10 text-center text-slate-500 text-sm">Loading assumptions...</div>
            ) : assumptionList.length === 0 ? (
              <div className="glass rounded-2xl p-10 text-center">
                <p className="text-slate-500 text-sm">No assumptions extracted yet</p>
              </div>
            ) : (
              <div className="grid sm:grid-cols-2 gap-3">
                {assumptionList.map((a, i) => (
                  <motion.div
                    key={a.id}
                    initial={{ opacity: 0, y: 16 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: i * 0.08 }}
                  >
                    <AssumptionCard
                      assumption={{
                        ...a,
                        impactScore: a.impactScore ?? a.impact_score ?? 0,
                        isHidden: a.isHidden ?? a.is_hidden ?? false,
                      }}
                    />
                  </motion.div>
                ))}
              </div>
            )}

            <div className="flex justify-end mt-6">
              <Link
                href={`/project/${projectId}/prototype`}
                className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium transition-all"
              >
                View prototype <ArrowRight className="w-4 h-4" />
              </Link>
            </div>
          </div>
        </div>
      </motion.div>
    </div>
  )
}
