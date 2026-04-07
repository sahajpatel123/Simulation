'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

const FEATURES = [
  {
    word: 'Build',
    desc: 'Prompt TheCee to generate your product UI — every page, every flow, every button working.',
    cue: 'See UI generation',
  },
  {
    word: 'Simulate',
    desc: '10,000 synthetic users interact with your product. Real clicks, real funnels, real truth.',
    cue: 'See simulation engine',
  },
  {
    word: 'Decide',
    desc: 'Every pricing and positioning scenario compared. The path that survives, identified.',
    cue: 'See decision studio',
  },
  {
    word: 'Know',
    desc: 'The exact autopsy of your idea — failure modes ranked — before you build or spend anything.',
    cue: 'See pre-mortem report',
  },
] as const

const CRUMBS = ['UI Builder', 'Simulation Engine', 'Decision Studio', 'Pre-mortem Report'] as const
const DUR = 7000

export default function FeatureShowcase() {
  const [active, setActive] = useState(0)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const animTimers = useRef<ReturnType<typeof setTimeout>[]>([])
  const rafRefs = useRef<number[]>([])
  const progressRef = useRef<HTMLDivElement>(null)
  const c2CanvasRef = useRef<HTMLCanvasElement>(null)

  const [typedText, setTypedText] = useState('')
  const [showBtn, setShowBtn] = useState(false)
  const [showPages, setShowPages] = useState([false, false, false])
  const [showSite, setShowSite] = useState(false)
  const [siteCards, setSiteCards] = useState([false, false, false])
  const [genBarW, setGenBarW] = useState(0)

  const [agentCount, setAgentCount] = useState(0)
  const [funnelWidths, setFunnelWidths] = useState([0, 0, 0, 0, 0])
  const [funnelNums, setFunnelNums] = useState(['—', '—', '—', '—', '—'])
  const [showResult, setShowResult] = useState(false)
  const [showSegs, setShowSegs] = useState([false, false, false])

  const [showScenarios, setShowScenarios] = useState([false, false, false])
  const [scenarioBars, setScenarioBars] = useState([0, 0, 0])
  const [showVerdict, setShowVerdict] = useState(false)

  const [showRows, setShowRows] = useState([false, false, false])
  const [stats, setStats] = useState(['—', '—', '—'])
  const [showExport, setShowExport] = useState(false)

  const clrTimers = useCallback(() => {
    animTimers.current.forEach(clearTimeout)
    animTimers.current = []
    rafRefs.current.forEach(cancelAnimationFrame)
    rafRefs.current = []
  }, [])

  const addT = useCallback((fn: () => void, ms: number) => {
    const t = setTimeout(fn, ms)
    animTimers.current.push(t)
    return t
  }, [])

  const resetAll = useCallback(() => {
    setTypedText('')
    setShowBtn(false)
    setShowPages([false, false, false])
    setShowSite(false)
    setSiteCards([false, false, false])
    setGenBarW(0)
    setAgentCount(0)
    setFunnelWidths([0, 0, 0, 0, 0])
    setFunnelNums(['—', '—', '—', '—', '—'])
    setShowResult(false)
    setShowSegs([false, false, false])
    setShowScenarios([false, false, false])
    setScenarioBars([0, 0, 0])
    setShowVerdict(false)
    setShowRows([false, false, false])
    setStats(['—', '—', '—'])
    setShowExport(false)
  }, [])

  const animBuild = useCallback(() => {
    const text =
      'A SaaS platform helping Indian founders validate startup ideas through AI-powered consumer simulation — before they build.'
    let ci = 0

    const type = () => {
      if (ci <= text.length) {
        setTypedText(text.slice(0, ci))
        ci += 1
        addT(type, 18 + Math.random() * 12)
      }
    }

    type()

    ;[0, 1, 2].forEach((n) => {
      addT(() => {
        setShowPages((p) => {
          const next = [...p]
          next[n] = true
          return next
        })
      }, 1300 + n * 420)
    })

    addT(() => setShowBtn(true), 2900)
    addT(() => setGenBarW(100), 1600)
    addT(() => {
      setShowSite(true)
      ;[0, 1, 2].forEach((n) =>
        addT(() => {
          setSiteCards((p) => {
            const next = [...p]
            next[n] = true
            return next
          })
        }, n * 220)
      )
    }, 3900)
  }, [addT])

  const animSimulate = useCallback(() => {
    const vals = [100, 78, 51, 28, 19]
    const ns = ['10,000', '7,800', '5,100', '2,800', '1,930']

    vals.forEach((v, i) => {
      addT(() => {
        setFunnelWidths((p) => {
          const next = [...p]
          next[i] = v
          return next
        })
        addT(() => {
          setFunnelNums((p) => {
            const next = [...p]
            next[i] = ns[i]
            return next
          })
        }, 300)
      }, 450 + i * 420)
    })

    let n = 0
    const cnt = () => {
      n = Math.min(10000, n + 148)
      setAgentCount(n)
      if (n < 10000) {
        addT(cnt, 28)
      }
    }

    addT(cnt, 180)
    addT(() => setShowResult(true), 3000)

    ;[0, 1, 2].forEach((i) => {
      addT(() => {
        setShowSegs((p) => {
          const next = [...p]
          next[i] = true
          return next
        })
      }, 700 + i * 440)
    })
  }, [addT])

  const animDecide = useCallback(() => {
    const sv = [22, 51, 74]
    ;[0, 1, 2].forEach((i) => {
      addT(() => {
        setShowScenarios((p) => {
          const next = [...p]
          next[i] = true
          return next
        })
        addT(() => {
          setScenarioBars((p) => {
            const next = [...p]
            next[i] = sv[i]
            return next
          })
        }, 160)
      }, 450 + i * 500)
    })

    addT(() => setShowVerdict(true), 2400)

    const cv = c2CanvasRef.current
    if (!cv) return

    const wrap = cv.parentElement
    if (!wrap) return

    const cw = wrap.clientWidth
    const ch = wrap.clientHeight - 36
    cv.width = cw
    cv.height = ch

    const ctx = cv.getContext('2d')
    if (!ctx) return

    const gauss = (x: number, mu: number, sd: number) =>
      Math.exp(-0.5 * ((x - mu) / sd) ** 2) / (sd * Math.sqrt(2 * Math.PI))

    const scs = [
      { c: 'rgba(192,57,43,.5)', mu: 0.22, sd: 0.065 },
      { c: 'rgba(186,117,23,.55)', mu: 0.51, sd: 0.09 },
      { c: 'rgba(59,109,17,.55)', mu: 0.74, sd: 0.07 },
    ]

    let p = 0
    const dd = () => {
      ctx.clearRect(0, 0, cw, ch)
      const pad = { l: 10, r: 8, t: 8, b: 24 }
      const fw = cw - pad.l - pad.r
      const fh = ch - pad.t - pad.b

      ctx.fillStyle = 'rgba(26,23,20,.04)'
      ctx.fillRect(pad.l, pad.t, fw, fh)

      scs.forEach((sc, si) => {
        const lp = Math.min(1, Math.max(0, (p - si * 0.28) / 0.55))
        if (lp <= 0) return

        ctx.beginPath()
        for (let xi = 0; xi <= 140; xi += 1) {
          const x = xi / 140
          const gv = gauss(x, sc.mu, sc.sd) * fh * sc.sd * 2.8 * lp
          const px = pad.l + x * fw
          const py = pad.t + fh - gv
          if (xi === 0) {
            ctx.moveTo(px, py)
          } else {
            ctx.lineTo(px, py)
          }
        }

        ctx.strokeStyle = sc.c
        ctx.lineWidth = 1.4
        ctx.stroke()
        ctx.lineTo(pad.l + sc.mu * fw, pad.t + fh)
        ctx.lineTo(pad.l, pad.t + fh)
        ctx.fillStyle = sc.c.replace('.5', '.05').replace('.55', '.05')
        ctx.fill()
      })

      ctx.font = '9px system-ui,sans-serif'
      ctx.fillStyle = 'rgba(26,23,20,.22)'
      ctx.textAlign = 'center'
      ctx.fillText('Fails', pad.l + 6, pad.t + fh + 16)
      ctx.fillText('Survives', pad.l + fw - 6, pad.t + fh + 16)

      if (p < 1) {
        p += 0.013
        const r = requestAnimationFrame(dd)
        rafRefs.current.push(r)
      }
    }

    addT(() => {
      const r = requestAnimationFrame(dd)
      rafRefs.current.push(r)
    }, 280)
  }, [addT])

  const animKnow = useCallback(() => {
    ;[0, 1, 2].forEach((i) => {
      addT(() => {
        setShowRows((p) => {
          const next = [...p]
          next[i] = true
          return next
        })
      }, 450 + i * 700)
    })

    const targets = [
      { v: 14, s: '' },
      { v: 9, s: '%' },
      { v: 10000, s: '' },
    ]

    targets.forEach((target, i) => {
      addT(() => {
        let n = 0
        const c = () => {
          n = Math.min(target.v, n + Math.ceil(target.v / 32))
          setStats((p) => {
            const next = [...p]
            next[i] = `${n.toLocaleString()}${target.s}`
            return next
          })
          if (n < target.v) {
            addT(c, 44)
          }
        }
        c()
      }, 1900 + i * 180)
    })

    addT(() => setShowExport(true), 3300)
  }, [addT])

  const go = useCallback(
    (i: number) => {
      clrTimers()
      if (timerRef.current) clearTimeout(timerRef.current)
      resetAll()
      setActive(i)

      if (progressRef.current) {
        progressRef.current.style.transition = 'none'
        progressRef.current.style.width = '0%'
        requestAnimationFrame(() =>
          requestAnimationFrame(() => {
            if (progressRef.current) {
              progressRef.current.style.transition = `width ${DUR}ms linear`
              progressRef.current.style.width = '100%'
            }
          })
        )
      }

      timerRef.current = setTimeout(() => go((i + 1) % 4), DUR)
      ;[animBuild, animSimulate, animDecide, animKnow][i]()
    },
    [animBuild, animDecide, animKnow, animSimulate, clrTimers, resetAll]
  )

  useEffect(() => {
    go(0)
    return () => {
      clrTimers()
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [clrTimers, go])

  const ink = (op: number) => `rgba(26,23,20,${op})`
  const red = '#c0392b'

  const SideIcons = () => (
    <div
      style={{
        width: 46,
        background: '#1a1714',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        padding: '10px 0',
        gap: 2,
        flexShrink: 0,
        borderRight: '0.5px solid rgba(255,255,255,.04)',
      }}
    >
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          style={{
            width: 34,
            height: 34,
            borderRadius: 6,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            opacity: i === 0 ? 1 : 0.22,
            background: i === 0 ? 'rgba(255,255,255,.07)' : 'transparent',
          }}
        >
          {i === 0 && (
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <rect x="1.5" y="1.5" width="4" height="4" rx="1" stroke="rgba(255,255,255,.7)" strokeWidth=".9" />
              <rect x="8.5" y="1.5" width="4" height="4" rx="1" stroke="rgba(255,255,255,.7)" strokeWidth=".9" />
              <rect x="1.5" y="8.5" width="4" height="4" rx="1" stroke="rgba(255,255,255,.7)" strokeWidth=".9" />
              <rect x="8.5" y="8.5" width="4" height="4" rx="1" stroke="rgba(255,255,255,.7)" strokeWidth=".9" />
            </svg>
          )}
          {i === 1 && (
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <rect x="1.5" y="1.5" width="11" height="8" rx="1.5" stroke="rgba(255,255,255,.55)" strokeWidth=".9" />
              <path d="M4 12.5h6M7 9.5v3" stroke="rgba(255,255,255,.55)" strokeWidth=".9" strokeLinecap="round" />
            </svg>
          )}
          {i === 2 && (
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <circle cx="7" cy="7" r="4.5" stroke="rgba(255,255,255,.55)" strokeWidth=".9" />
              <path d="M7 4v4l2.5 1.5" stroke="rgba(255,255,255,.55)" strokeWidth=".9" strokeLinecap="round" />
            </svg>
          )}
        </div>
      ))}
    </div>
  )

  return (
    <section
      style={{
        background: '#f2ece0',
        borderTop: '0.5px solid rgba(26,23,20,.08)',
        borderBottom: '0.5px solid rgba(26,23,20,.08)',
      }}
    >
      <div
        style={{
          maxWidth: 1280,
          margin: '0 auto',
          display: 'grid',
          gridTemplateColumns: '260px 1fr',
          minHeight: 580,
        }}
      >
        <div
          style={{
            padding: '56px 0 40px 52px',
            display: 'flex',
            flexDirection: 'column',
            position: 'relative',
            borderRight: '0.5px solid rgba(26,23,20,.08)',
          }}
        >
          <div
            style={{
              fontSize: 8,
              letterSpacing: '.28em',
              textTransform: 'uppercase',
              color: ink(0.25),
              fontFamily: 'system-ui,sans-serif',
              marginBottom: 44,
            }}
          >
            What TheCee does
          </div>
          {FEATURES.map((f, i) => (
            <div
              key={f.word}
              onClick={() => go(i)}
              style={{
                padding: '20px 0 20px 14px',
                borderBottom: '0.5px solid rgba(26,23,20,.06)',
                cursor: 'pointer',
                position: 'relative',
                borderTop: i === 0 ? '0.5px solid rgba(26,23,20,.06)' : undefined,
              }}
            >
              <div
                style={{
                  position: 'absolute',
                  left: 0,
                  top: 0,
                  bottom: 0,
                  width: 1.5,
                  background: active === i ? red : 'transparent',
                  transition: 'background .3s',
                }}
              />
              <div
                style={{
                  fontSize: active === i ? 44 : 36,
                  fontWeight: 400,
                  color: active === i ? '#1a1714' : ink(0.11),
                  fontFamily: 'Georgia,serif',
                  lineHeight: 1,
                  transition: 'all .35s cubic-bezier(.4,0,.2,1)',
                }}
              >
                {f.word}
              </div>
              <div
                style={{
                  fontSize: 10,
                  fontFamily: 'system-ui,sans-serif',
                  color: active === i ? ink(0.38) : 'transparent',
                  lineHeight: 1.6,
                  maxHeight: active === i ? 48 : 0,
                  overflow: 'hidden',
                  transition: 'all .38s ease',
                  marginTop: active === i ? 7 : 0,
                }}
              >
                {f.desc}
              </div>
              <div
                style={{
                  fontSize: 9,
                  fontFamily: 'system-ui,sans-serif',
                  color: active === i ? red : 'transparent',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 4,
                  maxHeight: active === i ? 18 : 0,
                  overflow: 'hidden',
                  transition: 'all .3s ease',
                  marginTop: active === i ? 5 : 0,
                }}
              >
                <span style={{ width: 10, height: 0.5, background: red, display: 'inline-block' }} />
                {f.cue}
              </div>
            </div>
          ))}
          <div style={{ position: 'absolute', bottom: 0, left: 52, right: 0, height: 1, background: ink(0.05) }}>
            <div ref={progressRef} style={{ height: '100%', background: red, width: '0%' }} />
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', background: '#EDE8DF' }}>
          <div
            style={{
              height: 38,
              background: '#1a1714',
              display: 'flex',
              alignItems: 'center',
              padding: '0 14px',
              flexShrink: 0,
              borderBottom: '0.5px solid rgba(255,255,255,.05)',
            }}
          >
            <div
              style={{
                width: 26,
                height: 26,
                borderRadius: 5,
                background: red,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                marginRight: 14,
                flexShrink: 0,
              }}
            >
              <span style={{ fontSize: 11, color: '#f2ece0', fontFamily: 'Georgia,serif', fontStyle: 'italic' }}>T</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 5, flex: 1 }}>
              <span style={{ fontSize: 9, fontFamily: 'system-ui,sans-serif', color: 'rgba(255,255,255,.25)' }}>Projects</span>
              <span style={{ fontSize: 9, color: 'rgba(255,255,255,.12)', fontFamily: 'system-ui,sans-serif' }}>/</span>
              <span style={{ fontSize: 9, fontFamily: 'system-ui,sans-serif', color: 'rgba(255,255,255,.25)' }}>Foundr</span>
              <span style={{ fontSize: 9, color: 'rgba(255,255,255,.12)', fontFamily: 'system-ui,sans-serif' }}>/</span>
              <span style={{ fontSize: 9, fontFamily: 'system-ui,sans-serif', color: 'rgba(255,255,255,.6)' }}>{CRUMBS[active]}</span>
            </div>
          </div>

          <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
            <SideIcons />
            <div style={{ flex: 1, position: 'relative', overflow: 'hidden' }}>
              <div
                style={{
                  position: 'absolute',
                  inset: 0,
                  opacity: active === 0 ? 1 : 0,
                  pointerEvents: active === 0 ? 'all' : 'none',
                  transition: 'opacity .55s ease',
                  display: 'flex',
                  flexDirection: 'column',
                  background: '#F4F0E8',
                }}
              >
                <div
                  style={{
                    padding: '22px 28px 18px',
                    display: 'grid',
                    gridTemplateColumns: '220px 1fr',
                    gap: 20,
                    borderBottom: '0.5px solid rgba(26,23,20,.08)',
                    flexShrink: 0,
                  }}
                >
                  <div>
                    <div style={{ fontSize: 8, letterSpacing: '.2em', textTransform: 'uppercase', color: ink(0.3), fontFamily: 'system-ui,sans-serif', marginBottom: 8 }}>
                      Your product prompt
                    </div>
                    <div
                      style={{
                        background: '#fff',
                        border: '0.5px solid rgba(26,23,20,.12)',
                        borderRadius: 4,
                        padding: '11px 13px',
                        fontSize: 10,
                        fontFamily: 'system-ui,sans-serif',
                        color: ink(0.55),
                        lineHeight: 1.6,
                        minHeight: 68,
                      }}
                    >
                      {typedText}
                      <span
                        style={{
                          display: 'inline-block',
                          width: 1.5,
                          height: 10,
                          background: red,
                          marginLeft: 1,
                          animation: 'tcBlink .65s step-end infinite',
                          verticalAlign: 'middle',
                        }}
                      />
                    </div>
                    <button
                      style={{
                        marginTop: 10,
                        background: '#1a1714',
                        border: 'none',
                        borderRadius: 3,
                        padding: '8px 14px',
                        fontSize: 8,
                        fontFamily: 'system-ui,sans-serif',
                        letterSpacing: '.16em',
                        textTransform: 'uppercase',
                        color: '#f2ece0',
                        cursor: 'pointer',
                        opacity: showBtn ? 1 : 0,
                        transition: 'opacity .5s',
                      }}
                    >
                      Generate UI →
                    </button>
                  </div>
                  <div>
                    <div style={{ fontSize: 8, letterSpacing: '.2em', textTransform: 'uppercase', color: ink(0.3), fontFamily: 'system-ui,sans-serif', marginBottom: 8 }}>
                      Pages generating
                    </div>
                    {['Landing page', 'Pricing page', 'Checkout flow'].map((pg, i) => (
                      <div
                        key={pg}
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: 9,
                          padding: '8px 11px',
                          borderRadius: 4,
                          background: '#fff',
                          border: '0.5px solid rgba(26,23,20,.08)',
                          marginBottom: 7,
                          opacity: showPages[i] ? 1 : 0,
                          transform: showPages[i] ? 'none' : 'translateX(-5px)',
                          transition: 'all .38s ease',
                        }}
                      >
                        <div style={{ fontSize: 10, fontFamily: 'system-ui,sans-serif', color: ink(0.6), flex: 1 }}>{pg}</div>
                        <div
                          style={{
                            fontSize: 8,
                            letterSpacing: '.1em',
                            textTransform: 'uppercase',
                            fontFamily: 'system-ui,sans-serif',
                            color: i < 2 ? 'rgba(59,109,17,.7)' : 'rgba(186,117,23,.7)',
                          }}
                        >
                          {i < 2 ? 'Ready' : 'Building...'}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
                <div style={{ flex: 1, position: 'relative', overflow: 'hidden', background: '#F4F0E8' }}>
                  {!showSite && (
                    <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 10 }}>
                      <div style={{ fontSize: 10, fontFamily: 'system-ui,sans-serif', color: ink(0.32), letterSpacing: '.06em' }}>
                        Generating your product UI
                      </div>
                      <div style={{ width: 180, height: 2, background: 'rgba(26,23,20,.08)', borderRadius: 1, overflow: 'hidden' }}>
                        <div style={{ height: '100%', background: red, width: `${genBarW}%`, transition: 'width 2.2s ease' }} />
                      </div>
                    </div>
                  )}
                  <div
                    style={{
                      position: 'absolute',
                      inset: 0,
                      opacity: showSite ? 1 : 0,
                      transition: 'opacity .8s ease',
                      display: 'flex',
                      flexDirection: 'column',
                      background: '#0F0D0B',
                    }}
                  >
                    <div
                      style={{
                        height: 38,
                        background: '#161210',
                        borderBottom: '0.5px solid rgba(255,255,255,.06)',
                        display: 'flex',
                        alignItems: 'center',
                        padding: '0 18px',
                        justifyContent: 'space-between',
                        flexShrink: 0,
                      }}
                    >
                      <div style={{ fontSize: 13, color: '#f2ece0', fontFamily: 'Georgia,serif', fontStyle: 'italic', display: 'flex', alignItems: 'center', gap: 6 }}>
                        <div style={{ width: 8, height: 8, borderRadius: '50%', background: red }} />
                        Foundr
                      </div>
                      <div style={{ display: 'flex', gap: 16 }}>
                        {['Features', 'Pricing', 'Docs'].map((l) => (
                          <span key={l} style={{ fontSize: 9, color: 'rgba(255,255,255,.3)', fontFamily: 'system-ui,sans-serif' }}>
                            {l}
                          </span>
                        ))}
                      </div>
                      <div style={{ background: red, color: '#f2ece0', fontSize: 8, letterSpacing: '.12em', textTransform: 'uppercase', padding: '5px 12px', fontFamily: 'system-ui,sans-serif', borderRadius: 2 }}>
                        Try free →
                      </div>
                    </div>
                    <div style={{ padding: '28px 22px 16px', flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
                      <div>
                        <div style={{ fontSize: 8, letterSpacing: '.22em', textTransform: 'uppercase', color: 'rgba(192,57,43,.7)', fontFamily: 'system-ui,sans-serif', marginBottom: 10 }}>
                          AI-powered · Early access
                        </div>
                        <div style={{ fontSize: 26, color: '#f2ece0', fontFamily: 'Georgia,serif', lineHeight: 1.1, marginBottom: 10 }}>
                          Know if your idea works
                          <br />
                          <em style={{ color: 'rgba(242,236,224,.35)' }}>before you build anything.</em>
                        </div>
                        <div style={{ fontSize: 10, fontFamily: 'system-ui,sans-serif', color: 'rgba(255,255,255,.35)', lineHeight: 1.55, marginBottom: 16, maxWidth: 280 }}>
                          Simulate 10,000 customers interacting with your product before spending a rupee on development.
                        </div>
                        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                          <div style={{ background: red, color: '#f2ece0', fontSize: 8, letterSpacing: '.12em', textTransform: 'uppercase', padding: '8px 16px', fontFamily: 'system-ui,sans-serif', borderRadius: 2 }}>
                            Start free →
                          </div>
                          <div style={{ fontSize: 9, color: 'rgba(255,255,255,.28)', fontFamily: 'system-ui,sans-serif' }}>Watch demo →</div>
                        </div>
                      </div>
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 8, marginTop: 16 }}>
                        {[
                          ['Simulate', '10,000 agents', 'Real click data'],
                          ['Analyse', 'Full funnel', 'Drop-off insights'],
                          ['Export', 'PDF report', 'Investor-ready'],
                        ].map(([l, n, s], i) => (
                          <div
                            key={l}
                            style={{
                              background: 'rgba(255,255,255,.04)',
                              border: '0.5px solid rgba(255,255,255,.07)',
                              borderRadius: 4,
                              padding: '10px 12px',
                              opacity: siteCards[i] ? 1 : 0,
                              transition: 'opacity .4s ease',
                            }}
                          >
                            <div style={{ fontSize: 7, letterSpacing: '.16em', textTransform: 'uppercase', color: 'rgba(192,57,43,.6)', fontFamily: 'system-ui,sans-serif', marginBottom: 3 }}>{l}</div>
                            <div style={{ fontSize: 11, fontFamily: 'Georgia,serif', color: 'rgba(255,255,255,.5)' }}>{n}</div>
                            <div style={{ fontSize: 9, fontFamily: 'system-ui,sans-serif', color: 'rgba(255,255,255,.2)', marginTop: 2 }}>{s}</div>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <div
                style={{
                  position: 'absolute',
                  inset: 0,
                  opacity: active === 1 ? 1 : 0,
                  pointerEvents: active === 1 ? 'all' : 'none',
                  transition: 'opacity .55s ease',
                  display: 'flex',
                  flexDirection: 'column',
                  background: '#F4F0E8',
                }}
              >
                <div
                  style={{
                    padding: '22px 28px 18px',
                    display: 'flex',
                    alignItems: 'flex-end',
                    justifyContent: 'space-between',
                    borderBottom: '0.5px solid rgba(26,23,20,.08)',
                    flexShrink: 0,
                  }}
                >
                  <div>
                    <div style={{ fontSize: 9, fontFamily: 'system-ui,sans-serif', color: ink(0.3), letterSpacing: '.14em', textTransform: 'uppercase', marginBottom: 3 }}>
                      Agents processed
                    </div>
                    <div style={{ fontSize: 48, fontFamily: 'Georgia,serif', color: '#1a1714', lineHeight: 1 }}>{agentCount.toLocaleString()}</div>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 8, fontFamily: 'system-ui,sans-serif', color: 'rgba(192,57,43,.65)', letterSpacing: '.18em', textTransform: 'uppercase' }}>
                    <div style={{ width: 5, height: 5, borderRadius: '50%', background: red, animation: 'tcPulse 1.2s ease-in-out infinite' }} />
                    Live simulation
                  </div>
                </div>
                <div style={{ flex: 1, display: 'grid', gridTemplateColumns: '1fr 196px', overflow: 'hidden' }}>
                  <div style={{ padding: '20px 28px', display: 'flex', flexDirection: 'column', gap: 8, justifyContent: 'center' }}>
                    {['Arrive', 'Browse', 'Consider', 'Decide', 'Convert'].map((stage, i) => (
                      <div key={stage} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                        <div style={{ fontSize: 10, fontFamily: 'system-ui,sans-serif', color: ink(0.35), width: 66, textAlign: 'right', flexShrink: 0 }}>{stage}</div>
                        <div style={{ flex: 1, height: 22, background: 'rgba(26,23,20,.07)', borderRadius: 2, overflow: 'hidden' }}>
                          <div
                            style={{
                              height: '100%',
                              borderRadius: 2,
                              transition: 'width 1.1s cubic-bezier(.4,0,.2,1)',
                              width: `${funnelWidths[i]}%`,
                              background: i >= 3 ? `rgba(192,57,43,${i === 4 ? 1 : 0.45})` : `rgba(26,23,20,${0.22 - i * 0.02})`,
                            }}
                          />
                        </div>
                        <div style={{ fontSize: 9, fontFamily: 'system-ui,sans-serif', color: ink(0.3), width: 42, flexShrink: 0 }}>{funnelNums[i]}</div>
                      </div>
                    ))}
                    <div style={{ marginTop: 10, padding: '11px 14px', background: '#fff', border: '0.5px solid rgba(26,23,20,.08)', borderRadius: 4, display: 'flex', alignItems: 'center', justifyContent: 'space-between', opacity: showResult ? 1 : 0, transition: 'opacity .5s' }}>
                      <div>
                        <div style={{ fontSize: 28, fontFamily: 'Georgia,serif', color: red }}>19.3%</div>
                        <div style={{ fontSize: 8, fontFamily: 'system-ui,sans-serif', color: ink(0.3), letterSpacing: '.12em', textTransform: 'uppercase', marginTop: 2 }}>
                          Conversion rate
                        </div>
                      </div>
                      <div style={{ fontSize: 9, fontFamily: 'system-ui,sans-serif', color: ink(0.3), textAlign: 'right', lineHeight: 1.6 }}>
                        ₹999 threshold fails
                        <br />
                        68% abandon checkout
                      </div>
                    </div>
                  </div>
                  <div style={{ borderLeft: '0.5px solid rgba(26,23,20,.08)', padding: '20px 16px', display: 'flex', flexDirection: 'column', gap: 8 }}>
                    <div style={{ fontSize: 8, letterSpacing: '.18em', textTransform: 'uppercase', color: ink(0.25), fontFamily: 'system-ui,sans-serif', marginBottom: 2 }}>
                      Demographic breakdown
                    </div>
                    {[
                      ['Metro professional', '₹80k–1.2L/mo · 26–34', 'Converts · 61%', 'rgba(59,109,17,.1)', '#3b6d11'],
                      ['Tier-2 founder', '₹30k–60k/mo · 22–30', 'Abandons · 79%', 'rgba(192,57,43,.08)', '#a32d2d'],
                      ['Student builder', '₹0–20k/mo · 18–24', 'Abandons · 91%', 'rgba(192,57,43,.08)', '#a32d2d'],
                    ].map(([n, d, o, bg, col], i) => (
                      <div
                        key={n}
                        style={{
                          background: '#fff',
                          border: '0.5px solid rgba(26,23,20,.07)',
                          borderRadius: 4,
                          padding: '9px 11px',
                          opacity: showSegs[i] ? 1 : 0,
                          transform: showSegs[i] ? 'none' : 'translateX(5px)',
                          transition: 'all .4s',
                        }}
                      >
                        <div style={{ fontSize: 10, fontFamily: 'system-ui,sans-serif', color: ink(0.62) }}>{n}</div>
                        <div style={{ fontSize: 9, fontFamily: 'system-ui,sans-serif', color: ink(0.28), marginTop: 2 }}>{d}</div>
                        <div style={{ display: 'inline-block', marginTop: 5, fontSize: 8, letterSpacing: '.1em', textTransform: 'uppercase', padding: '2px 7px', borderRadius: 2, fontFamily: 'system-ui,sans-serif', background: bg, color: col }}>
                          {o}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              <div
                style={{
                  position: 'absolute',
                  inset: 0,
                  opacity: active === 2 ? 1 : 0,
                  pointerEvents: active === 2 ? 'all' : 'none',
                  transition: 'opacity .55s ease',
                  display: 'flex',
                  flexDirection: 'column',
                  background: '#F4F0E8',
                }}
              >
                <div style={{ padding: '22px 28px 18px', borderBottom: '0.5px solid rgba(26,23,20,.08)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexShrink: 0 }}>
                  <div>
                    <div style={{ fontSize: 8, letterSpacing: '.2em', textTransform: 'uppercase', color: ink(0.28), fontFamily: 'system-ui,sans-serif', marginBottom: 6 }}>
                      Decision studio
                    </div>
                    <div style={{ fontSize: 13, fontFamily: 'Georgia,serif', color: ink(0.6), fontStyle: 'italic' }}>3 scenarios · 10,000 runs each</div>
                  </div>
                  <div style={{ background: '#fff', border: '0.5px solid rgba(26,23,20,.12)', borderRadius: 3, padding: '5px 10px', fontSize: 8, fontFamily: 'system-ui,sans-serif', color: ink(0.38), letterSpacing: '.1em', textTransform: 'uppercase' }}>
                    TheCee has a recommendation
                  </div>
                </div>
                <div style={{ flex: 1, display: 'grid', gridTemplateColumns: '1fr 1fr', overflow: 'hidden' }}>
                  <div style={{ padding: '20px 24px', display: 'flex', flexDirection: 'column', gap: 9, overflow: 'hidden' }}>
                    {[
                      { tag: 'Scenario A — Current pricing', col: 'rgba(192,57,43,.65)', desc: '₹999/month · No free trial · Direct outreach', barCol: 'rgba(192,57,43,.55)', pct: '22% survival rate' },
                      { tag: 'Scenario B — Freemium', col: 'rgba(186,117,23,.75)', desc: 'Free tier + ₹599 pro · Referral programme', barCol: 'rgba(186,117,23,.6)', pct: '51% survival rate' },
                      { tag: 'Scenario C — Community-led ✓', col: 'rgba(59,109,17,.8)', desc: '₹299 founding price · Cohort model · Waitlist', barCol: 'rgba(59,109,17,.65)', pct: '74% survival rate' },
                    ].map((sc, i) => (
                      <div
                        key={sc.tag}
                        style={{
                          background: '#fff',
                          border: `0.5px solid rgba(26,23,20,${i === 2 ? 0.18 : 0.08})`,
                          borderRadius: 4,
                          padding: '12px 14px',
                          opacity: showScenarios[i] ? 1 : 0,
                          transform: showScenarios[i] ? 'none' : 'translateY(7px)',
                          transition: 'all .4s',
                        }}
                      >
                        <div style={{ fontSize: 8, letterSpacing: '.12em', textTransform: 'uppercase', fontFamily: 'system-ui,sans-serif', marginBottom: 4, color: sc.col }}>{sc.tag}</div>
                        <div style={{ fontSize: 10, fontFamily: 'system-ui,sans-serif', color: ink(0.42), marginBottom: 8, lineHeight: 1.4 }}>{sc.desc}</div>
                        <div style={{ height: 2.5, background: 'rgba(26,23,20,.07)', borderRadius: 2, overflow: 'hidden', marginBottom: 4 }}>
                          <div style={{ height: '100%', borderRadius: 2, transition: 'width 1.1s ease', width: `${scenarioBars[i]}%`, background: sc.barCol }} />
                        </div>
                        <div style={{ fontSize: 9, fontFamily: 'system-ui,sans-serif', color: ink(0.28) }}>{sc.pct}</div>
                      </div>
                    ))}
                    <div style={{ background: 'rgba(26,23,20,.04)', border: '0.5px solid rgba(26,23,20,.1)', borderRadius: 4, padding: '12px 14px', opacity: showVerdict ? 1 : 0, transition: 'opacity .5s' }}>
                      <div style={{ fontSize: 8, letterSpacing: '.18em', textTransform: 'uppercase', color: ink(0.28), fontFamily: 'system-ui,sans-serif', marginBottom: 4 }}>
                        TheCee recommends
                      </div>
                      <div style={{ fontSize: 12, fontFamily: 'Georgia,serif', color: '#1a1714', fontStyle: 'italic', lineHeight: 1.4 }}>
                        "Scenario C survives 74% of all runs across every demographic tested."
                      </div>
                    </div>
                  </div>
                  <div style={{ borderLeft: '0.5px solid rgba(26,23,20,.08)', padding: '20px 20px', display: 'flex', flexDirection: 'column' }}>
                    <div style={{ fontSize: 8, letterSpacing: '.18em', textTransform: 'uppercase', color: ink(0.25), fontFamily: 'system-ui,sans-serif', marginBottom: 10 }}>
                      Outcome probability distributions
                    </div>
                    <canvas ref={c2CanvasRef} style={{ flex: 1, width: '100%' }} />
                  </div>
                </div>
              </div>

              <div
                style={{
                  position: 'absolute',
                  inset: 0,
                  opacity: active === 3 ? 1 : 0,
                  pointerEvents: active === 3 ? 'all' : 'none',
                  transition: 'opacity .55s ease',
                  display: 'flex',
                  flexDirection: 'column',
                  background: '#F4F0E8',
                }}
              >
                <div style={{ padding: '22px 28px 18px', borderBottom: '0.5px solid rgba(26,23,20,.08)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexShrink: 0 }}>
                  <div>
                    <div style={{ fontSize: 8, letterSpacing: '.2em', textTransform: 'uppercase', color: ink(0.28), fontFamily: 'system-ui,sans-serif', marginBottom: 6 }}>
                      Pre-mortem report
                    </div>
                    <div style={{ fontSize: 16, fontFamily: 'Georgia,serif', color: '#1a1714', fontStyle: 'italic' }}>Why this idea fails — before you build it</div>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '7px 14px', border: '0.5px solid rgba(26,23,20,.14)', borderRadius: 3, fontSize: 8, fontFamily: 'system-ui,sans-serif', letterSpacing: '.14em', textTransform: 'uppercase', color: ink(0.42), cursor: 'pointer', background: '#fff', opacity: showExport ? 1 : 0, transition: 'opacity .5s' }}>
                    <svg width="11" height="11" viewBox="0 0 11 11" fill="none">
                      <path d="M5.5 1v6M3 5l2.5 2.5L8 5M1 9.5h9" stroke="rgba(26,23,20,.4)" strokeWidth=".9" strokeLinecap="round" />
                    </svg>
                    Export PDF report
                  </div>
                </div>
                <div style={{ flex: 1, padding: '18px 28px', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
                  {[
                    { title: 'Pricing assumption collapses at ₹799+', desc: '68% of agents abandon at checkout. Perceived value does not justify cost without social proof or a free trial entry point.', chip: 'Critical · Impact 9.1 / 10', chipBg: 'rgba(192,57,43,.07)', chipCol: '#a32d2d' },
                    { title: 'Retention breaks without a weekly engagement hook', desc: 'Day-30 churn reaches 74% across all scenarios. No habit-forming loop exists in the current product structure — users do not return.', chip: 'Critical · Impact 8.7 / 10', chipBg: 'rgba(192,57,43,.07)', chipCol: '#a32d2d' },
                    { title: 'CAC is 3× the assumption — word-of-mouth never triggers', desc: 'Organic referral loop fails in 91% of runs. Paid CAC exceeds lifetime value by month 4 in the base-case scenario, making growth unsustainable.', chip: 'High · Impact 7.4 / 10', chipBg: 'rgba(186,117,23,.07)', chipCol: '#633806' },
                  ].map((row, i) => (
                    <div key={row.title} style={{ display: 'flex', gap: 14, padding: '13px 0', borderBottom: '0.5px solid rgba(26,23,20,.05)', opacity: showRows[i] ? 1 : 0, transform: showRows[i] ? 'none' : 'translateY(5px)', transition: 'all .45s' }}>
                      <div style={{ fontSize: 13, color: 'rgba(192,57,43,.35)', fontFamily: 'Georgia,serif', flexShrink: 0, width: 22, paddingTop: 2 }}>{`0${i + 1}`}</div>
                      <div>
                        <div style={{ fontSize: 12, fontFamily: 'system-ui,sans-serif', color: ink(0.7), marginBottom: 4 }}>{row.title}</div>
                        <div style={{ fontSize: 10, fontFamily: 'system-ui,sans-serif', color: ink(0.36), lineHeight: 1.55 }}>{row.desc}</div>
                        <div style={{ marginTop: 6, display: 'inline-block', fontSize: 8, letterSpacing: '.12em', textTransform: 'uppercase', padding: '2px 8px', borderRadius: 2, fontFamily: 'system-ui,sans-serif', background: row.chipBg, color: row.chipCol }}>
                          {row.chip}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
                <div style={{ padding: '14px 28px', borderTop: '0.5px solid rgba(26,23,20,.08)', display: 'flex', gap: 0, flexShrink: 0 }}>
                  {[
                    ['Failure modes', stats[0]],
                    ['Survival rate', stats[1]],
                    ['Scenarios run', stats[2]],
                  ].map(([lbl, val], i) => (
                    <div key={lbl} style={{ flex: 1, borderRight: i < 2 ? '0.5px solid rgba(26,23,20,.07)' : 'none', padding: i === 0 ? '0 20px 0 0' : '0 20px' }}>
                      <div style={{ fontSize: 26, fontFamily: 'Georgia,serif', color: ink(0.6) }}>{val}</div>
                      <div style={{ fontSize: 8, fontFamily: 'system-ui,sans-serif', color: ink(0.25), letterSpacing: '.14em', textTransform: 'uppercase', marginTop: 3 }}>{lbl}</div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
      <style>{`@keyframes tcBlink{0%,100%{opacity:1}50%{opacity:0}}@keyframes tcPulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.15;transform:scale(.6)}}`}</style>
    </section>
  )
}
