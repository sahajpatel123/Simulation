/*
  WebSocket client for simulation progress.
  Handles reconnection with exponential backoff.
  Uses wss:// in production, ws:// in development.
*/

const WS_BASE = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1')
  .replace('https://', 'wss://')
  .replace('http://',  'ws://')

export function createSimulationSocket(
  simulationId: number,
  token:        string,
  handlers: {
    onProgress: (data: SimulationProgressEvent) => void
    onComplete: (data: SimulationCompleteEvent) => void
    onError:    (msg: string) => void
  },
): () => void {
  let ws:          WebSocket | null = null
  let retries      = 0
  let destroyed    = false
  const MAX_RETRY  = 5

  function connect() {
    if (destroyed) return
    const url = `${WS_BASE}/ws/simulation/${simulationId}`
    ws        = new WebSocket(url)

    ws.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data)
        if (data.type === 'progress') handlers.onProgress(data)
        if (data.type === 'pong')     return
        if (data.status === 'COMPLETED') handlers.onComplete(data)
        if (data.status === 'FAILED')    handlers.onError(data.error || 'Simulation failed')
      } catch { /* ignore malformed messages */ }
    }

    ws.onopen  = () => {
      retries = 0
      ws?.send(JSON.stringify({ type: 'auth', access_token: token }))
      ws?.send('ping')
    }

    ws.onclose = (e) => {
      if (destroyed) return
      if (e.code === 4001) { handlers.onError('Unauthenticated'); return }
      if (e.code === 4003) { handlers.onError('Unauthorized');    return }
      if (retries < MAX_RETRY) {
        const delay = Math.min(1000 * 2 ** retries, 16000)
        retries++
        setTimeout(connect, delay)
      }
    }

    ws.onerror = () => handlers.onError('WebSocket connection failed')
  }

  connect()

  /* Return a cleanup function */
  return () => {
    destroyed = true
    ws?.close()
  }
}

export interface SimulationProgressEvent {
  type:             'progress'
  simulation_id:    number
  status:           string
  stage:            string
  pct:              number
  agents_processed: number
  agents_total:     number
  ts:               string
}

export interface SimulationCompleteEvent {
  type:            string
  simulation_id:   number
  status:          'COMPLETED'
  conversion_rate: number
}
