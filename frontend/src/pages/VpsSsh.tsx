import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, RefreshCw, SquareTerminal } from 'lucide-react'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'
import { api, ApiError, wsUrl } from '../lib/api'
import type { VPS } from '../lib/types'
import { Badge, Button } from '../components/ui'

type ConnState = 'requesting' | 'connecting' | 'connected' | 'disconnected' | 'error'

/**
 * Browser SSH terminal. Opens in its own tab and bridges an xterm.js
 * terminal over the authenticated /ws/ssh WebSocket — the panel holds the
 * VM credential server-side, the browser never sees the password.
 */
export default function VpsSsh() {
  const { id } = useParams()
  const hostRef = useRef<HTMLDivElement>(null)
  const termRef = useRef<Terminal | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const [vps, setVps] = useState<VPS | null>(null)
  const [state, setState] = useState<ConnState>('requesting')
  const [detail, setDetail] = useState('')

  const connect = useCallback(async () => {
    setState('connecting')
    setDetail('')
    try {
      const session = await api.post<{ ws_path: string; expires_at: string }>(`/api/vps/${id}/ssh-session`)

      const term = new Terminal({
        fontFamily: 'Inter, ui-monospace, Menlo, monospace',
        fontSize: 13,
        cursorBlink: true,
        theme: { background: '#000000', foreground: '#e5e7eb', cursor: '#3b82f6' },
      })
      const fit = new FitAddon()
      term.loadAddon(fit)
      term.open(hostRef.current!)
      fit.fit()
      termRef.current = term

      const ws = new WebSocket(wsUrl(session.ws_path))
      wsRef.current = ws

      ws.onopen = () => {
        setState('connected')
        term.focus()
        ws.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }))
      }
      ws.onmessage = (event) => term.write(typeof event.data === 'string' ? event.data : event.data)
      ws.onerror = () => {
        setState('error')
        setDetail('SSH tunnel error — the guest may still be booting or unreachable.')
      }
      ws.onclose = (event) => {
        const reason = event.reason || 'SSH session ended'
        setState(event.code === 1000 || event.code === 1001 ? 'disconnected' : 'error')
        setDetail(reason)
        term.write(`\r\n\x1b[33m${reason}\x1b[0m\r\n`)
      }

      term.onData((data) => ws.readyState === WebSocket.OPEN && ws.send(data))

      const resize = () => {
        fit.fit()
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }))
        }
      }
      window.addEventListener('resize', resize)
      ws.addEventListener('close', () => window.removeEventListener('resize', resize))
    } catch (err) {
      setState('error')
      setDetail(err instanceof ApiError ? err.message : 'Could not open an SSH session')
    }
  }, [id])

  useEffect(() => {
    api
      .get<VPS>(`/api/vps/${id}`)
      .then(setVps)
      .catch((err) => setDetail(err instanceof ApiError ? err.message : 'VPS not found'))
    connect()
    return () => {
      wsRef.current?.close()
      termRef.current?.dispose()
      termRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id])

  const stateBadge: Record<ConnState, string> = {
    requesting: 'provisioning',
    connecting: 'provisioning',
    connected: 'running',
    disconnected: 'stopped',
    error: 'error',
  }

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div>
          <Link to={`/vps/${id}`} className="mb-2 inline-flex items-center gap-1.5 text-sm text-muted hover:text-electric">
            <ArrowLeft className="h-4 w-4" /> Back to VPS
          </Link>
          <h1 className="flex items-center gap-2 text-2xl font-bold text-white">
            <SquareTerminal className="h-6 w-6 text-electric" />
            {vps?.name ?? 'VPS'} — SSH
          </h1>
          <div className="mt-1 flex items-center gap-2">
            <Badge value={stateBadge[state]} />
            {vps && <Badge value={vps.status} />}
            {vps?.ip_address && <span className="text-xs text-muted">{vps.cloud_init_user ?? 'ubuntu'}@{vps.ip_address}</span>}
          </div>
        </div>
        <Button variant="secondary" onClick={connect} loading={state === 'connecting'}>
          <RefreshCw className="h-4 w-4" /> Reconnect
        </Button>
      </div>

      <div className="card-base overflow-hidden">
        <div className="flex items-center gap-2 border-b border-line bg-panel px-4 py-2.5">
          <span className="h-3 w-3 rounded-full bg-danger/80" />
          <span className="h-3 w-3 rounded-full bg-yellow-500/80" />
          <span className="h-3 w-3 rounded-full bg-success/80" />
          <span className="ml-2 text-xs uppercase tracking-wider text-muted">
            secure ssh session · single-use token
          </span>
        </div>

        <div className="relative h-[75vh] min-h-[460px] w-full bg-black">
          <div ref={hostRef} className="h-full w-full p-2" />

          {state !== 'connected' && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-black/85 p-6 text-center">
              <div className="max-w-lg">
                <p className="text-lg font-semibold text-white">
                  {state === 'connecting' && 'Establishing SSH tunnel…'}
                  {state === 'requesting' && 'Requesting short-lived SSH token…'}
                  {state === 'disconnected' && 'SSH session disconnected'}
                  {state === 'error' && 'SSH unavailable'}
                </p>
                {detail && <p className="mt-2 text-sm text-muted">{detail}</p>}
                {state === 'error' && (
                  <p className="mt-3 text-xs text-muted">
                    Common causes: the VPS is stopped, still acquiring a DHCP lease, or qemu-guest-agent has not
                    reported an address yet. Start the VPS and retry.
                  </p>
                )}
                <div className="mt-5">
                  <Button onClick={connect} loading={state === 'connecting'}>
                    <RefreshCw className="h-4 w-4" /> Connect again
                  </Button>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      <p className="mt-3 text-xs text-muted">
        Tokens expire in 60 seconds and are single-use. The VM credential stays encrypted on the panel server — the
        browser only sees the terminal stream, never the password.
      </p>
    </div>
  )
}
