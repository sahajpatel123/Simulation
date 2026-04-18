'use client'

import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import { SlidersHorizontal, TrendingUp, Layers, ArrowRight, ArrowLeft, Check, Loader2 } from 'lucide-react'

import { useEnvironment } from '@/hooks/useEnvironment'
import { useProject } from '@/hooks/useProjects'
import { EnvironmentMode } from '@/types'

const scenarios = [
  {
    id: 'base',
    label: 'Base case',
    description: 'Neutral market. Average sentiment and ordinary purchase cadence.',
    tag: 'Neutral',
  },
  {
    id: 'recession',
    label: 'Recession',
    description: 'Price-sensitive readers, reduced discretionary spend, higher churn.',
    tag: 'Bearish',
  },
  {
    id: 'viral',
    label: 'Viral moment',
    description: 'Sudden traffic spike, elevated intent, compressed decision cycles.',
    tag: 'Bullish',
  },
  {
    id: 'competitor',
    label: 'Competitor entry',
    description: 'A well-funded rival splits intent and depresses conversion.',
    tag: 'Threat',
  },
] as const

const tagStyles: Record<string, { color: string; bg: string; border: string }> = {
  Neutral: { color: 'var(--ink-secondary)', bg: 'rgba(26,23,20,0.04)', border: 'var(--border-color)' },
  Bearish: { color: 'var(--red)', bg: 'rgba(192,57,43,0.06)', border: 'rgba(192,57,43,0.35)' },
  Bullish: { color: '#2d5a4a', bg: 'rgba(45, 90, 74, 0.08)', border: 'rgba(45, 90, 74, 0.3)' },
  Threat: { color: '#8a5a1a', bg: 'rgba(184, 138, 58, 0.1)', border: 'rgba(184, 138, 58, 0.35)' },
}

export default function EnvironmentPage() {
  const params = useParams()
  const projectId = Number(params.id)
  const idStr = String(projectId)

  const { data: project, isLoading: projLoading, isError: projError } = useProject(
    Number.isFinite(projectId) ? projectId : null,
  )
  const { data: envData, isLoading: envLoading } = useEnvironment(Number.isFinite(projectId) ? projectId : null)

  const [mode, setMode] = useState<EnvironmentMode>(EnvironmentMode.MANUAL)
  const [volume, setVolume] = useState(10000)
  const [growth, setGrowth] = useState(15)
  const [aov, setAov] = useState(1000)
  const [selectedScenario, setSelectedScenario] = useState<string>('base')
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    if (!envData) return
    setMode(envData.mode || EnvironmentMode.MANUAL)
    setVolume(envData.consumer_volume ?? envData.consumerVolume ?? 10000)
    setGrowth(envData.growth_rate_per_month ?? envData.growthRatePerMonth ?? 15)
    setAov(envData.average_order_value ?? envData.averageOrderValue ?? 1000)
    const st = envData.scenario_type ?? envData.scenarioType
    if (st && scenarios.some((s) => s.id === st)) setSelectedScenario(st)
  }, [envData])

  const handleSave = async () => {
    await new Promise((r) => setTimeout(r, 800))
    setSaved(true)
    setTimeout(() => setSaved(false), 2200)
  }

  if (!Number.isFinite(projectId) || projError) {
    return (
      <div style={{ padding: '64px 48px', maxWidth: 560 }}>
        <div className="kicker" style={{ color: 'var(--red)', marginBottom: 10 }}>
          Errata
        </div>
        <h1 className="font-serif" style={{ fontSize: 32, fontWeight: 900, fontStyle: 'italic', color: 'var(--ink)' }}>
          This dossier could not be opened.
        </h1>
        <Link href="/projects" style={{ marginTop: 16, display: 'inline-block', color: 'var(--red)', fontSize: 14 }}>
          Return to the index.
        </Link>
      </div>
    )
  }

  if (projLoading || !project) {
    return (
      <div style={{ padding: '64px 48px', display: 'flex', gap: 12, alignItems: 'center', color: 'var(--ink-secondary)' }}>
        <Loader2 className="animate-spin" style={{ width: 14, height: 14 }} />
        <span className="kicker">Casting the room…</span>
      </div>
    )
  }

  const tabs = [
    { mode: EnvironmentMode.MANUAL, label: 'Manual', icon: SlidersHorizontal },
    { mode: EnvironmentMode.TREND, label: 'Trend', icon: TrendingUp },
    { mode: EnvironmentMode.SCENARIO, label: 'Scenario', icon: Layers },
  ]

  const sliderRow = (
    label: string,
    value: number,
    setValue: (n: number) => void,
    min: number,
    max: number,
    step: number,
    format: (v: number) => string,
    suffix: string,
  ) => (
    <div
      key={label}
      style={{
        border: '0.5px solid var(--border-strong)',
        background: 'var(--paper)',
        padding: 24,
      }}
      className="rise"
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
        <label style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)' }}>{label}</label>
        <span className="font-serif" style={{ fontSize: 18, fontWeight: 800, fontStyle: 'italic', color: 'var(--red)' }}>
          {format(value)}
          {suffix ? ` ${suffix}` : ''}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => setValue(Number(e.target.value))}
        style={{
          width: '100%',
          height: 4,
          accentColor: 'var(--red)',
          cursor: 'pointer',
        }}
      />
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          marginTop: 10,
          fontSize: 11,
          letterSpacing: '0.06em',
          textTransform: 'uppercase',
          color: 'var(--ink-tertiary)',
        }}
      >
        <span>{format(min)}</span>
        <span>{format(max)}</span>
      </div>
    </div>
  )

  return (
    <div style={{ padding: '36px 48px 56px', maxWidth: 720 }}>
      <motion.div initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.45 }}>
        <header style={{ marginBottom: 28 }}>
          <div
            className="kicker"
            style={{ color: 'var(--red)', marginBottom: 12, display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}
          >
            <Link href={`/project/${idStr}/prototype`} style={{ color: 'inherit', textDecoration: 'none' }}>
              Reader&apos;s proof
            </Link>
            <span style={{ color: 'var(--ink-tertiary)' }}>·</span>
            <span style={{ color: 'var(--ink-secondary)' }}>Press room</span>
            <span style={{ color: 'var(--ink-tertiary)' }}>·</span>
            <span>Cast</span>
          </div>
          <h1
            className="font-serif"
            style={{
              fontSize: 'clamp(28px, 3.5vw, 40px)',
              fontWeight: 900,
              fontStyle: 'italic',
              lineHeight: 1.05,
              color: 'var(--ink)',
              marginBottom: 8,
            }}
          >
            Assemble the <span style={{ color: 'var(--red)' }}>room</span>.
          </h1>
          <p style={{ fontSize: 13, lineHeight: 1.65, color: 'var(--ink-secondary)', maxWidth: 520, fontWeight: 300 }}>
            Define the market conditions your synthetic readers move through before the presses run.
          </p>
          {envLoading && (
            <p style={{ marginTop: 10, fontSize: 11, letterSpacing: '0.14em', textTransform: 'uppercase', color: 'var(--ink-tertiary)' }}>
              Syncing saved cast…
            </p>
          )}
        </header>

        {/* Mode rail */}
        <div
          role="tablist"
          aria-label="Environment mode"
          style={{
            display: 'inline-flex',
            border: '0.5px solid var(--ink)',
            background: 'var(--paper-dark)',
            marginBottom: 28,
          }}
        >
          {tabs.map(({ mode: m, label, icon: Icon }) => {
            const active = mode === m
            return (
              <button
                key={m}
                type="button"
                role="tab"
                aria-selected={active}
                onClick={() => setMode(m)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  padding: '10px 18px',
                  border: 'none',
                  cursor: 'pointer',
                  fontFamily: 'var(--font-body)',
                  fontSize: 10,
                  fontWeight: 600,
                  letterSpacing: '0.18em',
                  textTransform: 'uppercase',
                  color: active ? 'var(--paper)' : 'var(--ink-secondary)',
                  background: active ? 'var(--ink)' : 'transparent',
                  transition: 'background 180ms ease, color 180ms ease',
                }}
              >
                <Icon style={{ width: 14, height: 14 }} />
                {label}
              </button>
            )
          })}
        </div>

        {mode === EnvironmentMode.MANUAL && (
          <motion.div
            initial={{ opacity: 0, x: -8 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.3 }}
            style={{ display: 'flex', flexDirection: 'column', gap: 18 }}
          >
            {sliderRow('Consumer volume', volume, setVolume, 1000, 10000, 500, (v) => v.toLocaleString(), 'agents')}
            {sliderRow('Monthly growth rate', growth, setGrowth, 0, 100, 1, (v) => String(v), '%')}
            {sliderRow(
              'Average order value',
              aov,
              setAov,
              100,
              50000,
              100,
              (v) => `₹${v.toLocaleString()}`,
              '',
            )}
          </motion.div>
        )}

        {mode === EnvironmentMode.TREND && (
          <motion.div
            initial={{ opacity: 0, x: -8 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.3 }}
            style={{
              border: '0.5px solid var(--border-strong)',
              background: 'var(--paper)',
              padding: 40,
              textAlign: 'center',
            }}
            className="rise"
          >
            <TrendingUp style={{ width: 40, height: 40, color: 'var(--red)', margin: '0 auto 16px', opacity: 0.75 }} />
            <h3 className="font-serif" style={{ fontSize: 20, fontWeight: 800, fontStyle: 'italic', color: 'var(--ink)', marginBottom: 8 }}>
              Live market wires
            </h3>
            <p style={{ fontSize: 13, color: 'var(--ink-secondary)', maxWidth: 360, margin: '0 auto', lineHeight: 1.65 }}>
              Trend mode pulls real signals to auto-configure your cast. Reserved for subscribers with wire-room access.
            </p>
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(3, 1fr)',
                gap: 10,
                marginTop: 28,
                opacity: 0.45,
                pointerEvents: 'none',
              }}
            >
              {['Search volume', 'Market sentiment', 'Industry CAC'].map((label) => (
                <div key={label} style={{ border: '0.5px dashed var(--border-color)', padding: 14 }}>
                  <div style={{ height: 32, background: 'rgba(26,23,20,0.06)', marginBottom: 8 }} />
                  <p className="kicker" style={{ fontSize: 9, color: 'var(--ink-tertiary)' }}>
                    {label}
                  </p>
                </div>
              ))}
            </div>
          </motion.div>
        )}

        {mode === EnvironmentMode.SCENARIO && (
          <motion.div
            initial={{ opacity: 0, x: -8 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.3 }}
            style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 14 }}
          >
            {scenarios.map((s) => {
              const sel = selectedScenario === s.id
              const tag = tagStyles[s.tag] ?? tagStyles.Neutral
              return (
                <button
                  key={s.id}
                  type="button"
                  onClick={() => setSelectedScenario(s.id)}
                  style={{
                    textAlign: 'left',
                    padding: 20,
                    border: sel ? '0.5px solid var(--ink)' : '0.5px solid var(--border-strong)',
                    background: sel ? 'var(--paper-dark)' : 'var(--paper)',
                    boxShadow: sel ? '8px 8px 0 rgba(192,57,43,0.12)' : 'none',
                    cursor: 'pointer',
                    transition: 'box-shadow 200ms ease, border-color 200ms ease',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
                    <span className="font-serif" style={{ fontSize: 15, fontWeight: 800, fontStyle: 'italic', color: 'var(--ink)' }}>
                      {s.label}
                    </span>
                    <span
                      style={{
                        fontSize: 9,
                        letterSpacing: '0.12em',
                        textTransform: 'uppercase',
                        fontWeight: 600,
                        padding: '4px 8px',
                        border: `0.5px solid ${tag.border}`,
                        color: tag.color,
                        background: tag.bg,
                      }}
                    >
                      {s.tag}
                    </span>
                  </div>
                  <p style={{ fontSize: 12, lineHeight: 1.6, color: 'var(--ink-secondary)' }}>{s.description}</p>
                </button>
              )
            })}
          </motion.div>
        )}

        <footer
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 16,
            marginTop: 36,
            paddingTop: 24,
            borderTop: '0.5px solid var(--border-color)',
            flexWrap: 'wrap',
          }}
        >
          <Link href={`/project/${idStr}/prototype`} className="btn-ghost" style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
            <ArrowLeft style={{ width: 14, height: 14 }} /> Reader&apos;s proof
          </Link>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <button
              type="button"
              onClick={handleSave}
              className={saved ? 'btn-ink' : 'btn-ghost'}
              style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}
            >
              {saved ? (
                <>
                  <Check style={{ width: 14, height: 14 }} /> Filed
                </>
              ) : (
                'Save cast'
              )}
            </button>
            <Link href={`/project/${idStr}/simulation`} className="btn-ink" style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
              Run the press <ArrowRight style={{ width: 14, height: 14 }} />
            </Link>
          </div>
        </footer>
      </motion.div>
    </div>
  )
}
