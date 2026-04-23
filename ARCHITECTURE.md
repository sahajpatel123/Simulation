# TheCee — Architecture Reference

## Conductor → Architect → Cluster Flow

```
Founder Input
     │
     ▼
AssumptionExtractor (Claude)
     │  extracts claims with confidence tags
     ▼
Conductor.run()
     │
     ├── For each of 52 clusters:
     │       │
     │       ├── CognitiveState mutations applied
     │       │     trust_delta  (brand_deficit < 0.50, no free trial)
     │       │     frustration  (will_pay < 0.20, steps < 4)
     │       │     intent_clarity (category_awareness < 0.35)
     │       │
     │       ├── 20 Architects compute() in dependency order:
     │       │     MarketTimingArchitect
     │       │     CompetitiveDynamicsArchitect
     │       │     TrustArchitect         ← mutations applied here
     │       │     PricingArchitect
     │       │     OnboardingArchitect
     │       │     ViralityArchitect
     │       │     RetentionArchitect
     │       │     ... (remaining 13)
     │       │
     │       └── Markov transition matrix built from outputs
     │             → conversion_rate per cluster
     │
     ▼
AccountabilityEngine
     │  attributes conversion delta to architects
     ▼
ClusterRunSummary stored per cluster
     │
     ▼
Results: cluster_breakdown, domain_findings,
         primary_failure_domain, architect_accountability
```

## Learning System Layer

```
Simulation completes
     │
     ├── Signal Quality Score computed
     │     (assumption confidence distribution)
     │     < 0.25 → quarantine (no calibration write)
     │     0.25-0.50 → partial write
     │     > 0.50 → full calibration write
     │
     ├── User layer (activates after 3 founder outcomes)
     │     user_claim_accuracy_profiles
     │     user_market_blindspots
     │     user_simulation_accuracy_history
     │     ← corrections apply only to this user's sims
     │     ← NEVER touches global cluster_parameters
     │
     └── Global layer (15+ effective samples required)
           cluster_parameters.calibrated_value updated
           AccountabilityEngine benchmarks adjusted
           Accuracy score published to landing page
```

## CognitiveState Mutation Flow

```
Per cluster, after MarketTiming + Competitive architects:

agent_profile (8 trait dimensions)
     │
     ▼
CognitiveStateMutator.apply()
     │
     ├── trust_delta trigger:
     │     brand_deficit_multiplier < 0.50
     │     AND no free trial in assumptions
     │     → trust trait -= 0.15
     │
     ├── frustration trigger:
     │     will_pay_probability < 0.20
     │     AND progressive_disclosure_limit < 4
     │     → patience_score -= 0.20
     │
     └── intent_clarity trigger:
           category_awareness_score < 0.35
           → motivation -= 0.12

Rules:
  Max total mutation per trait: -0.35
  Trait floor: 0.05 (never below)
  Mutations stack across triggers
  Logged in ClusterRunSummary.architect_scores
     as CognitiveState_trust_delta etc.
     │
     ▼
mutated_profile passed to remaining architects
```

## Hardware Simulation Flow

```
Hardware product created
     │
     ├── Step 70-71: Semantic spec JSON generated (Claude)
     ├── Step 73:    Material properties looked up
     ├── Step 74:    Test configs selected by category
     ├── Step 75:    Physics simulation (pure Python)
     ├── Step 76:    Results stored, top 3 failures identified
     ├── Step 78:    BOM + manufacturing cost + viability verdict
     ├── Step 79:    Consumer simulation (52-cluster Conductor)
     │               If generated_ui_id exists:
     │               → BrowserPool sessions against prototype
     │               → Prototype loop closed
     └── Step 81:    Hardware PDF report
```

## Intake Mode → Confidence Mapping

```
IDEA        → DESIGN_INTENT       (default, no validation)
MID_BUILD   → VALIDATED_INTERNAL  (features shipped, claims credible)
PRE_LAUNCH  → VALIDATED_EXTERNAL  (pricing, live URL available)

Higher confidence = lower simulation penalty on assumptions
= higher starting trust in architect outputs
```

## Database Tables Reference

```
Core:
  users, projects, simulations, assumptions
  cluster_run_summaries, architect_run_logs

UI simulation:
  generated_uis, ui_simulation_runs
  ui_simulation_sessions

Hardware:
  hardware_products, hardware_3d_models
  hardware_test_configs, hardware_test_results
  hardware_manufacturing_estimates
  hardware_consumer_simulation_runs

Learning:
  user_claim_accuracy_profiles
  user_market_blindspots
  user_simulation_accuracy_history
  cluster_parameters

Auth + billing:
  refresh_tokens
  users.subscription_tier
  users.razorpay_subscription_id
```
