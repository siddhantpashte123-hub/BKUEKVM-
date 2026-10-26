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

const PIE_COLORS = ['#22C55E', '#A1A1AA', '#008CFF', '#EF4444']

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
        <div className="flex items-center gap-2 rounded-lg border border-warning/40 bg-warning/10 px-4 py-2.5 text-sm text-warning">
          <AlertTriangle className="h-4 w-4" /> Live metrics disconnected — retrying automatically
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard icon={<Server className="h-5 w-5" />} label="Total VPS" value={s.vps_total} sub={`${s.vps_running} running · ${s.vps_stopped} stopped`} />
        <StatCard icon={<Activity className="h-5 w-5" />} label="Provisioning" value={s.vps_provisioning} sub={`${s.vps_error} in error state`} tone="text-warning" />
        <StatCard icon={<MonitorCog className="h-5 w-5" />} label="Nodes" value={`${s.nodes_online}/${s.nodes_total}`} sub="online / registered" tone="text-success" />
        <StatCard icon={<Wifi className="h-5 w-5" />} label="Background Jobs" value={s.tasks_running + s.tasks_queued} sub={`${s.tasks_running} running · ${s.tasks_queued} queued`} />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* CPU chart */}
        <Card className="lg:col-span-2">
          <div className="mb-4 flex items-center justify-between">
            <h3 className="flex items-center gap-2 font-semibold text-white">
              <Cpu className="h-4 w-4 text-electric" /> CPU Utilization
            </h3>
            <span className="text-2xl font-bold text-electric">{m ? `${m.cpu.percent.toFixed(1)}%` : '—'}</span>
          </div>
          {series.length === 0 ? (
            <p className="py-16 text-center text-sm text-muted">Collecting samples… metrics appear within seconds.</p>
          ) : (
            <ResponsiveContainer width="100%" height={220}>
              <AreaChart data={series}>
                <defs>
                  <linearGradient id="cpuFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#008CFF" stopOpacity={0.45} />
                    <stop offset="100%" stopColor="#008CFF" stopOpacity={0.02} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="#222222" vertical={false} />
                <XAxis dataKey="time" stroke="#A1A1AA" fontSize={11} minTickGap={40} />
                <YAxis stroke="#A1A1AA" fontSize={11} domain={[0, 100]} unit="%" />
                <Tooltip contentStyle={{ background: '#0D0D0D', border: '1px solid #222222', borderRadius: 8, fontSize: 12 }} />
                <Area type="monotone" dataKey="cpu" stroke="#008CFF" strokeWidth={2} fill="url(#cpuFill)" name="CPU %" isAnimationActive={false} />
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
                  <Pie data={distribution} dataKey="value" nameKey="name" innerRadius={45} outerRadius={70} paddingAngle={3}>
                    {distribution.map((_, i) => (
                      <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} stroke="#000000" />
                    ))}
                  </Pie>
                  <Tooltip contentStyle={{ background: '#0D0D0D', border: '1px solid #222222', borderRadius: 8, fontSize: 12 }} />
                </PieChart>
              </ResponsiveContainer>
              <div className="mt-2 space-y-1.5">
                {distribution.map((d, i) => (
                  <div key={d.name} className="flex items-center justify-between text-sm">
                    <span className="flex items-center gap-2 text-muted">
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
            <MemoryStick className="h-4 w-4 text-electric" /> Memory
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
            <HardDrive className="h-4 w-4 text-electric" /> Storage
          </h3>
          {m ? (
            <>
              <div className="mb-2 flex justify-between text-sm text-muted">
                <span>{formatBytes(m.disk.used_bytes)} used</span>
                <span>{formatBytes(m.disk.total_bytes)}</span>
              </div>
              <ProgressBar percent={m.disk.percent} tone="bg-primary" />
            </>
          ) : (
            <p className="text-sm text-muted">Unavailable</p>
          )}
        </Card>
        <Card>
          <h3 className="mb-3 flex items-center gap-2 font-semibold text-white">
            <Wifi className="h-4 w-4 text-electric" /> Network Activity
          </h3>
          {m ? (
            <div className="space-y-2 text-sm">
              <div className="flex justify-between"><span className="text-muted">Received</span><span className="font-medium text-white">{formatBytes(m.network.bytes_recv)}</span></div>
              <div className="flex justify-between"><span className="text-muted">Sent</span><span className="font-medium text-white">{formatBytes(m.network.bytes_sent)}</span></div>
              <div className="flex justify-between"><span className="text-muted">Packets in</span><span className="font-medium text-white">{m.network.packets_recv.toLocaleString()}</span></div>
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
                  <p className="truncate text-xs text-muted">{a.resource_type || 'system'} · {relativeTime(a.created_at)}</p>
                </div>
              </div>
            ))}
          </div>
        </Card>
        <Card>
          <div className="mb-4 flex items-center justify-between">
            <h3 className="font-semibold text-white">Recent Provisioning Tasks</h3>
            <Link to="/tasks" className="text-xs font-semibold text-electric hover:underline">View all</Link>
          </div>
          <div className="space-y-3">
            {(activity.data?.tasks ?? []).length === 0 && <p className="text-sm text-muted">No tasks yet</p>}
            {(activity.data?.tasks ?? []).map((t) => (
              <div key={t.id} className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-white">{titleCase(t.task_type.replace(/_/g, ' '))}</p>
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
