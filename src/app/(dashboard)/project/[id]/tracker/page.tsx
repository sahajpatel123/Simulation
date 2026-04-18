'use client'

import { useState, type CSSProperties } from 'react'
import { motion } from 'framer-motion'
import { useForm, type Resolver } from 'react-hook-form'
import { z } from 'zod'
import { zodResolver } from '@hookform/resolvers/zod'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import { ArrowLeft, CheckCircle2, TrendingUp, TrendingDown, Minus, ClipboardList, Loader2 } from 'lucide-react'

import { useProject } from '@/hooks/useProjects'
import { getSimulationResultByProjectId } from '@/lib/mock-data'

const schema = z.object({
  actualConversionRate: z.coerce.number().min(0).max(100),
  actualRevenue: z.coerce.number().min(0),
  notes: z.string().optional(),
})
type FormData = z.infer<typeof schema>

function optionalNumber(v: unknown): number | undefined {
  if (v === '' || v === undefined || v === null) return undefined
  const n = typeof v === 'number' ? v : Number(v)
  return Number.isNaN(n) ? undefined : n
}

const mockHistory = [
  { date: '12 Mar 2026', predicted: 3.1, actual: 2.8, revenue: 381000, status: 'under' as const },
  { date: '28 Feb 2026', predicted: 4.2, actual: 4.9, revenue: 612000, status: 'over' as const },
]

const inputStyle: CSSProperties = {
  width: '100%',
  padding: '12px 14px',
  border: '0.5px solid var(--border-strong)',
  background: 'var(--paper)',
  color: 'var(--ink)',
  fontSize: 14,
  outline: 'none',
  transition: 'border-color 150ms ease',
}

export default function TrackerPage() {
  const params = useParams()
  const projectId = Number(params.id)
  const idStr = String(projectId)

  const { data: project, isLoading, isError } = useProject(Number.isFinite(projectId) ? projectId : null)
  const result = getSimulationResultByProjectId(idStr)
  const [submitted, setSubmitted] = useState(false)

  const { register, handleSubmit, watch, formState: { errors, isSubmitting } } = useForm<FormData>({
    resolver: zodResolver(schema) as Resolver<FormData>,
  })

  const watchedConversion = watch('actualConversionRate')
  const watchedRevenue = watch('actualRevenue')

  const onSubmit = async (_data: FormData) => {
    await new Promise((r) => setTimeout(r, 1000))
    setSubmitted(true)
  }

  if (!Number.isFinite(projectId) || isError) {
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

  if (isLoading || !project) {
    return (
      <div style={{ padding: '64px 48px', display: 'flex', gap: 12, alignItems: 'center', color: 'var(--ink-secondary)' }}>
        <Loader2 className="animate-spin" style={{ width: 14, height: 14 }} />
        <span className="kicker">Opening ledger…</span>
      </div>
    )
  }

  const predicted = result?.conversionRate || 3.8
  const actual = optionalNumber(watchedConversion)
  const hasActualConv = actual !== undefined
  const variance = actual !== undefined ? (((actual - predicted) / predicted) * 100).toFixed(1) : null

  const DiffIcon = !variance ? Minus : Number(variance) > 0 ? TrendingUp : TrendingDown
  const diffColor =
    !variance ? 'var(--ink-tertiary)' : Number(variance) > 0 ? '#2d5a4a' : 'var(--red)'

  const revenueNum = optionalNumber(watchedRevenue)
  const hasRevenue = revenueNum !== undefined

  return (
    <div style={{ padding: '36px 48px 56px', maxWidth: 900 }}>
      <motion.div initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.45 }}>
        <header style={{ marginBottom: 28 }}>
          <div
            className="kicker"
            style={{ color: 'var(--red)', marginBottom: 10, display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}
          >
            <Link href={`/project/${idStr}/results`} style={{ color: 'inherit', textDecoration: 'none' }}>
              Proofs
            </Link>
            <span style={{ color: 'var(--ink-tertiary)' }}>·</span>
            <span style={{ color: 'var(--ink-secondary)' }}>Ledger</span>
          </div>
          <h1
            className="font-serif"
            style={{
              fontSize: 'clamp(28px, 3.5vw, 40px)',
              fontWeight: 900,
              fontStyle: 'italic',
              color: 'var(--ink)',
              marginBottom: 8,
            }}
          >
            Record the <span style={{ color: 'var(--red)' }}>truth</span>.
          </h1>
          <p style={{ fontSize: 13, lineHeight: 1.65, color: 'var(--ink-secondary)', maxWidth: 520, fontWeight: 300 }}>
            Compare what happened in the field against what the archive predicted. Each entry sharpens the next run.
          </p>
        </header>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 18, marginBottom: 22 }}>
          <div style={{ border: '0.5px solid var(--border-strong)', background: 'var(--paper)', padding: 28 }} className="rise">
            {submitted ? (
              <motion.div
                initial={{ opacity: 0, scale: 0.98 }}
                animate={{ opacity: 1, scale: 1 }}
                style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center', padding: '32px 8px' }}
              >
                <div
                  style={{
                    width: 56,
                    height: 56,
                    border: '0.5px solid #2d5a4a',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    marginBottom: 18,
                    background: 'rgba(45,90,74,0.08)',
                  }}
                >
                  <CheckCircle2 style={{ width: 28, height: 28, color: '#2d5a4a' }} />
                </div>
                <h3 className="font-serif" style={{ fontSize: 20, fontWeight: 800, fontStyle: 'italic', color: 'var(--ink)', marginBottom: 8 }}>
                  Line filed
                </h3>
                <p style={{ fontSize: 13, color: 'var(--ink-secondary)', maxWidth: 320, lineHeight: 1.65 }}>
                  The calibration desk will fold this into the next impression.
                </p>
                <button
                  type="button"
                  onClick={() => setSubmitted(false)}
                  style={{
                    marginTop: 20,
                    background: 'none',
                    border: 'none',
                    cursor: 'pointer',
                    fontSize: 12,
                    letterSpacing: '0.12em',
                    textTransform: 'uppercase',
                    fontWeight: 600,
                    color: 'var(--red)',
                  }}
                >
                  File another line
                </button>
              </motion.div>
            ) : (
              <>
                <h3 className="font-serif" style={{ fontSize: 16, fontWeight: 800, fontStyle: 'italic', color: 'var(--ink)', marginBottom: 20 }}>
                  Actuals
                </h3>
                <form onSubmit={handleSubmit(onSubmit)} style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
                  <div>
                    <label style={{ display: 'block', fontSize: 11, letterSpacing: '0.14em', textTransform: 'uppercase', color: 'var(--ink-secondary)', marginBottom: 8, fontWeight: 600 }}>
                      Conversion rate (%)
                    </label>
                    <input {...register('actualConversionRate')} type="number" step="0.1" placeholder="e.g. 3.2" style={inputStyle} />
                    {errors.actualConversionRate && (
                      <p style={{ color: 'var(--red)', fontSize: 11, marginTop: 6 }}>Enter a valid rate (0–100)</p>
                    )}
                  </div>

                  <div>
                    <label style={{ display: 'block', fontSize: 11, letterSpacing: '0.14em', textTransform: 'uppercase', color: 'var(--ink-secondary)', marginBottom: 8, fontWeight: 600 }}>
                      Revenue (₹)
                    </label>
                    <input {...register('actualRevenue')} type="number" placeholder="e.g. 380000" style={inputStyle} />
                    {errors.actualRevenue && (
                      <p style={{ color: 'var(--red)', fontSize: 11, marginTop: 6 }}>Enter a valid amount</p>
                    )}
                  </div>

                  <div>
                    <label style={{ display: 'block', fontSize: 11, letterSpacing: '0.14em', textTransform: 'uppercase', color: 'var(--ink-secondary)', marginBottom: 8, fontWeight: 600 }}>
                      Notes <span style={{ color: 'var(--ink-tertiary)', fontWeight: 400 }}>(optional)</span>
                    </label>
                    <textarea
                      {...register('notes')}
                      rows={3}
                      placeholder="What surprised you? What matched the proof?"
                      style={{ ...inputStyle, resize: 'none', minHeight: 88 }}
                    />
                  </div>

                  <button type="submit" disabled={isSubmitting} className="btn-ink" style={{ width: '100%', justifyContent: 'center' }}>
                    {isSubmitting ? 'Filing…' : 'File line'}
                  </button>
                </form>
              </>
            )}
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <div style={{ border: '0.5px solid var(--border-strong)', background: 'var(--paper)', padding: 22 }} className="rise">
              <h4 className="kicker" style={{ marginBottom: 16, color: 'var(--ink-tertiary)' }}>
                Predicted vs actual
              </h4>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                {[
                  { label: 'Conversion rate', predicted: `${predicted}%`, actual: hasActualConv ? `${actual}%` : '—' },
                  {
                    label: 'Revenue',
                    predicted: `₹${((result?.projectedRevenue || 0) / 1000).toFixed(0)}K`,
                    actual: hasRevenue ? `₹${((revenueNum ?? 0) / 1000).toFixed(0)}K` : '—',
                  },
                ].map(({ label, predicted: p, actual: a }) => (
                  <div
                    key={label}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      paddingBottom: 12,
                      borderBottom: '0.5px solid var(--border-color)',
                    }}
                  >
                    <span style={{ fontSize: 11, color: 'var(--ink-tertiary)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
                      {label}
                    </span>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 12, fontSize: 12 }}>
                      <span style={{ color: 'var(--ink-secondary)' }}>{p}</span>
                      <span style={{ color: 'var(--ink-tertiary)' }}>→</span>
                      <span style={{ color: a === '—' ? 'var(--ink-tertiary)' : 'var(--ink)', fontWeight: 700 }}>{a}</span>
                    </div>
                  </div>
                ))}
              </div>

              {variance && (
                <motion.div
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 16, paddingTop: 16, borderTop: '0.5px solid var(--border-color)', color: diffColor }}
                >
                  <DiffIcon style={{ width: 16, height: 16 }} />
                  <span style={{ fontSize: 13, fontWeight: 600 }}>
                    {Number(variance) > 0 ? '+' : ''}
                    {variance}% vs proof
                  </span>
                </motion.div>
              )}
            </div>

            <div style={{ border: '0.5px solid var(--border-strong)', background: 'var(--paper)', padding: 22 }} className="rise">
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
                <ClipboardList style={{ width: 16, height: 16, color: 'var(--red)' }} />
                <h4 className="kicker" style={{ color: 'var(--ink-secondary)' }}>
                  Calibration depth
                </h4>
              </div>
              <div style={{ height: 4, background: 'rgba(26,23,20,0.08)', overflow: 'hidden', marginBottom: 10 }}>
                <div style={{ height: '100%', width: '18%', background: 'var(--ink)' }} />
              </div>
              <p style={{ fontSize: 11, lineHeight: 1.55, color: 'var(--ink-tertiary)' }}>
                Two of ten or more outcomes on file. Add more field lines to tighten the next impression.
              </p>
            </div>
          </div>
        </div>

        <div style={{ border: '0.5px solid var(--border-strong)', background: 'var(--paper)', padding: 24 }} className="rise">
          <h3 className="font-serif" style={{ fontSize: 16, fontWeight: 800, fontStyle: 'italic', color: 'var(--ink)', marginBottom: 18 }}>
            Prior filings
          </h3>
          {mockHistory.length === 0 ? (
            <p style={{ fontSize: 13, color: 'var(--ink-tertiary)', textAlign: 'center', padding: 24 }}>No outcomes yet.</p>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {mockHistory.map((h, i) => (
                <motion.div
                  key={i}
                  initial={{ opacity: 0, x: -6 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: i * 0.06 }}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    gap: 16,
                    padding: '14px 0',
                    borderBottom: i < mockHistory.length - 1 ? '0.5px solid var(--border-color)' : 'none',
                    flexWrap: 'wrap',
                  }}
                >
                  <div>
                    <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--ink)' }}>{h.date}</span>
                    <div style={{ fontSize: 11, color: 'var(--ink-tertiary)', marginTop: 4 }}>
                      Predicted {h.predicted}% → Actual {h.actual}%
                    </div>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                    <span style={{ fontSize: 13, color: 'var(--ink-secondary)' }}>₹{(h.revenue / 1000).toFixed(0)}K</span>
                    <span
                      style={{
                        fontSize: 9,
                        letterSpacing: '0.1em',
                        textTransform: 'uppercase',
                        fontWeight: 600,
                        padding: '4px 10px',
                        border: `0.5px solid ${h.status === 'over' ? 'rgba(45,90,74,0.35)' : 'rgba(192,57,43,0.35)'}`,
                        color: h.status === 'over' ? '#2d5a4a' : 'var(--red)',
                        background: h.status === 'over' ? 'rgba(45,90,74,0.08)' : 'rgba(192,57,43,0.06)',
                      }}
                    >
                      {h.status === 'over' ? 'Above proof' : 'Below proof'}
                    </span>
                  </div>
                </motion.div>
              ))}
            </div>
          )}
        </div>

        <div style={{ marginTop: 22 }}>
          <Link href={`/project/${idStr}/results`} className="btn-ghost" style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
            <ArrowLeft style={{ width: 14, height: 14 }} /> Back to proofs
          </Link>
        </div>
      </motion.div>
    </div>
  )
}
