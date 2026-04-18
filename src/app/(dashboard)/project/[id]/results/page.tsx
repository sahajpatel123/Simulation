'use client'

import { useState } from 'react'
import { motion } from 'framer-motion'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import { ArrowRight, TrendingUp, Users, IndianRupee, Target, ChevronDown, Loader2 } from 'lucide-react'

import InterventionCard from '@/components/project/InterventionCard'
import ProbabilityChart from '@/components/project/ProbabilityChart'
import { useProject } from '@/hooks/useProjects'
import { getSimulationResultByProjectId } from '@/lib/mock-data'

export default function ResultsPage() {
  const params = useParams()
  const projectId = Number(params.id)
  const idStr = String(projectId)

  const { data: project, isLoading, isError } = useProject(Number.isFinite(projectId) ? projectId : null)
  const result = getSimulationResultByProjectId(idStr)
  const [volume, setVolume] = useState(result?.consumerVolume || 10000)

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
        <span className="kicker">Gathering proofs…</span>
      </div>
    )
  }

  if (!result) {
    return (
      <div style={{ padding: '48px 48px 64px', maxWidth: 560 }}>
        <div className="kicker" style={{ color: 'var(--red)', marginBottom: 12 }}>
          Proofs missing
        </div>
        <h1 className="font-serif" style={{ fontSize: 32, fontWeight: 900, fontStyle: 'italic', color: 'var(--ink)', marginBottom: 12 }}>
          No impression on file.
        </h1>
        <p style={{ fontSize: 14, lineHeight: 1.7, color: 'var(--ink-secondary)', marginBottom: 24 }}>
          Run the press once to generate probability tables and recommended interventions for this dossier.
        </p>
        <Link href={`/project/${idStr}/simulation`} className="btn-ink" style={{ display: 'inline-flex', alignItems: 'center', gap: 10 }}>
          Run the press <ArrowRight style={{ width: 14, height: 14 }} />
        </Link>
      </div>
    )
  }

  const scaledRevenue = Math.round((result.projectedRevenue * volume) / result.consumerVolume)

  const metrics = [
    {
      label: 'Conversion rate',
      value: `${result.conversionRate}%`,
      sub: `${result.confidenceInterval.low}–${result.confidenceInterval.high}% CI`,
      icon: Target,
    },
    {
      label: 'Projected revenue',
      value: `₹${(scaledRevenue / 1000).toFixed(0)}K`,
      sub: `at ${volume.toLocaleString()} agents`,
      icon: IndianRupee,
    },
    {
      label: 'Avg order value',
      value: `₹${result.averageOrderValue.toLocaleString()}`,
      sub: 'per conversion',
      icon: TrendingUp,
    },
    {
      label: 'Consumer volume',
      value: volume.toLocaleString(),
      sub: 'simulation agents',
      icon: Users,
    },
  ]

  return (
    <div style={{ padding: '36px 48px 56px', maxWidth: 1000 }}>
      <motion.div initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.45 }}>
        <header
          style={{
            display: 'flex',
            alignItems: 'flex-start',
            justifyContent: 'space-between',
            gap: 24,
            flexWrap: 'wrap',
            marginBottom: 28,
          }}
        >
          <div>
            <div
              className="kicker"
              style={{ color: 'var(--red)', marginBottom: 10, display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}
            >
              <Link href={`/project/${idStr}/simulation`} style={{ color: 'inherit', textDecoration: 'none' }}>
                At press
              </Link>
              <span style={{ color: 'var(--ink-tertiary)' }}>·</span>
              <span style={{ color: 'var(--ink-secondary)' }}>Proofs</span>
            </div>
            <h1
              className="font-serif"
              style={{
                fontSize: 'clamp(28px, 3.5vw, 40px)',
                fontWeight: 900,
                fontStyle: 'italic',
                color: 'var(--ink)',
                marginBottom: 6,
              }}
            >
              The <span style={{ color: 'var(--red)' }}>numbers</span> in brief.
            </h1>
            <p style={{ fontSize: 13, color: 'var(--ink-secondary)', fontWeight: 300 }}>{project.title}</p>
          </div>
          <div
            style={{
              border: '0.5px solid var(--ink)',
              background: 'var(--paper)',
              padding: '18px 28px',
              textAlign: 'center',
              minWidth: 140,
            }}
            className="rise"
          >
            <div className="font-serif" style={{ fontSize: 36, fontWeight: 800, fontStyle: 'italic', color: 'var(--red)', lineHeight: 1 }}>
              {result.overallConfidence}%
            </div>
            <div className="kicker" style={{ marginTop: 8, color: 'var(--ink-tertiary)' }}>
              Confidence
            </div>
          </div>
        </header>

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))',
            gap: 14,
            marginBottom: 22,
          }}
        >
          {metrics.map(({ label, value, sub, icon: Icon }, i) => (
            <motion.div
              key={label}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.06 }}
              style={{
                border: '0.5px solid var(--border-strong)',
                background: 'var(--paper)',
                padding: 20,
              }}
              className="rise"
            >
              <Icon style={{ width: 16, height: 16, color: 'var(--red)', opacity: 0.85, marginBottom: 12 }} />
              <div className="font-serif" style={{ fontSize: 22, fontWeight: 800, fontStyle: 'italic', color: 'var(--ink)', marginBottom: 4 }}>
                {value}
              </div>
              <div className="kicker" style={{ fontSize: 9, color: 'var(--ink-secondary)', marginBottom: 6 }}>
                {label}
              </div>
              <div style={{ fontSize: 11, color: 'var(--ink-tertiary)', lineHeight: 1.45 }}>{sub}</div>
            </motion.div>
          ))}
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 18, marginBottom: 22 }}>
          <div
            style={{ border: '0.5px solid var(--border-strong)', background: 'var(--paper)', padding: 24 }}
            className="rise"
          >
            <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 6 }}>
              <h3 className="font-serif" style={{ fontSize: 16, fontWeight: 800, fontStyle: 'italic', color: 'var(--ink)' }}>
                Probability spread
              </h3>
              <span className="kicker" style={{ color: 'var(--ink-tertiary)' }}>
                3 runs
              </span>
            </div>
            <p style={{ fontSize: 11, color: 'var(--ink-secondary)', marginBottom: 18, lineHeight: 1.5 }}>
              Interval {result.confidenceInterval.low}% – {result.confidenceInterval.high}%
            </p>
            <ProbabilityChart conversionRate={result.conversionRate} confidenceInterval={result.confidenceInterval} />

            <div style={{ marginTop: 22, paddingTop: 20, borderTop: '0.5px solid var(--border-color)' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
                <label className="kicker" style={{ color: 'var(--ink-secondary)' }}>
                  Adjust reader count
                </label>
                <span className="font-serif" style={{ fontSize: 15, fontWeight: 800, fontStyle: 'italic', color: 'var(--red)' }}>
                  {volume.toLocaleString()}
                </span>
              </div>
              <input
                type="range"
                min={1000}
                max={50000}
                step={500}
                value={volume}
                onChange={(e) => setVolume(Number(e.target.value))}
                style={{ width: '100%', height: 4, accentColor: 'var(--red)', cursor: 'pointer' }}
              />
            </div>
          </div>

          <div
            style={{ border: '0.5px solid var(--border-strong)', background: 'var(--paper)', padding: 24 }}
            className="rise"
          >
            <h3 className="font-serif" style={{ fontSize: 16, fontWeight: 800, fontStyle: 'italic', color: 'var(--ink)', marginBottom: 18 }}>
              Funnel bleed
            </h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              {result.funnelDropOff.map(({ stage, dropOffPercentage }) => (
                <div key={stage}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginBottom: 6, color: 'var(--ink-secondary)' }}>
                    <span>{stage}</span>
                    <span style={{ color: 'var(--red)', fontWeight: 600 }}>−{dropOffPercentage}%</span>
                  </div>
                  <div style={{ height: 3, background: 'rgba(26,23,20,0.08)', overflow: 'hidden' }}>
                    <motion.div
                      style={{ height: '100%', background: 'rgba(192,57,43,0.45)' }}
                      initial={{ width: 0 }}
                      animate={{ width: `${dropOffPercentage}%` }}
                      transition={{ duration: 0.75, delay: 0.25 }}
                    />
                  </div>
                </div>
              ))}
            </div>

            <div style={{ marginTop: 22, paddingTop: 20, borderTop: '0.5px solid var(--border-color)' }}>
              <h4 className="kicker" style={{ marginBottom: 12, color: 'var(--ink-tertiary)' }}>
                Sensitivity
              </h4>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {Object.entries(result.sensitivityAnalysis).map(([key, val]) => (
                  <div key={key} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, fontSize: 11 }}>
                    <span style={{ color: 'var(--ink-secondary)' }}>{key}</span>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <div style={{ width: 72, height: 3, background: 'rgba(26,23,20,0.08)', overflow: 'hidden' }}>
                        <div style={{ height: '100%', width: `${val * 100}%`, background: 'var(--ink)' }} />
                      </div>
                      <span style={{ color: 'var(--ink-tertiary)', width: 32, textAlign: 'right' }}>{Math.round(val * 100)}%</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>

        <section style={{ marginBottom: 28 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 14, gap: 12 }}>
            <h3 className="font-serif" style={{ fontSize: 18, fontWeight: 800, fontStyle: 'italic', color: 'var(--ink)' }}>
              Marginalia — interventions
            </h3>
            <span className="kicker" style={{ color: 'var(--ink-tertiary)' }}>
              {result.topInterventions.length} actions
            </span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 14 }}>
            {result.topInterventions.map((intervention, i) => (
              <motion.div
                key={intervention.id}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.08 }}
              >
                <InterventionCard intervention={intervention} rank={i + 1} />
              </motion.div>
            ))}
          </div>
        </section>

        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 12, flexWrap: 'wrap' }}>
          <button
            type="button"
            className="btn-ghost"
            style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}
          >
            <ChevronDown style={{ width: 14, height: 14 }} /> Export folio
          </button>
          <Link href={`/project/${idStr}/tracker`} className="btn-ink" style={{ display: 'inline-flex', alignItems: 'center', gap: 10 }}>
            Record what happened <ArrowRight style={{ width: 14, height: 14 }} />
          </Link>
        </div>
      </motion.div>
    </div>
  )
}
