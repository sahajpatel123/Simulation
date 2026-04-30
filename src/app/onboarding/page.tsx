'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { AnimatePresence, motion } from 'framer-motion'

import { IntakeModeSelector, type IntakeMode } from '@/components/IntakeModeSelector'
import { getApiV1Base } from '@/lib/api-v1-base'

const apiV1 = () => getApiV1Base()

const PRODUCT_TYPES = [
  { value: 'saas', label: 'SaaS', icon: '💻' },
  { value: 'marketplace', label: 'Marketplace', icon: '🏪' },
  { value: 'mobile_app', label: 'Mobile App', icon: '📱' },
  { value: 'developer_tool', label: 'Developer Tool', icon: '⚙️' },
  { value: 'enterprise_software', label: 'Enterprise Software', icon: '🏛️' },
  { value: 'consumer_hardware', label: 'Consumer Hardware', icon: '📦' },
  { value: 'health_hardware', label: 'Health Hardware', icon: '❤️' },
  { value: 'iot_hardware', label: 'IoT Hardware', icon: '🌐' },
  { value: 'wearable', label: 'Wearable', icon: '⌚' },
  { value: 'b2b_hardware', label: 'B2B Hardware', icon: '🔧' },
]

const HW_TYPES = new Set([
  'consumer_hardware',
  'health_hardware',
  'iot_hardware',
  'wearable',
  'b2b_hardware',
])

const STORAGE_KEY = 'thecee_onboarding'
const ONBOARDING_DONE_KEY = 'thecee_onboarding_complete'

function setOnboardedCookie() {
  if (typeof document === 'undefined') return
  document.cookie = 'onboarded=1; max-age=31536000; path=/'
}

function markOnboardingComplete() {
  try {
    localStorage.setItem(ONBOARDING_DONE_KEY, '1')
  } catch {
    /* ignore */
  }
  setOnboardedCookie()
}

type SavedOnboarding = {
  step?: number
  intakeMode?: IntakeMode
  productType?: string
  projectName?: string
  description?: string
  projectId?: number
  simId?: number
}

function loadProgress(): SavedOnboarding {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? (JSON.parse(raw) as SavedOnboarding) : { step: 1 }
  } catch {
    return { step: 1 }
  }
}

function saveProgress(data: object) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(data))
  } catch {
    /* ignore */
  }
}

function clearProgress() {
  try {
    localStorage.removeItem(STORAGE_KEY)
  } catch {
    /* ignore */
  }
}

export default function OnboardingPage() {
  const router = useRouter()
  const [step, setStep] = useState(1)
  const [intakeMode, setIntakeMode] = useState<IntakeMode>('IDEA')
  const [productType, setProductType] = useState('')
  const [projectName, setProjectName] = useState('')
  const [description, setDescription] = useState('')
  const [projectId, setProjectId] = useState<number | null>(null)
  const [simId, setSimId] = useState<number | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const token = typeof window !== 'undefined' ? localStorage.getItem('access_token') : null
  const headers: HeadersInit = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  }

  useEffect(() => {
    const saved = loadProgress()
    if (saved.step) setStep(saved.step)
    if (saved.intakeMode) setIntakeMode(saved.intakeMode)
    if (saved.productType) setProductType(saved.productType)
    if (saved.projectId) setProjectId(saved.projectId)
    if (saved.simId) setSimId(saved.simId)
    if (saved.projectName) setProjectName(saved.projectName)
    if (saved.description) setDescription(saved.description)
  }, [])

  const persist = (patch: object) => {
    const current = loadProgress()
    saveProgress({ ...current, ...patch })
  }

  const next = () => {
    setStep((s) => {
      const n = s + 1
      persist({ step: n })
      return n
    })
  }

  const handleSkip = () => {
    markOnboardingComplete()
    clearProgress()
    router.push('/dashboard')
  }

  const handleCreateProject = async () => {
    if (!projectName.trim() || !description.trim()) return
    setLoading(true)
    setError('')
    try {
      const axis = HW_TYPES.has(productType) ? 'hardware' : 'software'
      const desc =
        productType.trim().length > 0
          ? `${description.trim()}\n\n(Product type: ${productType.replace(/_/g, ' ')})`
          : description.trim()

      const r = await fetch(`${apiV1()}/projects`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          title: projectName.trim(),
          description: desc,
          intake_mode: intakeMode,
          dossier_axis: axis,
        }),
      })
      if (!r.ok) throw new Error(await r.text())
      const data = (await r.json()) as { id: number }
      setProjectId(data.id)
      persist({
        projectId: data.id,
        projectName: projectName.trim(),
        description: description.trim(),
        step: 4,
      })
      setStep(4)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Request failed')
    } finally {
      setLoading(false)
    }
  }

  const handleRunSimulation = async () => {
    if (!projectId) return
    setLoading(true)
    setError('')
    try {
      const envR = await fetch(`${apiV1()}/projects/${projectId}/environments`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ mode: 'MANUAL' }),
      })
      if (!envR.ok) throw new Error((await envR.text()) || 'Failed to set environment')

      const simR = await fetch(`${apiV1()}/simulations`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ project_id: projectId, consumer_volume: 10000 }),
      })
      if (!simR.ok) throw new Error(await simR.text())
      const data = (await simR.json()) as { id: number }
      setSimId(data.id)
      persist({ simId: data.id, step: 5 })
      setStep(5)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Request failed')
    } finally {
      setLoading(false)
    }
  }

  const handleComplete = () => {
    markOnboardingComplete()
    clearProgress()
    if (projectId && simId) {
      router.push(`/project/${projectId}/results?sim=${simId}`)
    } else {
      router.push('/dashboard')
    }
  }

  const STEPS = ['Build type', 'Product', 'Project', 'Simulate', 'Meet your people']

  function stepBody() {
    switch (step) {
      case 1:
        return (
          <>
            <div>
              <p className="text-xs text-blue-400 tracking-widest uppercase mb-1">Step 1 of 5</p>
              <h1 className="text-xl font-bold text-white">What are you building?</h1>
              <p className="text-sm text-slate-500 mt-1">This shapes how TheCee interprets your product.</p>
            </div>
            <IntakeModeSelector
              value={intakeMode}
              onChange={(v) => {
                setIntakeMode(v)
                persist({ intakeMode: v })
              }}
            />
            <button
              type="button"
              onClick={next}
              className="w-full py-3 bg-blue-600 hover:bg-blue-500 rounded-xl text-sm font-bold tracking-widest uppercase transition-all"
            >
              Continue →
            </button>
          </>
        )
      case 2:
        return (
          <>
            <div>
              <p className="text-xs text-blue-400 tracking-widest uppercase mb-1">Step 2 of 5</p>
              <h1 className="text-xl font-bold text-white">What type of product?</h1>
            </div>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-2">
              {PRODUCT_TYPES.map((pt) => (
                <button
                  key={pt.value}
                  type="button"
                  onClick={() => {
                    setProductType(pt.value)
                    persist({ productType: pt.value })
                  }}
                  className={`flex items-center gap-2 p-3 rounded-xl border text-left transition-all text-sm ${
                    productType === pt.value
                      ? 'border-blue-500 bg-blue-500/10 text-white'
                      : 'border-slate-800 text-slate-400 hover:border-slate-700'
                  }`}
                >
                  <span>{pt.icon}</span>
                  <span>{pt.label}</span>
                </button>
              ))}
            </div>
            <div className="flex gap-3">
              <button
                type="button"
                onClick={() => setStep(1)}
                className="flex-1 py-2.5 border border-slate-800 rounded-xl text-sm text-slate-500 hover:text-slate-300 transition-all"
              >
                ← Back
              </button>
              <button
                type="button"
                onClick={next}
                disabled={!productType}
                className="flex-1 py-2.5 bg-blue-600 hover:bg-blue-500 rounded-xl text-sm font-bold tracking-widest uppercase disabled:opacity-40 transition-all"
              >
                Continue →
              </button>
            </div>
          </>
        )
      case 3:
        return (
          <>
            <div>
              <p className="text-xs text-blue-400 tracking-widest uppercase mb-1">Step 3 of 5</p>
              <h1 className="text-xl font-bold text-white">File your first dossier</h1>
              <p className="text-sm text-slate-500 mt-1">Describe your product in plain language.</p>
            </div>
            <div className="space-y-3">
              <input
                value={projectName}
                onChange={(e) => {
                  setProjectName(e.target.value)
                  persist({ projectName: e.target.value })
                }}
                placeholder="Product name"
                className="w-full bg-slate-800 border border-slate-700 rounded-xl px-4 py-3 text-sm text-slate-200 placeholder-slate-600 focus:border-blue-500 focus:outline-none"
              />
              <textarea
                value={description}
                onChange={(e) => {
                  setDescription(e.target.value)
                  persist({ description: e.target.value })
                }}
                placeholder="We're building a..."
                rows={4}
                className="w-full bg-slate-800 border border-slate-700 rounded-xl px-4 py-3 text-sm text-slate-200 placeholder-slate-600 resize-none focus:border-blue-500 focus:outline-none"
              />
            </div>
            {error && <p className="text-xs text-red-400">{error}</p>}
            <div className="flex gap-3">
              <button
                type="button"
                onClick={() => setStep(2)}
                className="flex-1 py-2.5 border border-slate-800 rounded-xl text-sm text-slate-500 hover:text-slate-300 transition-all"
              >
                ← Back
              </button>
              <button
                type="button"
                onClick={handleCreateProject}
                disabled={!projectName.trim() || !description.trim() || loading}
                className="flex-1 py-2.5 bg-blue-600 hover:bg-blue-500 rounded-xl text-sm font-bold tracking-widest uppercase disabled:opacity-40 transition-all"
              >
                {loading ? 'Creating...' : 'Create Project →'}
              </button>
            </div>
            <button
              type="button"
              onClick={handleSkip}
              className="w-full text-xs text-slate-700 hover:text-slate-500 transition-all"
            >
              Skip onboarding → go to dashboard
            </button>
          </>
        )
      case 4:
        return (
          <>
            <div>
              <p className="text-xs text-blue-400 tracking-widest uppercase mb-1">Step 4 of 5</p>
              <h1 className="text-xl font-bold text-white">Run your first simulation</h1>
              <p className="text-sm text-slate-500 mt-1">
                52 clusters of real-world people will evaluate your product. Queued on the worker — may take a
                minute.
              </p>
            </div>
            <div className="bg-slate-800 rounded-xl p-4 space-y-2">
              {[
                'Extracting assumptions from your description',
                'Running 52-cluster Conductor analysis',
                'Applying CognitiveState mutations',
                'Generating Key Person Report',
              ].map((item, i) => (
                <p key={i} className="text-xs text-slate-400 flex items-center gap-2">
                  <span className="text-blue-500">→</span> {item}
                </p>
              ))}
            </div>
            {error && <p className="text-xs text-red-400">{error}</p>}
            <button
              type="button"
              onClick={handleRunSimulation}
              disabled={loading}
              className="w-full py-3 bg-blue-600 hover:bg-blue-500 rounded-xl text-sm font-bold tracking-widest uppercase disabled:opacity-40 transition-all"
            >
              {loading ? (
                <span className="flex items-center justify-center gap-2">
                  <span className="w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  Queuing simulation...
                </span>
              ) : (
                '▶ Run Simulation →'
              )}
            </button>
            <button
              type="button"
              onClick={handleSkip}
              className="w-full text-xs text-slate-700 hover:text-slate-500 transition-all"
            >
              Skip → go to dashboard
            </button>
          </>
        )
      case 5:
        return (
          <>
            <div>
              <p className="text-xs text-green-400 tracking-widest uppercase mb-1">✓ Simulation complete</p>
              <h1 className="text-xl font-bold text-white">Meet the people who decided</h1>
              <p className="text-sm text-slate-500 mt-1">
                TheCee identified the exact people who would convert — and the ones who would walk away, and
                why.
              </p>
            </div>
            <div className="space-y-3">
              {[
                {
                  icon: '🔴',
                  label: 'Blockers',
                  desc: 'People who dropped — with the one thing that would have changed their mind',
                },
                {
                  icon: '🟢',
                  label: 'Champions',
                  desc: 'People who convert — your acquisition focus',
                },
                {
                  icon: '⚡',
                  label: 'Insights',
                  desc: 'Assumption conflicts, primary failure domain, iteration delta',
                },
              ].map((item) => (
                <div key={item.label} className="flex items-start gap-3 p-3 bg-slate-800 rounded-xl">
                  <span className="text-xl">{item.icon}</span>
                  <div>
                    <p className="text-sm font-bold text-white">{item.label}</p>
                    <p className="text-xs text-slate-500">{item.desc}</p>
                  </div>
                </div>
              ))}
            </div>
            <button
              type="button"
              onClick={handleComplete}
              className="w-full py-3 bg-blue-600 hover:bg-blue-500 rounded-xl text-sm font-bold tracking-widest uppercase transition-all"
            >
              View My Results →
            </button>
          </>
        )
      default:
        return null
    }
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 font-mono flex flex-col items-center justify-center px-4">
      <div className="w-full max-w-xl mb-8">
        <div className="flex justify-between mb-2">
          {STEPS.map((_, i) => (
            <span
              key={i}
              className={`text-xs tracking-widest uppercase ${
                i + 1 === step ? 'text-blue-400' : i + 1 < step ? 'text-green-400' : 'text-slate-700'
              }`}
            >
              {i + 1 < step ? '✓' : i + 1}
            </span>
          ))}
        </div>
        <div className="h-1 bg-slate-800 rounded-full overflow-hidden">
          <div
            className="h-full bg-blue-500 rounded-full transition-all duration-500"
            style={{ width: `${((step - 1) / (STEPS.length - 1)) * 100}%` }}
          />
        </div>
        <div className="flex justify-between mt-1">
          {STEPS.map((label, i) => (
            <span key={i} className="text-xs text-slate-700">
              {label}
            </span>
          ))}
        </div>
      </div>

      <AnimatePresence mode="wait">
        <motion.div
          key={step}
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -12 }}
          className="w-full max-w-xl bg-slate-900 border border-slate-800 rounded-2xl p-8 space-y-6"
        >
          {stepBody()}
        </motion.div>
      </AnimatePresence>
    </div>
  )
}
