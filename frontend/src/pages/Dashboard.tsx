import { Link } from 'react-router-dom'
import {
  Activity,
  AlertTriangle,
  Cpu,
  HardDrive,
  MemoryStick,
  MonitorCog,
  Plus,
  Server,
  Wifi,
} from 'lucide-react'
import {
  Area,
  AreaChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { api } from '../lib/api'
import { usePoll } from '../lib/usePoll'
import { formatBytes, relativeTime, titleCase } from '../lib/format'
import type { DashboardSummary, HostMetrics, Task } from '../lib/types'
import { Badge, Button, Card, ErrorState, LoadingState, PageHeader, ProgressBar, StatCard } from '../components/ui'

const PIE_COLORS = ['#A1A1AA', '#71717A', '#E4E4E7', '#FFFFFF']

export default function Dashboard() {
  const summary = usePoll<DashboardSummary>('/api/dashboard/summary', 10000)
  const metrics = usePoll<HostMetrics>('/api/dashboard/metrics', 5000)
  const activity = usePoll<{ audit: { id: number; action: string; resource_type: string; created_at: string }[]; tasks: Task[] }>(
    '/api/dashboard/activity',
    8000,
  )

  if (summary.loading && !summary.data) return <LoadingState label="Loading dashboard…" />
  if (summary.error && !summary.data) return <ErrorState message={summary.error} onRetry={summary.reload} />

  const s = summary.data!
  const m = metrics.data
  const distribution = [
    { name: 'Running', value: s.vps_running },
    { name: 'Stopped', value: s.vps_stopped },
    { name: 'Provisioning', value: s.vps_provisioning },
    { name: 'Error', value: s.vps_error },
  ].filter((d) => d.value > 0)

  const series = (m?.timeseries ?? []).map((p) => ({
    time: new Date(p.ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
    cpu: p.cpu_percent,
    mem: p.mem_percent,
  }))

  return (
    <div className="space-y-6">
      <PageHeader
        title="Dashboard"
        description="Live overview of your virtualization infrastructure"
        actions={
          <Link to="/vps/create">
            <Button>
              <Plus className="h-4 w-4" /> Quick Create VPS
            </Button>
          </Link>
        }
      />

      {metrics.error && (
        <div className="flex items-center gap-2 rounded-lg border border-color bg-card px-4 py-2.5 text-sm text-secondary">
          <AlertTriangle className="h-4 w-4 shrink-0" /> Live metrics disconnected — retrying automatically
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard icon={<Server className="h-5 w-5" />} label="Total VPS" value={s.vps_total} sub={`${s.vps_running} running · ${s.vps_stopped} stopped`} />
        <StatCard icon={<Activity className="h-5 w-5" />} label="Provisioning" value={s.vps_provisioning} sub={`${s.vps_error} in error state`} />
        <StatCard icon={<MonitorCog className="h-5 w-5" />} label="Nodes" value={`${s.nodes_online}/${s.nodes_total}`} sub="online / registered" />
        <StatCard icon={<Wifi className="h-5 w-5" />} label="Background Jobs" value={s.tasks_running + s.tasks_queued} sub={`${s.tasks_running} running · ${s.tasks_queued} queued`} />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* CPU chart */}
        <Card className="lg:col-span-2">
          <div className="mb-4 flex items-center justify-between">
            <h3 className="flex items-center gap-2 font-semibold text-white">
              <Cpu className="h-4 w-4 shrink-0" /> CPU Utilization
            </h3>
            <span className="text-2xl font-bold text-white">{m ? `${m.cpu.percent.toFixed(1)}%` : '—'}</span>
          </div>
          {series.length === 0 ? (
            <p className="py-16 text-center text-sm text-muted">Collecting samples… metrics appear within seconds.</p>
          ) : (
            <ResponsiveContainer width="100%" height={220}>
              <AreaChart data={series}>
                <CartesianGrid stroke="#2D2D30" vertical={false} />
                <XAxis dataKey="time" stroke="#A1A1AA" fontSize={11} minTickGap={40} />
                <YAxis stroke="#A1A1AA" fontSize={11} domain={[0, 100]} unit="%" />
                <Tooltip
                  contentStyle={{
                    background: 'var(--bg-card)',
                    border: '1px solid var(--border-color)',
                    borderRadius: 8,
                    fontSize: 12,
                    color: 'var(--text-primary)',
                  }}
                />
                <Area type="monotone" dataKey="cpu" stroke="#A1A1AA" strokeWidth={2} fill="#A1A1AA" opacity={0.35} name="CPU %" isAnimationActive={false} />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </Card>

        {/* VPS distribution */}
        <Card>
          <h3 className="mb-4 font-semibold text-white">VPS Status Distribution</h3>
          {distribution.length === 0 ? (
            <p className="py-16 text-center text-sm text-muted">No VPS instances yet</p>
          ) : (
            <>
              <ResponsiveContainer width="100%" height={180}>
                <PieChart>
                  <Pie
                    data={distribution}
                    dataKey="value"
                    nameKey="name"
                    innerRadius={45}
                    outerRadius={70}
                    paddingAngle={3}
                  >
                    {distribution.map((_, i) => (
                      <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} stroke="#0F0F11" />
                    ))}
                  </Pie>
                  <Tooltip
                    contentStyle={{
                      background: 'var(--bg-card)',
                      border: '1px solid var(--border-color)',
                      borderRadius: 8,
                      fontSize: 12,
                      color: 'var(--text-primary)',
                    }}
                  />
                </PieChart>
              </ResponsiveContainer>
              <div className="mt-2 space-y-1.5">
                {distribution.map((d, i) => (
                  <div key={d.name} className="flex items-center justify-between text-sm">
                    <span className="flex items-center gap-2 text-secondary">
                      <span className="h-2.5 w-2.5 rounded-full" style={{ background: PIE_COLORS[i % PIE_COLORS.length] }} />
                      {d.name}
                    </span>
                    <span className="font-semibold text-white">{d.value}</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </Card>
      </div>

      {/* RAM / Disk / Network */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card>
          <h3 className="mb-3 flex items-center gap-2 font-semibold text-white">
            <MemoryStick className="h-4 w-4 shrink-0" /> Memory
          </h3>
          {m ? (
            <>
              <div className="mb-2 flex justify-between text-sm text-muted">
                <span>{formatBytes(m.memory.used_bytes)} used</span>
                <span>{formatBytes(m.memory.total_bytes)}</span>
              </div>
              <ProgressBar percent={m.memory.percent} />
            </>
          ) : (
            <p className="text-sm text-muted">Unavailable</p>
          )}
        </Card>
        <Card>
          <h3 className="mb-3 flex items-center gap-2 font-semibold text-white">
            <HardDrive className="h-4 w-4 shrink-0" /> Storage
          </h3>
          {m ? (
            <>
              <div className="mb-2 flex justify-between text-sm text-muted">
                <span>{formatBytes(m.disk.used_bytes)} used</span>
                <span>{formatBytes(m.disk.total_bytes)}</span>
              </div>
              <ProgressBar percent={m.disk.percent} />
            </>
          ) : (
            <p className="text-sm text-muted">Unavailable</p>
          )}
        </Card>
        <Card>
          <h3 className="mb-3 flex items-center gap-2 font-semibold text-white">
            <Wifi className="h-4 w-4 shrink-0" /> Network Activity
          </h3>
          {m ? (
            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-muted">Received</span>
                <span className="font-medium text-white">{formatBytes(m.network.bytes_recv)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted">Sent</span>
                <span className="font-medium text-white">{formatBytes(m.network.bytes_sent)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted">Packets in</span>
                <span className="font-medium text-white">{m.network.packets_recv.toLocaleString()}</span>
              </div>
            </div>
          ) : (
            <p className="text-sm text-muted">Unavailable</p>
          )}
        </Card>
      </div>

      {/* Recent activity & tasks */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <h3 className="mb-4 font-semibold text-white">Recent Activity</h3>
          <div className="space-y-3">
            {(activity.data?.audit ?? []).length === 0 && <p className="text-sm text-muted">No activity recorded yet</p>}
            {(activity.data?.audit ?? []).map((a) => (
              <div key={a.id} className="flex items-center justify-between gap-3 text-sm">
                <div className="min-w-0">
                  <p className="truncate font-medium text-white">{titleCase(a.action)}</p>
                  <p className="truncate text-xs text-muted">
                    {a.resource_type || 'system'} · {relativeTime(a.created_at)}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </Card>
        <Card>
          <div className="mb-4 flex items-center justify-between">
            <h3 className="font-semibold text-white">Recent Provisioning Tasks</h3>
            <Link to="/tasks" className="text-xs font-semibold text-secondary hover:text-white underline-offset-4 hover:underline">
              View all
            </Link>
          </div>
          <div className="space-y-3">
            {(activity.data?.tasks ?? []).length === 0 && <p className="text-sm text-muted">No tasks yet</p>}
            {(activity.data?.tasks ?? []).map((t) => (
              <div key={t.id} className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-white">
                    {titleCase(t.task_type.replace(/_/g, ' '))}
                  </p>
                  <div className="mt-1 w-40"><ProgressBar percent={t.progress} /></div>
                </div>
                <Badge value={t.status} />
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  )
}
