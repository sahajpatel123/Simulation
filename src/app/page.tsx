'use client'

import { motion, useScroll, useTransform } from 'framer-motion'
import { useRef } from 'react'
import { ArrowRight, ChevronRight } from 'lucide-react'
import Link from 'next/link'

export default function LandingPage() {
  const heroRef = useRef<HTMLElement>(null)
  const { scrollY } = useScroll()
  const heroY = useTransform(scrollY, [0, 600], [0, 60])
  const heroOpacity = useTransform(scrollY, [0, 480], [1, 0])

  const marqueeItems = [
    'Idea Validation',
    'Launch Readiness',
    'Product-Market Fit',
    'Customer Behavior',
    'Risk Discovery',
    'Revenue Forecasting',
    'Growth Scenarios',
    'Startup Stress Testing',
    'Decision Intelligence',
    'Market Readiness',
    'Competitor Scenarios',
    'Pricing Confidence',
  ]

  return (
    <div className="relative min-h-screen overflow-x-hidden bg-[#06060e] text-white">
      <div
        className="fixed inset-0 pointer-events-none"
        style={{
          backgroundImage: `linear-gradient(rgba(99,102,241,0.03) 1px, transparent 1px),
                            linear-gradient(90deg, rgba(99,102,241,0.03) 1px, transparent 1px)`,
          backgroundSize: '60px 60px',
        }}
      />

      <motion.nav
        initial={{ opacity: 0, y: -16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6 }}
        className="fixed top-0 left-0 right-0 z-50 flex items-center justify-between px-8 py-5"
        style={{
          backdropFilter: 'blur(20px)',
          background: 'rgba(6,6,14,0.7)',
          borderBottom: '1px solid rgba(255,255,255,0.04)',
        }}
      >
        <div className="flex items-center gap-2.5">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
            <circle cx="12" cy="12" r="4" fill="#6366f1" />
            <circle cx="12" cy="12" r="8" stroke="#6366f1" strokeWidth="1" opacity="0.3" />
            <circle cx="12" cy="12" r="11" stroke="#6366f1" strokeWidth="0.5" opacity="0.15" />
          </svg>
          <span className="font-display text-lg tracking-tight text-white font-700">TheCee</span>
        </div>

        <div className="hidden items-center gap-10 md:flex">
          {['How it works', 'Use cases', 'Pricing'].map((item) => (
            <a
              key={item}
              href="#"
              className="text-sm tracking-wide text-slate-500 transition-colors duration-200 hover:text-white"
            >
              {item}
            </a>
          ))}
        </div>

        <div className="flex items-center gap-4">
          <Link href="/login" className="text-sm text-slate-500 transition-colors hover:text-white">
            Sign in
          </Link>
          <Link
            href="/signup"
            className="flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-medium text-white transition-all duration-200"
            style={{ background: 'rgba(99,102,241,0.9)', boxShadow: '0 0 20px rgba(99,102,241,0.25)' }}
          >
            Get started <ArrowRight className="h-3.5 w-3.5" />
          </Link>
        </div>
      </motion.nav>

      <div className="fixed inset-0 z-0 pointer-events-none">
        <img
          src="/nature-bg.jpeg"
          alt=""
          className="w-full h-full object-cover object-center"
          style={{ opacity: 0.22, objectPosition: 'center 30%' }}
        />
        <div
          className="absolute inset-0"
          style={{
            background: 'linear-gradient(to bottom, rgba(6,6,14,0.55) 0%, rgba(6,6,14,0.35) 35%, rgba(6,6,14,0.8) 78%, rgba(6,6,14,1) 100%)',
          }}
        />
      </div>

      <section ref={heroRef} className="relative z-10 flex min-h-screen items-center justify-center pt-20">
        <motion.div
          style={{ y: heroY, opacity: heroOpacity }}
          className="mx-auto w-full max-w-4xl px-8 text-center"
        >
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5 }}
            className="mb-8 inline-flex items-center gap-2"
          >
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400" />
            <span className="text-xs font-medium uppercase tracking-widest text-slate-500">Now in early access</span>
          </motion.div>

          <motion.h1
            initial={{ opacity: 0, y: 24 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, delay: 0.1 }}
            className="mb-6 font-display text-5xl leading-[1.04] tracking-tight lg:text-6xl xl:text-7xl font-800"
          >
            <span style={{ color: '#f1f5f9' }}>Know if your</span>
            <br />
            <span
              style={{
                background: 'linear-gradient(135deg, #818cf8 0%, #38bdf8 60%, #34d399 100%)',
                WebkitBackgroundClip: 'text',
                WebkitTextFillColor: 'transparent',
                backgroundClip: 'text',
              }}
            >
              startup will work.
            </span>
            <br />
            <span style={{ color: '#94a3b8' }}>Before you build it.</span>
          </motion.h1>

          <motion.p
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.22 }}
            className="mx-auto mb-10 max-w-2xl text-lg leading-relaxed text-slate-400"
            style={{ fontWeight: 300 }}
          >
            Describe your product, idea, or launch plan. TheCee stress-tests it
            against thousands of real-world scenarios and tells you exactly
            what will work, what will fail, and how to improve your odds.
          </motion.p>

          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.35 }}
            className="mb-14 flex flex-col items-center justify-center gap-4 sm:flex-row"
          >
            <Link
              href="/signup"
              className="group flex items-center gap-2 rounded-xl px-6 py-3.5 text-sm font-medium text-white transition-all duration-200 hover:-translate-y-0.5"
              style={{
                background: 'linear-gradient(135deg, #6366f1, #4f46e5)',
                boxShadow: '0 0 30px rgba(99,102,241,0.3), inset 0 1px 0 rgba(255,255,255,0.1)',
              }}
            >
              Validate your idea free
              <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
            </Link>
            <a
              href="#how"
              className="flex items-center gap-1.5 text-sm text-slate-500 transition-colors hover:text-slate-300"
            >
              See how it works <ChevronRight className="h-4 w-4" />
            </a>
          </motion.div>

          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.5 }}
            className="flex items-center justify-center gap-3"
          >
            <div className="flex -space-x-2">
              {['#6366f1', '#06b6d4', '#10b981', '#f59e0b'].map((c, i) => (
                <div
                  key={i}
                  className="flex h-7 w-7 items-center justify-center rounded-full border-2 border-[#06060e] text-xs font-700"
                  style={{ background: c }}
                >
                  {['S', 'M', 'R', 'A'][i]}
                </div>
              ))}
            </div>
            <p className="text-xs text-slate-600">
              Trusted by <span className="text-slate-400">240+ founders</span> before their launch
            </p>
          </motion.div>
        </motion.div>
      </section>

      <div
        className="relative z-10 overflow-hidden border-y border-white/[0.04] py-5"
        style={{ background: 'rgba(255,255,255,0.01)' }}
      >
        <div className="flex whitespace-nowrap animate-marquee">
          {[...Array(2)].map((_, i) => (
            <div key={i} className="flex items-center gap-0">
              {marqueeItems.map((item, j) => (
                <span key={`${i}-${j}`} className="flex items-center gap-6 px-6">
                  <span className="text-[11px] uppercase tracking-[0.15em] text-slate-600 font-500">{item}</span>
                  <span className="h-1 w-1 rounded-full bg-slate-700" />
                </span>
              ))}
            </div>
          ))}
        </div>
      </div>

      <section id="how" className="relative z-10 mx-auto max-w-6xl bg-[#06060e] px-8 py-36">
        <motion.div
          initial={{ opacity: 0, y: 24 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: '-80px' }}
          transition={{ duration: 0.6 }}
          className="mb-20"
        >
          <p className="mb-4 text-xs uppercase tracking-widest text-slate-600">How it works</p>
          <h2 className="max-w-xl font-display text-4xl leading-tight text-slate-100 md:text-5xl font-700">
            From idea to answer
            <br />
            in three steps.
          </h2>
        </motion.div>

        <div className="grid gap-px overflow-hidden rounded-2xl bg-white/[0.04] md:grid-cols-3">
          {[
            {
              num: '01',
              title: 'Describe your idea',
              body: 'Write your product idea, business model, or launch plan in plain English. No technical knowledge needed.',
            },
            {
              num: '02',
              title: 'We test it for you',
              body: 'TheCee runs your idea through thousands of real-world scenarios - different customers, market conditions, and competitive landscapes.',
            },
            {
              num: '03',
              title: 'Get clear answers',
              body: 'See what is likely to succeed, what risks to avoid, and the exact changes that will improve your chances.',
            },
          ].map(({ num, title, body }, i) => (
            <motion.div
              key={num}
              initial={{ opacity: 0, y: 24 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: '-60px' }}
              transition={{ duration: 0.5, delay: i * 0.1 }}
              className="bg-[#06060e] p-10 transition-colors duration-300 hover:bg-[#0a0a18]"
            >
              <div
                className="mb-8 font-display text-5xl leading-none font-800"
                style={{
                  background: 'linear-gradient(135deg, rgba(99,102,241,0.4) 0%, rgba(99,102,241,0.05) 100%)',
                  WebkitBackgroundClip: 'text',
                  WebkitTextFillColor: 'transparent',
                  backgroundClip: 'text',
                }}
              >
                {num}
              </div>
              <h3 className="mb-3 font-display text-lg text-white font-600">{title}</h3>
              <p className="text-sm leading-relaxed text-slate-500" style={{ fontWeight: 300 }}>{body}</p>
            </motion.div>
          ))}
        </div>
      </section>

      <section className="relative z-10 mx-auto max-w-6xl bg-[#06060e] px-8 py-24">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.6 }}
          className="mb-16"
        >
          <p className="mb-4 text-xs uppercase tracking-widest text-slate-600">Who it&apos;s for</p>
          <h2 className="max-w-lg font-display text-4xl leading-tight text-slate-100 font-700">
            Built for people who cannot afford to guess.
          </h2>
        </motion.div>

        <div className="grid gap-4 md:grid-cols-2">
          {[
            {
              title: 'First-time founders',
              body: 'Launching your first product with limited runway. Know which risks are real before you spend a single rupee.',
              highlight: 'Validate before you build',
            },
            {
              title: 'Product managers',
              body: 'Justify your next feature or launch decision with scenario data instead of opinions in a room.',
              highlight: 'Data over opinion',
            },
            {
              title: 'D2C and physical products',
              body: 'Test pricing, channels, and customer response before you commit to inventory or manufacturing.',
              highlight: 'Test before you manufacture',
            },
            {
              title: 'Side project builders',
              body: 'Find out if your weekend idea is worth your evenings before you invest months into it.',
              highlight: 'Know before you commit',
            },
          ].map(({ title, body, highlight }, i) => (
            <motion.div
              key={title}
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.5, delay: i * 0.08 }}
              className="group cursor-pointer rounded-2xl border border-white/[0.05] bg-white/[0.01] p-8 transition-all duration-300 hover:border-indigo-500/20 hover:bg-indigo-500/[0.02]"
            >
              <div className="mb-4 text-xs font-medium tracking-wide text-indigo-400">{highlight}</div>
              <h3 className="mb-2 font-display text-lg text-white font-600">{title}</h3>
              <p className="text-sm leading-relaxed text-slate-500" style={{ fontWeight: 300 }}>{body}</p>
            </motion.div>
          ))}
        </div>
      </section>

      <section className="relative z-10 border-y border-white/[0.04] bg-[#06060e] px-8 py-20">
        <motion.div
          initial={{ opacity: 0 }}
          whileInView={{ opacity: 1 }}
          viewport={{ once: true }}
          transition={{ duration: 0.8 }}
          className="mx-auto grid max-w-4xl grid-cols-2 gap-12 md:grid-cols-4"
        >
          {[
            { value: '10,000+', label: 'Scenarios per test' },
            { value: '< 2 min', label: 'Time to first insight' },
            { value: '240+', label: 'Founders validated' },
            { value: '3 runs', label: 'Cross-validated by default' },
          ].map(({ value, label }) => (
            <div key={label} className="text-center">
              <div
                className="mb-1.5 font-display text-3xl font-800"
                style={{
                  background: 'linear-gradient(135deg, #c7d2fe, #818cf8)',
                  WebkitBackgroundClip: 'text',
                  WebkitTextFillColor: 'transparent',
                  backgroundClip: 'text',
                }}
              >
                {value}
              </div>
              <div className="text-xs tracking-wide text-slate-600">{label}</div>
            </div>
          ))}
        </motion.div>
      </section>

      <section className="relative z-10 bg-[#06060e] px-8 py-44 text-center">
        <div
          className="pointer-events-none absolute top-1/2 left-1/2 h-[300px] w-[600px] -translate-x-1/2 -translate-y-1/2"
          style={{ background: 'radial-gradient(ellipse at center, rgba(99,102,241,0.07) 0%, transparent 70%)' }}
        />
        <motion.div
          initial={{ opacity: 0, y: 32 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.7 }}
          className="relative mx-auto max-w-2xl"
        >
          <h2 className="mb-6 font-display text-5xl leading-tight text-slate-100 md:text-6xl font-800">
            Your next big decision
            <br />
            <span
              style={{
                background: 'linear-gradient(135deg, #818cf8, #38bdf8)',
                WebkitBackgroundClip: 'text',
                WebkitTextFillColor: 'transparent',
                backgroundClip: 'text',
              }}
            >
              deserves certainty.
            </span>
          </h2>
          <p className="mb-10 text-lg text-slate-500" style={{ fontWeight: 300 }}>
            Stop guessing. Start simulating.
          </p>
          <Link
            href="/signup"
            className="group inline-flex items-center gap-2 rounded-xl px-8 py-4 text-base font-medium text-white transition-all duration-200 hover:-translate-y-0.5"
            style={{
              background: 'linear-gradient(135deg, #6366f1, #4f46e5)',
              boxShadow: '0 0 40px rgba(99,102,241,0.25), inset 0 1px 0 rgba(255,255,255,0.1)',
            }}
          >
            Validate your idea - it&apos;s free
            <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
          </Link>
        </motion.div>
      </section>

      <footer className="relative z-10 border-t border-white/[0.04] bg-[#06060e] px-8 py-8">
        <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-4 md:flex-row">
          <div className="flex items-center gap-2">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
              <circle cx="12" cy="12" r="4" fill="#6366f1" />
              <circle cx="12" cy="12" r="8" stroke="#6366f1" strokeWidth="1" opacity="0.3" />
            </svg>
            <span className="font-display text-sm text-slate-400 font-600">TheCee</span>
          </div>
          <p className="text-xs text-slate-700">© 2026 TheCee. Simulate before you build.</p>
          <div className="flex items-center gap-6">
            {['Privacy', 'Terms', 'Contact'].map((item) => (
              <a key={item} href="#" className="text-xs text-slate-700 transition-colors hover:text-slate-500">{item}</a>
            ))}
          </div>
        </div>
      </footer>
    </div>
  )
}
