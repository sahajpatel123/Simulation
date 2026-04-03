export enum SimulationStatus {
  DRAFT = "DRAFT",
  ASSUMPTIONS_EXTRACTED = "ASSUMPTIONS_EXTRACTED",
  PROTOTYPE_GENERATED = "PROTOTYPE_GENERATED",
  ENVIRONMENT_SET = "ENVIRONMENT_SET",
  RUNNING = "RUNNING",
  COMPLETED = "COMPLETED",
  FAILED = "FAILED",
}

export enum EnvironmentMode {
  MANUAL = "MANUAL",
  TREND = "TREND",
  SCENARIO = "SCENARIO",
}

export enum AssumptionSensitivity {
  LOW = "LOW",
  MEDIUM = "MEDIUM",
  HIGH = "HIGH",
  CRITICAL = "CRITICAL",
}

export type EffortLevel = "LOW" | "MEDIUM" | "HIGH"
export type FunnelStage = "ARRIVE" | "BROWSE" | "CONSIDER" | "DECIDE" | "PURCHASE" | "ABANDON"

export interface FunnelNode {
  id: string
  label: string
  stage: FunnelStage
  expectedTimeSeconds?: number
}

export interface FunnelEdge {
  from: string
  to: string
  probability: number
  label?: string
}

export interface FunnelGraph {
  nodes: FunnelNode[]
  edges: FunnelEdge[]
}

export interface Project {
  id: string
  userId: string
  title: string
  description: string
  createdAt: Date
  updatedAt: Date
  status: SimulationStatus
  prototypeHtml?: string
  funnelGraph?: FunnelGraph
}

export interface Assumption {
  id: string
  text: string
  category: string
  sensitivity: AssumptionSensitivity
  impactScore: number
  isHidden: boolean
}

export interface Environment {
  mode: EnvironmentMode
  consumerVolume: number
  growthRatePerMonth?: number
  averageOrderValue?: number
  manualParams?: Record<string, number>
  scenarioType?: string
}

export interface ConsumerProfile {
  id: string
  demographics: {
    age: number
    income: number
    location: string
    occupation?: string
  }
  priceSensitivity: number
  intentLevel: number
  trustThreshold: number
  socialInfluence: number
}

export interface Intervention {
  id: string
  title: string
  description: string
  probabilityShift: number
  effortLevel: EffortLevel
  estimatedCost?: number
}

export interface SimulationResult {
  simulationId: string
  projectId: string
  runAt: Date
  consumerVolume: number
  conversionRate: number
  averageOrderValue: number
  projectedRevenue: number
  confidenceInterval: { low: number; high: number }
  funnelDropOff: Array<{ stage: string; dropOffPercentage: number; reason?: string }>
  sensitivityAnalysis: Record<string, number>
  topInterventions: Intervention[]
  overallConfidence: number
}

export interface OutcomeRecord {
  simulationId: string
  actualConversionRate: number
  actualRevenue: number
  actualDropOff: Array<{ stage: string; dropOffPercentage: number }>
  notes?: string
  recordedAt: Date
}

export interface SimulationProgress {
  simulationId: string
  status: SimulationStatus
  agentsCompleted: number
  totalAgents: number
  currentStage: string
  estimatedTimeRemaining: number
}

export interface ApiResponse<T> {
  success: boolean
  data?: T
  error?: string
  message?: string
}
