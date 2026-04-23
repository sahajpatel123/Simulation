'use client'

import { motion } from 'framer-motion'

import type { DomainFindingRow } from '@/components/simulation-results/types'
import { getPersona } from '@/lib/cluster-personas'

export type ClusterBreakdownMap = Record<
  string,
  { conversion_rate?: number; population_fraction?: number }
>

type DropStage = 'ARRIVE' | 'BROWSE' | 'CONSIDER' | 'DECIDE' | 'PURCHASE'

export interface KeyPersonFinding {
  cluster_id: string
  conversion_rate: number
  population_fraction: number
  drop_stage: DropStage
  primary_failure: string
  top_finding: string
  recommended_action: string
  severity: string
}

export interface KeyPersonReportProps {
  findings: DomainFindingRow[]
  clusterBreakdown: ClusterBreakdownMap
  primaryFailure: string
}

const DROP_LABELS: Record<DropStage, string> = {
  ARRIVE: 'left before even browsing',
  BROWSE: 'browsed but never really considered buying',
  CONSIDER: 'considered it but never decided',
  DECIDE: 'reached the edge of buying but walked away',
  PURCHASE: 'converted — then the product had to earn the next chapter',
}

function getDropStageLabel(stage: string): string {
  return DROP_LABELS[stage as DropStage] ?? 'dropped at an unknown stage'
}

const ARCHITECT_FIXES: Record<string, string> = {
  PricingArchitect: 'lower the price or add an EMI option',
  TrustArchitect: 'add social proof or a free trial',
  OnboardingArchitect: 'simplify onboarding to under three steps',
  MarketTimingArchitect: 'educate the market before you sell hard',
  CompetitiveDynamicsArchitect: 'build a migration path from the incumbent',
  RetentionArchitect: 'shorten time-to-value dramatically',
  DistributionChannelArchitect: 'make the product easier to reach offline',
  HealthSafetyHardwareArchitect: 'get clinical validation or a doctor partnership',
  PurchaseDecisionArchitect: 'sharpen the purchase story — risk reversal and proof at the moment of decision',
  PhysicalSensoryArchitect: 'close the gap between what they expect to feel and what the product delivers',
  PerformanceThresholdArchitect: 'meet the minimum spec bar your segment quietly compares against',
  SetupFirstUseArchitect: 'ship a first-run that succeeds without a YouTube tutorial',
  EcosystemCompatibilityArchitect: 'prove it works inside the ecosystem they already live in',
  AftersalesLifecycleArchitect: 'make post-purchase support feel as considered as the sale',
  FeatureAdoptionArchitect: 'guide people to one habit-forming action before you show the rest',
  ViralityArchitect: 'give them something worth sharing before you ask for a referral',
  MacroeconomicArchitect: 'reframe value for the economic moment they are actually in',
  DemographicInteractionArchitect: 'adapt the journey for how this segment actually discovers and decides',
  AssumptionCascadeArchitect: 'validate the riskiest assumption before it compounds downstream',
  SupportFrictionArchitect: 'remove the wait between “I need help” and “I am unstuck”',
}

function getFixLabel(finding: KeyPersonFinding): string {
  const arch = finding.primary_failure?.trim() ?? ''
  if (arch && ARCHITECT_FIXES[arch]) return ARCHITECT_FIXES[arch]
  const action = finding.recommended_action?.trim()
  if (action) return action
  return 'talk to three people in this segment and watch them use the product out loud'
}

function inferDropStage(metricAffected: string | undefined): DropStage {
  const m = (metricAffected ?? '').toLowerCase()
  if (/survival|habit_loop|viral_coefficient|core_feature_dau|organic_referral/.test(m)) return 'PURCHASE'
  if (/empty_state|bounce/.test(m)) return 'ARRIVE'
  if (/onboarding|oob_setup/.test(m)) return 'BROWSE'
  if (
    /will_pay|freemium|brand|social_proof|incumbent|category_awareness|feature_depth|problem_urgency|technology_adoption|clinical_gate|gift_purchase/.test(
      m,
    )
  )
    return 'CONSIDER'
  if (/distribution|purchase/.test(m)) return 'DECIDE'
  return 'BROWSE'
}

/** One highest-impact finding per cluster, then top 3 clusters by impact. */
function extractTopPersonas(
  findings: DomainFindingRow[],
  clusterBreakdown: ClusterBreakdownMap,
): KeyPersonFinding[] {
  const clusterImpact: Record<string, { impact: number; finding: DomainFindingRow }> = {}

  for (const f of findings) {
    const cid = f.cluster_id
    if (!cid) continue
    const rawImpact = f.conversion_impact
    const sevBonus = f.severity === 'CRITICAL' ? 0.0001 : f.severity === 'WARNING' ? 0.00005 : 0
    const imp = (typeof rawImpact === 'number' && Number.isFinite(rawImpact) ? rawImpact : 0) + sevBonus
    if (!clusterImpact[cid] || imp > clusterImpact[cid].impact) {
      clusterImpact[cid] = { impact: imp, finding: f }
    }
  }

  return Object.entries(clusterImpact)
    .sort(([, a], [, b]) => b.impact - a.impact)
    .slice(0, 3)
    .map(([cid, { finding }]) => {
      const cb = clusterBreakdown[cid] ?? {}
      const popFromFinding =
        typeof (finding as { population_fraction?: number }).population_fraction === 'number'
          ? (finding as { population_fraction?: number }).population_fraction
          : undefined
      return {
        cluster_id: cid,
        conversion_rate: cb.conversion_rate ?? 0,
        population_fraction: cb.population_fraction ?? popFromFinding ?? 0,
        drop_stage: inferDropStage((finding as { metric_affected?: string }).metric_affected),
        primary_failure: finding.architect_name ?? '',
        top_finding: finding.finding ?? '',
        recommended_action: finding.recommended_action ?? '',
        severity: finding.severity ?? 'WARNING',
      }
    })
}

export function KeyPersonReport({ findings, clusterBreakdown, primaryFailure }: KeyPersonReportProps) {
  const personas = extractTopPersonas(findings, clusterBreakdown)

  if (personas.length === 0) return null

  const serif = { fontFamily: 'var(--font-keyperson), "DM Serif Display", Georgia, serif' } as const

  return (
    <section className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="mb-1 font-mono text-[10px] uppercase tracking-[0.28em] text-blue-400/90">Key person report</p>
          <h2
            className="text-xl font-normal leading-snug tracking-tight text-white md:text-[1.65rem]"
            style={serif}
          >
            Meet the people who will decide your product&rsquo;s fate.
          </h2>
          {primaryFailure && primaryFailure !== '—' && primaryFailure !== 'unknown' && (
            <p className="mt-2 max-w-2xl text-base leading-relaxed text-slate-500 md:text-lg">
              Strongest signal in this run points to{' '}
              <span className="text-slate-300">{primaryFailure.replace(/Architect/g, '')}</span>
              {' — '}
              the thread runs through the three voices below.
            </p>
          )}
        </div>
        <p className="shrink-0 pb-0.5 font-mono text-[10px] uppercase tracking-[0.2em] text-slate-600 sm:pb-1">
          Top three highest-impact segments
        </p>
      </div>

      <div className="grid grid-cols-1 gap-5">
        {personas.map((p, i) => {
          const persona = getPersona(p.cluster_id)
          const name = persona?.firstName ?? p.cluster_id.replace(/_/g, ' ')
          const tagline = persona?.tagline ?? ''
          const desc = persona?.description ?? ''
          const reach = persona?.reachEstimate ?? ''
          const pronoun =
            persona?.gender === 'she' ? 'She' : persona?.gender === 'he' ? 'He' : persona?.gender === 'they' ? 'They' : 'They'
          const fix = getFixLabel(p)
          const dropLabel = getDropStageLabel(p.drop_stage)
          const archShort = p.primary_failure ? p.primary_failure.replace(/Architect/g, '') : 'this lens'

          return (
            <motion.article
              key={p.cluster_id}
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.12, duration: 0.45, ease: [0.2, 0.7, 0.2, 1] }}
              className={`rounded-2xl border p-6 sm:p-7 ${
                i === 0 ? 'border-blue-500/35 bg-slate-900/80' : 'border-slate-800/90 bg-slate-950/60'
              }`}
            >
              <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-start">
                <div
                  className={`flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl text-2xl ${
                    i === 0 ? 'bg-blue-500/15' : 'bg-slate-800/80'
                  }`}
                  aria-hidden
                >
                  {persona?.emoji ?? '👤'}
                </div>

                <div className="min-w-0 flex-1">
                  <div className="mb-1 flex flex-col gap-1 sm:flex-row sm:items-baseline sm:justify-between sm:gap-4">
                    <h3 className="text-lg font-normal text-white md:text-xl" style={serif}>
                      {name}
                    </h3>
                    {reach ? (
                      <span className="shrink-0 font-mono text-[11px] text-slate-500">{reach}</span>
                    ) : null}
                  </div>

                  {tagline ? (
                    <p className="mb-3 font-mono text-[11px] tracking-wide text-blue-400/95">{tagline}</p>
                  ) : null}

                  {desc ? <p className="mb-5 text-sm leading-relaxed text-slate-400">{desc}</p> : null}

                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    <div className="rounded-xl border border-red-500/20 bg-red-500/[0.06] p-4">
                      <p className="mb-2 font-mono text-[10px] uppercase tracking-[0.22em] text-red-400/95">
                        What happened
                      </p>
                      <p className="text-sm leading-relaxed text-slate-300">
                        <span className="font-semibold text-slate-100">
                          {pronoun} {dropLabel}.
                        </span>{' '}
                        {p.top_finding}
                      </p>
                      <p className="mt-2 font-mono text-[11px] text-slate-600">
                        Conversion {(p.conversion_rate * 100).toFixed(1)}% · {(p.population_fraction * 100).toFixed(1)}%
                        of weighted market
                      </p>
                    </div>

                    <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/[0.06] p-4">
                      <p className="mb-2 font-mono text-[10px] uppercase tracking-[0.22em] text-emerald-400/95">
                        One fix that changes this
                      </p>
                      <p className="text-sm font-medium leading-relaxed text-slate-100">
                        {fix.charAt(0).toUpperCase() + fix.slice(1)}.
                      </p>
                      <p className="mt-2 font-mono text-[11px] text-slate-600">via {archShort}</p>
                    </div>
                  </div>
                </div>
              </div>
            </motion.article>
          )
        })}
      </div>
    </section>
  )
}
