'use client'

import { useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { ArrowRight, FolderOpen, Loader2, Plus, X, Zap } from 'lucide-react'
import Link from 'next/link'

import { apiError } from '@/lib/api'
import { useCreateProject, useProjects } from '@/hooks/useProjects'

const statusConfig: Record<string, { label: string; color: string; dot: string }> = {
  DRAFT: { label: 'Draft', color: 'text-slate-400 bg-slate-400/10 border-slate-400/20', dot: 'bg-slate-400' },
  ASSUMPTIONS_EXTRACTED: {
    label: 'Assumptions ready',
    color: 'text-amber-400 bg-amber-400/10 border-amber-400/20',
    dot: 'bg-amber-400',
  },
  PROTOTYPE_GENERATED: {
    label: 'Prototype ready',
    color: 'text-blue-400 bg-blue-400/10 border-blue-400/20',
    dot: 'bg-blue-400',
  },
  ENVIRONMENT_SET: {
    label: 'Environment set',
    color: 'text-purple-400 bg-purple-400/10 border-purple-400/20',
    dot: 'bg-purple-400',
  },
  QUEUED: { label: 'Queued', color: 'text-indigo-400 bg-indigo-400/10 border-indigo-400/20', dot: 'bg-indigo-400' },
  RUNNING: {
    label: 'Running',
    color: 'text-indigo-400 bg-indigo-400/10 border-indigo-400/20',
    dot: 'bg-indigo-400 animate-pulse',
  },
  COMPLETED: {
    label: 'Completed',
    color: 'text-emerald-400 bg-emerald-400/10 border-emerald-400/20',
    dot: 'bg-emerald-400',
  },
  FAILED: { label: 'Failed', color: 'text-red-400 bg-red-400/10 border-red-400/20', dot: 'bg-red-400' },
}

export default function ProjectsPage() {
  const [showModal, setShowModal] = useState(false)
  const [idea, setIdea] = useState('')

  const { data: projects, isLoading, isError, error } = useProjects()
  const createProject = useCreateProject()
  const projectList = projects ?? []

  if (isLoading) {
    return (
      <div className="p-8 flex items-center gap-2 text-slate-400">
        <Loader2 className="w-4 h-4 animate-spin" />
        Loading projects...
      </div>
    )
  }

  if (isError) {
    return <div className="p-8 text-red-400">Error: {apiError(error)}</div>
  }

  const handleCreate = async () => {
    const description = idea.trim()
    if (!description) return
    await createProject.mutateAsync({ description })
    setShowModal(false)
    setIdea('')
  }

  return (
    <div className="p-8">
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
        className="flex items-center justify-between mb-8"
      >
        <div>
          <h1 className="font-display text-2xl font-700 text-white">Projects</h1>
          <p className="text-slate-500 text-sm mt-0.5">
            {projectList.length} simulation{projectList.length !== 1 ? 's' : ''} in progress
          </p>
        </div>
        <button
          onClick={() => setShowModal(true)}
          className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium transition-all duration-200 hover:shadow-lg hover:shadow-indigo-500/20"
        >
          <Plus className="w-4 h-4" /> New simulation
        </button>
      </motion.div>

      {projectList.length === 0 ? (
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.2 }} className="flex flex-col items-center justify-center py-32 text-center">
          <div className="w-16 h-16 rounded-2xl bg-white/5 border border-white/10 flex items-center justify-center mb-4">
            <FolderOpen className="w-7 h-7 text-slate-600" />
          </div>
          <h3 className="font-display text-lg font-600 text-white mb-2">No simulations yet</h3>
          <p className="text-slate-500 text-sm mb-6 max-w-xs">Describe your idea and run it through synthetic consumers before committing.</p>
          <button
            onClick={() => setShowModal(true)}
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium transition-all"
          >
            <Plus className="w-4 h-4" /> Start first simulation
          </button>
        </motion.div>
      ) : (
        <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">
          {projectList.map((project, i) => {
            const status = statusConfig[project.status] ?? statusConfig.DRAFT
            const created = project.created_at ? new Date(project.created_at) : null
            return (
              <motion.div key={project.id} initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4, delay: i * 0.07 }}>
                <Link href={`/project/${project.id}`} className="block glass rounded-2xl p-6 glass-hover group cursor-pointer">
                  <div className="flex items-start justify-between mb-4">
                    <div className="w-9 h-9 rounded-xl bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center">
                      <Zap className="w-4 h-4 text-indigo-400" />
                    </div>
                    <span className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs border font-medium ${status.color}`}>
                      <span className={`w-1.5 h-1.5 rounded-full ${status.dot}`} />
                      {status.label}
                    </span>
                  </div>
                  <h3 className="font-display text-base font-600 text-white mb-1.5 line-clamp-1">{project.title}</h3>
                  <p className="text-slate-500 text-xs leading-relaxed line-clamp-2 mb-4">{project.description}</p>
                  <div className="flex items-center justify-between">
                    <span className="text-slate-600 text-xs">
                      {created ? created.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' }) : '—'}
                    </span>
                    <ArrowRight className="w-3.5 h-3.5 text-slate-600 group-hover:text-indigo-400 group-hover:translate-x-0.5 transition-all" />
                  </div>
                </Link>
              </motion.div>
            )
          })}
        </div>
      )}

      <AnimatePresence>
        {showModal && (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50"
              onClick={() => setShowModal(false)}
            />
            <motion.div
              initial={{ opacity: 0, scale: 0.96, y: 16 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.96, y: 16 }}
              transition={{ duration: 0.2 }}
              className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-full max-w-lg z-50"
            >
              <div className="glass rounded-2xl p-8 border border-white/10">
                <div className="flex items-center justify-between mb-6">
                  <div>
                    <h2 className="font-display text-lg font-700 text-white">Describe your idea</h2>
                    <p className="text-slate-500 text-xs mt-0.5">This creates a real project in your backend</p>
                  </div>
                  <button onClick={() => setShowModal(false)} className="w-7 h-7 rounded-lg bg-white/5 hover:bg-white/10 flex items-center justify-center transition-colors">
                    <X className="w-3.5 h-3.5 text-slate-400" />
                  </button>
                </div>
                <textarea
                  value={idea}
                  onChange={(e) => setIdea(e.target.value)}
                  placeholder="Describe your product idea in plain language..."
                  rows={5}
                  className="w-full px-4 py-3 rounded-xl bg-white/5 border border-white/10 text-white placeholder-slate-600 text-sm focus:outline-none focus:border-indigo-500/50 transition-all resize-none mb-5"
                />
                <div className="flex items-center gap-3 justify-end">
                  <button onClick={() => setShowModal(false)} className="px-4 py-2 rounded-lg text-slate-400 hover:text-white text-sm transition-colors">
                    Cancel
                  </button>
                  <button
                    onClick={handleCreate}
                    disabled={!idea.trim() || createProject.isPending}
                    className="flex items-center gap-2 px-5 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium transition-all"
                  >
                    {createProject.isPending ? (
                      <>
                        <Loader2 className="w-3.5 h-3.5 animate-spin" /> Creating...
                      </>
                    ) : (
                      <>
                        Create project <ArrowRight className="w-3.5 h-3.5" />
                      </>
                    )}
                  </button>
                </div>
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </div>
  )
}
