/** Live notification socket — /ws/notifications/ with JWT in the query string.
 *
 * Reconnects with capped exponential backoff; each attempt re-reads the latest
 * access token so a background refresh heals rejected sockets. Client → server
 * traffic is unused; the server pushes {type:'notification', kind, title, ...}.
 */
import { getAccessToken, hasSession } from './api'

export interface LiveNotification {
  type: 'notification'
  kind: string
  title: string
  payload: Record<string, unknown>
  created_at: string
}

let socket: WebSocket | null = null
let started = false
let attempt = 0
let generation = 0
let listener: ((n: LiveNotification) => void) | null = null

function wsUrl(): string {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  const token = getAccessToken()
  return `${proto}://${location.host}/ws/notifications/?token=${encodeURIComponent(token ?? '')}`
}

function scheduleReconnect(): void {
  const gen = generation
  attempt = Math.min(attempt + 1, 6)
  const delay = Math.min(15000, 500 * 2 ** attempt)
  setTimeout(() => {
    if (gen === generation) start()
  }, delay)
}

function start(): void {
  if (started || !hasSession()) return
  started = true
  try {
    socket = new WebSocket(wsUrl())
  } catch {
    started = false
    scheduleReconnect()
    return
  }
  socket.onopen = () => {
    attempt = 0
  }
  socket.onmessage = (ev) => {
    try {
      const data = JSON.parse(ev.data) as LiveNotification
      if (data.type === 'notification') listener?.(data)
    } catch {
      /* non-JSON frame — ignore */
    }
  }
  socket.onclose = () => {
    started = false
    socket = null
    scheduleReconnect()
  }
  socket.onerror = () => {
    socket?.close()
  }
}

export function startNotifications(onNotify: (n: LiveNotification) => void): void {
  listener = onNotify
  start()
}

export function stopNotifications(): void {
  generation += 1
  started = false
  listener = null
  socket?.close()
  socket = null
}
