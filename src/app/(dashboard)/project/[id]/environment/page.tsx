'use client'
import { useState, use } from 'react'
import { motion } from 'framer-motion'
import { getProjectById, getEnvironmentByProjectId } from '@/lib/mock-data'
import { EnvironmentMode } from '@/types'
import { SlidersHorizontal, TrendingUp, Layers, ArrowRight, ArrowLeft, AlertCircle, Check } from 'lucide-react'
import Link from 'next/link'

const scenarios = [
  { id: 'base', label: 'Base Case', description: 'Normal market conditions. Average consumer sentiment and buying behavior.', tag: 'Neutral' },
  { id: 'recession', label: 'Recession', description: 'Price-sensitive consumers, reduced discretionary spend, higher churn.', tag: 'Bearish' },
  { id: 'viral', label: 'Viral Moment', description: 'Sudden traffic spike, elevated intent, compressed decision cycles.', tag: 'Bullish' },
  { id: 'competitor', label: 'Competitor Entry', description: 'New well-funded competitor enters, splits intent and reduces conversion.', tag: 'Threat' },
]

const tagColors: Record<string, string> = {
  Neutral: 'text-slate-400 bg-slate-400/10 border-slate-400/20',
  Bearish: 'text-red-400 bg-red-400/10 border-red-400/20',
  Bullish: 'text-emerald-400 bg-emerald-400/10 border-emerald-400/20',
  Threat: 'text-orange-400 bg-orange-400/10 border-orange-400/20',
}

export default function EnvironmentPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params)
  const project = getProjectById(id)
  const env = getEnvironmentByProjectId(id)

  const [mode, setMode] = useState<EnvironmentMode>(env?.mode || EnvironmentMode.MANUAL)
  const [volume, setVolume] = useState(env?.consumerVolume || 10000)
  const [growth, setGrowth] = useState(env?.growthRatePerMonth || 15)
  const [aov, setAov] = useState(env?.averageOrderValue || 1000)
  const [selectedScenario, setSelectedScenario] = useState('base')
  const [saved, setSaved] = useState(false)

  const handleSave = async () => {
    await new Promise(r => setTimeout(r, 800))
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  if (!project) return (
    <div className="p-8 flex items-center justify-center min-h-screen">
      <AlertCircle className="w-10 h-10 text-slate-600 mx-auto" />
    </div>
  )

  const tabs = [
    { mode: EnvironmentMode.MANUAL, label: 'Manual', icon: SlidersHorizontal },
    { mode: EnvironmentMode.TREND, label: 'Trend', icon: TrendingUp },
    { mode: EnvironmentMode.SCENARIO, label: 'Scenario', icon: Layers },
  ]

  return (
    <div className="p-8 max-w-3xl">
      <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }}>
        <div className="mb-8">
          <div className="flex items-center gap-2 text-xs text-slate-600 mb-1.5">
            <Link href={`/project/${id}/prototype`} className="hover:text-slate-400">Prototype</Link>
            <span>/</span>
            <span className="text-slate-400">Environment</span>
          </div>
          <h1 className="font-display text-2xl font-700 text-white mb-1">Set simulation environment</h1>
          <p className="text-slate-500 text-sm">Define the market conditions your synthetic consumers operate in.</p>
        </div>

        {/* Tab bar */}
        <div className="flex gap-1 glass rounded-xl p-1 mb-8 w-fit">
          {tabs.map(({ mode: m, label, icon: Icon }) => (
            <button key={m} onClick={() => setMode(m)}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all duration-200 ${
                mode === m ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-white'
              }`}>
              <Icon className="w-3.5 h-3.5" />{label}
            </button>
          ))}
        </div>

        {/* Manual tab */}
        {mode === EnvironmentMode.MANUAL && (
          <motion.div initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ duration: 0.3 }}
            className="space-y-6">
            {[
              { label: 'Consumer volume', value: volume, setValue: setVolume, min: 1000, max: 50000, step: 500, format: (v: number) => v.toLocaleString(), suffix: 'agents' },
              { label: 'Monthly growth rate', value: growth, setValue: setGrowth, min: 0, max: 100, step: 1, format: (v: number) => v, suffix: '%' },
              { label: 'Average order value', value: aov, setValue: setAov, min: 100, max: 50000, step: 100, format: (v: number) => `₹${v.toLocaleString()}`, suffix: '' },
            ].map(({ label, value, setValue, min, max, step, format, suffix }) => (
              <div key={label} className="glass rounded-2xl p-6">
                <div className="flex items-center justify-between mb-4">
                  <label className="text-sm font-medium text-white">{label}</label>
                  <span className="font-display text-lg font-700 text-indigo-400">{format(value)}{suffix && ` ${suffix}`}</span>
                </div>
                <input type="range" min={min} max={max} step={step} value={value}
                  onChange={e => setValue(Number(e.target.value))}
                  className="w-full h-1.5 rounded-full appearance-none cursor-pointer accent-indigo-500 bg-white/10"
                />
                <div className="flex justify-between mt-2 text-xs text-slate-600">
                  <span>{format(min)}</span><span>{format(max)}</span>
                </div>
              </div>
            ))}
          </motion.div>
        )}

        {/* Trend tab */}
        {mode === EnvironmentMode.TREND && (
          <motion.div initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ duration: 0.3 }}
            className="glass rounded-2xl p-8 text-center">
            <TrendingUp className="w-10 h-10 text-indigo-400 mx-auto mb-4 opacity-60" />
            <h3 className="font-display text-base font-600 text-white mb-2">Live market data</h3>
            <p className="text-slate-500 text-sm max-w-xs mx-auto">Trend mode pulls real market signals to auto-configure your environment. Available in Pro tier.</p>
            <div className="grid grid-cols-3 gap-3 mt-6 opacity-40 pointer-events-none">
              {['Search volume', 'Market sentiment', 'Industry CAC'].map(label => (
                <div key={label} className="glass rounded-xl p-3">
                  <div className="h-8 bg-white/10 rounded-lg mb-2" />
                  <p className="text-xs text-slate-600">{label}</p>
                </div>
              ))}
            </div>
          </motion.div>
        )}

        {/* Scenario tab */}
        {mode === EnvironmentMode.SCENARIO && (
          <motion.div initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ duration: 0.3 }}
            className="grid sm:grid-cols-2 gap-3">
            {scenarios.map(s => (
              <button key={s.id} onClick={() => setSelectedScenario(s.id)}
                className={`glass rounded-xl p-5 text-left transition-all duration-200 ${
                  selectedScenario === s.id ? 'border-indigo-500/40 bg-indigo-500/5' : 'glass-hover'
                }`}>
                <div className="flex items-center justify-between mb-2">
                  <span className="font-display text-sm font-600 text-white">{s.label}</span>
                  <span className={`text-xs px-2 py-0.5 rounded-full border ${tagColors[s.tag]}`}>{s.tag}</span>
                </div>
                <p className="text-slate-500 text-xs leading-relaxed">{s.description}</p>
              </button>
            ))}
          </motion.div>
        )}

        {/* Footer */}
        <div className="flex items-center justify-between mt-8">
          <Link href={`/project/${id}/prototype`}
            className="flex items-center gap-2 px-4 py-2 rounded-lg glass glass-hover text-slate-400 text-sm">
            <ArrowLeft className="w-3.5 h-3.5" /> Prototype
          </Link>
          <div className="flex items-center gap-3">
            <button onClick={handleSave}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all ${
                saved ? 'bg-emerald-600/20 text-emerald-400 border border-emerald-500/20' : 'glass glass-hover text-slate-300'
              }`}>
              {saved ? <><Check className="w-3.5 h-3.5" /> Saved</> : 'Save'}
            </button>
            <Link href={`/project/${id}/simulation`}
              className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium transition-all">
              Run simulation <ArrowRight className="w-4 h-4" />
            </Link>
          </div>
        </div>
      </motion.div>
    </div>
  )
}
