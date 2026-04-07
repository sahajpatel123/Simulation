'use client'

import { useEffect, useRef } from 'react'

export default function SimulationTimeline() {
  const wrapRef = useRef<HTMLDivElement>(null)
  const cvRef   = useRef<HTMLCanvasElement>(null)

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

    const TY = 24, BY = 20
    const FY = TY, FH = H - TY - BY
    const CY = FY + FH / 2
    const PAD = 48

    const LABELS = ['Idea','Assume','Market','Pricing','Build','Launch','Retain','Scale']
    const N = LABELS.length
    const NX = LABELS.map((_, i) => PAD + (i / (N - 1)) * (W - PAD * 2))

    type Pt = { x: number; y: number }

    /* ── particles ── */
    class Particle {
      x: number; y: number; vx: number; vy: number
      op = 0.85; r: number; col: string; dead = false
      constructor(x: number, y: number, col: string) {
        this.x = x; this.y = y; this.col = col
        const a = Math.random() * Math.PI * 2
        const s = 0.6 + Math.random() * 2.2
        this.vx = Math.cos(a) * s
        this.vy = Math.sin(a) * s - 1.0
        this.r  = 0.6 + Math.random() * 1.0
      }
      step() { this.x += this.vx; this.vy += 0.06; this.y += this.vy; this.op *= 0.93; if (this.op < 0.02) this.dead = true }
      draw() { ctx.beginPath(); ctx.arc(this.x, this.y, this.r, 0, Math.PI * 2); ctx.fillStyle = `rgba(${this.col},${this.op})`; ctx.fill() }
    }
    const particles: Particle[] = []

    /* ── ghost history ── */
    const ghosts: { pts: Pt[]; op: number; col: string }[] = []

    /* ── Line class ── */
    class Line {
      /* visual */
      col:  string
      lw:   number
      op:   number
      gold: boolean

      /* complete path — never trimmed */
      allPts: Pt[] = []

      /* current segment bezier */
      seg = 0            /* currently travelling from node seg → seg+1 */
      t   = 0
      spd: number

      /* per-node die probability — set once randomly per line */
      diePr: number

      /* pause at node */
      paused    = false
      pauseAge  = 0
      pauseLen: number

      /* state */
      dead     = false
      finished = false

      /* bezier control points */
      b0: Pt; b1: Pt; b2: Pt

      constructor(startY: number) {
        /* gold: ~20% chance */
        this.gold = Math.random() < 0.20
        this.col  = this.gold ? '210,170,70' : `${185 + Math.floor(Math.random()*30)},${175 + Math.floor(Math.random()*25)},${155 + Math.floor(Math.random()*25)}`
        this.lw   = this.gold ? 1.0 : 0.5 + Math.random() * 0.5
        this.op   = 0.45 + Math.random() * 0.45
        this.spd  = 0.020 + Math.random() * 0.014
        /* random die probability per line — some survive easily, some don't */
        this.diePr    = 0.08 + Math.random() * 0.32
        this.pauseLen = 22 + Math.floor(Math.random() * 26)
        this.b0 = { x: NX[0], y: startY }
        this.b1 = { x: 0, y: 0 }
        this.b2 = { x: 0, y: 0 }
        this.allPts = [{ x: NX[0], y: startY }]
        this.buildSeg()
      }

      buildSeg() {
        const fromX = this.b0.x
        const fromY = this.b0.y
        const toIdx = this.seg + 1
        const toX   = NX[toIdx]
        /* control point — dramatically random Y anywhere in field */
        const ctrlX = fromX + (toX - fromX) * (0.25 + Math.random() * 0.5)
        const ctrlY = FY + 6 + Math.random() * (FH - 12)
        /* end Y — random in field */
        const endY  = FY + 6 + Math.random() * (FH - 12)
        this.b1 = { x: ctrlX, y: ctrlY }
        this.b2 = { x: toX,   y: endY  }
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

        /* ── PAUSED at a node ── */
        if (this.paused) {
          this.pauseAge++
          if (this.pauseAge >= this.pauseLen) {
            this.paused   = false
            this.pauseAge = 0
            /* die check — random per line */
            if (Math.random() < this.diePr) {
              this.dead = true
              const cx = NX[this.seg + 1]
              const cy = this.b2.y
              const pc = this.gold ? this.col : '192,57,43'
              for (let i = 0; i < 10; i++) particles.push(new Particle(cx, cy, pc))
              return
            }
            /* advance */
            this.seg++
            if (this.seg >= N - 1) { this.finished = true; return }
            this.t  = 0
            this.b0 = { x: this.b2.x, y: this.b2.y }
            this.buildSeg()
          }
          return
        }

        /* ── TRAVELLING ── */
        this.t = Math.min(1, this.t + this.spd)
        const pos = this.bez(this.t)
        this.allPts.push({ x: pos.x, y: pos.y })

        /* arrived at node — SNAP exactly to node X */
        if (this.t >= 1) {
          /* force exact node position */
          const snapped = { x: NX[this.seg + 1], y: this.b2.y }
          this.allPts[this.allPts.length - 1] = snapped
          this.b2 = snapped
          this.paused   = true
          this.pauseAge = 0
        }
      }

      draw(time: number) {
        if (this.allPts.length < 2) return

        /* draw ENTIRE path from origin */
        ctx.beginPath()
        ctx.moveTo(this.allPts[0].x, this.allPts[0].y)
        for (let i = 1; i < this.allPts.length; i++) {
          ctx.lineTo(this.allPts[i].x, this.allPts[i].y)
        }
        const fade  = this.dead ? 0.22 : 1
        const pulse = this.gold ? 0.7 + Math.sin(time * 3) * 0.3 : 1
        ctx.strokeStyle = `rgba(${this.col},${this.op * fade * pulse})`
        ctx.lineWidth   = this.lw
        ctx.stroke()

        if (this.dead || this.finished) return

        const tail = this.allPts[this.allPts.length - 1]

        if (this.paused) {
          /* large pulsing ring expanding from node dot */
          const nodeX = NX[this.seg + 1]
          const nodeY = this.b2.y
          const pr    = this.pauseAge / this.pauseLen

          /* outer ring */
          ctx.beginPath()
          ctx.arc(nodeX, nodeY, 5 + pr * 18, 0, Math.PI * 2)
          ctx.strokeStyle = `rgba(${this.col},${(1 - pr) * this.op * 0.7})`
          ctx.lineWidth   = 0.7; ctx.stroke()

          /* inner ring */
          ctx.beginPath()
          ctx.arc(nodeX, nodeY, 3 + pr * 9, 0, Math.PI * 2)
          ctx.strokeStyle = `rgba(${this.col},${(1 - pr) * this.op * 0.4})`
          ctx.lineWidth   = 0.5; ctx.stroke()

          /* bright pause dot */
          ctx.beginPath()
          ctx.arc(nodeX, nodeY, 3, 0, Math.PI * 2)
          ctx.fillStyle = `rgba(${this.col},${this.op * (0.5 + Math.sin(time * 9) * 0.5)})`
          ctx.fill()

        } else {
          /* small travelling dot */
          ctx.beginPath()
          ctx.arc(tail.x, tail.y, 1.8, 0, Math.PI * 2)
          ctx.fillStyle = `rgba(${this.col},${this.op * 0.85})`
          ctx.fill()
        }

        /* gold finish bloom */
        if (this.gold && this.finished) {
          const ep = this.allPts[this.allPts.length - 1]
          ;[8, 18, 30].forEach((r, i) => {
            ctx.beginPath()
            ctx.arc(ep.x, ep.y, r + Math.sin(time * 2 + i) * 0.6, 0, Math.PI * 2)
            ctx.strokeStyle = `rgba(230,190,80,${(0.4 - i * 0.1) * pulse})`
            ctx.lineWidth   = 0.5; ctx.stroke()
          })
        }
      }
    }

    /* ── pulse back on gold win ── */
    class PulseBack {
      p = 1.0; op = 1.0; y: number
      constructor(y: number) { this.y = y }
      done()  { return this.p <= 0 }
      step()  { this.p = Math.max(0, this.p - 0.014); this.op *= 0.98 }
      draw()  {
        const x = PAD + this.p * (W - PAD * 2)
        ctx.beginPath(); ctx.arc(x, this.y, 4.5, 0, Math.PI * 2)
        ctx.fillStyle = `rgba(230,190,80,${this.op * 0.9})`; ctx.fill()
        ;[11, 22, 38].forEach((r, i) => {
          ctx.beginPath(); ctx.arc(x, this.y, r, 0, Math.PI * 2)
          ctx.strokeStyle = `rgba(230,190,80,${(0.5 - i * 0.13) * this.op})`
          ctx.lineWidth = 0.6; ctx.stroke()
        })
      }
    }
    let pulseBack: PulseBack | null = null

    /* ── run state ── */
    let lines: Line[] = []
    let runAge = 0

    function startRun() {
      /* save ghosts */
      lines.forEach(l => {
        if (l.allPts.length > 8) {
          ghosts.push({
            pts: [...l.allPts],
            op:  l.op * (l.gold ? 0.09 : 0.032),
            col: l.col,
          })
        }
      })
      while (ghosts.length > 260) ghosts.shift()

      /* random line count 5–8 */
      const count = 5 + Math.floor(Math.random() * 4)
      lines = []
      for (let i = 0; i < count; i++) {
        /* spread randomly across full field height */
        const startY = FY + 10 + Math.random() * (FH - 20)
        lines.push(new Line(startY))
      }
      runAge = 0
    }
    startRun()

    /* ── node dots ── */
    function drawNodes(time: number) {
      LABELS.forEach((label, i) => {
        const x = NX[i]
        /* dashed column */
        ctx.beginPath(); ctx.moveTo(x, FY + 5); ctx.lineTo(x, FY + FH - 5)
        ctx.setLineDash([1, 9])
        ctx.strokeStyle = 'rgba(242,236,224,0.045)'; ctx.lineWidth = 0.4
        ctx.stroke(); ctx.setLineDash([])
        /* base connector */
        if (i < N - 1) {
          ctx.beginPath(); ctx.moveTo(x, CY); ctx.lineTo(NX[i + 1], CY)
          ctx.strokeStyle = 'rgba(242,236,224,0.035)'; ctx.lineWidth = 0.35; ctx.stroke()
        }
        /* outer halo */
        const hp = 0.3 + Math.sin(time * 1.3 + i * 0.8) * 0.25
        ctx.beginPath(); ctx.arc(x, CY, 6, 0, Math.PI * 2)
        ctx.strokeStyle = `rgba(242,236,224,${hp * 0.12})`; ctx.lineWidth = 0.5; ctx.stroke()
        /* inner dot — bright and always visible */
        ctx.beginPath(); ctx.arc(x, CY, 3, 0, Math.PI * 2)
        ctx.fillStyle = `rgba(242,236,224,${0.45 + hp * 0.2})`; ctx.fill()
        /* label */
        ctx.save(); ctx.font = '7px system-ui,sans-serif'; ctx.textAlign = 'center'
        ctx.fillStyle = 'rgba(242,236,224,0.16)'; ctx.fillText(label.toUpperCase(), x, FY + 12)
        ctx.restore()
      })
    }

    /* ── atmosphere ── */
    function drawAtmo(time: number) {
      ;[0.3, 0.7].forEach((f, i) => {
        const y  = FY + f * FH
        const op = 0.014 + Math.sin(time * 0.2 + i * 1.4) * 0.008
        ctx.beginPath()
        for (let x = PAD; x <= W - PAD; x += 5) {
          const dy = Math.sin(x * 0.011 + time * 0.14 + i) * FH * 0.005
          x === PAD ? ctx.moveTo(x, y + dy) : ctx.lineTo(x, y + dy)
        }
        ctx.strokeStyle = `rgba(212,160,80,${op})`; ctx.lineWidth = 0.3; ctx.stroke()
      })
    }

    /* ── vignettes ── */
    function drawVig() {
      const make = (x0: number, x1: number) => {
        const g = ctx.createLinearGradient(x0, 0, x1, 0)
        g.addColorStop(0, '#060408'); g.addColorStop(1, 'rgba(6,4,8,0)'); return g
      }
      ctx.fillStyle = make(0, 72);     ctx.fillRect(0, 0, 72, H)
      ctx.fillStyle = make(W, W - 72); ctx.fillRect(W - 72, 0, 72, H)
      const tg = ctx.createLinearGradient(0, FY - 2, 0, FY + 22)
      tg.addColorStop(0, '#060408'); tg.addColorStop(1, 'rgba(6,4,8,0)')
      ctx.fillStyle = tg; ctx.fillRect(0, 0, W, FY + 22)
      const bg = ctx.createLinearGradient(0, FY + FH - 18, 0, H)
      bg.addColorStop(0, 'rgba(6,4,8,0)'); bg.addColorStop(1, '#060408')
      ctx.fillStyle = bg; ctx.fillRect(0, FY + FH - 18, W, H)
    }

    /* ── main loop ── */
    let time  = 0
    let rafId = 0

    function frame() {
      ctx.clearRect(0, 0, W, H)
      ctx.fillStyle = '#060408'; ctx.fillRect(0, 0, W, H)
      time += 0.016; runAge++

      drawAtmo(time)

      /* ghost traces */
      ghosts.forEach(g => {
        if (g.pts.length < 2) return
        ctx.beginPath(); ctx.moveTo(g.pts[0].x, g.pts[0].y)
        g.pts.forEach(p => ctx.lineTo(p.x, p.y))
        ctx.strokeStyle = `rgba(${g.col},${g.op})`
        ctx.lineWidth = 0.3; ctx.stroke()
      })

      drawNodes(time)

      /* update then draw — order matters */
      lines.forEach(l => l.step())
      lines.forEach(l => l.draw(time))

      /* particles */
      for (let i = particles.length - 1; i >= 0; i--) {
        particles[i].step(); particles[i].draw()
        if (particles[i].dead) particles.splice(i, 1)
      }

      /* pulse back */
      if (pulseBack) { pulseBack.step(); pulseBack.draw(); if (pulseBack.done()) pulseBack = null }

      drawVig()

      /* scan */
      ctx.fillStyle = 'rgba(212,140,60,0.012)'
      ctx.fillRect(PAD, FY + ((time * 7) % FH), W - PAD * 2, 0.7)

      /* check run complete */
      const allDone = lines.every(l => l.finished || l.dead)
      if (allDone || runAge > 1400) {
        const winner = lines.find(l => l.gold && l.finished && !l.dead)
          || lines.find(l => l.finished && !l.dead)
        if (winner && !pulseBack) {
          const ey = winner.allPts.length > 0
            ? winner.allPts[winner.allPts.length - 1].y : CY
          pulseBack = new PulseBack(ey)
        }
        setTimeout(startRun, winner ? 1600 : 500)
      }

      rafId = requestAnimationFrame(frame)
    }

    frame()
    return () => cancelAnimationFrame(rafId)
  }, [])

  return (
    <div
      ref={wrapRef}
      style={{
        width: '100%', height: '120px',
        background: '#060408',
        position: 'relative', overflow: 'hidden',
        borderTop:    '0.5px solid rgba(26,23,20,0.5)',
        borderBottom: '0.5px solid rgba(26,23,20,0.5)',
      }}
    >
      <canvas ref={cvRef} style={{ position: 'absolute', inset: 0 }} />
      <div style={{
        position: 'absolute', top: 0, left: 0, right: 0, height: 24,
        display: 'flex', alignItems: 'center',
        justifyContent: 'space-between', padding: '0 18px',
        borderBottom: '0.5px solid rgba(255,255,255,.025)',
        zIndex: 10, pointerEvents: 'none',
      }}>
        <span style={{ fontFamily: 'Georgia,serif', fontStyle: 'italic', fontSize: 10, color: 'rgba(242,236,224,.1)' }}>
          TheCee
        </span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <div style={{ width: 16, height: 0.5, background: 'rgba(212,140,80,.4)' }} />
          <div style={{ width: 4, height: 4, borderRadius: '50%', background: '#d48c50' }} />
          <span style={{ fontSize: 7, color: 'rgba(212,140,80,.4)', letterSpacing: '0.2em', textTransform: 'uppercase', fontFamily: 'system-ui' }}>
            Timeline running
          </span>
          <div style={{ width: 16, height: 0.5, background: 'rgba(212,140,80,.4)' }} />
        </div>
        <span style={{ fontFamily: '"Courier New",monospace', fontSize: 9, color: 'rgba(242,236,224,.12)', letterSpacing: '.04em' }}>
          Simulation Engine
        </span>
      </div>
    </div>
  )
}
