'use client'

import React from 'react'
import { ShieldAlert, TrendingDown, TrendingUp, Zap } from 'lucide-react'
import { useSimulationStressScenarios } from '@/hooks/useSimulation'
import type { ScenarioImpactItem } from '@/types'

interface ScenarioStressMatrixProps {
  simulationId: number
}

function riskBadgeClass(level: ScenarioImpactItem['risk_level']): string {
  switch (level) {
    case 'SEVERE':
      return 'bg-rose-500/10 text-rose-400 border-rose-500/20'
    case 'HIGH':
      return 'bg-amber-500/10 text-amber-400 border-amber-500/20'
    case 'MODERATE':
      return 'bg-yellow-500/10 text-yellow-400 border-yellow-500/20'
    default:
      return 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
  }
}

export const ScenarioStressMatrix: React.FC<ScenarioStressMatrixProps> = ({ simulationId }) => {
  const { data: stressData, isLoading, isError } = useSimulationStressScenarios(simulationId)

  if (isLoading) {
    return (
      <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-6 animate-pulse space-y-4">
        <div className="h-6 w-48 bg-slate-800 rounded"></div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-32 bg-slate-800/60 rounded-lg"></div>
          ))}
        </div>
      </div>
    )
  }

  if (isError || !stressData) {
    return null
  }

  const { overall_resilience_score, scenario_impacts } = stressData

  return (
    <div className="rounded-2xl border border-slate-800/80 bg-slate-900/40 p-6 space-y-6 backdrop-blur-md">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-slate-800/80">
        <div>
          <div className="flex items-center gap-2">
            <ShieldAlert className="w-5 h-5 text-indigo-400" />
            <h3 className="text-lg font-semibold text-slate-100">Macro Stress Resilience Matrix</h3>
          </div>
          <p className="text-xs text-slate-400 mt-1">
            Simulated performance across 4 macroeconomic and competitive market disruption scenarios.
          </p>
        </div>

        <div className="flex items-center gap-3 bg-slate-950/60 px-4 py-2 rounded-xl border border-slate-800">
          <span className="text-xs font-medium text-slate-400 uppercase tracking-wider">Resilience Score</span>
          <div className="flex items-baseline gap-1">
            <span className="text-xl font-bold text-indigo-400">{overall_resilience_score}</span>
            <span className="text-xs text-slate-500">/100</span>
          </div>
        </div>
      </div>

      {/* Scenario Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {scenario_impacts.map((scenario) => {
          const isPositive = scenario.conversion_delta_pct >= 0
          return (
            <div
              key={scenario.scenario_key}
              className="group relative rounded-xl border border-slate-800 bg-slate-950/40 p-4 transition-all duration-200 hover:border-slate-700 hover:bg-slate-950/70"
            >
              <div className="flex items-start justify-between gap-2 mb-2">
                <div>
                  <h4 className="text-sm font-semibold text-slate-200 group-hover:text-white transition-colors">
                    {scenario.scenario_name}
                  </h4>
                  <p className="text-xs text-slate-400 line-clamp-2 mt-0.5">{scenario.description}</p>
                </div>
                <span
                  className={`inline-flex items-center px-2 py-0.5 text-[10px] font-semibold rounded-full border ${riskBadgeClass(
                    scenario.risk_level
                  )}`}
                >
                  {scenario.risk_level}
                </span>
              </div>

              {/* Metrics row */}
              <div className="flex items-center justify-between mt-4 pt-3 border-t border-slate-800/60 text-xs">
                <div className="text-slate-400">
                  Projected Rate:{' '}
                  <span className="font-mono text-slate-200 font-medium">
                    {(scenario.projected_conversion_rate * 100).toFixed(2)}%
                  </span>
                </div>

                <div
                  className={`flex items-center gap-1 font-mono font-semibold ${
                    isPositive ? 'text-emerald-400' : 'text-rose-400'
                  }`}
                >
                  {isPositive ? (
                    <TrendingUp className="w-3.5 h-3.5" />
                  ) : (
                    <TrendingDown className="w-3.5 h-3.5" />
                  )}
                  {isPositive ? '+' : ''}
                  {scenario.conversion_delta_pct}%
                </div>
              </div>

              {/* Recommendation */}
              <div className="mt-3 bg-slate-900/60 rounded-lg p-2.5 border border-slate-800/40 text-[11px] text-slate-300 leading-relaxed">
                <span className="text-indigo-400 font-medium flex items-center gap-1 mb-0.5">
                  <Zap className="w-3 h-3" /> Mitigation Strategy:
                </span>
                {scenario.mitigation_recommendation}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
