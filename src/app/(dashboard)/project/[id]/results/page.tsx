'use client'

import { Suspense, useMemo, useState } from 'react'
import Link from 'next/link'
import { useParams, useSearchParams } from 'next/navigation'
import { useQuery } from '@tanstack/react-query'
import { motion, AnimatePresence } from 'framer-motion'

import { KeyPersonReport } from '@/components/KeyPersonReport'
import type { ClusterBreakdownRow, DomainFindingRow, MeBlindspotRow, SimulationResultsPayload } from '@/components/simulation-results/types'
import api, { apiError } from '@/lib/api'
import { getApiV1Base } from '@/lib/api-v1-base'

type Tab = 'personas' | 'overview' | 'clusters' | 'findings' | 'funnel' | 'blindspots'

function populationWeightedConversion(
  clusters: ClusterBreakdownRow[],
  resultsJson: Record<string, unknown> | null,
): number {
  const raw = resultsJson?.population_weighted_conversion
  if (typeof raw === 'number' && Number.isFinite(raw)) return raw
  const mean = resultsJson?.mean_conversion_rate
  if (typeof mean === 'number' && Number.isFinite(mean)) return mean
  return clusters.reduce((acc, c) => acc + c.conversion_rate * c.population_fraction, 0)
}

function SimulationResultsInner() {
  const { id: projectId } = useParams<{ id: string }>()
  const searchParams = useSearchParams()
  const simulationId = searchParams.get('sim')
  const [activeTab, setActiveTab] = useState<Tab>('personas')
  const [clusterSort, setClusterSort] = useState<'conversion' | 'population'>('conversion')
  const [clusterFilter, setClusterFilter] = useState('')

  const { data: results, isLoading, isError, error } = useQuery({
    queryKey: ['sim-results', simulationId],
    queryFn: async () =>
      (await api.get<SimulationResultsPayload>(`/simulations/${simulationId}/results`)).data,
    enabled: !!simulationId,
  })

  const { data: blindspotsPayload } = useQuery({
    queryKey: ['blindspots'],
    queryFn: async () => (await api.get<{ blindspots: MeBlindspotRow[] }>('/users/me/blindspots')).data,
  })

  const findingByCluster = useMemo(() => {
    const list = results?.domain_findings
    if (!Array.isArray(list)) return new Map<string, string>()
    const m = new Map<string, string>()
    for (const f of list) {
      if (f.cluster_id && f.finding) m.set(f.cluster_id, f.finding)
    }
    return m
  }, [results])

  if (!simulationId) {
    return (
      <div className="min-h-[calc(100dvh-120px)] bg-slate-950 flex flex-col items-center justify-center gap-4 px-6">
        <p className="text-slate-500 font-mono text-sm">No simulation selected.</p>
        <p className="text-slate-600 font-mono text-xs text-center max-w-md">
          Open a completed run from your dossier (Press runs) with a results link, or append{' '}
          <code className="text-blue-400/90">?sim=</code> and the simulation id.
        </p>
        <Link
          href={`/project/${projectId}`}
          className="text-xs text-blue-400 hover:text-blue-300 font-mono tracking-widest uppercase"
        >
          ← Back to dossier
        </Link>
      </div>
    )
  }

  if (isLoading) {
    return (
      <div className="min-h-[calc(100dvh-120px)] bg-slate-950 flex flex-col items-center justify-center gap-4">
        <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
        <p className="text-slate-400 font-mono text-sm">Loading results...</p>
      </div>
    )
  }

  if (isError || !results) {
    const msg = error ? apiError(error) : ''
    return (
      <div className="min-h-[calc(100dvh-120px)] bg-slate-950 flex flex-col items-center justify-center gap-3 px-6">
        <p className="text-red-400 font-mono text-sm text-center max-w-lg">
          {msg || 'Could not load simulation results.'}
        </p>
        <Link href={`/project/${projectId}`} className="text-xs text-blue-400 font-mono">
          ← Back to dossier
        </Link>
      </div>
    )
  }

  const resultsJson = results.results
  const clusterRows = Array.isArray(results.cluster_breakdown) ? results.cluster_breakdown : []
  const conversion = populationWeightedConversion(clusterRows, resultsJson)
  const primaryFailure = results.primary_failure_domain ?? '—'
  const productType = results.product_type_detected?.trim() || '—'
  const signalQuality = results.signal_quality ?? 0
  const findings: DomainFindingRow[] = Array.isArray(results.domain_findings) ? results.domain_findings : []
  const narrative = results.cluster_narrative ?? ''
  const accountab = results.architect_accountability ?? {}
  const blindList = blindspotsPayload?.blindspots ?? []

  const clusterBreakdownMap = useMemo(() => {
    const m: Record<string, { conversion_rate: number; population_fraction: number }> = {}
    for (const row of clusterRows) {
      m[row.cluster_id] = {
        conversion_rate: row.conversion_rate ?? 0,
        population_fraction: row.population_fraction ?? 0,
      }
    }
    return m
  }, [clusterRows])
  const clusters = clusterBreakdownMap

  const cascadeFindingsSorted = useMemo(
    () =>
      [...findings]
        .filter((f) => f.architect_name === 'AssumptionCascadeArchitect')
        .sort((a, b) => (b.conversion_impact ?? 0) - (a.conversion_impact ?? 0)),
    [findings],
  )

  const topFindingByImpact = useMemo(() => {
    if (findings.length === 0) return null
    return [...findings].sort((a, b) => (b.conversion_impact ?? 0) - (a.conversion_impact ?? 0))[0]
  }, [findings])

  const clusterList = clusterRows.map((row) => ({
    cluster_id: row.cluster_id,
    cluster_name: row.cluster_name ?? row.cluster_id,
    conversion_rate: row.conversion_rate ?? 0,
    population_fraction: row.population_fraction ?? 0,
    top_finding: findingByCluster.get(row.cluster_id) ?? 'No critical findings',
    segment: row.segment_description ?? '',
  }))

  const filteredClusters = clusterList
    .filter(
      (c) =>
        c.cluster_name.toLowerCase().includes(clusterFilter.toLowerCase()) ||
        c.cluster_id.toLowerCase().includes(clusterFilter.toLowerCase()),
    )
    .sort((a, b) =>
      clusterSort === 'conversion'
        ? b.conversion_rate - a.conversion_rate
        : b.population_fraction - a.population_fraction,
    )

  const TABS: { key: Tab; label: string }[] = [
    { key: 'personas', label: 'Key People' },
    { key: 'overview', label: 'Overview' },
    { key: 'clusters', label: `Clusters (${clusterList.length})` },
    { key: 'findings', label: `Findings (${findings.length})` },
    { key: 'funnel', label: 'Funnel' },
    {
      key: 'blindspots',
      label: `Blindspots ${blindList.length > 0 ? `(${blindList.length})` : ''}`,
    },
  ]

  const severityColor = (s: string) =>
    s === 'CRITICAL' ? 'text-red-400' : s === 'WARNING' ? 'text-amber-400' : 'text-green-400'

  const severityBg = (s: string) =>
    s === 'CRITICAL'
      ? 'bg-red-500/10 border-red-500/30'
      : s === 'WARNING'
        ? 'bg-amber-500/10 border-amber-500/30'
        : 'bg-green-500/10 border-green-500/30'

  const apiV1 = getApiV1Base()
  const pdfHref = `${apiV1}/simulations/${simulationId}/report.pdf`

  return (
    <div className="min-h-[calc(100dvh-120px)] bg-slate-950 text-slate-100 font-mono">
      <div className="border-b border-slate-800 px-8 py-5">
        <div className="flex flex-wrap items-start justify-between gap-4 mb-1">
          <p className="text-xs text-blue-400 tracking-widest uppercase w-full sm:w-auto">TheCee / Simulation Results</p>
          <Link
            href={`/project/${projectId}`}
            className="text-[10px] text-slate-500 hover:text-slate-300 tracking-widest uppercase"
          >
            Dossier #{projectId}
          </Link>
        </div>
        <div className="flex items-center justify-between flex-wrap gap-4">
          <h1 className="text-xl font-bold tracking-tight">Simulation #{simulationId}</h1>
          <div className="flex items-center gap-4 flex-wrap">
            <span className="text-xs text-slate-500">{productType.replace(/_/g, ' ').toUpperCase()}</span>
            <span
              className={`text-xs px-2 py-1 rounded border ${
                signalQuality >= 0.5
                  ? 'border-green-500/40 text-green-400'
                  : signalQuality >= 0.25
                    ? 'border-amber-500/40 text-amber-400'
                    : 'border-red-500/40 text-red-400'
              }`}
            >
              Signal {signalQuality >= 0.5 ? 'FULL' : signalQuality >= 0.25 ? 'PARTIAL' : 'LOW'}{' '}
              {Math.round(signalQuality * 100)}%
            </span>
            <a
              href={pdfHref}
              className="px-3 py-1.5 text-xs bg-blue-600 hover:bg-blue-500 rounded text-white transition-all tracking-widest uppercase"
              target="_blank"
              rel="noopener noreferrer"
            >
              ↓ PDF Report
            </a>
          </div>
        </div>

        <div className="flex gap-1 mt-4 flex-wrap">
          {TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              onClick={() => setActiveTab(t.key)}
              className={`px-4 py-1.5 text-xs rounded-t tracking-wide transition-all ${
                activeTab === t.key
                  ? 'bg-slate-800 text-blue-400 border-b-2 border-blue-500'
                  : 'text-slate-500 hover:text-slate-300'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      <div className="p-8">
        <AnimatePresence mode="wait">
          {activeTab === 'personas' && (
            <motion.div
              key="personas"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              className="space-y-8"
            >
              <KeyPersonReport
                findings={findings}
                clusterBreakdown={clusters}
                primaryFailure={primaryFailure}
              />

              {cascadeFindingsSorted.length > 0 && (
                <div className="space-y-3">
                  <div>
                    <p className="mb-1 font-mono text-[10px] uppercase tracking-[0.28em] text-amber-400">
                      Assumption conflicts
                    </p>
                    <p className="text-sm text-slate-400">
                      These are internal contradictions in your product assumptions. Fix these before optimising anything
                      else.
                    </p>
                  </div>
                  {cascadeFindingsSorted.slice(0, 3).map((f, i) => (
                    <div key={i} className="rounded-xl border border-amber-500/25 bg-amber-500/[0.05] p-5">
                      <div className="flex items-start justify-between gap-4">
                        <div className="min-w-0">
                          <p className="text-sm font-medium text-white">{f.finding}</p>
                          {f.recommended_action && (
                            <p className="mt-2 font-mono text-xs text-slate-500">{f.recommended_action}</p>
                          )}
                        </div>
                        <span className="shrink-0 font-mono text-xs text-amber-400">
                          {((f.conversion_impact ?? 0) * 100).toFixed(1)}% impact
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </motion.div>
          )}

          {activeTab === 'overview' && (
            <motion.div
              key="overview"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              className="space-y-6"
            >
              {cascadeFindingsSorted.length > 0 && (
                <div className="rounded-xl border border-amber-500/25 bg-amber-500/[0.05] p-5">
                  <p className="mb-2 font-mono text-[10px] uppercase tracking-[0.28em] text-amber-400">
                    Assumption cascade
                  </p>
                  <p className="text-sm leading-relaxed text-slate-200">{cascadeFindingsSorted[0]?.finding}</p>
                  {cascadeFindingsSorted[0]?.recommended_action && (
                    <p className="mt-3 font-mono text-xs text-slate-500">
                      {cascadeFindingsSorted[0].recommended_action}
                    </p>
                  )}
                </div>
              )}

              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
                {[
                  {
                    label: 'Primary conflict',
                    value:
                      cascadeFindingsSorted[0]?.finding ??
                      (findings.length === 0 ? '—' : 'No cascade conflicts flagged'),
                    sub: 'AssumptionCascade — top signal',
                    valueClass: 'text-base font-semibold leading-snug text-slate-100 line-clamp-6',
                  },
                  {
                    label: 'Highest impact fix',
                    value: topFindingByImpact?.recommended_action ?? '—',
                    sub: topFindingByImpact
                      ? `${topFindingByImpact.architect_name?.replace(/Architect/g, '') ?? 'Finding'} · top impact`
                      : 'from highest-impact finding',
                    valueClass: 'text-base font-semibold leading-snug text-blue-400 line-clamp-6',
                  },
                  {
                    label: 'Conversion rate',
                    value: `${(conversion * 100).toFixed(1)}%`,
                    sub: 'population weighted',
                    valueClass: 'text-2xl font-bold text-blue-400',
                  },
                  {
                    label: 'Critical findings',
                    value: `${findings.filter((f) => f.severity === 'CRITICAL').length}`,
                    sub: 'need action',
                    valueClass: 'text-2xl font-bold text-blue-400',
                  },
                ].map((kpi) => (
                  <div key={kpi.label} className="rounded-xl border border-slate-800 bg-slate-900 p-5">
                    <p className="mb-2 text-xs uppercase tracking-widest text-slate-500">{kpi.label}</p>
                    <p className={kpi.valueClass}>{kpi.value}</p>
                    <p className="mt-1 text-xs text-slate-600">{kpi.sub}</p>
                  </div>
                ))}
              </div>

              <div>
                <p className="mb-2 font-mono text-[10px] uppercase tracking-[0.28em] text-slate-500">Drop analysis</p>
                <div className="rounded-xl border border-slate-800 bg-slate-900/80 p-5">
                  <p className="text-sm text-slate-300">
                    Weighted conversion sits at{' '}
                    <span className="font-semibold text-white">{(conversion * 100).toFixed(1)}%</span>. The strongest
                    structural drag in this run maps to{' '}
                    <span className="text-slate-100">{primaryFailure.replace(/Architect/g, '')}</span>
                    {clusterList.length > 0 ? (
                      <>
                        {' '}
                        across <span className="text-slate-200">{clusterList.length}</span> analysed segments (52
                        archetypes in the model).
                      </>
                    ) : null}
                  </p>
                  <ul className="mt-4 space-y-2 border-t border-slate-800 pt-4">
                    {[...findings]
                      .sort((a, b) => (b.conversion_impact ?? 0) - (a.conversion_impact ?? 0))
                      .slice(0, 3)
                      .map((f, i) => (
                        <li key={i} className="text-xs leading-relaxed text-slate-500">
                          <span className="text-slate-400">
                            {f.architect_name?.replace(/Architect/g, '') ?? 'Finding'}
                          </span>
                          {' — '}
                          {f.finding}
                        </li>
                      ))}
                    {findings.length === 0 && (
                      <li className="text-xs text-slate-600">No ranked findings for this run.</li>
                    )}
                  </ul>
                </div>
              </div>

              {Object.keys(accountab).length > 0 && (
                <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
                  <p className="text-xs text-slate-500 tracking-widest uppercase mb-4">Architect Accountability</p>
                  <div className="space-y-2">
                    {Object.entries(accountab as Record<string, number>)
                      .sort(([, a], [, b]) => b - a)
                      .slice(0, 6)
                      .map(([arch, score]) => (
                        <div key={arch} className="flex items-center gap-3">
                          <span className="text-xs text-slate-400 w-48 truncate">
                            {arch.replace(/Architect/g, '')}
                          </span>
                          <div className="flex-1 h-1.5 bg-slate-800 rounded-full overflow-hidden">
                            <div
                              className="h-full bg-blue-500 rounded-full transition-all"
                              style={{ width: `${Math.min(100, score * 100)}%` }}
                            />
                          </div>
                          <span className="text-xs text-slate-500 w-10 text-right">{(score * 100).toFixed(0)}%</span>
                        </div>
                      ))}
                  </div>
                </div>
              )}

              {narrative && (
                <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
                  <p className="text-xs text-slate-500 tracking-widest uppercase mb-3">Cluster Narrative</p>
                  <div className="space-y-1">
                    {narrative
                      .split('\n')
                      .filter(Boolean)
                      .map((line: string, i: number) => (
                        <p key={i} className="text-sm text-slate-300 leading-relaxed">
                          {line}
                        </p>
                      ))}
                  </div>
                </div>
              )}
            </motion.div>
          )}

          {activeTab === 'clusters' && (
            <motion.div
              key="clusters"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              className="space-y-4"
            >
              <div className="flex flex-wrap items-center gap-4">
                <input
                  value={clusterFilter}
                  onChange={(e) => setClusterFilter(e.target.value)}
                  placeholder="Filter clusters..."
                  className="bg-slate-900 border border-slate-800 rounded px-3 py-2 text-sm text-slate-200 placeholder-slate-600 focus:border-blue-500 focus:outline-none w-full sm:w-64"
                />
                <div className="flex gap-1">
                  {(['conversion', 'population'] as const).map((s) => (
                    <button
                      key={s}
                      type="button"
                      onClick={() => setClusterSort(s)}
                      className={`px-3 py-1.5 text-xs rounded transition-all ${
                        clusterSort === s
                          ? 'bg-blue-600 text-white'
                          : 'text-slate-500 border border-slate-800 hover:text-slate-300'
                      }`}
                    >
                      Sort: {s}
                    </button>
                  ))}
                </div>
                <span className="text-xs text-slate-600 ml-auto">{filteredClusters.length} clusters</span>
              </div>

              <div className="grid grid-cols-1 gap-2">
                {filteredClusters.length === 0 ? (
                  <p className="text-slate-600 text-sm">No clusters match this filter.</p>
                ) : (
                  filteredClusters.map((c, i) => (
                    <div
                      key={c.cluster_id}
                      className="bg-slate-900 border border-slate-800 rounded-lg px-5 py-4 hover:border-slate-700 transition-all grid grid-cols-12 gap-4 items-center"
                    >
                      <span className="col-span-1 text-xs text-slate-600">{i + 1}</span>
                      <div className="col-span-4 min-w-0">
                        <p className="text-sm text-slate-200 truncate">{c.cluster_name}</p>
                        <p className="text-xs text-slate-600 mt-0.5 truncate">{c.cluster_id}</p>
                      </div>
                      <div className="col-span-3 flex items-center gap-2 min-w-0">
                        <div className="flex-1 h-1.5 bg-slate-800 rounded-full overflow-hidden">
                          <div
                            className={`h-full rounded-full transition-all ${
                              c.conversion_rate > 0.3
                                ? 'bg-green-500'
                                : c.conversion_rate > 0.1
                                  ? 'bg-blue-500'
                                  : c.conversion_rate > 0.03
                                    ? 'bg-amber-500'
                                    : 'bg-red-500'
                            }`}
                            style={{ width: `${Math.min(100, c.conversion_rate * 100)}%` }}
                          />
                        </div>
                        <span className="text-xs font-bold text-slate-300 w-10 text-right shrink-0">
                          {(c.conversion_rate * 100).toFixed(1)}%
                        </span>
                      </div>
                      <div className="col-span-2 text-center">
                        <span className="text-xs text-slate-400">{(c.population_fraction * 100).toFixed(1)}%</span>
                        <p className="text-xs text-slate-600">of market</p>
                      </div>
                      <div className="col-span-2 min-w-0">
                        <p className="text-xs text-slate-500 truncate" title={c.top_finding}>
                          {c.top_finding}
                        </p>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </motion.div>
          )}

          {activeTab === 'findings' && (
            <motion.div
              key="findings"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              className="space-y-3"
            >
              {findings.length === 0 ? (
                <p className="text-slate-600 text-sm">No findings available.</p>
              ) : (
                findings.map((f: DomainFindingRow, i: number) => (
                  <div key={i} className={`border rounded-xl p-5 ${severityBg(f.severity ?? 'INFO')}`}>
                    <div className="flex items-start justify-between gap-4">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-3 mb-2 flex-wrap">
                          <span className={`text-xs font-bold tracking-widest ${severityColor(f.severity ?? 'INFO')}`}>
                            {f.severity ?? 'INFO'}
                          </span>
                          <span className="text-xs text-slate-500 truncate">
                            {f.architect_name?.replace(/Architect/g, '')} · {f.cluster_name}
                          </span>
                        </div>
                        <p className="text-sm text-slate-200">{f.finding}</p>
                        {f.recommended_action && (
                          <p className="text-xs text-slate-500 mt-2">{f.recommended_action}</p>
                        )}
                      </div>
                      <div className="text-right shrink-0">
                        <p className="text-xs text-slate-500">Impact</p>
                        <p className="text-lg font-bold text-blue-400">
                          {((f.conversion_impact ?? 0) * 100).toFixed(1)}%
                        </p>
                      </div>
                    </div>
                  </div>
                ))
              )}
            </motion.div>
          )}

          {activeTab === 'funnel' && (
            <motion.div
              key="funnel"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              className="space-y-4"
            >
              <p className="text-xs text-slate-500">
                Funnel data loads from the UI simulation run. Run a UI simulation first to see stage-level drop-off.
              </p>
              <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
                <p className="text-xs text-slate-500 tracking-widest uppercase mb-4">Overall Funnel (Markov model)</p>
                {[
                  { stage: 'ARRIVE', rate: 1.0 },
                  { stage: 'BROWSE', rate: Math.min(0.95, conversion * 6) },
                  { stage: 'CONSIDER', rate: Math.min(0.85, conversion * 4) },
                  { stage: 'DECIDE', rate: Math.min(0.7, conversion * 2.5) },
                  { stage: 'PURCHASE', rate: conversion },
                ].map((s, i, arr) => (
                  <div key={s.stage} className="flex items-center gap-4 mb-3">
                    <span className="text-xs text-slate-500 w-20 shrink-0">{s.stage}</span>
                    <div className="flex-1 h-6 bg-slate-800 rounded relative overflow-hidden min-w-0">
                      <div
                        className="h-full bg-blue-600 rounded transition-all"
                        style={{ width: `${s.rate * 100}%` }}
                      />
                      <span className="absolute right-2 top-1 text-xs text-slate-300">{(s.rate * 100).toFixed(1)}%</span>
                    </div>
                    {i > 0 && (
                      <span className="text-xs text-red-400 w-14 text-right shrink-0">
                        -{((arr[i - 1].rate - s.rate) * 100).toFixed(1)}%
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </motion.div>
          )}

          {activeTab === 'blindspots' && (
            <motion.div
              key="blindspots"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              className="space-y-3"
            >
              {blindList.length === 0 ? (
                <div className="bg-slate-900 border border-slate-800 rounded-xl p-8 text-center">
                  <p className="text-slate-500 text-sm">No blindspots detected yet.</p>
                  <p className="text-slate-700 text-xs mt-2">Run 3+ simulations to unlock personal pattern detection.</p>
                </div>
              ) : (
                blindList.map((b: MeBlindspotRow, i: number) => (
                  <div key={i} className="bg-amber-500/5 border border-amber-500/20 rounded-xl p-5">
                    <div className="flex items-start justify-between gap-4">
                      <div className="min-w-0">
                        <span className="text-xs text-amber-400 tracking-widest uppercase">
                          {b.type?.replace(/_/g, ' ')}
                        </span>
                        <p className="text-sm text-slate-200 mt-1">{b.value}</p>
                        {b.description && <p className="text-xs text-slate-500 mt-1">{b.description}</p>}
                      </div>
                      <span className="text-xs text-slate-600 shrink-0">seen {b.occurrence_count ?? 0}×</span>
                    </div>
                  </div>
                ))
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  )
}

function ResultsFallback() {
  return (
    <div className="min-h-[calc(100dvh-120px)] bg-slate-950 flex flex-col items-center justify-center gap-4">
      <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
      <p className="text-slate-400 font-mono text-sm">Loading…</p>
    </div>
  )
}

export default function SimulationResultsPage() {
  return (
    <Suspense fallback={<ResultsFallback />}>
      <SimulationResultsInner />
    </Suspense>
  )
}
