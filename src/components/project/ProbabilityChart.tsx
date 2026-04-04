'use client'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'

interface Props {
  conversionRate: number
  confidenceInterval: { low: number; high: number }
}

export default function ProbabilityChart({ conversionRate, confidenceInterval }: Props) {
  const data = [
    { label: `${confidenceInterval.low.toFixed(1)}%`, value: 35, type: 'low' },
    { label: `${(confidenceInterval.low + (conversionRate - confidenceInterval.low) / 2).toFixed(1)}%`, value: 55, type: 'mid-low' },
    { label: `${conversionRate.toFixed(1)}%`, value: 100, type: 'median' },
    { label: `${(conversionRate + (confidenceInterval.high - conversionRate) / 2).toFixed(1)}%`, value: 62, type: 'mid-high' },
    { label: `${confidenceInterval.high.toFixed(1)}%`, value: 28, type: 'high' },
  ]

  return (
    <ResponsiveContainer width="100%" height={160}>
      <BarChart data={data} barSize={28}>
        <XAxis dataKey="label" tick={{ fill: '#64748b', fontSize: 11 }} axisLine={false} tickLine={false} />
        <YAxis hide />
        <Tooltip
          cursor={{ fill: 'rgba(255,255,255,0.03)' }}
          contentStyle={{ background: '#111', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 8, fontSize: 12 }}
          labelStyle={{ color: '#94a3b8' }}
          formatter={(v) => [`${Number(v ?? 0)}%`, 'Probability']}
        />
        <Bar dataKey="value" radius={[6, 6, 0, 0]}>
          {data.map((d) => (
            <Cell key={d.label} fill={d.type === 'median' ? '#6366f1' : 'rgba(99,102,241,0.25)'} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}
