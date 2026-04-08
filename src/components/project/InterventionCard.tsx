import { Intervention } from '@/types'
import { TrendingUp, Zap, Clock } from 'lucide-react'

const effortConfig = {
  LOW: { label: 'Low effort', color: 'text-emerald-400 bg-emerald-400/10 border-emerald-400/20', icon: Zap },
  MEDIUM: { label: 'Medium effort', color: 'text-amber-400 bg-amber-400/10 border-amber-400/20', icon: Clock },
  HIGH: { label: 'High effort', color: 'text-red-400 bg-red-400/10 border-red-400/20', icon: TrendingUp },
}

export default function InterventionCard({ intervention, rank }: { intervention: Intervention; rank: number }) {
  const effortKey = intervention.effortLevel ?? intervention.difficulty ?? 'MEDIUM'
  const effort = effortConfig[effortKey]
  const EffortIcon = effort.icon
  return (
    <div className="glass rounded-xl p-5 glass-hover">
      <div className="flex items-start gap-3 mb-3">
        <div className="w-6 h-6 rounded-md bg-indigo-500/20 border border-indigo-500/20 flex items-center justify-center shrink-0">
          <span className="text-indigo-400 text-xs font-700">{rank}</span>
        </div>
        <div className="flex-1">
          <h4 className="text-sm font-600 text-white mb-1">{intervention.title}</h4>
          <p className="text-xs text-slate-500 leading-relaxed">{intervention.description}</p>
        </div>
      </div>
      <div className="flex items-center justify-between">
        <span className={`flex items-center gap-1 text-xs px-2 py-0.5 rounded-full border ${effort.color}`}>
          <EffortIcon className="w-3 h-3" />{effort.label}
        </span>
        <span className="text-emerald-400 text-sm font-700 font-display">+{intervention.probabilityShift}%</span>
      </div>
    </div>
  )
}
