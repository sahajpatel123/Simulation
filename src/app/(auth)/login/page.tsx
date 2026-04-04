'use client'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { Activity, Loader2, AlertCircle } from 'lucide-react'
import { motion } from 'framer-motion'

const schema = z.object({
  email: z.string().email('Enter a valid email'),
  password: z.string().min(8, 'Password must be at least 8 characters'),
})
type FormData = z.infer<typeof schema>

export default function LoginPage() {
  const router = useRouter()
  const [error, setError] = useState('')
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<FormData>({
    resolver: zodResolver(schema),
  })

  const onSubmit = async (_data: FormData) => {
    setError('')
    await new Promise(r => setTimeout(r, 1200))
    router.push('/dashboard')
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 24 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5 }}
    >
      <div className="text-center mb-8">
        <div className="flex items-center justify-center gap-2 mb-6">
          <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-indigo-500 to-cyan-400 flex items-center justify-center">
            <Activity className="w-4.5 h-4.5 text-white" />
          </div>
          <span className="font-display font-700 text-white text-xl">TheCee</span>
        </div>
        <h1 className="font-display text-2xl font-700 text-white mb-1">Welcome back</h1>
        <p className="text-slate-400 text-sm">Sign in to continue simulating</p>
      </div>

      <div className="glass rounded-2xl p-8">
        {error && (
          <div className="flex items-center gap-2 p-3 mb-5 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm">
            <AlertCircle className="w-4 h-4 shrink-0" />
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit(onSubmit)} className="space-y-5">
          <div>
            <label className="block text-sm text-slate-300 mb-1.5 font-medium">Email</label>
            <input
              {...register('email')}
              type="email"
              placeholder="you@example.com"
              className="w-full px-4 py-2.5 rounded-lg bg-white/5 border border-white/10 text-white placeholder-slate-600 text-sm focus:outline-none focus:border-indigo-500/60 focus:bg-white/8 transition-all"
            />
            {errors.email && <p className="text-red-400 text-xs mt-1">{errors.email.message}</p>}
          </div>

          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label className="text-sm text-slate-300 font-medium">Password</label>
              <a href="#" className="text-xs text-indigo-400 hover:text-indigo-300">Forgot password?</a>
            </div>
            <input
              {...register('password')}
              type="password"
              placeholder="••••••••"
              className="w-full px-4 py-2.5 rounded-lg bg-white/5 border border-white/10 text-white placeholder-slate-600 text-sm focus:outline-none focus:border-indigo-500/60 focus:bg-white/8 transition-all"
            />
            {errors.password && <p className="text-red-400 text-xs mt-1">{errors.password.message}</p>}
          </div>

          <button
            type="submit"
            disabled={isSubmitting}
            className="w-full flex items-center justify-center gap-2 py-2.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-60 disabled:cursor-not-allowed text-white font-medium text-sm transition-all duration-200"
          >
            {isSubmitting ? <><Loader2 className="w-4 h-4 animate-spin" /> Signing in...</> : 'Sign in'}
          </button>
        </form>

        <p className="text-center text-sm text-slate-500 mt-6">
          No account?{' '}
          <Link href="/signup" className="text-indigo-400 hover:text-indigo-300">Create one free</Link>
        </p>
      </div>
    </motion.div>
  )
}
