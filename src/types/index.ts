/* Backend-aligned status values */
export enum SimulationStatus {
  DRAFT = 'DRAFT',
  ASSUMPTIONS_EXTRACTED = 'ASSUMPTIONS_EXTRACTED',
  PROTOTYPE_GENERATED = 'PROTOTYPE_GENERATED',
  ENVIRONMENT_SET = 'ENVIRONMENT_SET',
  QUEUED = 'QUEUED',
  RUNNING = 'RUNNING',
  COMPLETED = 'COMPLETED',
  FAILED = 'FAILED',
  PREMORTEM_COMPLETE = 'PREMORTEM_COMPLETE',
  INTERVENTIONS_READY = 'INTERVENTIONS_READY',
  COMPETITIVE_ANALYSIS_COMPLETE = 'COMPETITIVE_ANALYSIS_COMPLETE',
  OUTCOME_RECORDED = 'OUTCOME_RECORDED',
}

export enum EnvironmentMode {
  MANUAL = 'MANUAL',
  TREND = 'TREND',
  SCENARIO = 'SCENARIO',
}

export enum AssumptionSensitivity {
  LOW = 'LOW',
  MEDIUM = 'MEDIUM',
  HIGH = 'HIGH',
  CRITICAL = 'CRITICAL',
}

/* ── Project ── */
export interface Project {
  id: number | string
  title: string
  description: string
  status: string
  /** New dossiers: software vs hardware axis; null/omitted = legacy (full folio) */
  dossier_axis?: string | null
  precis?: string | null
  readings_json?: string | null
  /** Title snapshot after last display-précis mint (rename detection). */
  precis_title_fingerprint?: string | null
  is_archived?: boolean
  created_at?: string
  updated_at?: string
  /* legacy compatibility */
  userId?: string
  createdAt?: Date
  updatedAt?: Date
  prototypeHtml?: string
}

/* ── Assumption ── */
export interface Assumption {
  id: number | string
  project_id?: number
  text: string
  sensitivity: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW'
  impact_score?: number
  impactScore: number
  category: string
  created_at?: string
  is_hidden?: boolean
  isHidden?: boolean
}

/* ── Environment ── */
export interface Environment {
  id?: number
  project_id?: number
  mode: EnvironmentMode
  consumer_volume?: number
  growth_rate_per_month?: number
  average_order_value?: number
  price_sensitivity?: number
  market_maturity?: number
  scenario_type?: string | null
  manual_params_json?: Record<string, number> | null
  created_at?: string
  updated_at?: string
  /* legacy compatibility */
  consumerVolume?: number
  growthRatePerMonth?: number
  averageOrderValue?: number
  manualParams?: Record<string, number>
  scenarioType?: string
}

/* ── Simulation ── */
export interface SimulationStatusResponse {
  id?: number
  project_id?: number
  status?: 'QUEUED' | 'RUNNING' | 'COMPLETED' | 'FAILED'
  consumer_volume?: number
  task_id?: string | null
  error_message?: string | null
  created_at?: string
  updated_at?: string
}

export interface SimulationResult extends SimulationStatusResponse {
  results?: SimulationResultData | null
  cluster_breakdown: Array<{
    cluster_id: string
    cluster_name: string
    conversion_rate: number
    population_fraction: number
    agent_count?: number
    segment_description?: string
  }>
  domain_findings: Array<{
    architect_name?: string
    cluster_id?: string
    cluster_name?: string
    finding: string
    recommended_action?: string
    severity?: string
    conversion_impact?: number
    metric_affected?: string
    population_fraction?: number
  }>
  primary_failure_domain: string
  highest_value_cluster: Record<string, unknown>
  architect_accountability: Record<string, number>
  product_type_detected: string
  cluster_narrative: string
  signal_quality: number | null
  user_blindspots: Array<{ type?: string; value?: string; count?: number }>
}

export interface SimulationResultData {
  mean_conversion_rate?: number
  conversion_rate?: number
  std_dev?: number
  ci_90?: { low: number; high: number }
  ci_95?: { low: number; high: number }
  total_agents?: number
  total_runs?: number
  mean_revenue?: number
  revenue_projection?: number
  confidence_score?: number
  worst_drop_off_stage?: string
  optimal_price?: number
  optimal_conversion?: number
  stage_aggregations?: StageMetric[]
  stage_metrics?: StageMetric[]
  price_curve?: PriceCurvePoint[]
  demographic_segments?: DemographicSegment[]
  insights?: Insight[]
}

export interface StageMetric {
  state: string
  agent_count?: number
  entry_rate?: number
  drop_off_rate?: number
  avg_time_seconds?: number
  mean_entry_rate?: number
  mean_drop_off_rate?: number
  mean_time_seconds?: number
}

export interface PriceCurvePoint {
  price: number
  conversion_rate: number
  revenue_per_1000_visitors: number
  is_optimal: boolean
}

export interface DemographicSegment {
  name: string
  conversion_rate: number
  count_fraction: number
  revenue_index: number
}

export interface Insight {
  severity: 'CRITICAL' | 'WARNING' | 'INFO'
  category: string
  text: string
}

/* ── Premortem ── */
export interface FailureMode {
  title: string
  probability: number
  severity: 'CRITICAL' | 'HIGH' | 'MEDIUM'
  trigger_condition: string
  linked_assumption_texts: string[]
  intervention: string
  intervention_impact: string
  earliest_signal: string
}

export interface Premortem {
  project_id: number
  failure_modes: FailureMode[]
  total: number
  critical_count: number
  generated_at: string
}

/* ── Intervention ── */
export interface Intervention {
  id: string
  title: string
  description: string
  expected_impact?: string
  probabilityShift?: number
  difficulty?: 'LOW' | 'MEDIUM' | 'HIGH'
  effortLevel?: 'LOW' | 'MEDIUM' | 'HIGH'
  estimated_cost?: string
  linked_assumption?: string | null
  linked_failure_mode?: string | null
  priority_score?: number
  time_to_implement?: string
  success_metric?: string
}

export interface Interventions {
  project_id: number
  interventions: Intervention[]
  total: number
  quick_wins: Intervention[]
  generated_at: string
  context_used: Record<string, boolean>
}

/* ── Competitive ── */
export interface Competitor {
  name: string
  category: string
  features: string[]
  pricing: string
  positioning: string
  target_segment: string
  strengths: string[]
  weaknesses: string[]
  india_presence: string
  threat_level: string
}

export interface CompetitiveAnalysis {
  project_id: number
  competitors: Competitor[]
  gap_analysis: GapAnalysis
  market_map: MarketMap
  overall_competitive_position: string
  position_rationale: string
  direct_competitor_count: number
  high_threat_count: number
  generated_at: string
}

export interface GapAnalysis {
  our_wins: string[]
  our_losses: string[]
  underserved_segments: string[]
  key_differentiators: string[]
  recommended_counter_moves: string[]
}

export interface MarketMap {
  most_dangerous_competitor: string
  easiest_to_displace: string
  most_similar_to_us: string
}

/* ── Outcome ── */
export interface OutcomeRecord {
  id?: number
  project_id?: number
  actual_conversion_rate?: number
  actual_mrr?: number
  actual_cac?: number
  actual_churn_rate?: number
  days_since_launch?: number
  notes?: string | null
  predicted_conversion_rate?: number | null
  calibration_score?: number
  recorded_at?: string | Date
  variance?: {
    conversion: number | null
    mrr: number | null
  }
  /* legacy compatibility */
  simulationId?: string
  actualConversionRate?: number
  actualRevenue?: number
  actualDropOff?: Array<{ stage: string; dropOffPercentage: number }>
}

/* ── Report preview ── */
export interface ReportPreview {
  project_id: number
  title: string
  sections: Record<string, boolean>
  simulation_runs: number
  assumptions_count: number
  outcomes_count: number
  recommended_action: string
}

/* ── Simulation progress (backend shape) ── */
export interface SimulationProgress {
  simulation_id:    number
  status:           string
  pct:              number
  agents_processed: number
  agents_total:     number
  elapsed_seconds:  number
  task_id:          string | null
  error:            string | null
  results:          SimulationResultData | null
}

/* ── Stress test ── */
export interface StressTestStatus {
  project_id: number
  status:     'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED'
  task_id:    string | null
  result:     StressTestResult | null
}

export interface StressTestResult {
  project_id:            number
  status:                string
  sensitivity_matrix:    AssumptionStressResult[]
  kill_shots:            AssumptionStressResult[]
  overall_risk_level:    string
  baseline_conversion:   number
  assumptions_tested:    number
  generated_at:          string
}

export interface AssumptionStressResult {
  assumption_id:       number
  assumption_text:     string
  sensitivity:         string
  baseline_conversion: number
  stressed_conversion: number
  delta:               number
  delta_pct:           number
  kill_shot:           boolean
  kill_shot_prob:      number
  recommendation:      string
}

/* ── Decision ── */
export interface Decision {
  id:         number
  project_id: number
  title:      string
  status:     string
  task_id:    string | null
  result: {
    scenarios:            ScenarioResult[]
    recommended_scenario: string
    winner_margin:        number
    key_insights:         string[]
    generated_at:         string
  } | null
}

export interface ScenarioResult {
  scenario_name:        string
  scenario_description: string
  conversion_rate:      number
  ci_low:               number
  ci_high:              number
  revenue_projection:   number
  survival_probability: number
  confidence_score:     number
  rank:                 number
}
