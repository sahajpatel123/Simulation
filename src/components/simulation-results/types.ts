/** Mirrors `SimulationResultOut` from the FastAPI backend. */
export interface SimulationResultsPayload {
  id: number
  project_id: number
  status: string
  consumer_volume: number
  results: Record<string, unknown> | null
  error_message: string | null
  created_at: string
  updated_at: string
  cluster_breakdown: ClusterBreakdownRow[]
  domain_findings: DomainFindingRow[]
  primary_failure_domain: string
  highest_value_cluster: Record<string, unknown>
  architect_accountability: Record<string, number>
  product_type_detected: string
  cluster_narrative: string
  signal_quality: number | null
  user_blindspots: Array<{ type?: string; value?: string; count?: number }>
}

export interface ClusterBreakdownRow {
  cluster_id: string
  cluster_name: string
  conversion_rate: number
  population_fraction: number
  agent_count?: number
  segment_description?: string
}

export interface DomainFindingRow {
  architect_name?: string
  cluster_id?: string
  cluster_name?: string
  finding: string
  recommended_action?: string
  severity?: string
  conversion_impact?: number
  metric_affected?: string
  population_fraction?: number
}

export interface MeBlindspotRow {
  type?: string
  value?: string
  occurrence_count?: number
  description?: string
  first_seen?: string | null
}
