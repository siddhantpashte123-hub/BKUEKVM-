import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  Activity,
  Cpu,
  ExternalLink,
  HardDrive,
  MemoryStick,
  Network,
  Play,
  RotateCcw,
  Square,
  Trash2,
} from 'lucide-react'
import { api, ApiError } from '../lib/api'
import { formatBytes, formatDate, formatMb, relativeTime, titleCase } from '../lib/format'
import type { Backup, Task, VPS } from '../lib/types'
import { Badge, Button, Card, ConfirmDialog, ErrorState, LoadingState, PageHeader, ProgressBar } from '../components/ui'
import { useAuth } from '../lib/auth'

const TABS = ['Overview', 'Console', 'Network', 'Storage', 'Backups', 'Activity'] as const
type Tab = (typeof TABS)[number]

interface VmStats {
  available: boolean
  reason?: string
  cpu_percent?: number
  ram_used_mb?: number
  ram_total_mb?: number
  disk_used_bytes?: number
  network_rx_bytes?: number
  network_tx_bytes?: number
}

export default function VpsDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { can } = useAuth()
  const [vps, setVps] = useState<VPS | null>(null)
  const [stats, setStats] = useState<VmStats | null>(null)
  const [tasks, setTasks] = useState<Task[]>([])
  const [backups, setBackups] = useState<Backup[]>([])
  const [tab, setTab] = useState<Tab>('Overview')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [confirmReinstall, setConfirmReinstall] = useState(false)
  const [notice, setNotice] = useState('')

  const load = async () => {
    try {
      const [v, t, b] = await Promise.all([
        api.get<VPS>(`/api/vps/${id}`),
        api.get<Task[]>(`/api/vps/${id}/tasks`),
        can('backup:read') ? api.get<Backup[]>(`/api/backups`, { vps_id: '' as unknown as number }).catch(() => []) : Promise.resolve([]),
      ])
      setVps(v)
      setTasks(t)
      setBackups((b as Backup[]).filter((x) => x.vps_id === v.id))
      setError('')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load VPS')
    }
  }

  useEffect(() => {
    load()
    const interval = setInterval(load, 7000)
    return () => clearInterval(interval)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id])

  useEffect(() => {
    if (!vps || tab !== 'Overview') return
    api
      .get<VmStats>(`/api/vps/${id}/stats`)
      .then(setStats)
      .catch(() => setStats({ available: false, reason: 'Metrics unavailable' }))
  }, [id, tab, vps?.status])

  const act = async (kind: 'start' | 'stop' | 'shutdown' | 'restart') => {
    setBusy(true)
    try {
      const res = await api.post<{ message: string }>(`/api/vps/${id}/actions/${kind}`, {})
      setNotice(res.message)
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Action failed')
    } finally {
      setBusy(false)
    }
  }

  const remove = async () => {
    if (!vps) return
    setBusy(true)
    try {
      await api.delete(`/api/vps/${vps.public_id}`, { confirm: vps.name })
      navigate('/vps')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Delete failed')
      setBusy(false)
      setConfirmDelete(false)
    }
  }

  const reinstall = async () => {
    if (!vps) return
    setBusy(true)
    try {
      const res = await api.post<{ message: string }>(`/api/vps/${vps.public_id}/reinstall`)
      setNotice(res.message)
      setConfirmReinstall(false)
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Reinstall failed')
    } finally {
      setBusy(false)
    }
  }

  if (error && !vps) return <ErrorState message={error} onRetry={load} />
  if (!vps) return <LoadingState label="Loading VPS…" />

  return (
    <div>
      <PageHeader
        title={vps.name}
        description={`${vps.hostname} · ${vps.template_name ?? ''} · node ${vps.node_name}`}
        actions={
          <div className="flex flex-wrap gap-2">
            <Link to={`/vps/${vps.public_id}/console`}>
              <Button variant="secondary">
                <ExternalLink className="h-4 w-4" /> Open Console
              </Button>
            </Link>
            {can('vps:manage') && (
              <>
                <Button variant="secondary" disabled={busy} onClick={() => act('start')}>
                  <Play className="h-4 w-4" /> Start
                </Button>
                <Button variant="secondary" disabled={busy} onClick={() => act('shutdown')}>
                  <Square className="h-4 w-4" /> Shutdown
                </Button>
                <Button variant="secondary" disabled={busy} onClick={() => act('restart')}>
                  <RotateCcw className="h-4 w-4" /> Restart
                </Button>
                <Button variant="danger" disabled={busy} onClick={() => setConfirmDelete(true)}>
                  <Trash2 className="h-4 w-4" />
                </Button>
              </>
            )}
          </div>
        }
      />

      <div className="mb-5 flex flex-wrap items-center gap-3">
        <Badge value={vps.status} />
        <span className="text-sm text-muted">Power: <span className="text-white">{vps.power_state}</span></span>
        <span className="text-sm text-muted">Created {relativeTime(vps.created_at)}</span>
      </div>

      {notice && <div className="mb-4 rounded-lg border border-electric/40 bg-electric/10 px-4 py-2.5 text-sm text-white">{notice}</div>}
      {error && <div className="mb-4 rounded-lg border border-danger/40 bg-danger/10 px-4 py-2.5 text-sm text-danger">{error}</div>}

      <div className="mb-5 flex gap-1 overflow-x-auto rounded-lg border border-line bg-panel p-1">
        {TABS.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`whitespace-nowrap rounded-md px-4 py-2 text-sm font-medium transition ${
              tab === t ? 'bg-primary/20 text-electric shadow-[inset_0_0_0_1px_rgba(0,140,255,0.4)]' : 'text-muted hover:text-white'
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {tab === 'Overview' && (
        <div className="space-y-5">
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <Card>
              <h3 className="mb-3 flex items-center gap-2 font-semibold text-white"><Cpu className="h-4 w-4 text-electric" /> Compute</h3>
              <p className="text-sm text-muted">Allocated: <span className="text-white">{vps.vcpus} vCPU · {formatMb(vps.ram_mb)}</span></p>
              <p className="mt-2 text-sm text-muted">
                Live CPU:{' '}
                <span className="text-white">
                  {stats?.available && stats.cpu_percent !== undefined ? `${stats.cpu_percent}%` : 'unavailable'}
                </span>
              </p>
              {stats?.available && stats.cpu_percent !== undefined && (
                <div className="mt-2"><ProgressBar percent={stats.cpu_percent} /></div>
              )}
            </Card>
            <Card>
              <h3 className="mb-3 flex items-center gap-2 font-semibold text-white"><MemoryStick className="h-4 w-4 text-electric" /> Memory</h3>
              <p className="text-sm text-muted">
                Guest usage:{' '}
                <span className="text-white">
                  {stats?.available && stats.ram_used_mb ? `${formatMb(stats.ram_used_mb)} / ${formatMb(stats.ram_total_mb || vps.ram_mb)}` : 'unavailable'}
                </span>
              </p>
              {stats?.available && stats.ram_used_mb ? (
                <div className="mt-2">
                  <ProgressBar percent={(stats.ram_used_mb / (stats.ram_total_mb || vps.ram_mb)) * 100} />
                </div>
              ) : (
                <p className="mt-2 text-xs text-muted">Reported by the hypervisor once the guest agent/balloon is active</p>
              )}
            </Card>
            <Card>
              <h3 className="mb-3 flex items-center gap-2 font-semibold text-white"><HardDrive className="h-4 w-4 text-electric" /> Disk</h3>
              <p className="text-sm text-muted">Allocated capacity: <span className="text-white">{vps.disk_gb} GB</span></p>
              <p className="mt-2 text-sm text-muted">
                Written: <span className="text-white">{stats?.disk_used_bytes ? formatBytes(stats.disk_used_bytes) : 'unavailable'}</span>
              </p>
            </Card>
          </div>

          {vps.last_error && (
            <Card className="border-danger/40">
              <h3 className="mb-2 font-semibold text-danger">Last error</h3>
              <p className="text-sm text-white">{vps.last_error}</p>
            </Card>
          )}

          <Card>
            <h3 className="mb-3 flex items-center gap-2 font-semibold text-white"><Activity className="h-4 w-4 text-electric" /> Recent tasks</h3>
            {tasks.length === 0 ? (
              <p className="text-sm text-muted">No tasks recorded</p>
            ) : (
              <div className="space-y-3">
                {tasks.slice(0, 5).map((t) => (
                  <div key={t.id} className="rounded-lg border border-line bg-input p-3">
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-medium text-white">{titleCase(t.task_type.replace(/_/g, ' '))}</span>
                      <Badge value={t.status} />
                    </div>
                    <div className="mt-2"><ProgressBar percent={t.progress} /></div>
                    {t.error && <p className="mt-2 text-xs text-danger">{t.error}</p>}
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>
      )}

      {tab === 'Console' && (
        <Card>
          <h3 className="mb-2 font-semibold text-white">Browser console</h3>
          <p className="mb-4 text-sm text-muted">
            Consoles use a single-use, 60-second token over an authenticated WebSocket. Raw VNC ports are never exposed.
          </p>
          <Link to={`/vps/${vps.public_id}/console`}>
            <Button>
              <ExternalLink className="h-4 w-4" /> Launch noVNC console
            </Button>
          </Link>
        </Card>
      )}

      {tab === 'Network' && (
        <Card>
          <h3 className="mb-4 flex items-center gap-2 font-semibold text-white"><Network className="h-4 w-4 text-electric" /> Network information</h3>
          <dl className="grid gap-3 sm:grid-cols-2">
            <Info label="IP address" value={vps.ip_address || 'DHCP / unassigned'} mono />
            <Info label="MAC address" value={vps.mac_address || 'Auto-generated'} mono />
            <Info label="Network" value={`Network #${vps.network_id ?? '—'}`} />
            <Info label="SSH public key" value={vps.ssh_public_key ? 'Installed via cloud-init' : 'None'} />
          </dl>
          {stats?.network_rx_bytes !== undefined && (
            <div className="mt-4 grid gap-3 sm:grid-cols-2 text-sm">
              <p className="text-muted">RX: <span className="text-white">{formatBytes(stats.network_rx_bytes)}</span></p>
              <p className="text-muted">TX: <span className="text-white">{formatBytes(stats.network_tx_bytes)}</span></p>
            </div>
          )}
        </Card>
      )}

      {tab === 'Storage' && (
        <Card>
          <h3 className="mb-4 flex items-center gap-2 font-semibold text-white"><HardDrive className="h-4 w-4 text-electric" /> Storage</h3>
          <dl className="grid gap-3 sm:grid-cols-2">
            <Info label="Disk capacity" value={`${vps.disk_gb} GB qcow2`} />
            <Info label="Used (guest-reported)" value={stats?.disk_used_bytes ? formatBytes(stats.disk_used_bytes) : 'Unavailable'} />
          </dl>
        </Card>
      )}

      {tab === 'Backups' && (
        <Card>
          <div className="mb-4 flex items-center justify-between">
            <h3 className="font-semibold text-white">Backups & snapshots</h3>
            {can('backup:manage') && (
              <Button variant="secondary" onClick={() => setConfirmReinstall(true)}>
                <RotateCcw className="h-4 w-4" /> Reinstall OS
              </Button>
            )}
          </div>
          {backups.length === 0 ? (
            <p className="text-sm text-muted">No backups yet. Create one from the Backups page.</p>
          ) : (
            <div className="space-y-2">
              {backups.map((b) => (
                <div key={b.id} className="flex items-center justify-between rounded-lg border border-line bg-input p-3 text-sm">
                  <div>
                    <p className="font-medium text-white">{b.backup_type} · {b.snapshot_name || b.path}</p>
                    <p className="text-xs text-muted">{formatDate(b.created_at)} · {formatBytes(b.size_bytes)}</p>
                  </div>
                  <Badge value={b.status} />
                </div>
              ))}
            </div>
          )}
        </Card>
      )}

      {tab === 'Activity' && (
        <Card>
          <h3 className="mb-4 font-semibold text-white">Task history and logs</h3>
          <div className="space-y-3">
            {tasks.map((t) => (
              <div key={t.id} className="rounded-lg border border-line bg-input p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-sm font-semibold text-white">{titleCase(t.task_type.replace(/_/g, ' '))} <span className="text-muted">#{t.id}</span></span>
                  <Badge value={t.status} />
                </div>
                <p className="mt-1 text-xs text-muted">Created {formatDate(t.created_at)}</p>
                {t.logs && <pre className="mt-3 max-h-48 overflow-auto rounded-lg bg-black p-3 font-mono text-xs text-muted">{t.logs}</pre>}
                {t.error && <p className="mt-2 text-xs text-danger">{t.error}</p>}
              </div>
            ))}
            {tasks.length === 0 && <p className="text-sm text-muted">No activity yet</p>}
          </div>
        </Card>
      )}

      <ConfirmDialog
        open={confirmDelete}
        title="Delete this VPS"
        danger
        confirmLabel="Delete forever"
        loading={busy}
        onClose={() => setConfirmDelete(false)}
        onConfirm={remove}
        message={
          <>
            Permanently destroy <strong className="text-electric">{vps.name}</strong>, its libvirt domain and virtual disks.
            This cannot be undone.
          </>
        }
      />
      <ConfirmDialog
        open={confirmReinstall}
        title="Reinstall operating system"
        danger
        confirmLabel="Reinstall now"
        loading={busy}
        onClose={() => setConfirmReinstall(false)}
        onConfirm={reinstall}
        message={
          <>
            The existing disk of <strong className="text-electric">{vps.name}</strong> will be replaced with a fresh image
            from <strong>{vps.template_name}</strong>. All data on the disk is lost.
          </>
        }
      />
    </div>
  )
}

function Info({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="rounded-lg border border-line bg-input p-3">
      <dt className="text-xs uppercase tracking-wider text-muted">{label}</dt>
      <dd className={`mt-1 break-all text-sm font-medium text-white ${mono ? 'font-mono' : ''}`}>{value}</dd>
    </div>
  )
}
