"use client"

import { useState } from "react"
import { motion, AnimatePresence } from "framer-motion"

import { useIsMobile } from "@/hooks/useIsMobile"

export interface FailurePoint {
  component_id: string
  reason: string
  severity: "CRITICAL" | "WARNING" | "INFO"
  test_type?: string
  recommended_fix?: string
}

export interface TestResult {
  test_type: string
  status: string
  pass_rate: number
  severity: string
  failure_points: FailurePoint[]
  metrics: Record<string, unknown>
}

export interface Component {
  id: string
  name: string
  material: string
  zone: string
  volume_cm3: number
  stress_rating: number
  cluster_id?: string
}

export interface RenderHints {
  primary_shape: string
  dominant_material: string
  color_hex: string
  highlight_zones: string[]
}

export interface HardwareSpec {
  product_name?: string
  dimensions?: {
    length_mm: number
    width_mm: number
    height_mm: number
    weight_grams: number
  }
  components: Component[]
  render_hints?: RenderHints
}

export interface HardwareFailureMapProps {
  spec: HardwareSpec
  testResults: TestResult[]
  className?: string
}

const ZONE_POSITIONS: Record<string, { x: number; y: number; w: number; h: number }> = {
  top: { x: 60, y: 20, w: 280, h: 60 },
  shell: { x: 20, y: 20, w: 360, h: 260 },
  core: { x: 80, y: 100, w: 240, h: 120 },
  bottom: { x: 60, y: 220, w: 280, h: 60 },
  left: { x: 20, y: 60, w: 60, h: 180 },
  right: { x: 320, y: 60, w: 60, h: 180 },
}

const DEFAULT_ZONE = { x: 100, y: 100, w: 200, h: 100 }

const SEVERITY_COLORS = {
  CRITICAL: {
    fill: "#ef444430",
    stroke: "#ef4444",
    badge: "#ef4444",
    text: "text-red-400",
  },
  WARNING: {
    fill: "#f59e0b25",
    stroke: "#f59e0b",
    badge: "#f59e0b",
    text: "text-amber-400",
  },
  INFO: {
    fill: "#3b82f615",
    stroke: "#3b82f6",
    badge: "#3b82f6",
    text: "text-blue-400",
  },
} as const

const PULSE_KEYFRAMES = `
@keyframes hwPulse {
  0%, 100% { opacity: 0.3; }
  50%       { opacity: 0.8; }
}
`

export function HardwareFailureMap({
  spec,
  testResults,
  className = "",
}: HardwareFailureMapProps) {
  const isMobile = useIsMobile()
  const [hoveredComponent, setHoveredComponent] = useState<string | null>(null)
  const [selectedTest, setSelectedTest] = useState<string | null>(null)

  const failureIndex: Record<string, FailurePoint & { test_type: string }> = {}
  const SEVERITY_RANK = { CRITICAL: 0, WARNING: 1, INFO: 2 }

  for (const result of testResults) {
    if (selectedTest && result.test_type !== selectedTest) continue
    for (const fp of result.failure_points) {
      const existing = failureIndex[fp.component_id]
      const newRank = SEVERITY_RANK[fp.severity as keyof typeof SEVERITY_RANK] ?? 2
      const oldRank = existing
        ? SEVERITY_RANK[existing.severity as keyof typeof SEVERITY_RANK] ?? 2
        : 99
      if (!existing || newRank < oldRank) {
        failureIndex[fp.component_id] = {
          ...fp,
          test_type: result.test_type,
          recommended_fix: fp.recommended_fix ?? result.test_type,
        }
      }
    }
  }

  const hoveredFailure = hoveredComponent ? failureIndex[hoveredComponent] : null

  const criticalCount = Object.values(failureIndex).filter((f) => f.severity === "CRITICAL").length
  const warningCount = Object.values(failureIndex).filter((f) => f.severity === "WARNING").length
  const passedTests = testResults.filter((r) => r.status === "PASS").length

  const shape = spec.render_hints?.primary_shape ?? "box"
  const productColor = spec.render_hints?.color_hex ?? "#1e293b"

  const componentListItems = spec.components.map((comp) => {
    const failure = failureIndex[comp.id]
    const colors = failure
      ? SEVERITY_COLORS[failure.severity as keyof typeof SEVERITY_COLORS]
      : null
    const isHov = hoveredComponent === comp.id
    const failBorder =
      failure?.severity === "CRITICAL"
        ? "border-red-500/30 bg-red-500/5"
        : failure
          ? "border-amber-500/30 bg-amber-500/5"
          : ""

    return (
      <div
        key={comp.id}
        className={`rounded-lg px-3 py-2.5 cursor-pointer border transition-all ${
          isHov
            ? "border-blue-500/50 bg-blue-500/5"
            : failure
              ? failBorder
              : "border-slate-800 hover:border-slate-700"
        }`}
        onMouseEnter={() => setHoveredComponent(comp.id)}
        onMouseLeave={() => setHoveredComponent(null)}
      >
        <div className="flex items-center justify-between">
          <span className="text-xs text-slate-300 truncate max-w-[130px]">{comp.name}</span>
          {failure ? (
            <span className={`text-xs font-mono font-bold ${colors!.text}`}>
              {failure.severity.slice(0, 4)}
            </span>
          ) : (
            <span className="text-xs text-green-500">✓</span>
          )}
        </div>
        <p className="text-xs text-slate-600 mt-0.5">{comp.material}</p>
      </div>
    )
  })

  return (
    <div className={`bg-slate-950 rounded-2xl overflow-hidden ${className}`}>
      <style>{PULSE_KEYFRAMES}</style>

      <div className="border-b border-slate-800 px-5 py-4 flex items-center justify-between">
        <div>
          <p className="text-xs font-mono tracking-widest uppercase text-slate-500 mb-1">
            Failure Analysis
          </p>
          <h3 className="text-sm font-bold text-white">{spec.product_name ?? "Hardware Product"}</h3>
        </div>
        <div className="flex items-center gap-3">
          {criticalCount > 0 && (
            <span className="px-2 py-1 rounded text-xs font-mono bg-red-500/10 text-red-400 border border-red-500/30">
              {criticalCount} CRITICAL
            </span>
          )}
          {warningCount > 0 && (
            <span className="px-2 py-1 rounded text-xs font-mono bg-amber-500/10 text-amber-400 border border-amber-500/30">
              {warningCount} WARNING
            </span>
          )}
          <span className="px-2 py-1 rounded text-xs font-mono bg-green-500/10 text-green-400 border border-green-500/30">
            {passedTests}/{testResults.length} PASSED
          </span>
        </div>
      </div>

      {testResults.length > 1 && (
        <div className="flex gap-1 px-5 py-2 border-b border-slate-800 overflow-x-auto">
          <button
            type="button"
            onClick={() => setSelectedTest(null)}
            className={`px-3 py-1 text-xs font-mono rounded whitespace-nowrap transition-all ${
              !selectedTest ? "bg-slate-700 text-white" : "text-slate-500 hover:text-slate-300"
            }`}
          >
            All Tests
          </button>
          {testResults.map((r) => (
            <button
              type="button"
              key={r.test_type}
              onClick={() => setSelectedTest(selectedTest === r.test_type ? null : r.test_type)}
              className={`px-3 py-1 text-xs font-mono rounded whitespace-nowrap transition-all ${
                selectedTest === r.test_type
                  ? "bg-slate-700 text-white"
                  : r.status === "FAIL"
                    ? "text-red-400 hover:text-red-300"
                    : r.status === "PARTIAL"
                      ? "text-amber-400 hover:text-amber-300"
                      : "text-green-400 hover:text-green-300"
              }`}
            >
              {r.test_type.replace(/_/g, " ")} {r.status === "PASS" ? "✓" : r.status === "FAIL" ? "✗" : "~"}
            </button>
          ))}
        </div>
      )}

      <div className="flex flex-col md:flex-row">
        <div className="relative flex-1 p-6">
          <div
            className="absolute inset-0 pointer-events-none"
            style={{
              background: `
                linear-gradient(rgba(30,58,94,0.15) 1px, transparent 1px),
                linear-gradient(90deg, rgba(30,58,94,0.15) 1px, transparent 1px)
              `,
              backgroundSize: "24px 24px",
            }}
          />

          <svg
            viewBox="0 0 400 300"
            className="w-full max-w-lg mx-auto relative z-10"
            xmlns="http://www.w3.org/2000/svg"
          >
            {shape === "cylinder" ? (
              <ellipse
                cx="200"
                cy="150"
                rx="160"
                ry="100"
                fill={productColor}
                stroke="#334155"
                strokeWidth="1.5"
                opacity="0.6"
              />
            ) : shape === "flat" ? (
              <rect
                x="40"
                y="90"
                width="320"
                height="120"
                rx="8"
                fill={productColor}
                stroke="#334155"
                strokeWidth="1.5"
                opacity="0.6"
              />
            ) : (
              <>
                <rect
                  x="40"
                  y="60"
                  width="280"
                  height="200"
                  rx="6"
                  fill={productColor}
                  stroke="#334155"
                  strokeWidth="1.5"
                  opacity="0.7"
                />
                <polygon
                  points="40,60 100,20 380,20 320,60"
                  fill={productColor}
                  stroke="#334155"
                  strokeWidth="1.5"
                  opacity="0.5"
                />
                <polygon
                  points="320,60 380,20 380,220 320,260"
                  fill={productColor}
                  stroke="#1e293b"
                  strokeWidth="1.5"
                  opacity="0.4"
                />
              </>
            )}

            {spec.components.map((comp) => {
              const zonePos = ZONE_POSITIONS[comp.zone] ?? DEFAULT_ZONE
              const failure = failureIndex[comp.id]
              const isHovered = hoveredComponent === comp.id
              const colors = failure
                ? SEVERITY_COLORS[failure.severity as keyof typeof SEVERITY_COLORS]
                : null

              return (
                <g key={comp.id}>
                  <rect
                    x={zonePos.x}
                    y={zonePos.y}
                    width={zonePos.w}
                    height={zonePos.h}
                    rx="4"
                    fill={failure ? colors!.fill : isHovered ? "#3b82f615" : "transparent"}
                    stroke={failure ? colors!.stroke : isHovered ? "#3b82f6" : "#334155"}
                    strokeWidth={failure ? (isHovered ? 2.5 : 1.5) : 0.8}
                    strokeDasharray={failure ? undefined : "4 2"}
                    style={{
                      animation:
                        failure?.severity === "CRITICAL" && !isHovered
                          ? "hwPulse 2s ease-in-out infinite"
                          : "none",
                    }}
                    className="cursor-pointer transition-all duration-200"
                    onMouseEnter={() => setHoveredComponent(comp.id)}
                    onMouseLeave={() => setHoveredComponent(null)}
                  />

                  <text
                    x={zonePos.x + zonePos.w / 2}
                    y={zonePos.y + zonePos.h / 2 + 4}
                    textAnchor="middle"
                    fontSize="9"
                    fontFamily="monospace"
                    fill={failure ? colors!.stroke : "#64748b"}
                    className="pointer-events-none select-none"
                  >
                    {comp.name.length > 14 ? `${comp.name.slice(0, 12)}…` : comp.name}
                  </text>

                  {failure && (
                    <circle
                      cx={zonePos.x + zonePos.w - 10}
                      cy={zonePos.y + 10}
                      r="6"
                      fill={colors!.badge}
                      className="pointer-events-none"
                    />
                  )}

                  {isHovered && failure && (
                    <line
                      x1={zonePos.x + zonePos.w / 2}
                      y1={zonePos.y}
                      x2={zonePos.x + zonePos.w / 2}
                      y2={Math.max(10, zonePos.y - 20)}
                      stroke={colors!.stroke}
                      strokeWidth="1"
                      strokeDasharray="3 2"
                    />
                  )}
                </g>
              )
            })}

            {spec.dimensions && (
              <text x="200" y="290" textAnchor="middle" fontSize="7" fontFamily="monospace" fill="#475569">
                {spec.dimensions.length_mm}mm × {spec.dimensions.width_mm}mm · {spec.dimensions.weight_grams}g
              </text>
            )}
          </svg>
        </div>

        <div
          className={`hidden w-64 flex-shrink-0 space-y-2 overflow-y-auto border-l border-slate-800 p-4 max-h-96 md:block`}
        >
          <p className="mb-3 text-xs font-mono tracking-widest text-slate-600 uppercase">Components</p>
          {componentListItems}
        </div>
      </div>

      {isMobile && (
        <div className="space-y-2 border-t border-slate-800 p-4 md:hidden">
          <p className="mb-1 text-xs font-mono tracking-widest text-slate-600 uppercase">Components</p>
          {componentListItems}
        </div>
      )}

      <AnimatePresence>
        {hoveredComponent && hoveredFailure && (
          <motion.div
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 4 }}
            className="border-t border-slate-800 px-5 py-4"
          >
            <div className="flex items-start justify-between gap-4">
              <div className="flex-1">
                <div className="flex items-center gap-2 mb-1">
                  <span
                    className={`text-xs font-mono font-bold ${
                      SEVERITY_COLORS[hoveredFailure.severity as keyof typeof SEVERITY_COLORS]?.text
                    }`}
                  >
                    {hoveredFailure.severity}
                  </span>
                  <span className="text-xs text-slate-500">
                    {hoveredFailure.test_type?.replace(/_/g, " ")}
                  </span>
                </div>
                <p className="text-sm text-slate-200">{hoveredFailure.reason}</p>
                {hoveredFailure.recommended_fix && (
                  <p className="text-xs text-amber-400 mt-1.5 font-mono">→ {hoveredFailure.recommended_fix}</p>
                )}
              </div>
              <div className="text-right shrink-0">
                <p className="text-xs text-slate-500">Component</p>
                <p className="text-sm text-slate-300 font-mono">{hoveredComponent}</p>
              </div>
            </div>
          </motion.div>
        )}

        {hoveredComponent && !hoveredFailure && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="border-t border-slate-800 px-5 py-3"
          >
            <p className="text-xs text-green-400 font-mono">
              ✓ {spec.components.find((c) => c.id === hoveredComponent)?.name} — No failures detected
            </p>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
