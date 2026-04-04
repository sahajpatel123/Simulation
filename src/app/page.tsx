'use client'

import { motion, useScroll, useTransform } from 'framer-motion'
import { useRef } from 'react'
import { ArrowRight, Zap, Shield, TrendingUp, Users, BarChart3, Brain, ChevronRight, Sparkles, Activity } from 'lucide-react'
import Link from 'next/link'

const fadeUp = {
  initial: { opacity: 0, y: 32 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.6, ease: [0.25, 0.46, 0.45, 0.94] as const },
}

export default function LandingPage() {
  const heroRef = useRef<HTMLDivElement>(null)
  const { scrollYProgress } = useScroll({ target: heroRef, offset: ['start start', 'end start'] })
  const heroOpacity = useTransform(scrollYProgress, [0, 1], [1, 0])
  const heroY = useTransform(scrollYProgress, [0, 1], [0, 80])

  return (
    <div className="relative min-h-screen bg-[#080810] overflow-x-hidden noise">

      {/* ━━━ NAVBAR ━━━ */}
      <motion.nav
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6 }}
        className="fixed top-0 left-0 right-0 z-50 flex items-center justify-between px-6 py-4 glass"
      >
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-indigo-500 to-cyan-400 flex items-center justify-center">
            <Activity className="w-4 h-4 text-white" />
          </div>
          <span className="font-display font-700 text-white text-lg tracking-tight">TheCee</span>
        </div>
        <div className="hidden md:flex items-center gap-8">
          {['How it works', 'Use cases', 'Pricing'].map((item) => (
            <a key={item} href="#" className="text-sm text-slate-400 hover:text-white transition-colors duration-200">
              {item}
            </a>
          ))}
        </div>
        <div className="flex items-center gap-3">
          <Link href="/login" className="text-sm text-slate-400 hover:text-white transition-colors">
            Log in
          </Link>
          <Link href="/signup" className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium transition-all duration-200 hover:shadow-lg hover:shadow-indigo-500/25">
            Get started <ArrowRight className="w-3.5 h-3.5" />
          </Link>
        </div>
      </motion.nav>

      {/* ━━━ HERO ━━━ */}
      <section ref={heroRef} className="relative min-h-screen flex flex-col items-center justify-center px-6 pt-24 pb-20 overflow-hidden">

        {/* Background orbs */}
        <div className="absolute top-1/4 left-1/4 w-96 h-96 rounded-full bg-indigo-600/15 blur-[120px] animate-pulse-glow pointer-events-none" />
        <div className="absolute bottom-1/4 right-1/4 w-80 h-80 rounded-full bg-cyan-500/10 blur-[100px] animate-pulse-glow pointer-events-none" style={{ animationDelay: '1.5s' }} />
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] rounded-full bg-indigo-900/10 blur-[140px] pointer-events-none" />

        <motion.div style={{ opacity: heroOpacity, y: heroY }} className="relative z-10 max-w-5xl mx-auto text-center">

          {/* Badge */}
          <motion.div {...fadeUp} className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full glass text-xs text-slate-400 mb-8">
            <Sparkles className="w-3 h-3 text-indigo-400" />
            <span>10,000 synthetic consumers per simulation run</span>
          </motion.div>

          {/* Headline */}
          <motion.h1
            initial={{ opacity: 0, y: 40 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, delay: 0.1, ease: [0.25, 0.46, 0.45, 0.94] }}
            className="font-display text-5xl md:text-7xl lg:text-8xl font-800 leading-[1.02] tracking-tight mb-6"
          >
            <span className="gradient-text">Run your decision</span>
            <br />
            <span className="gradient-text-accent">10,000 times</span>
            <br />
            <span className="gradient-text">before you make it.</span>
          </motion.h1>

          {/* Subheadline */}
          <motion.p
            initial={{ opacity: 0, y: 24 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, delay: 0.25 }}
            className="text-slate-400 text-lg md:text-xl max-w-2xl mx-auto mb-10 leading-relaxed"
          >
            TheCee simulates real consumer behavior, surfaces hidden assumptions,
            and shows you the full probability distribution of outcomes — before
            you spend a single rupee.
          </motion.p>

          {/* CTAs */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.4 }}
            className="flex flex-col sm:flex-row items-center justify-center gap-4 mb-16"
          >
            <Link href="/signup" className="group flex items-center gap-2 px-6 py-3.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-medium text-base transition-all duration-200 hover:shadow-2xl hover:shadow-indigo-500/30 hover:-translate-y-0.5">
              Start your first simulation
              <ArrowRight className="w-4 h-4 group-hover:translate-x-0.5 transition-transform" />
            </Link>
            <a href="#how" className="flex items-center gap-2 px-6 py-3.5 rounded-xl glass glass-hover text-slate-300 text-base font-medium">
              See how it works <ChevronRight className="w-4 h-4" />
            </a>
          </motion.div>

          {/* Floating stat cards */}
          <motion.div
            initial={{ opacity: 0, y: 30 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, delay: 0.55 }}
            className="grid grid-cols-3 gap-4 max-w-xl mx-auto"
          >
            {[
              { value: '10,000', label: 'Agents per run', icon: Users },
              { value: '112ms', label: 'Avg runtime', icon: Zap },
              { value: '68%+', label: 'Confidence score', icon: Shield },
            ].map(({ value, label, icon: Icon }, i) => (
              <div key={label} className="glass rounded-xl p-4 text-center animate-float" style={{ animationDelay: `${i * 0.7}s` }}>
                <Icon className="w-4 h-4 text-indigo-400 mx-auto mb-2" />
                <div className="font-display font-700 text-white text-xl">{value}</div>
                <div className="text-slate-500 text-xs mt-0.5">{label}</div>
              </div>
            ))}
          </motion.div>
        </motion.div>

        {/* Bottom gradient fade */}
        <div className="absolute bottom-0 left-0 right-0 h-32 bg-gradient-to-t from-[#080810] to-transparent pointer-events-none" />
      </section>

      {/* ━━━ MARQUEE STRIP ━━━ */}
      <div className="relative overflow-hidden border-y border-white/5 py-4 bg-white/[0.02]">
        <div className="flex animate-marquee whitespace-nowrap">
          {[...Array(2)].map((_, i) => (
            <div key={i} className="flex items-center gap-12 px-6">
              {['Assumption Extraction', 'Funnel Simulation', 'Probability Distribution', 'Markov Agent Engine', 'Sensitivity Analysis', 'Pre-mortem Engine', 'Intervention Generator', 'Calibration Flywheel'].map((item) => (
                <span key={item} className="text-slate-600 text-sm font-medium tracking-wide uppercase">{item}</span>
              ))}
            </div>
          ))}
        </div>
      </div>

      {/* ━━━ HOW IT WORKS ━━━ */}
      <section id="how" className="relative px-6 py-32 max-w-6xl mx-auto">
        <motion.div
          initial={{ opacity: 0, y: 24 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: '-100px' }}
          transition={{ duration: 0.6 }}
          className="text-center mb-20"
        >
          <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full glass text-xs text-indigo-400 mb-4">
            <Brain className="w-3 h-3" /> How TheCee works
          </div>
          <h2 className="font-display text-4xl md:text-5xl font-700 gradient-text mb-4">Three steps to certainty</h2>
          <p className="text-slate-400 max-w-xl mx-auto">No guesswork. No gut feelings. Just a probability distribution of exactly what is likely to happen.</p>
        </motion.div>

        <div className="grid md:grid-cols-3 gap-6 relative">
          {/* Connecting line */}
          <div className="hidden md:block absolute top-10 left-1/3 right-1/3 h-px bg-gradient-to-r from-transparent via-indigo-500/40 to-transparent" />

          {[
            {
              step: '01',
              icon: Brain,
              title: 'Describe your idea',
              body: 'Type your product idea in plain language. TheCee extracts every hidden assumption you did not know you were making.',
              color: 'from-indigo-500 to-indigo-700',
            },
            {
              step: '02',
              icon: Users,
              title: 'Simulate reality',
              body: '10,000 synthetic consumers with distinct behavioral profiles traverse your product funnel using Markov decision chains.',
              color: 'from-cyan-500 to-indigo-500',
            },
            {
              step: '03',
              icon: BarChart3,
              title: 'Get clear answers',
              body: 'See probability distributions, conversion confidence intervals, funnel drop-off points, and ranked interventions.',
              color: 'from-emerald-500 to-cyan-500',
            },
          ].map(({ step, icon: Icon, title, body, color }, i) => (
            <motion.div
              key={step}
              initial={{ opacity: 0, y: 32 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: '-80px' }}
              transition={{ duration: 0.6, delay: i * 0.12 }}
              className="glass glass-hover rounded-2xl p-8 relative group"
            >
              <div className={`w-10 h-10 rounded-xl bg-gradient-to-br ${color} flex items-center justify-center mb-6`}>
                <Icon className="w-5 h-5 text-white" />
              </div>
              <div className="font-display text-xs text-slate-600 font-600 tracking-widest uppercase mb-2">{step}</div>
              <h3 className="font-display text-xl font-600 text-white mb-3">{title}</h3>
              <p className="text-slate-400 text-sm leading-relaxed">{body}</p>
            </motion.div>
          ))}
        </div>
      </section>

      {/* ━━━ USE CASES ━━━ */}
      <section className="px-6 py-24 max-w-6xl mx-auto">
        <motion.div
          initial={{ opacity: 0, y: 24 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: '-100px' }}
          transition={{ duration: 0.6 }}
          className="text-center mb-16"
        >
          <h2 className="font-display text-4xl md:text-5xl font-700 gradient-text mb-4">Built for founders who move fast</h2>
          <p className="text-slate-400 max-w-lg mx-auto">Every kind of launch. Every kind of decision. Simulated before committed.</p>
        </motion.div>

        <div className="grid md:grid-cols-2 gap-4">
          {[
            {
              icon: Zap,
              title: 'Indie founders',
              body: 'You have one shot and limited runway. Know exactly which assumptions are killing your conversion before you build.',
              tag: 'Solo launch',
            },
            {
              icon: TrendingUp,
              title: 'Product managers',
              body: 'Justify your roadmap decisions with probability data, not opinions. Run competing feature bets through simulation before the sprint.',
              tag: 'Roadmap decisions',
            },
            {
              icon: Shield,
              title: 'D2C and physical products',
              body: 'Simulate pricing sensitivity, channel ROI, and market fit before your first manufacturing run.',
              tag: 'Physical launch',
            },
            {
              icon: Users,
              title: 'Side project validation',
              body: 'Test your weekend idea against 10,000 synthetic users before you touch a single line of code.',
              tag: 'Pre-build',
            },
          ].map(({ icon: Icon, title, body, tag }, i) => (
            <motion.div
              key={title}
              initial={{ opacity: 0, y: 24 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: '-60px' }}
              transition={{ duration: 0.5, delay: i * 0.08 }}
              className="glass glass-hover rounded-2xl p-8 group"
            >
              <div className="flex items-start justify-between mb-5">
                <div className="w-9 h-9 rounded-lg bg-indigo-500/15 border border-indigo-500/20 flex items-center justify-center">
                  <Icon className="w-4.5 h-4.5 text-indigo-400" />
                </div>
                <span className="text-xs text-slate-600 px-2.5 py-1 rounded-full border border-white/5">{tag}</span>
              </div>
              <h3 className="font-display text-lg font-600 text-white mb-2">{title}</h3>
              <p className="text-slate-400 text-sm leading-relaxed">{body}</p>
            </motion.div>
          ))}
        </div>
      </section>

      {/* ━━━ STATS STRIP ━━━ */}
      <section className="px-6 py-20 border-y border-white/5">
        <motion.div
          initial={{ opacity: 0 }}
          whileInView={{ opacity: 1 }}
          viewport={{ once: true }}
          transition={{ duration: 0.8 }}
          className="max-w-4xl mx-auto grid grid-cols-2 md:grid-cols-4 gap-8 text-center"
        >
          {[
            { value: '10,000', label: 'Synthetic agents per run' },
            { value: '₹5.52', label: 'Cost per simulation' },
            { value: '112ms', label: 'Average execution time' },
            { value: '3×', label: 'Stochastic runs default' },
          ].map(({ value, label }) => (
            <div key={label}>
              <div className="font-display text-3xl md:text-4xl font-800 gradient-text-accent mb-1">{value}</div>
              <div className="text-slate-500 text-sm">{label}</div>
            </div>
          ))}
        </motion.div>
      </section>

      {/* ━━━ FINAL CTA ━━━ */}
      <section className="px-6 py-40 text-center relative overflow-hidden">
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[500px] h-[500px] rounded-full bg-indigo-600/10 blur-[120px] pointer-events-none" />
        <motion.div
          initial={{ opacity: 0, y: 32 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.7 }}
          className="relative z-10 max-w-2xl mx-auto"
        >
          <h2 className="font-display text-5xl md:text-6xl font-800 gradient-text mb-6 leading-tight">
            Stop guessing.<br />Start simulating.
          </h2>
          <p className="text-slate-400 text-lg mb-10">
            Every decision you make without simulation is a decision made blind.
          </p>
          <Link href="/signup" className="group inline-flex items-center gap-2 px-8 py-4 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-medium text-lg transition-all duration-200 hover:shadow-2xl hover:shadow-indigo-500/30 hover:-translate-y-0.5">
            Run your first simulation free
            <ArrowRight className="w-5 h-5 group-hover:translate-x-0.5 transition-transform" />
          </Link>
        </motion.div>
      </section>

      {/* ━━━ FOOTER ━━━ */}
      <footer className="px-6 py-10 border-t border-white/5">
        <div className="max-w-6xl mx-auto flex flex-col md:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded-md bg-gradient-to-br from-indigo-500 to-cyan-400 flex items-center justify-center">
              <Activity className="w-3.5 h-3.5 text-white" />
            </div>
            <span className="font-display font-600 text-white text-sm">TheCee</span>
          </div>
          <p className="text-slate-600 text-sm">© 2026 TheCee. Simulate before you build.</p>
          <div className="flex items-center gap-6">
            {['Privacy', 'Terms', 'Contact'].map((item) => (
              <a key={item} href="#" className="text-slate-600 hover:text-slate-400 text-sm transition-colors">{item}</a>
            ))}
          </div>
        </div>
      </footer>

    </div>
  )
}
