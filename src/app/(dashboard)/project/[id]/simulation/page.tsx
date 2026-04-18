'use client'

import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import { ArrowRight, X, Zap, Users, BarChart2, Brain, Activity, Loader2 } from 'lucide-react'

import { useProject } from '@/hooks/useProjects'

const stages = [
  { id: 'profile', label: 'Profile embedding', icon: Users, description: 'Building 10,000 consumer behavioral vectors' },
  { id: 'markov', label: 'Markov chains', icon: Brain, description: 'Initializing decision state machines' },
  { id: 'funnel', label: 'Funnel execution', icon: Activity, description: 'Running agents through product funnel' },
  { id: 'aggregate', label: 'Aggregation', icon: BarChart2, description: 'Computing probability distributions' },
]

function AnimatedCounter({ value }: { value: number }) {
  return (
    <motion.span
      key={value}
      initial={{ opacity: 0.5, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.15 }}
      className="font-serif"
      style={{ fontWeight: 800, fontStyle: 'italic', color: 'var(--ink)', fontSize: 'clamp(36px, 8vw, 52px)', lineHeight: 1 }}
    >
      {value.toLocaleString()}
    </motion.span>
  )
}

export default function SimulationPage() {
  const params = useParams()
  const projectId = Number(params.id)
  const idStr = String(projectId)

  const { data: project, isLoading, isError } = useProject(Number.isFinite(projectId) ? projectId : null)

  const [agentsCompleted, setAgentsCompleted] = useState(0)
  const [currentStage, setCurrentStage] = useState(0)
  const [elapsed, setElapsed] = useState(0)
  const [done, setDone] = useState(false)
  const TOTAL = 10000

  useEffect(() => {
    const timer = setInterval(() => setElapsed((e) => e + 1), 1000)
    return () => clearInterval(timer)
  }, [])

  useEffect(() => {
    if (done) return
    const interval = setInterval(() => {
      setAgentsCompleted((prev) => {
        const next = Math.min(prev + Math.floor(Math.random() * 180 + 120), TOTAL)
        if (next >= TOTAL) {
          setDone(true)
          clearInterval(interval)
        }
        setCurrentStage(Math.min(Math.floor((next / TOTAL) * stages.length), stages.length - 1))
        return next
      })
    }, 200)
    return () => clearInterval(interval)
  }, [done])

  const progress = (agentsCompleted / TOTAL) * 100
  const formatTime = (s: number) =>
    `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`

  if (!Number.isFinite(projectId) || isError) {
    return (
      <div style={{ padding: '64px 48px', maxWidth: 560 }}>
        <div className="kicker" style={{ color: 'var(--red)', marginBottom: 10 }}>
          Errata
        </div>
        <h1 className="font-serif" style={{ fontSize: 32, fontWeight: 900, fontStyle: 'italic', color: 'var(--ink)' }}>
          This dossier could not be opened.
        </h1>
        <Link href="/projects" style={{ marginTop: 16, display: 'inline-block', color: 'var(--red)', fontSize: 14 }}>
          Return to the index.
        </Link>
      </div>
    )
  }

  if (isLoading || !project) {
    return (
      <div style={{ padding: '64px 48px', display: 'flex', gap: 12, alignItems: 'center', color: 'var(--ink-secondary)' }}>
        <Loader2 className="animate-spin" style={{ width: 14, height: 14 }} />
        <span className="kicker">Warming the press…</span>
      </div>
    )
  }

  return (
    <div style={{ padding: '36px 48px 56px', maxWidth: 640 }}>
      <motion.div initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.45 }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16, marginBottom: 32 }}>
          <div>
            <div className="kicker" style={{ color: 'var(--red)', marginBottom: 10 }}>
              At press
            </div>
            <h1
              className="font-serif"
              style={{
                fontSize: 'clamp(26px, 3.5vw, 34px)',
                fontWeight: 900,
                fontStyle: 'italic',
                color: 'var(--ink)',
                marginBottom: 6,
              }}
            >
              {done ? 'Impression complete' : 'Running the edition'}
            </h1>
            <p style={{ fontSize: 13, color: 'var(--ink-secondary)', fontWeight: 300 }}>{project.title}</p>
          </div>
          {!done && (
            <button
              type="button"
              className="btn-ghost"
              style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 10, letterSpacing: '0.14em' }}
            >
              <X style={{ width: 12, height: 12 }} /> Abort
            </button>
          )}
        </div>

        <div
          style={{
            border: '0.5px solid var(--border-strong)',
            background: 'var(--paper)',
            padding: 36,
            marginBottom: 24,
            textAlign: 'center',
          }}
          className="rise"
        >
          <div style={{ marginBottom: 4 }}>
            <AnimatedCounter value={agentsCompleted} />
            <span style={{ fontSize: 28, color: 'var(--ink-tertiary)', fontFamily: 'var(--font-serif)', fontStyle: 'italic' }}>
              {' '}
              / {TOTAL.toLocaleString()}
            </span>
          </div>
          <p className="kicker" style={{ color: 'var(--ink-secondary)', marginBottom: 28 }}>
            Synthetic readers through the plate
          </p>
          <div style={{ height: 4, background: 'rgba(26,23,20,0.08)', overflow: 'hidden', marginBottom: 10 }}>
            <motion.div
              style={{ height: '100%', background: 'var(--red)' }}
              initial={{ width: 0 }}
              animate={{ width: `${progress}%` }}
              transition={{ duration: 0.3, ease: 'easeOut' }}
            />
          </div>
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              fontSize: 10,
              letterSpacing: '0.12em',
              textTransform: 'uppercase',
              color: 'var(--ink-tertiary)',
            }}
          >
            <span>{Math.round(progress)}% complete</span>
            <span>{formatTime(elapsed)} elapsed</span>
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginBottom: 28 }}>
          {stages.map((stage, i) => {
            const isActive = i === currentStage && !done
            const isDoneStage = done || i < currentStage
            const Icon = stage.icon
            return (
              <motion.div
                key={stage.id}
                initial={{ opacity: 0, x: -12 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: i * 0.08 }}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 16,
                  padding: 16,
                  border: isActive ? '0.5px solid var(--ink)' : '0.5px solid var(--border-strong)',
                  background: isActive ? 'var(--paper-dark)' : 'var(--paper)',
                  opacity: !isDoneStage && !isActive ? 0.38 : 1,
                  boxShadow: isActive ? '6px 6px 0 rgba(192,57,43,0.1)' : 'none',
                }}
              >
                <div
                  style={{
                    width: 36,
                    height: 36,
                    flexShrink: 0,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    border: isDoneStage ? '0.5px solid #2d5a4a' : '0.5px solid var(--border-color)',
                    background: isDoneStage ? 'rgba(45,90,74,0.08)' : 'transparent',
                  }}
                >
                  {isDoneStage ? (
                    <Zap style={{ width: 16, height: 16, color: '#2d5a4a' }} />
                  ) : (
                    <Icon style={{ width: 16, height: 16, color: isActive ? 'var(--red)' : 'var(--ink-tertiary)' }} />
                  )}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span
                      style={{
                        fontSize: 14,
                        fontWeight: 600,
                        color: isDoneStage ? '#2d5a4a' : isActive ? 'var(--ink)' : 'var(--ink-tertiary)',
                      }}
                    >
                      {stage.label}
                    </span>
                    {isActive && (
                      <span style={{ display: 'flex', gap: 3 }}>
                        {[0, 1, 2].map((d) => (
                          <motion.span
                            key={d}
                            style={{ width: 4, height: 4, borderRadius: '50%', background: 'var(--red)' }}
                            animate={{ opacity: [0.25, 1, 0.25] }}
                            transition={{ duration: 1.2, repeat: Infinity, delay: d * 0.2 }}
                          />
                        ))}
                      </span>
                    )}
                  </div>
                  <p style={{ fontSize: 11, color: 'var(--ink-secondary)', marginTop: 4, lineHeight: 1.5 }}>{stage.description}</p>
                </div>
              </motion.div>
            )
          })}
        </div>

        {done && (
          <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35 }}>
            <Link href={`/project/${idStr}/results`} className="btn-ink" style={{ display: 'flex', width: '100%', justifyContent: 'center', gap: 10 }}>
              Read the proofs <ArrowRight style={{ width: 16, height: 16 }} />
            </Link>
          </motion.div>
        )}
      </motion.div>
    </div>
  )
}
