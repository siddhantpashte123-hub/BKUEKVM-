import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, Maximize2, Power, RefreshCw, Square } from 'lucide-react'
import { api, ApiError, wsUrl } from '../lib/api'
import type { VPS } from '../lib/types'
import { Badge, Button } from '../components/ui'

type ConnState = 'requesting' | 'connecting' | 'connected' | 'disconnected' | 'error'

export default function VpsConsole() {
  const { id } = useParams()
  const screenRef = useRef<HTMLDivElement>(null)
  // Lazy-loaded noVNC client kept as an opaque handle (see dynamic import below)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const rfbRef = useRef<any>(null)
  const [vps, setVps] = useState<VPS | null>(null)
  const [state, setState] = useState<ConnState>('requesting')
  const [detail, setDetail] = useState('')

  const connect = useCallback(async () => {
    setState('connecting')
    setDetail('')
    try {
      const session = await api.post<{ ws_path: string; expires_at: string }>(`/api/vps/${id}/console-session`)
      if (!screenRef.current) return
      const { default: RFB } = await import('@novnc/novnc')
      const rfb = new RFB(screenRef.current, wsUrl(session.ws_path), {
        wsProtocols: ['binary'],
        shared: false,
      })
      rfb.background = '#000000'
      rfb.focusOnClick = true
      rfb.scaleViewport = true
      rfb.resizeSession = true
      rfb.addEventListener('connect', () => setState('connected'))
      rfb.addEventListener('disconnect', (event: Event) => {
        const clean = (event as CustomEvent<{ clean?: boolean }>).detail?.clean
        setState(clean ? 'disconnected' : 'error')
        setDetail(clean ? 'Console session ended' : 'Connection closed by the hypervisor or proxy')
      })
      rfb.addEventListener('credentialsrequired', () => {
        setState('error')
        setDetail('Console unexpectedly requested credentials — check the node configuration')
      })
      rfbRef.current = rfb
    } catch (err) {
      setState('error')
      setDetail(err instanceof ApiError ? err.message : 'Could not open a console session')
    }
  }, [id])

  useEffect(() => {
    api
      .get<VPS>(`/api/vps/${id}`)
      .then(setVps)
      .catch((err) => setDetail(err instanceof ApiError ? err.message : 'VPS not found'))
    connect()
    return () => {
      rfbRef.current?.disconnect()
      rfbRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id])

  const fullscreen = () => {
    screenRef.current?.requestFullscreen?.()
  }

  const sendKey = (kind: 'cad' | 'shutdown' | 'reboot' | 'reset') => {
    const rfb = rfbRef.current
    if (!rfb) return
    if (kind === 'cad') rfb.sendCtrlAltDel()
    if (kind === 'shutdown') rfb.machineShutdown()
    if (kind === 'reboot') rfb.machineReboot()
    if (kind === 'reset') rfb.machineReset()
  }

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
          <h1 className="text-2xl font-bold text-white">{vps?.name ?? 'VPS'} — Console</h1>
          <div className="mt-1 flex items-center gap-2">
            <Badge value={stateBadge[state]} />
            {vps && <Badge value={vps.status} />}
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" onClick={connect} loading={state === 'connecting'}>
            <RefreshCw className="h-4 w-4" /> Reconnect
          </Button>
          <Button variant="secondary" onClick={fullscreen}>
            <Maximize2 className="h-4 w-4" /> Fullscreen
          </Button>
        </div>
      </div>

      <div className="card-base overflow-hidden">
        <div className="flex flex-wrap items-center gap-2 border-b border-line bg-panel px-4 py-2.5">
          <span className="mr-2 text-xs font-semibold uppercase tracking-wider text-muted">Power keys</span>
          <ConsoleKey onClick={() => sendKey('cad')} label="Ctrl+Alt+Del" />
          <ConsoleKey onClick={() => sendKey('shutdown')} label="ACPI Shutdown" icon={<Power className="h-3.5 w-3.5" />} />
          <ConsoleKey onClick={() => sendKey('reboot')} label="Reboot" icon={<RefreshCw className="h-3.5 w-3.5" />} />
          <ConsoleKey onClick={() => sendKey('reset')} label="Hard Reset" danger icon={<Square className="h-3.5 w-3.5" />} />
        </div>

        <div className="relative h-[70vh] min-h-[420px] w-full bg-black">
          <div ref={screenRef} className="h-full w-full" />

          {state !== 'connected' && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-black/85 p-6 text-center">
              <div className="max-w-lg">
                <p className="text-lg font-semibold text-white">
                  {state === 'connecting' && 'Establishing secure console tunnel…'}
                  {state === 'requesting' && 'Requesting short-lived console token…'}
                  {state === 'disconnected' && 'Console disconnected'}
                  {state === 'error' && 'Console unavailable'}
                </p>
                {detail && <p className="mt-2 text-sm text-muted">{detail}</p>}
                {state === 'error' && (
                  <p className="mt-3 text-xs text-muted">
                    Common causes: the VM is stopped, no VNC graphics device is configured, or the node's VNC socket is
                    unreachable. Start the VPS and reconnect.
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
        Console tokens expire in 60 seconds and are single-use. Traffic is bridged server-side — no VNC port is exposed
        publicly.
      </p>
    </div>
  )
}

function ConsoleKey({ onClick, label, icon, danger }: { onClick: () => void; label: string; icon?: React.ReactNode; danger?: boolean }) {
  return (
    <button
      onClick={onClick}
      className={`inline-flex items-center gap-1.5 rounded-md border border-line bg-input px-2.5 py-1.5 text-xs font-medium transition hover:border-electric/60 hover:text-electric ${
        danger ? 'hover:border-danger/60 hover:text-danger' : ''
      }`}
    >
      {icon}
      {label}
    </button>
  )
}
