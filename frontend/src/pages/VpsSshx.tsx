import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, ExternalLink, RefreshCw, ShieldCheck, SquareTerminal } from 'lucide-react'
import { api, ApiError } from '../lib/api'
import { Button } from '../components/ui'

type SshxSession = {
  sshx_url: string
  expires_at: string
  kind: 'sshx'
}

/**
 * One-time SSHX hand-off page. It deliberately renders no terminal and stores
 * no URL outside component memory: a bearer URL is returned once after the
 * panel's normal per-VPS authorization and immediately replaces this tab.
 */
export default function VpsSshx() {
  const { id } = useParams()
  const [error, setError] = useState('')
  const [opening, setOpening] = useState(true)
  const [fallbackUrl, setFallbackUrl] = useState('')

  const openSshx = async () => {
    setOpening(true)
    setError('')
    setFallbackUrl('')
    try {
      const session = await api.post<SshxSession>(`/api/vps/${id}/sshx-session`)
      // Keep a temporary fallback only in this tab's memory. Never localStorage,
      // sessionStorage, URL params, audit records, or a panel database column.
      setFallbackUrl(session.sshx_url)
      window.location.replace(session.sshx_url)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not create the SSHX session')
      setOpening(false)
    }
  }

  useEffect(() => {
    openSshx()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id])

  return (
    <div className="mx-auto flex min-h-[70vh] max-w-2xl flex-col items-center justify-center px-4 text-center">
      <SquareTerminal className="mb-5 h-11 w-11 text-electric" />
      <h1 className="text-2xl font-bold text-white">Opening SSHX terminal…</h1>
      {opening && !error && (
        <p className="mt-3 max-w-lg text-sm text-muted">
          BLUEKVM is verifying your VPS access and creating a short-lived, encrypted sshx.io terminal session.
        </p>
      )}

      {error && (
        <div className="mt-5 w-full rounded-xl border border-danger/50 bg-danger/10 p-5 text-left">
          <p className="font-semibold text-danger">SSHX session unavailable</p>
          <p className="mt-2 text-sm text-muted">{error}</p>
          <p className="mt-3 text-xs text-muted">
            The VPS must be running with a discovered guest IP and SSH service. SSHX must also be installed on the
            panel node by the current BLUEKVM installer.
          </p>
        </div>
      )}

      {fallbackUrl && (
        <p className="mt-5 text-sm text-muted">
          Navigation was blocked.{' '}
          <a href={fallbackUrl} className="inline-flex items-center gap-1 text-electric hover:underline">
            Continue to SSHX <ExternalLink className="h-3.5 w-3.5" />
          </a>
        </p>
      )}

      <div className="mt-7 flex flex-wrap items-center justify-center gap-3">
        {error && (
          <Button onClick={openSshx} loading={opening}>
            <RefreshCw className="h-4 w-4" /> Try again
          </Button>
        )}
        <Link to={`/vps/${id}`}>
          <Button variant="secondary">
            <ArrowLeft className="h-4 w-4" /> Back to VPS
          </Button>
        </Link>
      </div>

      <div className="mt-8 flex max-w-xl items-start gap-2 rounded-lg border border-line bg-panel px-4 py-3 text-left text-xs text-muted">
        <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-electric" />
        <p>
          This hosted SSHX URL is a bearer link. BLUEKVM gives it only to the authorized VPS user, never stores it,
          and terminates the relay automatically after 15 minutes. Do not share the link.
        </p>
      </div>
    </div>
  )
}
