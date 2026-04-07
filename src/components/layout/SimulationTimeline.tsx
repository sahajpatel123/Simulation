'use client'

import { useEffect, useRef, useState } from 'react'

export default function SimulationTimeline() {
  const wrapRef = useRef<HTMLDivElement>(null)
  const cvRef   = useRef<HTMLCanvasElement>(null)
  const [stats, setStats] = useState({ scenarios: 0, conv: 0, risk: 0, conf: 0 })

  useEffect(() => {
    const wrap = wrapRef.current
    const cv   = cvRef.current
    if (!wrap || !cv) return

    const DPR = Math.min(window.devicePixelRatio || 1, 2)
    const W   = wrap.offsetWidth
    const H   = wrap.offsetHeight
    cv.width  = W * DPR
    cv.height = H * DPR
    cv.style.width  = W + 'px'
    cv.style.height = H + 'px'
    const ctx = cv.getContext('2d')!
    ctx.scale(DPR, DPR)

    const TY = 24, BY = 28
    const FY = TY
    const FH = H - TY - BY
    const CY = FY + FH / 2
    const PAD = 52

    const LABELS = ['Idea','Assume','Market','Pricing','Build','Launch','Retain','Scale']
    const N  = LABELS.length
    const NX = LABELS.map((_, i) => PAD + (i / (N - 1)) * (W - PAD * 2))

    /* THE KEY FIX:
       Every segment ends EXACTLY at the node dot (NX[seg+1], CY).
       Randomness only lives in the bezier control point.
       This guarantees every line touches every dot it reaches. */

    type Pt = { x: number; y: number }

    class Particle {
      x: number; y: number; vx: number; vy: number
      op = 0.9; r: number; col: string; dead = false
      constructor(x: number, y: number, col: string) {
        this.x = x; this.y = y; this.col = col
        const a = Math.random() * Math.PI * 2
        const s = 0.8 + Math.random() * 2.4
        this.vx = Math.cos(a) * s
        this.vy = Math.sin(a) * s - 1.2
        this.r  = 0.7 + Math.random() * 1.1
      }
      step() { this.x += this.vx; this.vy += 0.065; this.y += this.vy; this.op *= 0.92; if (this.op < 0.02) this.dead = true }
      draw() { ctx.beginPath(); ctx.arc(this.x, this.y, this.r, 0, Math.PI * 2); ctx.fillStyle = `rgba(${this.col},${this.op})`; ctx.fill() }
    }
    const particles: Particle[] = []
    const ghosts: { pts: Pt[]; op: number; col: string }[] = []

    class Line {
      col:  string
      lw:   number
      op:   number
      gold: boolean
      allPts: Pt[] = []
      seg   = 0
      t     = 0
      spd:  number
      diePr: number
      paused    = false
      pauseAge  = 0
      pauseLen: number
      dead     = false
      finished = false
      /* bezier: b0=start, b1=control, b2=end(always CY) */
      b0: Pt; b1: Pt; b2: Pt

      constructor() {
        this.gold = Math.random() < 0.18
        /* solid visible colors — dark cream to warm gold */
        const brightness = 170 + Math.floor(Math.random() * 55)
        this.col  = this.gold
          ? '218,175,72'
          : `${brightness},${brightness - 15},${brightness - 35}`
        this.lw   = this.gold ? 1.4 : 0.9 + Math.random() * 0.5
        this.op   = this.gold ? 0.85 : 0.65 + Math.random() * 0.25
        this.spd  = 0.018 + Math.random() * 0.012
        this.diePr    = 0.10 + Math.random() * 0.28
        this.pauseLen = 24 + Math.floor(Math.random() * 22)
        /* all lines start at (NX[0], CY) — the first dot */
        this.b0 = { x: NX[0], y: CY }
        this.b1 = { x: 0, y: 0 }
        this.b2 = { x: NX[1], y: CY }
        this.allPts = [{ x: NX[0], y: CY }]
        this.buildSeg()
      }

      buildSeg() {
        /* start = current position (always a dot = CY) */
        const fromX = NX[this.seg]
        const fromY = CY
        const toX   = NX[this.seg + 1]
        /* end ALWAYS at (toX, CY) — exact dot position */
        const endX  = toX
        const endY  = CY
        /* control point: dramatic Y swing anywhere in field */
        const ctrlX = fromX + (toX - fromX) * (0.3 + Math.random() * 0.4)
        const swing = (Math.random() > 0.5 ? 1 : -1) * (FH * 0.15 + Math.random() * FH * 0.38)
        const ctrlY = CY + swing
        this.b0 = { x: fromX, y: fromY }
        this.b1 = { x: ctrlX, y: Math.max(FY + 5, Math.min(FY + FH - 5, ctrlY)) }
        this.b2 = { x: endX,  y: endY }
      }

      bez(t: number): Pt {
        const mt = 1 - t
        return {
          x: mt * mt * this.b0.x + 2 * mt * t * this.b1.x + t * t * this.b2.x,
          y: mt * mt * this.b0.y + 2 * mt * t * this.b1.y + t * t * this.b2.y,
        }
      }

      step() {
        if (this.dead || this.finished) return

        if (this.paused) {
          this.pauseAge++
          if (this.pauseAge >= this.pauseLen) {
            this.paused   = false
            this.pauseAge = 0
            if (Math.random() < this.diePr) {
              this.dead = true
              const cx = NX[this.seg + 1]
              const pc = this.gold ? this.col : '192,57,43'
              for (let i = 0; i < 10; i++) particles.push(new Particle(cx, CY, pc))
              return
            }
            this.seg++
            if (this.seg >= N - 1) { this.finished = true; return }
            this.t = 0
            this.buildSeg()
          }
          return
        }

        this.t = Math.min(1, this.t + this.spd)
        const pos = this.bez(this.t)
        this.allPts.push(pos)

        if (this.t >= 1) {
          /* HARD SNAP to exact dot position */
          this.allPts[this.allPts.length - 1] = { x: NX[this.seg + 1], y: CY }
          this.paused   = true
          this.pauseAge = 0
        }
      }

      draw(time: number) {
        if (this.allPts.length < 2) return

        /* full path from origin — never trimmed */
        ctx.beginPath()
        ctx.moveTo(this.allPts[0].x, this.allPts[0].y)
        for (let i = 1; i < this.allPts.length; i++) ctx.lineTo(this.allPts[i].x, this.allPts[i].y)
        const fade  = this.dead ? 0.2 : 1
        const pulse = this.gold ? 0.75 + Math.sin(time * 3) * 0.25 : 1
        ctx.strokeStyle = `rgba(${this.col},${this.op * fade * pulse})`
        ctx.lineWidth   = this.lw
        ctx.stroke()

        if (this.dead || this.finished) return

        const tail = this.allPts[this.allPts.length - 1]

        if (this.paused) {
          const nodeX = NX[this.seg + 1]
          const pr    = this.pauseAge / this.pauseLen

          /* outer expanding ring */
          ctx.beginPath()
          ctx.arc(nodeX, CY, 6 + pr * 20, 0, Math.PI * 2)
          ctx.strokeStyle = `rgba(${this.col},${(1 - pr) * this.op * 0.65})`
          ctx.lineWidth   = 0.7; ctx.stroke()

          /* inner ring */
          ctx.beginPath()
          ctx.arc(nodeX, CY, 3 + pr * 10, 0, Math.PI * 2)
          ctx.strokeStyle = `rgba(${this.col},${(1 - pr) * this.op * 0.35})`
          ctx.lineWidth   = 0.5; ctx.stroke()

          /* bright node dot */
          ctx.beginPath(); ctx.arc(nodeX, CY, 3.5, 0, Math.PI * 2)
          ctx.fillStyle = `rgba(${this.col},${this.op * (0.6 + Math.sin(time * 9) * 0.4)})`
          ctx.fill()

        } else {
          /* travelling dot */
          ctx.beginPath(); ctx.arc(tail.x, tail.y, 2.2, 0, Math.PI * 2)
          ctx.fillStyle = `rgba(${this.col},${this.op * 0.9})`; ctx.fill()
        }

        if (this.gold && this.finished) {
          const ep = this.allPts[this.allPts.length - 1]
          ;[9, 18, 30].forEach((r, i) => {
            ctx.beginPath(); ctx.arc(ep.x, ep.y, r + Math.sin(time * 2 + i) * 0.6, 0, Math.PI * 2)
            ctx.strokeStyle = `rgba(218,175,72,${(0.45 - i * 0.12) * pulse})`
            ctx.lineWidth = 0.6; ctx.stroke()
          })
        }
      }
    }

    class PulseBack {
      p = 1.0; op = 1.0; y = CY
      done()  { return this.p <= 0 }
      step()  { this.p = Math.max(0, this.p - 0.013); this.op *= 0.979 }
      draw()  {
        const x = PAD + this.p * (W - PAD * 2)
        ctx.beginPath(); ctx.arc(x, CY, 5, 0, Math.PI * 2)
        ctx.fillStyle = `rgba(218,175,72,${this.op * 0.9})`; ctx.fill()
        ;[12, 24, 40].forEach((r, i) => {
          ctx.beginPath(); ctx.arc(x, CY, r, 0, Math.PI * 2)
          ctx.strokeStyle = `rgba(218,175,72,${(0.5 - i * 0.13) * this.op})`
          ctx.lineWidth = 0.7; ctx.stroke()
        })
      }
    }
    let pulseBack: PulseBack | null = null

    let lines: Line[] = []
    let runAge = 0

    /* rolling stats */
    let sCnt = 0, convTarget = 17.4, riskTarget = 44, confTarget = 61
    let curConv = 17.4, curRisk = 44, curConf = 61
    const rollingStatsId = window.setInterval(() => {
      convTarget = 9 + Math.random() * 22
      riskTarget = 18 + Math.random() * 58
      confTarget = 32 + Math.random() * 58
    }, 3200)

    function startRun() {
      lines.forEach(l => {
        if (l.allPts.length > 6) {
          ghosts.push({ pts: [...l.allPts], op: l.op * (l.gold ? 0.08 : 0.028), col: l.col })
        }
      })
      while (ghosts.length > 220) ghosts.shift()
      const count = 5 + Math.floor(Math.random() * 4)
      lines = Array.from({ length: count }, () => new Line())
      runAge = 0
    }
    startRun()

    function drawNodes(time: number) {
      LABELS.forEach((label, i) => {
        const x = NX[i]
        ctx.beginPath(); ctx.moveTo(x, FY + 5); ctx.lineTo(x, FY + FH - 5)
        ctx.setLineDash([1, 8])
        ctx.strokeStyle = 'rgba(242,236,224,0.05)'; ctx.lineWidth = 0.4
        ctx.stroke(); ctx.setLineDash([])
        if (i < N - 1) {
          ctx.beginPath(); ctx.moveTo(x, CY); ctx.lineTo(NX[i + 1], CY)
          ctx.strokeStyle = 'rgba(242,236,224,0.05)'; ctx.lineWidth = 0.4; ctx.stroke()
        }
        /* halo */
        const hp = 0.4 + Math.sin(time * 1.3 + i * 0.85) * 0.28
        ctx.beginPath(); ctx.arc(x, CY, 7, 0, Math.PI * 2)
        ctx.strokeStyle = `rgba(242,236,224,${hp * 0.1})`; ctx.lineWidth = 0.5; ctx.stroke()
        /* node dot — solid and bright */
        ctx.beginPath(); ctx.arc(x, CY, 3.5, 0, Math.PI * 2)
        ctx.fillStyle = `rgba(242,236,224,${0.5 + hp * 0.2})`; ctx.fill()
        ctx.save(); ctx.font = '7px system-ui,sans-serif'; ctx.textAlign = 'center'
        ctx.fillStyle = 'rgba(242,236,224,0.18)'; ctx.fillText(label.toUpperCase(), x, FY + 12)
        ctx.restore()
      })
    }

    function drawAtmo(time: number) {
      ;[0.28, 0.72].forEach((f, i) => {
        const y = FY + f * FH
        const op = 0.013 + Math.sin(time * 0.2 + i * 1.3) * 0.008
        ctx.beginPath()
        for (let x = PAD; x <= W - PAD; x += 5) {
          const dy = Math.sin(x * 0.01 + time * 0.14 + i) * FH * 0.005
          x === PAD ? ctx.moveTo(x, y + dy) : ctx.lineTo(x, y + dy)
        }
        ctx.strokeStyle = `rgba(212,160,80,${op})`; ctx.lineWidth = 0.3; ctx.stroke()
      })
    }

    function drawVig() {
      const makeH = (x0: number, x1: number) => {
        const g = ctx.createLinearGradient(x0, 0, x1, 0)
        g.addColorStop(0, '#060408'); g.addColorStop(1, 'rgba(6,4,8,0)'); return g
      }
      ctx.fillStyle = makeH(0, 70);     ctx.fillRect(0, 0, 70, H)
      ctx.fillStyle = makeH(W, W - 70); ctx.fillRect(W - 70, 0, 70, H)
      const tg = ctx.createLinearGradient(0, FY - 2, 0, FY + 20)
      tg.addColorStop(0, '#060408'); tg.addColorStop(1, 'rgba(6,4,8,0)')
      ctx.fillStyle = tg; ctx.fillRect(0, 0, W, FY + 20)
      const bg = ctx.createLinearGradient(0, FY + FH - 16, 0, H - BY)
      bg.addColorStop(0, 'rgba(6,4,8,0)'); bg.addColorStop(1, '#060408')
      ctx.fillStyle = bg; ctx.fillRect(0, FY + FH - 16, W, H)
    }

    let time = 0, rafId = 0
    let statTimer = 0

    function frame() {
      ctx.clearRect(0, 0, W, H)
      ctx.fillStyle = '#060408'; ctx.fillRect(0, 0, W, H)
      time += 0.016; runAge++; sCnt += 11; statTimer++

      curConv += (convTarget - curConv) * 0.012
      curRisk += (riskTarget - curRisk) * 0.013
      curConf += (confTarget - curConf) * 0.011

      /* update React stats every 30 frames */
      if (statTimer % 30 === 0) {
        setStats({
          scenarios: sCnt,
          conv:      Math.round(curConv * 10) / 10,
          risk:      Math.round(curRisk),
          conf:      Math.round(curConf),
        })
      }

      drawAtmo(time)

      ghosts.forEach(g => {
        if (g.pts.length < 2) return
        ctx.beginPath(); ctx.moveTo(g.pts[0].x, g.pts[0].y)
        g.pts.forEach(p => ctx.lineTo(p.x, p.y))
        ctx.strokeStyle = `rgba(${g.col},${g.op})`
        ctx.lineWidth = 0.35; ctx.stroke()
      })

      drawNodes(time)
      lines.forEach(l => l.step())
      lines.forEach(l => l.draw(time))

      for (let i = particles.length - 1; i >= 0; i--) {
        particles[i].step(); particles[i].draw()
        if (particles[i].dead) particles.splice(i, 1)
      }

      if (pulseBack) { pulseBack.step(); pulseBack.draw(); if (pulseBack.done()) pulseBack = null }

      drawVig()

      ctx.fillStyle = 'rgba(212,140,60,0.011)'
      ctx.fillRect(PAD, FY + ((time * 7) % FH), W - PAD * 2, 0.7)

      const allDone = lines.every(l => l.finished || l.dead)
      if (allDone || runAge > 1400) {
        const winner = lines.find(l => l.gold && l.finished && !l.dead)
          || lines.find(l => l.finished && !l.dead)
        if (winner && !pulseBack) pulseBack = new PulseBack()
        setTimeout(startRun, winner ? 1600 : 500)
      }

      rafId = requestAnimationFrame(frame)
    }

    frame()
    return () => {
      cancelAnimationFrame(rafId)
      window.clearInterval(rollingStatsId)
    }
  }, [])

  return (
    <div
      ref={wrapRef}
      style={{
        width: '100%', height: '130px',
        background: '#060408',
        position: 'relative', overflow: 'hidden',
        borderTop:    '0.5px solid rgba(26,23,20,0.6)',
        borderBottom: '0.5px solid rgba(26,23,20,0.6)',
      }}
    >
      <canvas ref={cvRef} style={{ position: 'absolute', inset: 0 }} />

      {/* top bar */}
      <div style={{
        position: 'absolute', top: 0, left: 0, right: 0, height: 24,
        display: 'flex', alignItems: 'center',
        justifyContent: 'space-between', padding: '0 18px',
        borderBottom: '0.5px solid rgba(255,255,255,.03)',
        zIndex: 10, pointerEvents: 'none',
      }}>
        <span style={{ fontFamily: 'Georgia,serif', fontStyle: 'italic', fontSize: 10, color: 'rgba(242,236,224,.1)' }}>TheCee</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <div style={{ width: 16, height: 0.5, background: 'rgba(212,140,80,.4)' }} />
          <div style={{ width: 4, height: 4, borderRadius: '50%', background: '#d48c50' }} />
          <span style={{ fontSize: 7, color: 'rgba(212,140,80,.4)', letterSpacing: '0.2em', textTransform: 'uppercase', fontFamily: 'system-ui' }}>Timeline running</span>
          <div style={{ width: 16, height: 0.5, background: 'rgba(212,140,80,.4)' }} />
        </div>
        <span style={{ fontFamily: '"Courier New",monospace', fontSize: 9, color: 'rgba(242,236,224,.12)' }}>Simulation Engine</span>
      </div>

      {/* bottom stats bar */}
      <div style={{
        position: 'absolute', bottom: 0, left: 0, right: 0, height: 28,
        display: 'flex', alignItems: 'center',
        padding: '0 20px', gap: 0,
        borderTop: '0.5px solid rgba(255,255,255,.03)',
        zIndex: 10, pointerEvents: 'none',
        background: 'rgba(6,4,8,0.6)',
      }}>
        {[
          { val: stats.scenarios.toLocaleString(), lbl: 'Scenarios' },
          { val: `${stats.conv}%`, lbl: 'Conversion' },
          { val: String(stats.risk), lbl: 'Risk' },
          { val: `${stats.conf}%`, lbl: 'Confidence' },
        ].map(({ val, lbl }, i) => (
          <div key={lbl} style={{ display: 'flex', alignItems: 'baseline', gap: 4, marginRight: i < 3 ? 0 : 0 }}>
            <span style={{ fontFamily: '"Courier New",monospace', fontSize: 11, color: 'rgba(242,236,224,.38)', letterSpacing: '.04em', fontVariantNumeric: 'tabular-nums' }}>
              {val}
            </span>
            <span style={{ fontSize: 7, color: 'rgba(242,236,224,.14)', letterSpacing: '.18em', textTransform: 'uppercase', fontFamily: 'system-ui' }}>
              {lbl}
            </span>
            {i < 3 && <div style={{ width: 0.5, height: 10, background: 'rgba(255,255,255,.06)', margin: '0 14px' }} />}
          </div>
        ))}
      </div>
    </div>
  )
}
