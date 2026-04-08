/*
  MIGRATION STATUS — Step 33
  Replace each mock export below with the corresponding
  React Query hook as pages are wired to the real API.

  Completed:
    - getAllProjects()       → useProjects()
    - getProject(id)         → useProject(id)

  Pending (replace these as you wire each page):
    - getAssumptions(id)     → useAssumptions(id)
    - getSimulation(id)      → useSimulationResults(id)
    - getPremortem(id)       → usePremortem(id)
    - getInterventions(id)   → useInterventions(id)
    - getCompetitive(id)     → useCompetitiveAnalysis(id)
    - getOutcomes(id)        → useOutcomes(id)

  Once all pages are wired, delete this file entirely.
*/

import type {
  Project,
  Assumption,
  SimulationResult,
  Intervention,
  Environment,
  SimulationProgress,
} from '@/types'
import { SimulationStatus, AssumptionSensitivity, EnvironmentMode } from '@/types'

export const mockProjects: Project[] = [
  {
    id: "proj_1",
    userId: "user_1",
    title: "Eco-Friendly Reusable Water Bottle Store",
    description: "An online store selling premium stainless steel water bottles with custom engravings targeted at environmentally conscious millennials.",
    createdAt: new Date("2026-03-15"),
    updatedAt: new Date("2026-04-02"),
    status: SimulationStatus.ASSUMPTIONS_EXTRACTED,
    prototypeHtml: "<div>Mock Prototype for Water Bottle Store</div>",
  },
  {
    id: "proj_2",
    userId: "user_1",
    title: "AI-Powered Fitness Coaching SaaS",
    description: "Subscription platform that creates personalized workout and nutrition plans using user data and progress tracking.",
    createdAt: new Date("2026-03-20"),
    updatedAt: new Date("2026-04-01"),
    status: SimulationStatus.PROTOTYPE_GENERATED,
  },
  {
    id: "proj_3",
    userId: "user_1",
    title: "Local Handmade Jewelry Marketplace",
    description: "A platform connecting local artisans with buyers for unique handmade jewelry in tier-2 cities.",
    createdAt: new Date("2026-03-25"),
    updatedAt: new Date("2026-03-30"),
    status: SimulationStatus.ENVIRONMENT_SET,
  },
  {
    id: "proj_4",
    userId: "user_1",
    title: "Healthy Meal Kit Delivery Service",
    description: "Weekly subscription service delivering pre-portioned healthy Indian meals with easy recipes.",
    createdAt: new Date("2026-04-01"),
    updatedAt: new Date("2026-04-03"),
    status: SimulationStatus.RUNNING,
  },
]

export const mockAssumptions: Record<string, Assumption[]> = {
  "proj_1": [
    { id: "ass_1", text: "Customers will pay ₹1,499+ for a premium engraved bottle", category: "Pricing", sensitivity: AssumptionSensitivity.HIGH, impactScore: 9, isHidden: true },
    { id: "ass_2", text: "Instagram ads will be the main acquisition channel", category: "Marketing", sensitivity: AssumptionSensitivity.MEDIUM, impactScore: 7, isHidden: false },
    { id: "ass_3", text: "Target audience is 22-35 year old urban professionals", category: "User Behavior", sensitivity: AssumptionSensitivity.CRITICAL, impactScore: 10, isHidden: true },
  ],
  "proj_2": [
    { id: "ass_4", text: "Users will stick with the app for at least 6 months", category: "Retention", sensitivity: AssumptionSensitivity.HIGH, impactScore: 8, isHidden: true },
  ],
  "proj_3": [
    { id: "ass_5", text: "Artisans in tier-2 cities have reliable smartphone access", category: "Technical", sensitivity: AssumptionSensitivity.MEDIUM, impactScore: 6, isHidden: false },
  ],
  "proj_4": [
    { id: "ass_6", text: "Customers will maintain weekly subscription beyond month 2", category: "Retention", sensitivity: AssumptionSensitivity.CRITICAL, impactScore: 9, isHidden: true },
  ],
}

export const mockSimulationResults: Record<string, SimulationResult> = {
  "proj_1": {
    simulationId: "sim_001",
    projectId: "proj_1",
    runAt: new Date(),
    consumerVolume: 10000,
    conversionRate: 3.8,
    averageOrderValue: 1249,
    projectedRevenue: 474620,
    confidenceInterval: { low: 2.9, high: 4.7 },
    funnelDropOff: [
      { stage: "ARRIVE", dropOffPercentage: 12 },
      { stage: "BROWSE", dropOffPercentage: 28 },
      { stage: "CONSIDER", dropOffPercentage: 41 },
    ],
    sensitivityAnalysis: { "Pricing": 0.42, "Marketing Channel": 0.31, "Trust": 0.18 },
    topInterventions: [
      { id: "int_1", title: "Lower entry price to ₹899", description: "Introduce a basic non-engraved model at a lower price point", probabilityShift: 1.8, effortLevel: "MEDIUM" },
      { id: "int_2", title: "Add social proof on landing page", description: "Display 50+ verified reviews above the fold", probabilityShift: 0.9, effortLevel: "LOW" },
    ],
    overallConfidence: 68,
  },
  "proj_3": {
    simulationId: "sim_002",
    projectId: "proj_3",
    runAt: new Date(),
    consumerVolume: 10000,
    conversionRate: 2.1,
    averageOrderValue: 3200,
    projectedRevenue: 672000,
    confidenceInterval: { low: 1.4, high: 2.8 },
    funnelDropOff: [
      { stage: "ARRIVE", dropOffPercentage: 18 },
      { stage: "BROWSE", dropOffPercentage: 35 },
      { stage: "CONSIDER", dropOffPercentage: 52 },
    ],
    sensitivityAnalysis: { "Trust": 0.51, "Pricing": 0.28 },
    topInterventions: [
      { id: "int_3", title: "Add artisan verification badges", description: "Build trust with verified artisan profiles", probabilityShift: 2.2, effortLevel: "LOW" },
    ],
    overallConfidence: 54,
  },
}

export const mockEnvironments: Record<string, Environment> = {
  "proj_1": {
    mode: EnvironmentMode.MANUAL,
    consumerVolume: 10000,
    growthRatePerMonth: 15,
    averageOrderValue: 1249,
  },
  "proj_3": {
    mode: EnvironmentMode.MANUAL,
    consumerVolume: 10000,
    growthRatePerMonth: 8,
    averageOrderValue: 3200,
  },
}

export const mockSimulationProgress: SimulationProgress = {
  simulation_id:    3,
  status:           SimulationStatus.RUNNING,
  pct:              62,
  agents_processed: 6240,
  agents_total:     10000,
  elapsed_seconds:  46,
  task_id:          null,
  error:            null,
  results:          null,
}

export const getProjectById = (id: string): Project | undefined =>
  mockProjects.find(p => p.id === id)

export const getAssumptionsByProjectId = (projectId: string): Assumption[] =>
  mockAssumptions[projectId] || []

export const getSimulationResultByProjectId = (projectId: string): SimulationResult | undefined =>
  mockSimulationResults[projectId]

export const getEnvironmentByProjectId = (projectId: string): Environment | undefined =>
  mockEnvironments[projectId]

export const getAllProjects = (): Project[] => mockProjects
