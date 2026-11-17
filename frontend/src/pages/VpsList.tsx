import { FormEvent, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
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
import { Badge, Button, ConfirmDialog, EmptyState, ErrorState, Input, LoadingState, PageHeader, Select, TableShell } from '../components/ui'
import { useAuth } from '../lib/auth'

export default function VpsList() {
  const navigate = useNavigate()
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

      {notice && <div className="mb-4 rounded-lg border border-color bg-card px-4 py-2.5 text-sm text-secondary">{notice}</div>}

      <div className="mb-4 grid grid-cols-1 gap-3 md:grid-cols-4">
        <form onSubmit={submitSearch} className="relative md:col-span-2">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-secondary" />
          <Input
            className="pl-10"
            placeholder="Search name, hostname or IP…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </form>
        <Select label="Status" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} className="md:col-span-1">
          <option value="">All statuses</option>
          <option value="running">Running</option>
          <option value="stopped">Stopped</option>
          <option value="provisioning">Provisioning</option>
          <option value="pending">Pending</option>
          <option value="error">Error</option>
        </Select>
        <Select label="Operating system" value={osFilter} onChange={(e) => setOsFilter(e.target.value)} className="md:col-span-1">
          <option value="">All operating systems</option>
          <option value="ubuntu">Ubuntu</option>
          <option value="debian">Debian</option>
        </Select>
      </div>

      <div className="mb-3 flex items-center gap-2">
        <Select label="Sort" value={sort} onChange={(e) => setSort(e.target.value)} className="w-auto">
          <option value="-created_at">Newest first</option>
          <option value="created_at">Oldest first</option>
          <option value="name">Name A–Z</option>
          <option value="-name">Name Z–A</option>
          <option value="status">Status</option>
        </Select>
        <Button variant="ghost" onClick={() => load()} loading={loading}>
          <RefreshCw className="h-4 w-4" /> Refresh
        </Button>
      </div>

      {loading && <LoadingState />}
      {error && !loading && <ErrorState message={error} onRetry={load} />}
      {!loading && !error && data && data.items.length === 0 && (
        <EmptyState
          title="No VPS instances found"
          hint={can('vps:manage') ? 'Adjust filters or create your first virtual machine. A KVM-capable online node is required.' : 'No VPS is assigned to your account yet.'}
          action={can('vps:manage') ? (
            <Link to="/vps/create">
              <Button>
                <Plus className="h-4 w-4" /> Create VPS
              </Button>
            </Link>
          ) : undefined}
        />
      )}

      {!loading && data && data.items.length > 0 && (
        <>
          <TableShell headers={['VPS', 'Operating System', 'IP Address', 'Resources', 'Node', 'Status', 'Created', 'Actions']}>
            {data.items.map((vps) => (
              <tr
                key={vps.id}
                className="cursor-pointer"
                onClick={(event) => {
                  // Preserve native link behavior (including open in new tab).
                  if ((event.target as HTMLElement).closest('a, button, input, select, textarea')) return
                  navigate(`/vps/${vps.public_id}`)
                }}
              >
                <td>
                  <Link to={`/vps/${vps.public_id}`} className="font-semibold text-white hover:text-white">
                    {vps.name}
                  </Link>
                  <p className="font-mono text-xs text-secondary">{vps.public_id.slice(0, 13)}…</p>
                </td>
                <td className="text-secondary">{vps.template_name?.replace(' cloud', '') ?? `Template #${vps.template_id}`}</td>
                <td className="font-mono text-xs text-white">{vps.ip_address || '—'}</td>
                <td>
                  <div className="space-y-1 text-xs text-secondary">
                    <span className="flex items-center gap-1.5"><Cpu className="h-3.5 w-3.5 shrink-0" />{vps.vcpus} vCPU</span>
                    <span className="flex items-center gap-1.5"><MemoryStick className="h-3.5 w-3.5 shrink-0" />{formatMb(vps.ram_mb)}</span>
                    <span className="flex items-center gap-1.5"><HardDrive className="h-3.5 w-3.5 shrink-0" />{vps.disk_gb} GB</span>
                  </div>
                </td>
                <td className="text-secondary">{vps.node_name || `Node #${vps.node_id}`}</td>
                <td>
                  <Badge value={vps.status} />
                  {vps.status === 'error' && vps.last_error && (
                    <p className="mt-1 max-w-[180px] truncate text-xs text-secondary" title={vps.last_error}>{vps.last_error}</p>
                  )}
                </td>
                <td className="text-xs text-secondary">{formatDate(vps.created_at)}</td>
                <td onClick={(event) => event.stopPropagation()}>
                  <div className="flex items-center gap-1">
                    {(can('vps:manage') || can('vps:power')) && (
                      <>
                        <IconBtn title="Start" disabled={busy || vps.status === 'running'} onClick={() => action(vps, 'start')}>
                          <Play className="h-4 w-4" />
                        </IconBtn>
                        <IconBtn title="Graceful shutdown" disabled={busy} onClick={() => action(vps, 'shutdown')}>
                          <Square className="h-4 w-4" />
                        </IconBtn>
                        <IconBtn title="Force stop" disabled={busy} onClick={() => action(vps, 'stop')}>
                          <span className="text-xs font-bold">■</span>
                        </IconBtn>
                        <IconBtn title="Restart" disabled={busy} onClick={() => action(vps, 'restart')}>
                          <RotateCcw className="h-4 w-4" />
                        </IconBtn>
                      </>
                    )}
                    <button
                      type="button"
                      title="Open SSHX in new tab"
                      disabled={vps.status !== 'running'}
                      onClick={() => window.open(`/vps/${vps.public_id}/sshx`, '_blank', 'noopener')}
                      className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-color text-secondary hover:bg-card hover:text-white disabled:opacity-40"
                    >
                      <SquareTerminal className="h-4 w-4" />
                    </button>
                    {can('vps:manage') && (
                      <IconBtn title="Delete" disabled={busy} onClick={() => setToDelete(vps)}>
                        <Trash2 className="h-4 w-4" />
                      </IconBtn>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </TableShell>

          <div className="mt-4 flex items-center justify-between text-sm text-secondary">
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
        confirmLabel="Delete forever"
        loading={busy}
        onClose={() => setToDelete(null)}
        onConfirm={confirmDelete}
        message={
          <>
            This will destroy the domain and its virtual disks for <strong>{toDelete?.name}</strong>. Type-confirm is enforced server-side; the
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
}: {
  children: React.ReactNode
  title: string
  onClick: () => void
  disabled?: boolean
}) {
  return (
    <button
      title={title}
      onClick={onClick}
      disabled={disabled}
      className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-color text-secondary transition-colors duration-150 disabled:opacity-30 disabled:cursor-not-allowed hover:bg-card hover:text-white"
    >
      {children}
    </button>
  )
}
