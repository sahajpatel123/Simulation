'use client'

import { useEffect, useRef, useState, type CSSProperties } from 'react'

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

    const TY = 28, BY = 28
    const FY = TY
    const FH = H - TY - BY
    const CY = FY + FH / 2
    const PAD = 52

    const LABELS = ['Idea','Assume','Market','Pricing','Build','Launch','Retain','Scale']
    const N  = LABELS.length
    const NX = LABELS.map((_, i) => PAD + (i / (N - 1)) * (W - PAD * 2))

    /* editorial palette */
    const PAPER     = '#f2ece0'
    const INK       = '26,23,20'       /* #1a1714 */
    const RED       = '192,57,43'      /* #c0392b */
    const GOLD      = '160,100,40'     /* warm editorial amber — not tech gold */

    type Pt = { x: number; y: number }

    class Particle {
      x: number; y: number; vx: number; vy: number
      op = 0.7; r: number; col: string; dead = false
      constructor(x: number, y: number, col: string) {
        this.x = x; this.y = y; this.col = col
        const a = Math.random() * Math.PI * 2
        const s = 0.5 + Math.random() * 1.8
        this.vx = Math.cos(a) * s
        this.vy = Math.sin(a) * s - 0.9
        this.r  = 0.5 + Math.random() * 0.9
      }
      step() {
        this.x += this.vx; this.vy += 0.055; this.y += this.vy
        this.op *= 0.91; if (this.op < 0.02) this.dead = true
      }
      draw() {
        ctx.beginPath(); ctx.arc(this.x, this.y, this.r, 0, Math.PI * 2)
        ctx.fillStyle = `rgba(${this.col},${this.op})`; ctx.fill()
      }
    }
    const particles: Particle[] = []
    const ghosts: { pts: Pt[]; op: number; col: string }[] = []

    type SubSeg = { b0: Pt; b1: Pt; b2: Pt }

    class Line {
      col:  string
      lw:   number
      op:   number
      red:  boolean   /* red line = failing path */
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
      /* 1–3 quadratic beziers chained per node gap — zigzag organic motion */
      subSegs: SubSeg[] = []
      subIdx = 0

      constructor() {
        /* ~15% red (failing), ~15% gold (winning), rest ink */
        const roll = Math.random()
        this.red  = roll < 0.15
        const isGold = roll > 0.85
        if (this.red) {
          this.col = RED
          this.lw  = 0.7
          this.op  = 0.45 + Math.random() * 0.25
        } else if (isGold) {
          this.col = GOLD
          this.lw  = 1.2
          this.op  = 0.75 + Math.random() * 0.2
        } else {
          /* ink lines — varying darkness */
          const a = Math.floor(Math.random() * 30)
          this.col = `${26 + a},${23 + a},${20 + a}`
          this.lw  = 0.4 + Math.random() * 1.2
          this.op  = 0.35 + Math.random() * 0.45
        }
        this.spd      = 0.012 + Math.random() * 0.022
        this.diePr    = this.red ? 0.5 + Math.random() * 0.35 : 0.05 + Math.random() * 0.35
        this.pauseLen = 12 + Math.floor(Math.random() * 40)
        this.allPts = [{ x: NX[0], y: CY }]
        this.buildSeg()
      }

      buildSeg() {
        const fromX = NX[this.seg]
        const toX   = NX[this.seg + 1]
        const subCount = 1 + Math.floor(Math.random() * 3)
        const waypoints: Pt[] = []
        waypoints.push({ x: fromX, y: CY })
        for (let k = 1; k < subCount; k++) {
          const tx = fromX + (toX - fromX) * (k / subCount)
          const ty = FY + 6 + Math.random() * (FH - 12)
          waypoints.push({ x: tx, y: ty })
        }
        waypoints.push({ x: toX, y: CY })

        this.subSegs = []
        for (let i = 0; i < subCount; i++) {
          const p0 = waypoints[i]
          const p2 = waypoints[i + 1]
          const swing = (Math.random() > 0.5 ? 1 : -1) * (FH * 0.1 + Math.random() * FH * 0.45)
          const ctrlX = p0.x + (p2.x - p0.x) * (0.25 + Math.random() * 0.5)
          const ctrlY = Math.max(FY + 5, Math.min(FY + FH - 5, CY + swing))
          this.subSegs.push({
            b0: { x: p0.x, y: p0.y },
            b1: { x: ctrlX, y: ctrlY },
            b2: { x: p2.x, y: p2.y },
          })
        }
        this.subIdx = 0
      }

      bezSeg(s: SubSeg, tt: number): Pt {
        const mt = 1 - tt
        return {
          x: mt * mt * s.b0.x + 2 * mt * tt * s.b1.x + tt * tt * s.b2.x,
          y: mt * mt * s.b0.y + 2 * mt * tt * s.b1.y + tt * tt * s.b2.y,
        }
      }

      step() {
        if (this.dead || this.finished) return
        if (this.paused) {
          this.pauseAge++
          if (this.pauseAge >= this.pauseLen) {
            this.paused = false; this.pauseAge = 0
            if (Math.random() < this.diePr) {
              this.dead = true
              const cx = NX[this.seg + 1]
              for (let i = 0; i < 8; i++) particles.push(new Particle(cx, CY, this.red ? RED : INK))
              return
            }
            this.seg++
            if (this.seg >= N - 1) { this.finished = true; return }
            this.t = 0; this.buildSeg()
          }
          return
        }
        const cur = this.subSegs[this.subIdx]
        if (!cur) return
        this.t = Math.min(1, this.t + this.spd)
        const pos = this.bezSeg(cur, this.t)
        this.allPts.push(pos)
        if (this.t >= 1) {
          this.allPts[this.allPts.length - 1] = { x: cur.b2.x, y: cur.b2.y }
          if (this.subIdx < this.subSegs.length - 1) {
            this.subIdx++
            this.t = 0
          } else {
            this.allPts[this.allPts.length - 1] = { x: NX[this.seg + 1], y: CY }
            this.paused = true
            this.pauseAge = 0
          }
        }
      }

      draw(time: number) {
        if (this.allPts.length < 2) return
        ctx.beginPath()
        ctx.moveTo(this.allPts[0].x, this.allPts[0].y)
        for (let i = 1; i < this.allPts.length; i++) ctx.lineTo(this.allPts[i].x, this.allPts[i].y)
        const fade  = this.dead ? 0.18 : 1
        const isGold = this.col === GOLD
        const pulse = isGold ? 0.8 + Math.sin(time * 2.5) * 0.2 : 1
        ctx.strokeStyle = `rgba(${this.col},${this.op * fade * pulse})`
        ctx.lineWidth   = this.lw
        ctx.stroke()
        if (this.dead || this.finished) return
        const tail = this.allPts[this.allPts.length - 1]
        if (this.paused) {
          const nodeX = NX[this.seg + 1]
          const pr    = this.pauseAge / this.pauseLen
          /* editorial pause ring — thin ink stroke */
          ctx.beginPath()
          ctx.arc(nodeX, CY, 5 + pr * 16, 0, Math.PI * 2)
          ctx.strokeStyle = `rgba(${this.col},${(1 - pr) * this.op * 0.55})`
          ctx.lineWidth = 0.6; ctx.stroke()
          ctx.beginPath()
          ctx.arc(nodeX, CY, 3 + pr * 8, 0, Math.PI * 2)
          ctx.strokeStyle = `rgba(${this.col},${(1 - pr) * this.op * 0.3})`
          ctx.lineWidth = 0.4; ctx.stroke()
          /* solid pause dot */
          ctx.beginPath(); ctx.arc(nodeX, CY, 3, 0, Math.PI * 2)
          ctx.fillStyle = `rgba(${this.col},${this.op * (0.6 + Math.sin(time * 8) * 0.4)})`
          ctx.fill()
        } else {
          ctx.beginPath(); ctx.arc(tail.x, tail.y, 2, 0, Math.PI * 2)
          ctx.fillStyle = `rgba(${this.col},${this.op * 0.85})`; ctx.fill()
        }
        /* gold finish — ink stamp effect */
        if (isGold && this.finished) {
          const ep = this.allPts[this.allPts.length - 1]
          ;[7, 14, 24].forEach((r, i) => {
            ctx.beginPath(); ctx.arc(ep.x, ep.y, r + Math.sin(time * 1.8 + i) * 0.5, 0, Math.PI * 2)
            ctx.strokeStyle = `rgba(${GOLD},${(0.4 - i * 0.11) * pulse})`
            ctx.lineWidth = 0.5; ctx.stroke()
          })
        }
      }
    }

    class PulseBack {
      p = 1.0; op = 1.0
      done()  { return this.p <= 0 }
      step()  { this.p = Math.max(0, this.p - 0.013); this.op *= 0.979 }
      draw()  {
        const x = PAD + this.p * (W - PAD * 2)
        ctx.beginPath(); ctx.arc(x, CY, 4, 0, Math.PI * 2)
        ctx.fillStyle = `rgba(${GOLD},${this.op * 0.85})`; ctx.fill()
        ;[10, 20, 34].forEach((r, i) => {
          ctx.beginPath(); ctx.arc(x, CY, r, 0, Math.PI * 2)
          ctx.strokeStyle = `rgba(${GOLD},${(0.45 - i * 0.12) * this.op})`
          ctx.lineWidth = 0.5; ctx.stroke()
        })
      }
    }
    let pulseBack: PulseBack | null = null

    let lines: Line[] = []
    let runAge = 0

    let sCnt = Math.floor(1000 + Math.random() * 8000)
    let sCntTarget = Math.floor(1 + Math.random() * 9999)
    let convT = parseFloat((8 + Math.random() * 22).toFixed(1))
    let riskT = Math.floor(25 + Math.random() * 55)
    let confT = Math.floor(30 + Math.random() * 58)
    let curConv = convT, curRisk = riskT, curConf = confT

    setStats({
      scenarios: Math.round(sCnt),
      conv: Math.min(99.9, Math.round(Math.min(99.9, curConv) * 10) / 10),
      risk: Math.min(99, Math.round(curRisk)),
      conf: Math.min(99, Math.round(curConf)),
    })

    const rollingStatsId = window.setInterval(() => {
      convT = parseFloat((5 + Math.random() * 28).toFixed(1))
      riskT = Math.floor(18 + Math.random() * 72)
      confT = Math.floor(25 + Math.random() * 68)
    }, 3200)

    function startRun() {
      lines.forEach(l => {
        if (l.allPts.length > 6) {
          ghosts.push({ pts: [...l.allPts], op: l.op * 0.06, col: l.col })
        }
      })
      while (ghosts.length > 200) ghosts.shift()
      const count = 1 + Math.floor(Math.random() * 5)
      lines = Array.from({ length: count }, () => new Line())
      runAge = 0
    }
    startRun()

    function drawNodes(time: number) {
      LABELS.forEach((label, i) => {
        const x = NX[i]
        /* hairline column — like a column rule in newspaper */
        ctx.beginPath(); ctx.moveTo(x, FY + 4); ctx.lineTo(x, FY + FH - 4)
        ctx.setLineDash([1, 7])
        ctx.strokeStyle = `rgba(${INK},0.08)`; ctx.lineWidth = 0.4
        ctx.stroke(); ctx.setLineDash([])
        /* baseline connector */
        if (i < N - 1) {
          ctx.beginPath(); ctx.moveTo(x, CY); ctx.lineTo(NX[i + 1], CY)
          ctx.strokeStyle = `rgba(${INK},0.08)`; ctx.lineWidth = 0.4; ctx.stroke()
        }
        /* outer halo — very faint ink */
        const hp = 0.35 + Math.sin(time * 1.2 + i * 0.85) * 0.25
        ctx.beginPath(); ctx.arc(x, CY, 6, 0, Math.PI * 2)
        ctx.strokeStyle = `rgba(${INK},${hp * 0.1})`; ctx.lineWidth = 0.5; ctx.stroke()
        /* node dot — solid ink */
        ctx.beginPath(); ctx.arc(x, CY, 3, 0, Math.PI * 2)
        ctx.fillStyle = `rgba(${INK},${0.4 + hp * 0.2})`; ctx.fill()
        /* editorial serif label */
        ctx.save()
        ctx.font = '600 7px system-ui,sans-serif'
        ctx.textAlign = 'center'
        ctx.fillStyle = `rgba(${INK},0.25)`
        ctx.fillText(label.toUpperCase(), x, FY + 13)
        ctx.restore()
      })
    }

    /* subtle horizontal ink wash lines — like aged paper grain */
    function drawPaperGrain(time: number) {
      ;[0.25, 0.5, 0.75].forEach((f, i) => {
        const y  = FY + f * FH
        const op = 0.025 + Math.sin(time * 0.15 + i * 1.2) * 0.012
        ctx.beginPath()
        for (let x = PAD; x <= W - PAD; x += 6) {
          const dy = Math.sin(x * 0.008 + time * 0.1 + i) * FH * 0.004
          x === PAD ? ctx.moveTo(x, y + dy) : ctx.lineTo(x, y + dy)
        }
        ctx.strokeStyle = `rgba(${INK},${op})`; ctx.lineWidth = 0.3; ctx.stroke()
      })
    }

    /* vignette in paper tone */
    function drawVig() {
      const makeH = (x0: number, x1: number, col: string) => {
        const g = ctx.createLinearGradient(x0, 0, x1, 0)
        g.addColorStop(0, col); g.addColorStop(1, 'rgba(242,236,224,0)'); return g
      }
      ctx.fillStyle = makeH(0, 80, PAPER);     ctx.fillRect(0, 0, 80, H)
      ctx.fillStyle = makeH(W, W - 80, PAPER); ctx.fillRect(W - 80, 0, 80, H)
      const tg = ctx.createLinearGradient(0, FY - 2, 0, FY + 24)
      tg.addColorStop(0, PAPER); tg.addColorStop(1, 'rgba(242,236,224,0)')
      ctx.fillStyle = tg; ctx.fillRect(0, 0, W, FY + 24)
      const bg = ctx.createLinearGradient(0, FY + FH - 20, 0, H - BY)
      bg.addColorStop(0, 'rgba(242,236,224,0)'); bg.addColorStop(1, PAPER)
      ctx.fillStyle = bg; ctx.fillRect(0, FY + FH - 20, W, H)
    }

    let time = 0, rafId = 0, statTimer = 0

    function frame() {
      ctx.clearRect(0, 0, W, H)
      /* paper background */
      ctx.fillStyle = PAPER; ctx.fillRect(0, 0, W, H)
      time += 0.016
      runAge++
      sCnt += (sCntTarget - sCnt) * 0.04
      if (Math.abs(sCntTarget - sCnt) < 50) {
        sCntTarget = Math.floor(1 + Math.random() * 9999)
      }
      statTimer++
      curConv += (convT - curConv) * 0.012
      curRisk += (riskT - curRisk) * 0.013
      curConf += (confT - curConf) * 0.011
      if (statTimer % 30 === 0) {
        setStats({
          scenarios: Math.round(sCnt),
          conv: Math.min(99.9, Math.round(Math.min(99.9, curConv) * 10) / 10),
          risk: Math.min(99, Math.round(curRisk)),
          conf: Math.min(99, Math.round(curConf)),
        })
      }

      drawPaperGrain(time)

      /* ghost traces — like faint pencil under-drawing */
      ghosts.forEach(g => {
        if (g.pts.length < 2) return
        ctx.beginPath(); ctx.moveTo(g.pts[0].x, g.pts[0].y)
        g.pts.forEach(p => ctx.lineTo(p.x, p.y))
        ctx.strokeStyle = `rgba(${g.col},${g.op})`
        ctx.lineWidth = 0.3; ctx.stroke()
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

      /* thin red scan line — editorial accent */
      const sy = FY + ((time * 5) % FH)
      ctx.fillStyle = `rgba(${RED},0.04)`
      ctx.fillRect(PAD, sy, W - PAD * 2, 0.6)

      const allDone = lines.every(l => l.finished || l.dead)
      if (allDone || runAge > 1400) {
        const winner = lines.find(l => l.col === GOLD && l.finished && !l.dead)
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

  /* editorial typography matching page */
  const labelStyle: CSSProperties = {
    fontSize: 9,
    letterSpacing: '0.14em',
    textTransform: 'uppercase',
    fontFamily: 'system-ui,sans-serif',
    color: 'rgba(26,23,20,0.35)',
    marginLeft: 3,
  }
  const valStyle: CSSProperties = {
    fontFamily: 'Georgia,serif',
    fontSize: 13,
    color: 'rgba(26,23,20,0.55)',
    letterSpacing: '-.01em',
    fontVariantNumeric: 'tabular-nums',
  }
  const sepStyle: CSSProperties = {
    width: 0.5,
    height: 10,
    background: 'rgba(26,23,20,0.15)',
    margin: '0 16px',
  }

  return (
    <div
      ref={wrapRef}
      style={{
        width: '100%', height: '130px',
        background: '#f2ece0',
        position: 'relative', overflow: 'hidden',
        borderTop:    '1px solid rgba(26,23,20,0.12)',
        borderBottom: '1px solid rgba(26,23,20,0.12)',
      }}
    >
      <canvas ref={cvRef} style={{ position: 'absolute', inset: 0 }} />

      {/* top editorial bar */}
      <div style={{
        position: 'absolute', top: 0, left: 0, right: 0, height: 28,
        display: 'flex', alignItems: 'center',
        justifyContent: 'space-between', padding: '0 20px',
        borderBottom: '0.5px solid rgba(26,23,20,0.08)',
        zIndex: 10, pointerEvents: 'none',
      }}>
        <span style={{
          fontFamily: 'Georgia,serif', fontStyle: 'italic',
          fontSize: 10, color: 'rgba(26,23,20,0.2)',
          letterSpacing: '.02em',
        }}>
          Simulation running
        </span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <div style={{ width: 14, height: 0.5, background: 'rgba(192,57,43,0.4)' }} />
          <div style={{ width: 4, height: 4, borderRadius: '50%', background: '#c0392b', opacity: 0.7 }} />
          <span style={{
            fontSize: 7, color: 'rgba(192,57,43,0.55)',
            letterSpacing: '0.22em', textTransform: 'uppercase',
            fontFamily: 'system-ui,sans-serif',
          }}>
            Live timeline
          </span>
          <div style={{ width: 14, height: 0.5, background: 'rgba(192,57,43,0.4)' }} />
        </div>
        <span style={{
          fontFamily: 'Georgia,serif', fontStyle: 'italic',
          fontSize: 10, color: 'rgba(26,23,20,0.2)',
        }}>
          TheCee
        </span>
      </div>

      {/* bottom stats — editorial serif */}
      <div style={{
        position: 'absolute', bottom: 0, left: 0, right: 0, height: 28,
        display: 'flex', alignItems: 'center',
        padding: '0 20px',
        borderTop: '0.5px solid rgba(26,23,20,0.08)',
        zIndex: 10, pointerEvents: 'none',
        background: 'rgba(242,236,224,0.7)',
      }}>
        <span style={valStyle}>{stats.scenarios.toLocaleString()}</span>
        <span style={labelStyle}>scenarios</span>
        <div style={sepStyle} />
        <span style={valStyle}>{stats.conv}%</span>
        <span style={labelStyle}>conversion</span>
        <div style={sepStyle} />
        <span style={valStyle}>{stats.risk}</span>
        <span style={labelStyle}>risk</span>
        <div style={sepStyle} />
        <span style={valStyle}>{stats.conf}%</span>
        <span style={labelStyle}>confidence</span>
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 10 }}>
          {/* legend */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <div style={{ width: 16, height: 1, background: 'rgba(26,23,20,0.4)' }} />
            <span style={{ ...labelStyle, marginLeft: 0 }}>Surviving</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <div style={{ width: 16, height: 1, background: 'rgba(192,57,43,0.6)' }} />
            <span style={{ ...labelStyle, marginLeft: 0 }}>Failing</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <div style={{ width: 16, height: 1, background: 'rgba(160,100,40,0.8)' }} />
            <span style={{ ...labelStyle, marginLeft: 0 }}>Winner</span>
          </div>
        </div>
      </div>
    </div>
  )
}
