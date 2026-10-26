import { useEffect, useState } from 'react'
import { Save, Settings as SettingsIcon } from 'lucide-react'
import { api, ApiError } from '../lib/api'
import { Button, Card, ErrorState, Input, LoadingState, PageHeader } from '../components/ui'
import { useAuth } from '../lib/auth'

interface SettingsResponse {
  settings: Record<string, unknown>
  environment: {
    version: string
    env: string
    port: number
    database: string
    cookie_secure: boolean
    csrf_enabled: boolean
  }
}

export default function SettingsPage() {
  const { can } = useAuth()
  const [data, setData] = useState<SettingsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState('')
  const [tagline, setTagline] = useState('')
  const [retention, setRetention] = useState(90)
  const [notes, setNotes] = useState('')

  useEffect(() => {
    api
      .get<SettingsResponse>('/api/settings')
      .then((res) => {
        setData(res)
        setTagline(String(res.settings.branding_tagline ?? ''))
        setRetention(Number(res.settings.audit_retention_days ?? 90))
        setNotes(String(res.settings.panel_notes ?? ''))
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : 'Failed to load settings'))
      .finally(() => setLoading(false))
  }, [])

  const save = async (key: string, value: unknown) => {
    setSaved('')
    try {
      await api.put(`/api/settings/${key}`, { value })
      setSaved(`${key} updated`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Update failed')
    }
  }

  if (loading) return <LoadingState label="Loading settings…" />
  if (error || !data) return <ErrorState message={error || 'Unavailable'} />

  return (
    <div className="space-y-6">
      <PageHeader title="Settings" description="Panel branding, runtime environment and service configuration" />

      {saved && <div className="rounded-lg border border-success/40 bg-success/10 px-4 py-2.5 text-sm text-success">{saved}</div>}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <h3 className="mb-4 flex items-center gap-2 font-semibold text-white"><SettingsIcon className="h-4 w-4 text-electric" /> Branding</h3>
          <div className="space-y-4">
            <Input label="Application name" value="BLUEKVM PANNEL" disabled />
            <Input label="Tagline" value={tagline} onChange={(e) => setTagline(e.target.value)} />
            <Button variant="secondary" disabled={!can('settings:manage')} onClick={() => save('branding_tagline', tagline)}>
              <Save className="h-4 w-4" /> Save branding
            </Button>
          </div>
        </Card>

        <Card>
          <h3 className="mb-4 font-semibold text-white">Runtime environment</h3>
          <dl className="space-y-3 text-sm">
            <Env label="Panel version" value={data.environment.version} />
            <Env label="Environment" value={data.environment.env} />
            <Env label="Web port" value={String(data.environment.port)} />
            <Env label="Database" value={data.environment.database} />
            <Env label="Secure cookies" value={data.environment.cookie_secure ? 'enabled' : 'disabled (HTTP)'} />
            <Env label="CSRF protection" value={data.environment.csrf_enabled ? 'enabled' : 'disabled'} />
          </dl>
          <p className="mt-4 text-xs text-muted">
            Port and TLS are configured through environment variables and the systemd/nginx deployment, never via the
            browser. Secrets are not readable from this API.
          </p>
        </Card>

        <Card>
          <h3 className="mb-4 font-semibold text-white">Retention & notes</h3>
          <div className="space-y-4">
            <Input
              label="Audit log retention (days)"
              type="number"
              value={retention}
              onChange={(e) => setRetention(Number(e.target.value))}
            />
            <Button variant="secondary" disabled={!can('settings:manage')} onClick={() => save('audit_retention_days', retention)}>
              <Save className="h-4 w-4" /> Save retention
            </Button>
            <div>
              <label className="label-base">Panel notes</label>
              <textarea className="input-base min-h-[100px]" value={notes} onChange={(e) => setNotes(e.target.value)} />
            </div>
            <Button variant="secondary" disabled={!can('settings:manage')} onClick={() => save('panel_notes', notes)}>
              <Save className="h-4 w-4" /> Save notes
            </Button>
          </div>
        </Card>

        <Card>
          <h3 className="mb-4 font-semibold text-white">Security posture</h3>
          <ul className="space-y-2 text-sm text-muted">
            <li>• Passwords hashed with bcrypt; no default passwords are shipped</li>
            <li>• Opaque session tokens stored only as SHA-256 hashes</li>
            <li>• Login rate limiting and double-submit CSRF tokens</li>
            <li>• Role-based authorization on every endpoint</li>
            <li>• Console access uses single-use, 60-second WebSocket tokens</li>
            <li>• libvirt access is restricted to the service layer — no root shell from the web UI</li>
          </ul>
        </Card>
      </div>
    </div>
  )
}

function Env({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between border-b border-line/60 pb-2">
      <dt className="text-muted">{label}</dt>
      <dd className="font-medium capitalize text-white">{value}</dd>
    </div>
  )
}
