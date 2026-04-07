'use client'

import { useEffect, useRef } from 'react'

export default function SimulationTimeline() {
  const wrapRef = useRef<HTMLDivElement>(null)
  const cvRef  = useRef<HTMLCanvasElement>(null)

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

    /* ── layout ── */
    const PAD  = 48
    const TY   = 24   /* top bar height */
    const BY   = 20   /* bottom bar height */
    const FY   = TY
    const FH   = H - TY - BY
    const CY   = FY + FH / 2

    /* ── nodes ── */
    const LABELS = ['Idea','Assume','Market','Pricing','Build','Launch','Retain','Scale']
    const N = LABELS.length
    const NX: number[] = LABELS.map((_, i) => PAD + (i / (N - 1)) * (W - PAD * 2))

    /* ── ghost history (past run traces) ── */
    type Pt = { x: number; y: number }
    const ghosts: { pts: Pt[]; op: number; gold: boolean }[] = []

    /* ── particles ── */
    class Particle {
      x: number; y: number
      vx: number; vy: number
      op = 0.9; r: number; col: string; dead = false
      constructor(x: number, y: number, col: string) {
        this.x = x; this.y = y; this.col = col
        const a = Math.random() * Math.PI * 2
        const s = 0.8 + Math.random() * 2.5
        this.vx = Math.cos(a) * s
        this.vy = Math.sin(a) * s - 1.2
        this.r  = 0.7 + Math.random() * 1.1
      }
      step() {
        this.x += this.vx; this.vy += 0.07; this.y += this.vy
        this.op *= 0.92; if (this.op < 0.02) this.dead = true
      }
      draw() {
        ctx.beginPath()
        ctx.arc(this.x, this.y, this.r, 0, Math.PI * 2)
        ctx.fillStyle = `rgba(${this.col},${this.op})`
        ctx.fill()
      }
    }
    const particles: Particle[] = []

    /* ── one line (travels node by node) ── */
    class Line {
      /* identity */
      gold: boolean
      col: string
      lw:  number
      op:  number

      /* full drawn history */
      pts: Pt[] = []

      /* segment state */
      seg  = 0          /* heading from node seg to node seg+1 */
      t    = 0          /* 0→1 progress within current segment */
      speed: number

      /* pause state */
      paused    = false
      pauseAge  = 0
      pauseLen: number  /* frames to wait at each node */

      dead      = false
      finished  = false

      /* bezier control points for current segment */
      bx0 = 0; by0 = 0  /* start */
      bx1 = 0; by1 = 0  /* control */
      bx2 = 0; by2 = 0  /* end   */

      constructor(startY: number, gold: boolean) {
        this.gold  = gold
        this.op    = 0.55 + Math.random() * 0.35
        this.col   = gold ? '210,170,70' : '205,195,178'
        this.lw    = gold ? 1.0 : 0.7
        this.speed = 0.022 + Math.random() * 0.012
        this.pauseLen = 28 + Math.floor(Math.random() * 20)
        this.pts.push({ x: NX[0], y: startY })
        this.buildSeg(NX[0], startY)
      }

      buildSeg(fromX: number, fromY: number) {
        const toX  = NX[this.seg + 1]
        const toY  = CY + (Math.random() - 0.5) * FH * 0.75
        /* control point — dramatic vertical swing */
        const ctrlX = fromX + (toX - fromX) * (0.3 + Math.random() * 0.4)
        const ctrlY = CY + (Math.random() - 0.5) * FH * 0.9
        this.bx0 = fromX; this.by0 = fromY
        this.bx1 = ctrlX; this.by1 = ctrlY
        this.bx2 = toX;   this.by2 = toY
      }

      /* quadratic bezier point at parameter t */
      bezier(t: number): Pt {
        const mt = 1 - t
        return {
          x: mt * mt * this.bx0 + 2 * mt * t * this.bx1 + t * t * this.bx2,
          y: mt * mt * this.by0 + 2 * mt * t * this.by1 + t * t * this.by2,
        }
      }

      step() {
        if (this.dead || this.finished) return

        /* ── PAUSING at a node ── */
        if (this.paused) {
          this.pauseAge++
          if (this.pauseAge >= this.pauseLen) {
            this.paused   = false
            this.pauseAge = 0
            /* die at this node? */
            const diePr = 0.28 + this.seg * 0.04
            if (Math.random() < diePr) {
              this.dead = true
              const nodeX = NX[this.seg + 1]
              const nodeY = this.bx2 === nodeX ? this.by2 : CY
              const col   = this.gold ? this.col : '192,57,43'
              for (let i = 0; i < 10; i++) particles.push(new Particle(nodeX, nodeY, col))
              return
            }
            /* advance to next segment */
            this.seg++
            if (this.seg >= N - 1) { this.finished = true; return }
            this.t = 0
            this.buildSeg(this.bx2, this.by2)
          }
          return
        }

        /* ── TRAVELLING ── */
        this.t = Math.min(1, this.t + this.speed)
        const pos = this.bezier(this.t)
        this.pts.push(pos)
        if (this.pts.length > 400) this.pts.shift()

        /* arrived at next node */
        if (this.t >= 1) {
          /* snap final point exactly to node X */
          const last = this.pts[this.pts.length - 1]
          last.x = NX[this.seg + 1]
          this.paused   = true
          this.pauseAge = 0
        }
      }

      draw(time: number) {
        if (this.pts.length < 2) return

        /* path so far */
        ctx.beginPath()
        ctx.moveTo(this.pts[0].x, this.pts[0].y)
        for (let i = 1; i < this.pts.length; i++) ctx.lineTo(this.pts[i].x, this.pts[i].y)
        const pulse = this.gold ? 0.7 + Math.sin(time * 3) * 0.3 : 1
        const fade  = this.dead ? 0.25 : 1
        ctx.strokeStyle = `rgba(${this.col},${this.op * pulse * fade})`
        ctx.lineWidth   = this.lw
        ctx.stroke()

        if (this.dead) return

        /* gold finish bloom (must run before finished early-return) */
        if (this.gold && this.finished) {
          const ep = this.pts[this.pts.length - 1]
          ;[8, 16, 26].forEach((r, i) => {
            ctx.beginPath()
            ctx.arc(ep.x, ep.y, r + Math.sin(time * 2 + i), 0, Math.PI * 2)
            ctx.strokeStyle = `rgba(230,190,80,${(0.4 - i * 0.1) * pulse})`
            ctx.lineWidth   = 0.5
            ctx.stroke()
          })
          return
        }

        if (this.finished) return

        const tail = this.pts[this.pts.length - 1]

        /* ── PAUSE VISUALS at node ── */
        if (this.paused) {
          const nodeX = NX[this.seg + 1]
          const nodeY = tail.y
          const pr    = this.pauseAge / this.pauseLen

          /* expanding ring */
          ctx.beginPath()
          ctx.arc(nodeX, nodeY, 4 + pr * 14, 0, Math.PI * 2)
          ctx.strokeStyle = `rgba(${this.col},${(1 - pr) * 0.55})`
          ctx.lineWidth   = 0.7
          ctx.stroke()

          /* second ring */
          ctx.beginPath()
          ctx.arc(nodeX, nodeY, 2 + pr * 7, 0, Math.PI * 2)
          ctx.strokeStyle = `rgba(${this.col},${(1 - pr) * 0.3})`
          ctx.lineWidth   = 0.5
          ctx.stroke()

          /* bright dot at node */
          ctx.beginPath()
          ctx.arc(nodeX, nodeY, 3.5, 0, Math.PI * 2)
          ctx.fillStyle = `rgba(${this.col},${0.9 * (0.5 + Math.sin(time * 8) * 0.5)})`
          ctx.fill()

        } else {
          /* travelling — small leading dot */
          ctx.beginPath()
          ctx.arc(tail.x, tail.y, 2, 0, Math.PI * 2)
          ctx.fillStyle = `rgba(${this.col},${this.op * 0.8})`
          ctx.fill()
        }
      }
    }

    /* ── pulse-back on gold finish ── */
    class PulseBack {
      p   = 1.0
      op  = 1.0
      y:  number
      constructor(y: number) { this.y = y }
      done() { return this.p <= 0 }
      step() { this.p = Math.max(0, this.p - 0.016); this.op *= 0.978 }
      draw() {
        const x = PAD + this.p * (W - PAD * 2)
        ctx.beginPath(); ctx.arc(x, this.y, 4, 0, Math.PI * 2)
        ctx.fillStyle = `rgba(230,190,80,${this.op * 0.9})`; ctx.fill()
        ;[10, 20, 36].forEach((r, i) => {
          ctx.beginPath(); ctx.arc(x, this.y, r, 0, Math.PI * 2)
          ctx.strokeStyle = `rgba(230,190,80,${(0.5 - i * 0.13) * this.op})`
          ctx.lineWidth = 0.6; ctx.stroke()
        })
      }
    }
    let pulse: PulseBack | null = null

    /* ── run management ── */
    let lines: Line[]      = []
    let runAge = 0

    function startRun() {
      /* save ghost traces */
      lines.forEach(l => {
        if (l.pts.length > 4) {
          ghosts.push({ pts: [...l.pts], op: l.op * (l.gold ? 0.08 : 0.035), gold: l.gold })
        }
      })
      while (ghosts.length > 240) ghosts.shift()

      /* always exactly 3 lines, evenly spaced Y */
      lines = [
        new Line(CY - FH * 0.24, false),
        new Line(CY,              true),   /* middle line is gold */
        new Line(CY + FH * 0.24, false),
      ]
      runAge = 0
    }
    startRun()

    /* ── draw nodes ── */
    function drawNodes(time: number) {
      LABELS.forEach((label, i) => {
        const x = NX[i]
        /* vertical column guide */
        ctx.beginPath(); ctx.moveTo(x, FY + 6); ctx.lineTo(x, FY + FH - 6)
        ctx.setLineDash([1, 9])
        ctx.strokeStyle = 'rgba(242,236,224,0.05)'; ctx.lineWidth = 0.4
        ctx.stroke(); ctx.setLineDash([])
        /* node dot — always visible */
        const pulse2 = 0.45 + Math.sin(time * 1.4 + i * 0.8) * 0.3
        /* outer ring */
        ctx.beginPath(); ctx.arc(x, CY, 5, 0, Math.PI * 2)
        ctx.strokeStyle = `rgba(242,236,224,${pulse2 * 0.15})`; ctx.lineWidth = 0.5; ctx.stroke()
        /* inner dot */
        ctx.beginPath(); ctx.arc(x, CY, 2.5, 0, Math.PI * 2)
        ctx.fillStyle = `rgba(242,236,224,${0.35 + pulse2 * 0.2})`; ctx.fill()
        /* baseline connector */
        if (i < N - 1) {
          ctx.beginPath(); ctx.moveTo(x, CY); ctx.lineTo(NX[i + 1], CY)
          ctx.strokeStyle = 'rgba(242,236,224,0.04)'; ctx.lineWidth = 0.4; ctx.stroke()
        }
        /* label */
        ctx.save(); ctx.font = '7px system-ui,sans-serif'; ctx.textAlign = 'center'
        ctx.fillStyle = 'rgba(242,236,224,0.14)'; ctx.fillText(label.toUpperCase(), x, FY + 12)
        ctx.restore()
      })
    }

    /* ── atmosphere ── */
    function drawAtmo(time: number) {
      ;[0.28, 0.72].forEach((f, i) => {
        const y  = FY + f * FH
        const op = 0.016 + Math.sin(time * 0.22 + i * 1.3) * 0.01
        ctx.beginPath()
        for (let x = PAD; x <= W - PAD; x += 5) {
          const dy = Math.sin(x * 0.01 + time * 0.15 + i) * 0.006 * FH
          x === PAD ? ctx.moveTo(x, y + dy) : ctx.lineTo(x, y + dy)
        }
        ctx.strokeStyle = `rgba(212,160,80,${op})`; ctx.lineWidth = 0.3; ctx.stroke()
      })
    }

    /* ── vignettes ── */
    function drawVig() {
      const lg = ctx.createLinearGradient(0, 0, 72, 0)
      lg.addColorStop(0, '#060408'); lg.addColorStop(1, 'rgba(6,4,8,0)')
      ctx.fillStyle = lg; ctx.fillRect(0, 0, 72, H)
      const rg = ctx.createLinearGradient(W - 72, 0, W, 0)
      rg.addColorStop(0, 'rgba(6,4,8,0)'); rg.addColorStop(1, '#060408')
      ctx.fillStyle = rg; ctx.fillRect(W - 72, 0, 72, H)
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

      time  += 0.016
      runAge++

      drawAtmo(time)

      /* ghost history */
      ghosts.forEach(g => {
        if (g.pts.length < 2) return
        ctx.beginPath(); ctx.moveTo(g.pts[0].x, g.pts[0].y)
        g.pts.forEach(p => ctx.lineTo(p.x, p.y))
        ctx.strokeStyle = `rgba(${g.gold ? '210,170,70' : '205,195,178'},${g.op})`
        ctx.lineWidth = g.gold ? 0.5 : 0.3; ctx.stroke()
      })

      drawNodes(time)

      /* update lines */
      lines.forEach(l => l.step())
      lines.forEach(l => l.draw(time))

      /* particles */
      for (let i = particles.length - 1; i >= 0; i--) {
        particles[i].step(); particles[i].draw()
        if (particles[i].dead) particles.splice(i, 1)
      }

      /* pulse back */
      if (pulse) { pulse.step(); pulse.draw(); if (pulse.done()) pulse = null }

      drawVig()

      /* scan line */
      ctx.fillStyle = 'rgba(212,140,60,0.013)'
      ctx.fillRect(PAD, FY + ((time * 8) % FH), W - PAD * 2, 0.8)

      /* check run end */
      const allDone = lines.every(l => l.finished || l.dead)
      if (allDone || runAge > 1200) {
        const goldWin = lines.find(l => l.gold && l.finished && !l.dead)
        if (goldWin && !pulse) {
          const ey = goldWin.pts.length > 0
            ? goldWin.pts[goldWin.pts.length - 1].y : CY
          pulse = new PulseBack(ey)
        }
        setTimeout(startRun, goldWin ? 1600 : 600)
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

      {/* top label */}
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
