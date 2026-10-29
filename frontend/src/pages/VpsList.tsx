import { FormEvent, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Cpu,
  HardDrive,
  MemoryStick,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  Search,
  SquareTerminal,
  Square,
  Trash2,
} from 'lucide-react'
import { api, ApiError } from '../lib/api'
import { formatDate, formatMb } from '../lib/format'
import type { Paginated, VPS } from '../lib/types'
import { Badge, Button, ConfirmDialog, EmptyState, ErrorState, LoadingState, PageHeader, TableShell } from '../components/ui'
import { useAuth } from '../lib/auth'

export default function VpsList() {
  const { can } = useAuth()
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [osFilter, setOsFilter] = useState('')
  const [sort, setSort] = useState('-created_at')
  const [page, setPage] = useState(1)
  const [data, setData] = useState<Paginated<VPS> | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [toDelete, setToDelete] = useState<VPS | null>(null)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const pageSize = 10

  const load = async (targetPage = page) => {
    setLoading(true)
    setError('')
    try {
      setData(
        await api.get<Paginated<VPS>>('/api/vps', {
          search,
          status: statusFilter,
          os: osFilter,
          sort,
          page: targetPage,
          page_size: pageSize,
        }),
      )
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load VPS instances')
    } finally {
      setLoading(false)
    }
  }

  // Reload whenever filters change (resetting to page 1)
  useEffect(() => {
    setPage(1)
    load(1)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search, statusFilter, osFilter, sort])

  useEffect(() => {
    load(page)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page])

  const action = async (vps: VPS, kind: 'start' | 'stop' | 'shutdown' | 'restart') => {
    setBusy(true)
    setNotice('')
    try {
      const res = await api.post<{ message: string }>(`/api/vps/${vps.public_id}/actions/${kind}`, {})
      setNotice(res.message)
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Action failed')
    } finally {
      setBusy(false)
    }
  }

  const confirmDelete = async () => {
    if (!toDelete) return
    setBusy(true)
    try {
      await api.delete(`/api/vps/${toDelete.public_id}`, { confirm: toDelete.name })
      setToDelete(null)
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Delete failed')
    } finally {
      setBusy(false)
    }
  }

  const submitSearch = (e: FormEvent) => {
    e.preventDefault()
    load()
  }

  return (
    <div>
      <PageHeader
        title="VPS Instances"
        description="Manage the full lifecycle of every virtual machine"
        actions={
          can('vps:manage') && (
            <Link to="/vps/create">
              <Button>
                <Plus className="h-4 w-4" /> Create VPS
              </Button>
            </Link>
          )
        }
      />

      {notice && <div className="mb-4 rounded-lg border border-electric/40 bg-electric/10 px-4 py-2.5 text-sm text-white">{notice}</div>}

      <div className="mb-4 grid grid-cols-1 gap-3 md:grid-cols-4">
        <form onSubmit={submitSearch} className="relative md:col-span-2">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
          <input
            className="input-base pl-10"
            placeholder="Search name, hostname or IP…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </form>
        <select className="input-base" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="">All statuses</option>
          <option value="running">Running</option>
          <option value="stopped">Stopped</option>
          <option value="provisioning">Provisioning</option>
          <option value="pending">Pending</option>
          <option value="error">Error</option>
        </select>
        <select className="input-base" value={osFilter} onChange={(e) => setOsFilter(e.target.value)}>
          <option value="">All operating systems</option>
          <option value="ubuntu">Ubuntu</option>
          <option value="debian">Debian</option>
        </select>
      </div>

      <div className="mb-3 flex items-center gap-2">
        <select className="input-base w-auto" value={sort} onChange={(e) => setSort(e.target.value)}>
          <option value="-created_at">Newest first</option>
          <option value="created_at">Oldest first</option>
          <option value="name">Name A–Z</option>
          <option value="-name">Name Z–A</option>
          <option value="status">Status</option>
        </select>
        <Button variant="ghost" onClick={() => load()} loading={loading}>
          <RefreshCw className="h-4 w-4" /> Refresh
        </Button>
      </div>

      {loading && <LoadingState />}
      {error && !loading && <ErrorState message={error} onRetry={load} />}
      {!loading && !error && data && data.items.length === 0 && (
        <EmptyState
          title="No VPS instances found"
          hint="Adjust filters or create your first virtual machine. A KVM-capable online node is required."
          action={
            <Link to="/vps/create">
              <Button>
                <Plus className="h-4 w-4" /> Create VPS
              </Button>
            </Link>
          }
        />
      )}

      {!loading && data && data.items.length > 0 && (
        <>
          <TableShell
            headers={['VPS', 'Operating System', 'IP Address', 'Resources', 'Node', 'Status', 'Created', 'Actions']}
          >
            {data.items.map((vps) => (
              <tr key={vps.id}>
                <td>
                  <Link to={`/vps/${vps.public_id}`} className="font-semibold text-white hover:text-electric">
                    {vps.name}
                  </Link>
                  <p className="font-mono text-xs text-muted">{vps.public_id.slice(0, 13)}…</p>
                </td>
                <td className="text-muted">{vps.template_name?.replace(' cloud', '') ?? `Template #${vps.template_id}`}</td>
                <td className="font-mono text-xs text-white">{vps.ip_address || '—'}</td>
                <td>
                  <div className="space-y-1 text-xs text-muted">
                    <span className="flex items-center gap-1.5"><Cpu className="h-3.5 w-3.5 text-electric" />{vps.vcpus} vCPU</span>
                    <span className="flex items-center gap-1.5"><MemoryStick className="h-3.5 w-3.5 text-electric" />{formatMb(vps.ram_mb)}</span>
                    <span className="flex items-center gap-1.5"><HardDrive className="h-3.5 w-3.5 text-electric" />{vps.disk_gb} GB</span>
                  </div>
                </td>
                <td className="text-muted">{vps.node_name || `Node #${vps.node_id}`}</td>
                <td>
                  <Badge value={vps.status} />
                  {vps.status === 'error' && vps.last_error && (
                    <p className="mt-1 max-w-[180px] truncate text-xs text-danger" title={vps.last_error}>{vps.last_error}</p>
                  )}
                </td>
                <td className="text-xs text-muted">{formatDate(vps.created_at)}</td>
                <td>
                  <div className="flex items-center gap-1">
                    {can('vps:manage') && (
                      <>
                        <IconBtn title="Start" disabled={busy || vps.status === 'running'} onClick={() => action(vps, 'start')}>
                          <Play className="h-4 w-4" />
                        </IconBtn>
                        <IconBtn title="Graceful shutdown" disabled={busy} onClick={() => action(vps, 'shutdown')}>
                          <Square className="h-4 w-4" />
                        </IconBtn>
                        <IconBtn title="Force stop" disabled={busy} onClick={() => action(vps, 'stop')}>
                          <Trash2 className="hidden h-4 w-4" />
                          <span className="text-xs font-bold">■</span>
                        </IconBtn>
                        <IconBtn title="Restart" disabled={busy} onClick={() => action(vps, 'restart')}>
                          <RotateCcw className="h-4 w-4" />
                        </IconBtn>
                      </>
                    )}
                    <button
                      type="button"
                      title="Open SSH in new tab"
                      disabled={vps.status !== 'running'}
                      onClick={() => window.open(`/vps/${vps.public_id}/ssh`, '_blank', 'noopener')}
                      className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-muted hover:bg-primary/15 hover:text-electric disabled:opacity-40"
                    >
                      <SquareTerminal className="h-4 w-4" />
                    </button>
                    {can('vps:manage') && (
                      <IconBtn title="Delete" danger disabled={busy} onClick={() => setToDelete(vps)}>
                        <Trash2 className="h-4 w-4" />
                      </IconBtn>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </TableShell>

          <div className="mt-4 flex items-center justify-between text-sm text-muted">
            <span>
              Page {data.page} of {data.pages} · {data.total} instance{data.total === 1 ? '' : 's'}
            </span>
            <div className="flex gap-2">
              <Button variant="secondary" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
                Previous
              </Button>
              <Button variant="secondary" disabled={page >= data.pages} onClick={() => setPage((p) => p + 1)}>
                Next
              </Button>
            </div>
          </div>
        </>
      )}

      <ConfirmDialog
        open={!!toDelete}
        title="Delete VPS"
        danger
        confirmLabel="Delete forever"
        loading={busy}
        onClose={() => setToDelete(null)}
        onConfirm={confirmDelete}
        message={
          <>
            This will <strong className="text-white">destroy the domain and its virtual disks</strong> for{' '}
            <strong className="text-electric">{toDelete?.name}</strong>. Type-confirm is enforced server-side; the
            queued deletion task must finish before the name can be reused. This cannot be undone.
          </>
        }
      />
    </div>
  )
}

function IconBtn({
  children,
  title,
  onClick,
  disabled,
  danger,
}: {
  children: React.ReactNode
  title: string
  onClick: () => void
  disabled?: boolean
  danger?: boolean
}) {
  return (
    <button
      title={title}
      onClick={onClick}
      disabled={disabled}
      className={`inline-flex h-8 w-8 items-center justify-center rounded-lg transition disabled:opacity-30 ${
        danger ? 'text-muted hover:bg-danger/15 hover:text-danger' : 'text-muted hover:bg-primary/15 hover:text-electric'
      }`}
    >
      {children}
    </button>
  )
}
