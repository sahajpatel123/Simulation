'use client'

import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'

interface Props {
  conversionRate: number
  confidenceInterval: { low: number; high: number }
}

const INK = '#1a1714'
const INK_MUTED = '#6b6560'
const RED = '#c0392b'
const PAPER = '#f2ece0'

export default function ProbabilityChart({ conversionRate, confidenceInterval }: Props) {
  const data = [
    { label: `${confidenceInterval.low.toFixed(1)}%`, value: 35, type: 'low' },
    {
      label: `${(confidenceInterval.low + (conversionRate - confidenceInterval.low) / 2).toFixed(1)}%`,
      value: 55,
      type: 'mid-low',
    },
    { label: `${conversionRate.toFixed(1)}%`, value: 100, type: 'median' },
    {
      label: `${(conversionRate + (confidenceInterval.high - conversionRate) / 2).toFixed(1)}%`,
      value: 62,
      type: 'mid-high',
    },
    { label: `${confidenceInterval.high.toFixed(1)}%`, value: 28, type: 'high' },
  ]

  return (
    <ResponsiveContainer width="100%" height={160}>
      <BarChart data={data} barSize={28}>
        <XAxis dataKey="label" tick={{ fill: INK_MUTED, fontSize: 11 }} axisLine={false} tickLine={false} />
        <YAxis hide />
        <Tooltip
          cursor={{ fill: 'rgba(26,23,20,0.06)' }}
          contentStyle={{
            background: PAPER,
            border: `0.5px solid ${INK}`,
            borderRadius: 0,
            fontSize: 12,
            boxShadow: '6px 6px 0 rgba(26,23,20,0.08)',
          }}
          labelStyle={{ color: INK_MUTED, fontSize: 10, letterSpacing: '0.08em', textTransform: 'uppercase' }}
          formatter={(v) => [`${Number(v ?? 0)}%`, 'Weight']}
        />
        <Bar dataKey="value" radius={[2, 2, 0, 0]}>
          {data.map((d) => (
            <Cell key={d.label} fill={d.type === 'median' ? RED : 'rgba(26,23,20,0.18)'} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}
