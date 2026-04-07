'use client'

import { useEffect, useRef } from 'react'

export default function SimulationTimeline() {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const wrapRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const wrap = wrapRef.current
    const cv = canvasRef.current
    if (!cv || !wrap) return

    const DPR = Math.min(window.devicePixelRatio || 1, 2)
    const W = wrap.offsetWidth
    const H = wrap.offsetHeight
    cv.width = W * DPR
    cv.height = H * DPR
    cv.style.width = W + 'px'
    cv.style.height = H + 'px'
    const ctx = cv.getContext('2d')!
    ctx.scale(DPR, DPR)

    const FY = 26, FB = 24, FH = H - FY - FB
    const CY = FY + FH / 2
    const PAD = 44
    const NODES = ['Idea','Assume','Market','Pricing','Build','Launch','Retain','Scale']
    const NC = NODES.length
    const NX = NODES.map((_, i) => PAD + (i / (NC - 1)) * (W - PAD * 2))

    interface Pt { x: number; y: number }

    class Particle {
      x: number; y: number; vx: number; vy: number
      gravity: number; op: number; col: string; r: number; dead = false
      constructor(x: number, y: number, col: string) {
        this.x = x; this.y = y
        const a = Math.random() * Math.PI * 2
        const spd = 1 + Math.random() * 3
        this.vx = Math.cos(a) * spd; this.vy = Math.sin(a) * spd - 1.5
        this.gravity = 0.08 + Math.random() * .06
        this.op = 0.8 + Math.random() * .2; this.col = col
        this.r = 0.8 + Math.random() * 1.2
      }
      update() { this.x += this.vx; this.vy += this.gravity; this.y += this.vy; this.op *= .91; if (this.op < .02) this.dead = true }
      draw() { ctx.beginPath(); ctx.arc(this.x, this.y, this.r, 0, Math.PI * 2); ctx.fillStyle = `rgba(${this.col},${this.op})`; ctx.fill() }
    }
    const particles: Particle[] = []

    class Flash {
      x: number; y: number; age = 0; maxAge = 22
      constructor(x: number, y: number) { this.x = x; this.y = y }
      isDead() { return this.age >= this.maxAge }
      draw() {
        this.age++
        const p = this.age / this.maxAge
        ctx.beginPath(); ctx.arc(this.x, this.y, p * 8, 0, Math.PI * 2)
        ctx.strokeStyle = `rgba(242,236,224,${(1-p)*.5})`; ctx.lineWidth = .5; ctx.stroke()
      }
    }
    const flashes: Flash[] = []

    function crossX(a: Pt, b: Pt, c: Pt, d: Pt): Pt | null {
      const rx = b.x-a.x, ry = b.y-a.y, sx = d.x-c.x, sy = d.y-c.y
      const den = rx*sy - ry*sx
      if (Math.abs(den) < .001) return null
      const t = ((c.x-a.x)*sy - (c.y-a.y)*sx) / den
      const u = ((c.x-a.x)*ry - (c.y-a.y)*rx) / den
      if (t >= 0 && t <= 1 && u >= 0 && u <= 1) return { x: a.x + t*rx, y: a.y + t*ry }
      return null
    }

    class Branch {
      depth: number; isGold: boolean; op: number; col: string; lw: number
      dead = false; drawnPts: Pt[] = []; children: Branch[] = []

      hasGoldWinner(): boolean {
        if (this.isGold && !this.dead && this.currentNode >= NC - 1) return true
        return this.children.some(c => c.hasGoldWinner())
      }

      isFullyComplete(): boolean {
        if (!this.segDone && !this.dead) return false
        return this.children.every(c => c.isFullyComplete())
      }

      collectAll(arr: Branch[]) { arr.push(this); this.children.forEach(c => c.collectAll(arr)) }

      /* segment state */
      currentNode: number
      segProgress = 0
      segSpeed: number
      pauseTimer = 0
      pauseDuration: number
      pausing = false
      segDone = false
      waypts: Pt[]
      segStart: Pt
      diePr: number

      constructor(startX: number, startY: number, parentOp: number, depth: number, isGold?: boolean) {
        this.depth = depth
        this.isGold = isGold || Math.random() < (.12 - depth * .03)
        this.op = (parentOp || 0.85) * (0.55 + Math.random() * .35)
        this.col = this.isGold ? '210,170,70' : depth === 0 ? '215,205,190' : depth === 1 ? '160,130,100' : '110,90,75'
        this.lw = depth === 0 ? 1.1 : depth === 1 ? .65 : .35
        this.diePr = .32 + depth * .12
        this.segSpeed = 0.018 + Math.random() * .012
        this.pauseDuration = 18 + Math.floor(Math.random() * 22)
        this.currentNode = 1
        this.segStart = { x: startX, y: startY }
        this.waypts = this.buildSegWaypts(startX, startY, 1)
        this.drawnPts = [{ x: startX, y: startY }]
      }

      buildSegWaypts(fromX: number, fromY: number, toNodeIdx: number): Pt[] {
        const toX = NX[toNodeIdx]
        const deviation = (Math.random() - .5) * FH * .9
        const midX = fromX + (toX - fromX) * (.35 + Math.random() * .3)
        const midY = Math.max(FY + 8, Math.min(FY + FH - 8, CY + deviation))
        const endY = Math.max(FY + 8, Math.min(FY + FH - 8, CY + (Math.random() - .5) * FH * .5))
        return [
          { x: fromX, y: fromY },
          { x: midX, y: midY },
          { x: toX, y: endY },
        ]
      }

      getSegPos(t: number): Pt {
        const [p0, p1, p2] = this.waypts
        const mt = 1 - t
        return {
          x: mt * mt * p0.x + 2 * mt * t * p1.x + t * t * p2.x,
          y: mt * mt * p0.y + 2 * mt * t * p1.y + t * t * p2.y,
        }
      }

      update() {
        if (this.dead || this.segDone) return

        if (this.pausing) {
          this.pauseTimer++
          if (this.pauseTimer >= this.pauseDuration) {
            this.pausing = false
            this.pauseTimer = 0
            if (Math.random() < this.diePr) {
              this.dead = true
              const pos = this.waypts[2]
              const pcol = this.isGold ? this.col : '192,57,43'
              for (let i = 0; i < (this.depth === 0 ? 12 : 6); i++) {
                particles.push(new Particle(pos.x, pos.y, pcol))
              }
              return
            }
            if (this.currentNode >= NC - 1) {
              this.segDone = true
              return
            }
            const prevEnd = this.waypts[2]
            this.currentNode++
            this.segProgress = 0
            this.pauseDuration = 14 + Math.floor(Math.random() * 24)
            this.waypts = this.buildSegWaypts(prevEnd.x, prevEnd.y, this.currentNode)
          }
          return
        }

        this.segProgress = Math.min(1, this.segProgress + this.segSpeed)
        const pos = this.getSegPos(this.segProgress)
        this.drawnPts.push({ x: pos.x, y: pos.y })
        if (this.drawnPts.length > 200) this.drawnPts.shift()

        if (this.segProgress >= 1) {
          this.pausing = true
          this.pauseTimer = 0
          flashes.push(new Flash(this.waypts[2].x, this.waypts[2].y))
        }

        this.children.forEach(ch => ch.update())
      }

      checkCrossings(others: Branch[]) {
        if (this.dead || this.drawnPts.length < 2) return
        const myL = this.drawnPts[this.drawnPts.length - 1]
        const myP = this.drawnPts[this.drawnPts.length - 2]
        others.forEach(o => {
          if (o === this || o.dead || o.drawnPts.length < 2) return
          const ol = o.drawnPts[o.drawnPts.length - 1]
          const op2 = o.drawnPts[o.drawnPts.length - 2]
          const fx = crossX(myP, myL, op2, ol)
          if (fx && Math.random() < .25) flashes.push(new Flash(fx.x, fx.y))
        })
        this.children.forEach(ch => ch.checkCrossings(others))
      }

      draw(time: number) {
        if (this.drawnPts.length < 2) return

        ctx.beginPath()
        ctx.moveTo(this.drawnPts[0].x, this.drawnPts[0].y)
        for (let i = 1; i < this.drawnPts.length; i++) ctx.lineTo(this.drawnPts[i].x, this.drawnPts[i].y)
        const fade = this.dead ? .28 : 1
        const pulse = this.isGold ? (.7 + Math.sin(time * 3 + this.depth) * .3) : 1
        ctx.strokeStyle = `rgba(${this.col},${this.op * fade * pulse})`
        ctx.lineWidth = this.lw; ctx.stroke()

        if (!this.dead && this.drawnPts.length > 0) {
          const last = this.drawnPts[this.drawnPts.length - 1]
          const dotPulse = this.pausing
            ? (.5 + Math.sin(time * 8) * .5)
            : (.6 + Math.sin(time * 4) * .4)
          const dotR = this.pausing ? 3 + Math.sin(time * 8) * 1.5 : 1.5
          ctx.beginPath(); ctx.arc(last.x, last.y, dotR, 0, Math.PI * 2)
          ctx.fillStyle = `rgba(${this.isGold ? '230,190,80' : this.col},${this.op * dotPulse})`
          ctx.fill()
          if (this.pausing) {
            const ringOp = (1 - this.pauseTimer / this.pauseDuration) * .5
            ctx.beginPath(); ctx.arc(last.x, last.y, 6 + (this.pauseTimer / this.pauseDuration) * 8, 0, Math.PI * 2)
            ctx.strokeStyle = `rgba(${this.isGold ? '230,190,80' : this.col},${ringOp})`
            ctx.lineWidth = .6; ctx.stroke()
          }
        }

        if (this.isGold && this.segDone) {
          const ep = this.drawnPts[this.drawnPts.length - 1];
          [8, 16, 28].forEach((r: number, i: number) => {
            ctx.beginPath(); ctx.arc(ep.x, ep.y, r + Math.sin(time * 2 + i) * .5, 0, Math.PI * 2)
            ctx.strokeStyle = `rgba(230,190,80,${(.3 - i * .08) * pulse})`; ctx.lineWidth = .5; ctx.stroke()
          })
        }

        this.children.forEach(ch => ch.draw(time))
      }
    }

    class PulseBack {
      p = 1; op = 1; y: number
      constructor(y: number) { this.y = y }
      isDead() { return this.p <= 0 }
      update() { this.p = Math.max(0, this.p - .018); this.op *= .977 }
      draw() {
        const x = PAD + this.p * (W - PAD * 2)
        ctx.beginPath(); ctx.arc(x, this.y, 4, 0, Math.PI * 2)
        ctx.fillStyle = `rgba(230,190,80,${this.op * .9})`; ctx.fill();
        [10, 22, 38].forEach((r, i) => {
          ctx.beginPath(); ctx.arc(x, this.y, r, 0, Math.PI * 2)
          ctx.strokeStyle = `rgba(230,190,80,${(.5 - i * .12) * this.op})`; ctx.lineWidth = .6; ctx.stroke()
        })
      }
    }
    let pulseBack: PulseBack | null = null

    const ghostHistory: { pts: Pt[]; col: string; op: number; lw: number; isGold: boolean }[] = []
    function saveGhosts(branches: Branch[]) {
      branches.forEach(b => {
        if (b.drawnPts.length > 2) ghostHistory.push({ pts: [...b.drawnPts], col: b.col, op: b.op * (b.isGold ? .09 : .04), lw: b.lw * .6, isGold: b.isGold })
      })
      while (ghostHistory.length > 300) ghostHistory.shift()
    }

    let roots: Branch[] = []
    let runAge = 0, runCount = 0

    function startRun() {
      if (roots.length > 0) {
        const all: Branch[] = []
        roots.forEach(r => r.collectAll(all))
        saveGhosts(all)
      }
      roots = []; runAge = 0
      const n = 2 + Math.floor(Math.random() * 3)
      for (let i = 0; i < n; i++) {
        roots.push(new Branch(PAD, CY + (Math.random() - .5) * FH * .3, 0.9, 0))
      }
      runCount++
    }
    startRun()

    function drawNodes(t: number) {
      NODES.forEach((label, i) => {
        const x = NX[i]
        ctx.beginPath(); ctx.moveTo(x, FY + 6); ctx.lineTo(x, FY + FH - 6)
        ctx.setLineDash([1, 8]); ctx.strokeStyle = 'rgba(242,236,224,.04)'; ctx.lineWidth = .4; ctx.stroke(); ctx.setLineDash([])
        const pulse = .4 + Math.sin(t * 1.2 + i * .9) * .3
        ctx.beginPath(); ctx.arc(x, CY, 2, 0, Math.PI * 2)
        ctx.fillStyle = `rgba(242,236,224,${.2 + pulse * .1})`; ctx.fill()
        ctx.save(); ctx.font = '7px system-ui,sans-serif'; ctx.textAlign = 'center'
        ctx.fillStyle = 'rgba(242,236,224,.13)'; ctx.fillText(label.toUpperCase(), x, FY + 11); ctx.restore()
        if (i < NC - 1) { ctx.beginPath(); ctx.moveTo(x, CY); ctx.lineTo(NX[i+1], CY); ctx.strokeStyle = 'rgba(242,236,224,.03)'; ctx.lineWidth = .4; ctx.stroke() }
      })
    }

    function drawAtmo(t: number) {
      [.25, .5, .75].forEach((f, i) => {
        const y = FY + f * FH
        const op = .018 + Math.sin(t * .25 + i * 1.1) * .012
        ctx.beginPath()
        for (let x = PAD; x <= W - PAD; x += 4) {
          const dy = Math.sin(x * .009 + t * .18 + i) * .008
          x === PAD ? ctx.moveTo(x, y + dy * FH) : ctx.lineTo(x, y + dy * FH)
        }
        ctx.strokeStyle = `rgba(212,160,80,${op})`; ctx.lineWidth = .4; ctx.stroke()
      })
    }

    function drawVig() {
      const lv = ctx.createLinearGradient(0, 0, 70, 0); lv.addColorStop(0, '#060408'); lv.addColorStop(1, 'rgba(6,4,8,0)'); ctx.fillStyle = lv; ctx.fillRect(0, 0, 70, H)
      const rv = ctx.createLinearGradient(W-70, 0, W, 0); rv.addColorStop(0, 'rgba(6,4,8,0)'); rv.addColorStop(1, '#060408'); ctx.fillStyle = rv; ctx.fillRect(W-70, 0, 70, H)
      const tv = ctx.createLinearGradient(0, FY-2, 0, FY+18); tv.addColorStop(0, '#060408'); tv.addColorStop(1, 'rgba(6,4,8,0)'); ctx.fillStyle = tv; ctx.fillRect(0, 0, W, FY+18)
      const bv = ctx.createLinearGradient(0, FY+FH-18, 0, H); bv.addColorStop(0, 'rgba(6,4,8,0)'); bv.addColorStop(1, '#060408'); ctx.fillStyle = bv; ctx.fillRect(0, FY+FH-18, W, H)
    }

    let t = 0
    let rafId: number
    function frame() {
      ctx.clearRect(0, 0, W, H)
      ctx.fillStyle = '#060408'; ctx.fillRect(0, 0, W, H)
      t += .016; runAge++

      drawAtmo(t)

      ghostHistory.forEach(g => {
        if (g.pts.length < 2) return
        ctx.beginPath(); ctx.moveTo(g.pts[0].x, g.pts[0].y)
        g.pts.forEach(p => ctx.lineTo(p.x, p.y))
        ctx.strokeStyle = `rgba(${g.col},${g.op * (g.isGold ? 1.8 : 1)})`; ctx.lineWidth = g.lw; ctx.stroke()
      })

      drawNodes(t)

      const allBranches: Branch[] = []
      roots.forEach(r => r.collectAll(allBranches))
      roots.forEach(r => r.update())
      if (Math.floor(t * 60) % 3 === 0) {
        const alive = allBranches.filter(b => !b.dead && b.drawnPts.length > 1)
        alive.forEach(b => b.checkCrossings(alive))
      }
      roots.forEach(r => r.draw(t))

      for (let i = flashes.length - 1; i >= 0; i--) { flashes[i].draw(); if (flashes[i].isDead()) flashes.splice(i, 1) }
      for (let i = particles.length - 1; i >= 0; i--) { particles[i].update(); particles[i].draw(); if (particles[i].dead) particles.splice(i, 1) }
      if (pulseBack) { pulseBack.update(); pulseBack.draw(); if (pulseBack.isDead()) pulseBack = null }

      drawVig()

      ctx.fillStyle = 'rgba(212,140,60,.012)'
      ctx.fillRect(PAD, FY + ((t * 7) % FH), W - PAD * 2, .7)

      ctx.save(); ctx.font = '7px system-ui,sans-serif'; ctx.textAlign = 'right'
      ctx.fillStyle = 'rgba(242,236,224,.06)'; ctx.fillText(`run #${runCount}`, W - PAD - 4, FY + 13); ctx.restore()

      const allDone = roots.length > 0 && roots.every(r => r.isFullyComplete())
      if (allDone || runAge > 900) {
        const won = roots.some(r => r.hasGoldWinner())
        if (won && !pulseBack) {
          let gy = CY
          function findGold(b: Branch): boolean {
            if (b.isGold && b.segDone && !b.dead && b.drawnPts.length > 0) { gy = b.drawnPts[b.drawnPts.length - 1].y; return true }
            return b.children.some(findGold)
          }
          roots.some(findGold)
          pulseBack = new PulseBack(gy)
        }
        setTimeout(startRun, won ? 1400 : 500)
      }

      rafId = requestAnimationFrame(frame)
    }
    frame()

    return () => { cancelAnimationFrame(rafId) }
  }, [])

  return (
    <div
      ref={wrapRef}
      style={{
        width: '100%',
        height: '120px',
        background: '#060408',
        position: 'relative',
        overflow: 'hidden',
        borderTop: '0.5px solid rgba(26,23,20,0.4)',
        borderBottom: '0.5px solid rgba(26,23,20,0.4)',
      }}
    >
      <canvas ref={canvasRef} style={{ position: 'absolute', inset: 0 }} />

      {/* Top label row */}
      <div style={{
        position: 'absolute', top: 0, left: 0, right: 0, height: '26px',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '0 18px', borderBottom: '0.5px solid rgba(255,255,255,.025)',
        zIndex: 20, pointerEvents: 'none',
      }}>
        <span style={{ fontFamily: 'Georgia,serif', fontStyle: 'italic', fontSize: '10px', color: 'rgba(242,236,224,.1)' }}>TheCee</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <div style={{ width: '16px', height: '.5px', background: 'rgba(212,140,80,.4)' }} />
          <div style={{ width: '4px', height: '4px', borderRadius: '50%', background: '#d48c50' }} />
          <span style={{ fontSize: '7px', color: 'rgba(212,140,80,.45)', letterSpacing: '.2em', textTransform: 'uppercase', fontFamily: 'system-ui,sans-serif' }}>Timeline running</span>
          <div style={{ width: '16px', height: '.5px', background: 'rgba(212,140,80,.4)' }} />
        </div>
        <span style={{ fontFamily: '"Courier New",monospace', fontSize: '9px', color: 'rgba(242,236,224,.12)', letterSpacing: '.04em' }}>Simulation Engine</span>
      </div>
    </div>
  )
}
