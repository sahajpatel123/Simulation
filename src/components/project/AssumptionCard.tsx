import { Assumption, AssumptionSensitivity } from '@/types'

const sensitivityConfig = {
  [AssumptionSensitivity.LOW]: { label: 'Low', color: 'text-slate-400 bg-slate-400/10 border-slate-400/20' },
  [AssumptionSensitivity.MEDIUM]: { label: 'Medium', color: 'text-amber-400 bg-amber-400/10 border-amber-400/20' },
  [AssumptionSensitivity.HIGH]: { label: 'High', color: 'text-orange-400 bg-orange-400/10 border-orange-400/20' },
  [AssumptionSensitivity.CRITICAL]: { label: 'Critical', color: 'text-red-400 bg-red-400/10 border-red-400/20' },
}

export default function AssumptionCard({ assumption }: { assumption: Assumption }) {
  const config = sensitivityConfig[assumption.sensitivity]
  return (
    <div className="glass rounded-xl p-5 glass-hover">
      <div className="flex items-start justify-between gap-3 mb-3">
        <span className={`shrink-0 px-2 py-0.5 rounded-full text-xs border font-medium ${config.color}`}>
          {config.label}
        </span>
        {assumption.isHidden && (
          <span className="text-xs text-slate-600 bg-white/5 px-2 py-0.5 rounded-full border border-white/5">Hidden</span>
        )}
      </div>
      <p className="text-slate-200 text-sm leading-relaxed mb-3">{assumption.text}</p>
      <div className="flex items-center justify-between">
        <span className="text-xs text-slate-600 px-2 py-0.5 rounded-full bg-white/5">{assumption.category}</span>
        <div className="flex items-center gap-1.5">
          <span className="text-slate-600 text-xs">Impact</span>
          <div className="flex gap-0.5">
            {[...Array(10)].map((_, i) => (
              <div key={i} className={`w-1.5 h-1.5 rounded-full ${i < assumption.impactScore ? 'bg-indigo-400' : 'bg-white/10'}`} />
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
