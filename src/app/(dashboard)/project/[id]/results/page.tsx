'use client'
import { useState, use } from 'react'
import { motion } from 'framer-motion'
import { getProjectById, getSimulationResultByProjectId } from '@/lib/mock-data'
import InterventionCard from '@/components/project/InterventionCard'
import ProbabilityChart from '@/components/project/ProbabilityChart'
import { ArrowRight, AlertCircle, TrendingUp, Users, IndianRupee, Target, ChevronDown } from 'lucide-react'
import Link from 'next/link'

export default function ResultsPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params)
  const project = getProjectById(id)
  const result = getSimulationResultByProjectId(id)
  const [volume, setVolume] = useState(result?.consumerVolume || 10000)

  if (!project || !result) return (
    <div className="p-8 flex flex-col items-center justify-center min-h-screen text-center">
      <AlertCircle className="w-10 h-10 text-slate-600 mb-3" />
      <p className="text-slate-400 text-sm">No results found for this project.</p>
      <Link href={`/project/${id}/simulation`} className="mt-4 text-indigo-400 text-sm hover:underline">
        Run simulation first
      </Link>
    </div>
  )

  const scaledRevenue = Math.round((result.projectedRevenue * volume) / result.consumerVolume)

  const metrics = [
    { label: 'Conversion rate', value: `${result.conversionRate}%`, sub: `${result.confidenceInterval.low}–${result.confidenceInterval.high}% CI`, icon: Target, color: 'text-indigo-400' },
    { label: 'Projected revenue', value: `₹${(scaledRevenue / 1000).toFixed(0)}K`, sub: `at ${volume.toLocaleString()} agents`, icon: IndianRupee, color: 'text-emerald-400' },
    { label: 'Avg order value', value: `₹${result.averageOrderValue.toLocaleString()}`, sub: 'per conversion', icon: TrendingUp, color: 'text-cyan-400' },
    { label: 'Consumer volume', value: volume.toLocaleString(), sub: 'simulation agents', icon: Users, color: 'text-amber-400' },
  ]

  return (
    <div className="p-8 max-w-5xl">
      <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }}>
        {/* Header */}
        <div className="flex items-start justify-between mb-8">
          <div>
            <div className="flex items-center gap-2 text-xs text-slate-600 mb-1.5">
              <Link href={`/project/${id}/simulation`} className="hover:text-slate-400">Simulation</Link>
              <span>/</span>
              <span className="text-slate-400">Results</span>
            </div>
            <h1 className="font-display text-2xl font-700 text-white mb-1">Simulation results</h1>
            <p className="text-slate-500 text-sm">{project.title}</p>
          </div>
          {/* Confidence score */}
          <div className="glass rounded-xl px-5 py-3 text-center">
            <div className="font-display text-3xl font-800 text-indigo-400">{result.overallConfidence}%</div>
            <div className="text-xs text-slate-500 mt-0.5">Confidence score</div>
          </div>
        </div>

        {/* Metrics grid */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
          {metrics.map(({ label, value, sub, icon: Icon, color }, i) => (
            <motion.div key={label} initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.07 }} className="glass rounded-xl p-5">
              <Icon className={`w-4 h-4 ${color} mb-3`} />
              <div className={`font-display text-2xl font-800 ${color} mb-0.5`}>{value}</div>
              <div className="text-xs text-slate-500">{label}</div>
              <div className="text-xs text-slate-600 mt-0.5">{sub}</div>
            </motion.div>
          ))}
        </div>

        <div className="grid lg:grid-cols-[3fr_2fr] gap-6 mb-6">
          {/* Chart */}
          <div className="glass rounded-2xl p-6">
            <div className="flex items-center justify-between mb-1">
              <h3 className="font-display text-sm font-600 text-white">Probability distribution</h3>
              <span className="text-xs text-slate-500">across 3 stochastic runs</span>
            </div>
            <p className="text-xs text-slate-600 mb-5">Conversion rate confidence interval: {result.confidenceInterval.low}% – {result.confidenceInterval.high}%</p>
            <ProbabilityChart conversionRate={result.conversionRate} confidenceInterval={result.confidenceInterval} />

            {/* Volume slider */}
            <div className="mt-6 pt-5 border-t border-white/5">
              <div className="flex items-center justify-between mb-2">
                <label className="text-xs text-slate-400">Adjust consumer volume</label>
                <span className="font-display text-sm font-700 text-indigo-400">{volume.toLocaleString()}</span>
              </div>
              <input type="range" min={1000} max={50000} step={500} value={volume}
                onChange={e => setVolume(Number(e.target.value))}
                className="w-full h-1.5 rounded-full appearance-none cursor-pointer accent-indigo-500 bg-white/10" />
            </div>
          </div>

          {/* Funnel drop-off */}
          <div className="glass rounded-2xl p-6">
            <h3 className="font-display text-sm font-600 text-white mb-5">Funnel drop-off</h3>
            <div className="space-y-3">
              {result.funnelDropOff.map(({ stage, dropOffPercentage }) => (
                <div key={stage}>
                  <div className="flex justify-between text-xs text-slate-400 mb-1.5">
                    <span>{stage}</span>
                    <span className="text-red-400">−{dropOffPercentage}%</span>
                  </div>
                  <div className="w-full h-1.5 bg-white/5 rounded-full overflow-hidden">
                    <motion.div className="h-full bg-red-500/50 rounded-full"
                      initial={{ width: 0 }} animate={{ width: `${dropOffPercentage}%` }}
                      transition={{ duration: 0.8, delay: 0.3 }} />
                  </div>
                </div>
              ))}
            </div>

            {/* Sensitivity */}
            <div className="mt-6 pt-5 border-t border-white/5">
              <h4 className="text-xs text-slate-500 mb-3">Sensitivity analysis</h4>
              <div className="space-y-2">
                {Object.entries(result.sensitivityAnalysis).map(([key, val]) => (
                  <div key={key} className="flex items-center justify-between text-xs">
                    <span className="text-slate-400">{key}</span>
                    <div className="flex items-center gap-2">
                      <div className="w-20 h-1 bg-white/5 rounded-full overflow-hidden">
                        <div className="h-full bg-indigo-400 rounded-full" style={{ width: `${val * 100}%` }} />
                      </div>
                      <span className="text-slate-500 w-8 text-right">{Math.round(val * 100)}%</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>

        {/* Interventions */}
        <div className="mb-8">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-display text-base font-600 text-white">Recommended interventions</h3>
            <span className="text-xs text-slate-600">{result.topInterventions.length} actions found</span>
          </div>
          <div className="grid sm:grid-cols-2 gap-3">
            {result.topInterventions.map((intervention, i) => (
              <motion.div key={intervention.id} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.1 }}>
                <InterventionCard intervention={intervention} rank={i + 1} />
              </motion.div>
            ))}
          </div>
        </div>

        {/* Footer nav */}
        <div className="flex items-center justify-end gap-3">
          <button className="flex items-center gap-2 px-4 py-2 rounded-lg glass glass-hover text-slate-400 text-sm">
            <ChevronDown className="w-3.5 h-3.5" /> Export PDF
          </button>
          <Link href={`/project/${id}/tracker`}
            className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium transition-all">
            Track real outcomes <ArrowRight className="w-4 h-4" />
          </Link>
        </div>
      </motion.div>
    </div>
  )
}
