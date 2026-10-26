import { Activity, Cpu, Database, HardDrive, MemoryStick, MonitorCog, Wifi } from 'lucide-react'
import { api } from '../lib/api'
import { usePoll } from '../lib/usePoll'
import { formatBytes } from '../lib/format'
import type { HostMetrics } from '../lib/types'
import { Badge, Card, ErrorState, LoadingState, PageHeader, ProgressBar, StatCard } from '../components/ui'

interface HealthResponse {
  services: { name: string; status: string; detail?: unknown }[]
  capabilities: Record<string, unknown>
  nodes: { id: number; name: string; status: string; kvm_ready: boolean; last_error: string; last_health_at: string | null }[]
}

export default function Monitoring() {
  const host = usePoll<HostMetrics>('/api/monitoring/host', 4000)
  const health = usePoll<HealthResponse>('/api/monitoring/health', 10000)

  if (host.loading && !host.data) return <LoadingState label="Collecting host telemetry…" />

  const m = host.data
  return (
    <div className="space-y-6">
      <PageHeader title="System Monitoring" description="Real host measurements — distinct from per-VM guest statistics" />

      {host.error && <ErrorState message={host.error} onRetry={host.reload} />}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard icon={<Cpu className="h-5 w-5" />} label="CPU usage" value={m ? `${m.cpu.percent.toFixed(1)}%` : '—'} sub={`${m?.cpu.cores_logical ?? 0} logical cores`} />
        <StatCard icon={<MemoryStick className="h-5 w-5" />} label="Memory" value={m ? `${m.memory.percent.toFixed(1)}%` : '—'} sub={m ? `${formatBytes(m.memory.used_bytes)} / ${formatBytes(m.memory.total_bytes)}` : ''} />
        <StatCard icon={<HardDrive className="h-5 w-5" />} label="Disk" value={m ? `${m.disk.percent}%` : '—'} sub={m ? formatBytes(m.disk.free_bytes) + ' free' : ''} tone="text-warning" />
        <StatCard icon={<Activity className="h-5 w-5" />} label="Active VMs" value={m?.active_vps ?? '—'} sub={`${m?.queued_tasks ?? 0} queued jobs`} tone="text-success" />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <h3 className="mb-4 flex items-center gap-2 font-semibold text-white"><Cpu className="h-4 w-4 text-electric" /> CPU & memory pressure</h3>
          <div className="space-y-5">
            <div>
              <div className="mb-2 flex justify-between text-sm text-muted"><span>CPU</span><span>{m?.cpu.percent.toFixed(1)}%</span></div>
              <ProgressBar percent={m?.cpu.percent ?? 0} />
              <p className="mt-1 text-xs text-muted">
                Load average: {m ? `${m.cpu.load_average['1m']} / ${m.cpu.load_average['5m']} / ${m.cpu.load_average['15m']}` : '—'}
              </p>
            </div>
            <div>
              <div className="mb-2 flex justify-between text-sm text-muted"><span>RAM</span><span>{m?.memory.percent.toFixed(1)}%</span></div>
              <ProgressBar percent={m?.memory.percent ?? 0} tone="bg-primary" />
            </div>
            <div>
              <div className="mb-2 flex justify-between text-sm text-muted"><span>Root filesystem</span><span>{m?.disk.percent}%</span></div>
              <ProgressBar percent={m?.disk.percent ?? 0} tone="bg-warning" />
            </div>
          </div>
        </Card>

        <Card>
          <h3 className="mb-4 flex items-center gap-2 font-semibold text-white"><Wifi className="h-4 w-4 text-electric" /> Network traffic</h3>
          {m ? (
            <div className="space-y-3 text-sm">
              <Row label="Total received" value={formatBytes(m.network.bytes_recv)} />
              <Row label="Total sent" value={formatBytes(m.network.bytes_sent)} />
              <Row label="Packets received" value={m.network.packets_recv.toLocaleString()} />
              <Row label="Packets sent" value={m.network.packets_sent.toLocaleString()} />
              <Row label="Boot time" value={m.boot_time ? new Date(m.boot_time * 1000).toLocaleString() : '—'} />
            </div>
          ) : (
            <p className="text-sm text-muted">Unavailable</p>
          )}
        </Card>
      </div>

      <Card>
        <h3 className="mb-4 flex items-center gap-2 font-semibold text-white">
          <Database className="h-4 w-4 text-electric" /> Service health
        </h3>
        {health.error ? (
          <p className="text-sm text-danger">{health.error}</p>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            {(health.data?.services ?? []).map((s) => (
              <div key={s.name} className="flex items-center justify-between rounded-lg border border-line bg-input p-3">
                <div>
                  <p className="text-sm font-semibold text-white">{s.name}</p>
                  {s.detail ? (
                    <p className="mt-0.5 break-all text-xs text-muted">
                      {typeof s.detail === 'string' ? s.detail : JSON.stringify(s.detail)}
                    </p>
                  ) : null}
                </div>
                <Badge value={s.status === 'connected' || s.status === 'ready' || s.status === 'running' ? 'active' : 'unconfigured'} />
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card>
        <h3 className="mb-4 flex items-center gap-2 font-semibold text-white"><MonitorCog className="h-4 w-4 text-electric" /> Node virtualization readiness</h3>
        <div className="space-y-3">
          {(health.data?.nodes ?? []).map((n) => (
            <div key={n.id} className="rounded-lg border border-line bg-input p-4">
              <div className="flex items-center justify-between">
                <p className="font-semibold text-white">{n.name}</p>
                <div className="flex gap-2">
                  <Badge value={n.status} />
                  <Badge value={n.kvm_ready ? 'online' : 'offline'} />
                </div>
              </div>
              {n.last_error && <p className="mt-2 text-xs text-danger">{n.last_error}</p>}
            </div>
          ))}
          {(!health.data || health.data.nodes.length === 0) && <p className="text-sm text-muted">No nodes registered</p>}
        </div>
      </Card>
    </div>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between border-b border-line/60 pb-2">
      <span className="text-muted">{label}</span>
      <span className="font-medium text-white">{value}</span>
    </div>
  )
}
