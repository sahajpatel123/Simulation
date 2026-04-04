'use client'
import { useState, useEffect, use } from 'react'
import { motion } from 'framer-motion'
import { getProjectById } from '@/lib/mock-data'
import { ArrowRight, X, Zap, Users, BarChart2, Brain, Activity } from 'lucide-react'
import Link from 'next/link'

const stages = [
  { id: 'profile', label: 'Profile embedding', icon: Users, description: 'Building 10,000 consumer behavioral vectors' },
  { id: 'markov', label: 'Markov chains', icon: Brain, description: 'Initializing decision state machines' },
  { id: 'funnel', label: 'Funnel execution', icon: Activity, description: 'Running agents through product funnel' },
  { id: 'aggregate', label: 'Aggregation', icon: BarChart2, description: 'Computing probability distributions' },
]

function AnimatedCounter({ value, suffix = '' }: { value: number; suffix?: string }) {
  return (
    <motion.span
      key={value}
      initial={{ opacity: 0.5, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.15 }}
      className="font-display font-800 text-white tabular-nums"
    >
      {value.toLocaleString()}{suffix}
    </motion.span>
  )
}

export default function SimulationPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params)
  const project = getProjectById(id)

  const [agentsCompleted, setAgentsCompleted] = useState(0)
  const [currentStage, setCurrentStage] = useState(0)
  const [elapsed, setElapsed] = useState(0)
  const [done, setDone] = useState(false)
  const TOTAL = 10000

  useEffect(() => {
    const timer = setInterval(() => setElapsed(e => e + 1), 1000)
    return () => clearInterval(timer)
  }, [])

  useEffect(() => {
    if (done) return
    const interval = setInterval(() => {
      setAgentsCompleted(prev => {
        const next = Math.min(prev + Math.floor(Math.random() * 180 + 120), TOTAL)
        if (next >= TOTAL) { setDone(true); clearInterval(interval) }
        setCurrentStage(Math.min(Math.floor((next / TOTAL) * stages.length), stages.length - 1))
        return next
      })
    }, 200)
    return () => clearInterval(interval)
  }, [done])

  const progress = (agentsCompleted / TOTAL) * 100

  const formatTime = (s: number) => `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`

  if (!project) return null

  return (
    <div className="p-8 max-w-2xl">
      <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }}>
        {/* Header */}
        <div className="flex items-start justify-between mb-10">
          <div>
            <h1 className="font-display text-2xl font-700 text-white mb-1">
              {done ? 'Simulation complete' : 'Simulating your idea'}
            </h1>
            <p className="text-slate-500 text-sm">{project.title}</p>
          </div>
          {!done && (
            <button className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg glass glass-hover text-slate-500 text-xs">
              <X className="w-3 h-3" /> Cancel
            </button>
          )}
        </div>

        {/* Big counter */}
        <div className="glass rounded-2xl p-8 mb-6 text-center">
          <div className="text-5xl mb-1">
            <AnimatedCounter value={agentsCompleted} />
            <span className="text-slate-600 text-3xl"> / {TOTAL.toLocaleString()}</span>
          </div>
          <p className="text-slate-500 text-sm mb-6">synthetic agents processed</p>

          {/* Progress bar */}
          <div className="w-full h-2 bg-white/5 rounded-full overflow-hidden mb-2">
            <motion.div
              className="h-full bg-gradient-to-r from-indigo-500 to-cyan-400 rounded-full"
              initial={{ width: 0 }}
              animate={{ width: `${progress}%` }}
              transition={{ duration: 0.3, ease: 'easeOut' }}
            />
          </div>
          <div className="flex justify-between text-xs text-slate-600">
            <span>{Math.round(progress)}% complete</span>
            <span>{formatTime(elapsed)} elapsed</span>
          </div>
        </div>

        {/* Stage indicators */}
        <div className="space-y-3 mb-8">
          {stages.map((stage, i) => {
            const isActive = i === currentStage && !done
            const isDone = done || i < currentStage
            const Icon = stage.icon
            return (
              <motion.div key={stage.id}
                initial={{ opacity: 0, x: -12 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: i * 0.1 }}
                className={`flex items-center gap-4 p-4 rounded-xl transition-all duration-300 ${
                  isActive ? 'glass border-indigo-500/30 bg-indigo-500/5' : isDone ? 'opacity-60' : 'glass opacity-30'
                }`}>
                <div className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 ${
                  isDone ? 'bg-emerald-500/20 border border-emerald-500/20' :
                  isActive ? 'bg-indigo-500/20 border border-indigo-500/30' :
                  'bg-white/5'
                }`}>
                  {isDone ? <Zap className="w-4 h-4 text-emerald-400" /> :
                   <Icon className={`w-4 h-4 ${isActive ? 'text-indigo-400' : 'text-slate-600'}`} />}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className={`text-sm font-medium ${isDone ? 'text-emerald-400' : isActive ? 'text-white' : 'text-slate-600'}`}>
                      {stage.label}
                    </span>
                    {isActive && (
                      <span className="flex gap-0.5">
                        {[0, 1, 2].map(d => (
                          <motion.span key={d} className="w-1 h-1 rounded-full bg-indigo-400"
                            animate={{ opacity: [0.3, 1, 0.3] }}
                            transition={{ duration: 1.2, repeat: Infinity, delay: d * 0.2 }} />
                        ))}
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-slate-600 truncate">{stage.description}</p>
                </div>
              </motion.div>
            )
          })}
        </div>

        {/* CTA when done */}
        {done && (
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }}>
            <Link href={`/project/${id}/results`}
              className="flex items-center justify-center gap-2 w-full py-3.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-medium transition-all hover:shadow-lg hover:shadow-indigo-500/20">
              View results <ArrowRight className="w-4 h-4" />
            </Link>
          </motion.div>
        )}
      </motion.div>
    </div>
  )
}
