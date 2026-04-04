'use client'
import { useState, use } from 'react'
import { motion } from 'framer-motion'
import { useForm, type Resolver } from 'react-hook-form'
import { z } from 'zod'
import { zodResolver } from '@hookform/resolvers/zod'
import { getProjectById, getSimulationResultByProjectId } from '@/lib/mock-data'
import { ArrowLeft, CheckCircle2, TrendingUp, TrendingDown, Minus, ClipboardList } from 'lucide-react'
import Link from 'next/link'

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
  { date: '12 Mar 2026', predicted: 3.1, actual: 2.8, revenue: 381000, status: 'under' },
  { date: '28 Feb 2026', predicted: 4.2, actual: 4.9, revenue: 612000, status: 'over' },
]

export default function TrackerPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params)
  const project = getProjectById(id)
  const result = getSimulationResultByProjectId(id)
  const [submitted, setSubmitted] = useState(false)

  const { register, handleSubmit, watch, formState: { errors, isSubmitting } } = useForm<FormData>({
    resolver: zodResolver(schema) as Resolver<FormData>,
  })

  const watchedConversion = watch('actualConversionRate')
  const watchedRevenue = watch('actualRevenue')

  const onSubmit = async (_data: FormData) => {
    await new Promise(r => setTimeout(r, 1000))
    setSubmitted(true)
  }

  if (!project) return null

  const predicted = result?.conversionRate || 3.8
  const actual = optionalNumber(watchedConversion)
  const hasActualConv = actual !== undefined
  const variance =
    actual !== undefined ? ((actual - predicted) / predicted * 100).toFixed(1) : null

  const DiffIcon = !variance ? Minus :
    Number(variance) > 0 ? TrendingUp : TrendingDown
  const diffColor = !variance ? 'text-slate-400' :
    Number(variance) > 0 ? 'text-emerald-400' : 'text-red-400'

  const revenueNum = optionalNumber(watchedRevenue)
  const hasRevenue = revenueNum !== undefined

  return (
    <div className="p-8 max-w-4xl">
      <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }}>
        {/* Header */}
        <div className="mb-8">
          <div className="flex items-center gap-2 text-xs text-slate-600 mb-1.5">
            <Link href={`/project/${id}/results`} className="hover:text-slate-400">Results</Link>
            <span>/</span>
            <span className="text-slate-400">Outcome tracker</span>
          </div>
          <h1 className="font-display text-2xl font-700 text-white mb-1">Record real outcomes</h1>
          <p className="text-slate-500 text-sm">Compare what actually happened against what TheCee predicted. This data improves future simulations.</p>
        </div>

        <div className="grid lg:grid-cols-[3fr_2fr] gap-6 mb-8">
          {/* Form */}
          <div className="glass rounded-2xl p-6">
            {submitted ? (
              <motion.div initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }}
                className="flex flex-col items-center justify-center py-10 text-center">
                <div className="w-14 h-14 rounded-2xl bg-emerald-500/15 border border-emerald-500/20 flex items-center justify-center mb-4">
                  <CheckCircle2 className="w-7 h-7 text-emerald-400" />
                </div>
                <h3 className="font-display text-lg font-700 text-white mb-2">Outcome recorded</h3>
                <p className="text-slate-500 text-sm max-w-xs">TheCee's calibration engine will use this to improve future simulation accuracy.</p>
                <button type="button" onClick={() => setSubmitted(false)}
                  className="mt-5 text-indigo-400 text-sm hover:text-indigo-300 transition-colors">
                  Record another outcome
                </button>
              </motion.div>
            ) : (
              <>
                <h3 className="font-display text-sm font-600 text-white mb-5">Record actual results</h3>
                <form onSubmit={handleSubmit(onSubmit)} className="space-y-5">
                  <div>
                    <label className="block text-sm text-slate-300 mb-1.5 font-medium">Actual conversion rate (%)</label>
                    <input {...register('actualConversionRate')} type="number" step="0.1" placeholder="e.g. 3.2"
                      className="w-full px-4 py-2.5 rounded-lg bg-white/5 border border-white/10 text-white placeholder-slate-600 text-sm focus:outline-none focus:border-indigo-500/50 transition-all" />
                    {errors.actualConversionRate && <p className="text-red-400 text-xs mt-1">Enter a valid rate (0–100)</p>}
                  </div>

                  <div>
                    <label className="block text-sm text-slate-300 mb-1.5 font-medium">Actual revenue (₹)</label>
                    <input {...register('actualRevenue')} type="number" placeholder="e.g. 380000"
                      className="w-full px-4 py-2.5 rounded-lg bg-white/5 border border-white/10 text-white placeholder-slate-600 text-sm focus:outline-none focus:border-indigo-500/50 transition-all" />
                    {errors.actualRevenue && <p className="text-red-400 text-xs mt-1">Enter a valid amount</p>}
                  </div>

                  <div>
                    <label className="block text-sm text-slate-300 mb-1.5 font-medium">Notes <span className="text-slate-600">(optional)</span></label>
                    <textarea {...register('notes')} rows={3} placeholder="What surprised you? What matched the prediction?"
                      className="w-full px-4 py-2.5 rounded-lg bg-white/5 border border-white/10 text-white placeholder-slate-600 text-sm focus:outline-none focus:border-indigo-500/50 transition-all resize-none" />
                  </div>

                  <button type="submit" disabled={isSubmitting}
                    className="w-full flex items-center justify-center gap-2 py-2.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-sm font-medium transition-all">
                    {isSubmitting ? 'Recording...' : 'Record outcome'}
                  </button>
                </form>
              </>
            )}
          </div>

          {/* Live comparison */}
          <div className="space-y-4">
            <div className="glass rounded-2xl p-5">
              <h4 className="text-xs text-slate-500 mb-4">Predicted vs Actual</h4>
              <div className="space-y-3">
                {[
                  { label: 'Conversion rate', predicted: `${predicted}%`, actual: hasActualConv ? `${actual}%` : '—' },
                  { label: 'Revenue', predicted: `₹${((result?.projectedRevenue || 0) / 1000).toFixed(0)}K`, actual: hasRevenue ? `₹${((revenueNum ?? 0) / 1000).toFixed(0)}K` : '—' },
                ].map(({ label, predicted: p, actual: a }) => (
                  <div key={label} className="flex items-center justify-between py-2 border-b border-white/5 last:border-0">
                    <span className="text-xs text-slate-500">{label}</span>
                    <div className="flex items-center gap-4 text-xs">
                      <span className="text-slate-400">{p}</span>
                      <span className="text-slate-600">→</span>
                      <span className={a === '—' ? 'text-slate-600' : 'text-white font-600'}>{a}</span>
                    </div>
                  </div>
                ))}
              </div>

              {variance && (
                <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
                  className={`flex items-center gap-2 mt-4 pt-4 border-t border-white/5 ${diffColor}`}>
                  <DiffIcon className="w-4 h-4" />
                  <span className="text-sm font-600">{Number(variance) > 0 ? '+' : ''}{variance}% vs prediction</span>
                </motion.div>
              )}
            </div>

            {/* Calibration indicator */}
            <div className="glass rounded-2xl p-5">
              <div className="flex items-center gap-2 mb-3">
                <ClipboardList className="w-4 h-4 text-indigo-400" />
                <h4 className="text-xs text-slate-400 font-medium">Calibration maturity</h4>
              </div>
              <div className="w-full h-1.5 bg-white/5 rounded-full overflow-hidden mb-2">
                <div className="h-full bg-gradient-to-r from-indigo-500 to-cyan-400 rounded-full" style={{ width: '18%' }} />
              </div>
              <p className="text-xs text-slate-600">2 of 10+ outcomes recorded. Add more real results to improve simulation accuracy.</p>
            </div>
          </div>
        </div>

        {/* History */}
        <div className="glass rounded-2xl p-6">
          <h3 className="font-display text-sm font-600 text-white mb-5">Past outcomes</h3>
          {mockHistory.length === 0 ? (
            <p className="text-slate-600 text-sm text-center py-6">No outcomes recorded yet</p>
          ) : (
            <div className="space-y-3">
              {mockHistory.map((h, i) => (
                <motion.div key={i} initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: i * 0.08 }}
                  className="flex items-center justify-between py-3 border-b border-white/5 last:border-0">
                  <div>
                    <span className="text-sm text-white">{h.date}</span>
                    <div className="text-xs text-slate-600 mt-0.5">Predicted {h.predicted}% → Actual {h.actual}%</div>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-sm text-slate-400">₹{(h.revenue / 1000).toFixed(0)}K</span>
                    <span className={`text-xs px-2 py-0.5 rounded-full border font-medium ${
                      h.status === 'over'
                        ? 'text-emerald-400 bg-emerald-400/10 border-emerald-400/20'
                        : 'text-red-400 bg-red-400/10 border-red-400/20'
                    }`}>
                      {h.status === 'over' ? 'Above prediction' : 'Below prediction'}
                    </span>
                  </div>
                </motion.div>
              ))}
            </div>
          )}
        </div>

        <div className="flex items-center gap-3 mt-6">
          <Link href={`/project/${id}/results`}
            className="flex items-center gap-2 px-4 py-2 rounded-lg glass glass-hover text-slate-400 text-sm">
            <ArrowLeft className="w-3.5 h-3.5" /> Results
          </Link>
        </div>
      </motion.div>
    </div>
  )
}
