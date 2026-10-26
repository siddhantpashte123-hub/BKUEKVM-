import { useEffect, useState } from 'react'
import { Archive, Camera, RefreshCw, Trash2 } from 'lucide-react'
import { api, ApiError } from '../lib/api'
import { formatBytes, formatDate } from '../lib/format'
import type { Backup, VPS } from '../lib/types'
import { Badge, Button, Card, ConfirmDialog, EmptyState, ErrorState, LoadingState, PageHeader, Select } from '../components/ui'
import { useAuth } from '../lib/auth'

export default function Backups() {
  const { can } = useAuth()
  const [backups, setBackups] = useState<Backup[]>([])
  const [vpsList, setVpsList] = useState<VPS[]>([])
  const [selected, setSelected] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [toDelete, setToDelete] = useState<Backup | null>(null)
  const [toRestore, setToRestore] = useState<Backup | null>(null)

  const load = async () => {
    try {
      const [b, v] = await Promise.all([api.get<Backup[]>('/api/backups'), api.get<{ items: VPS[] }>('/api/vps', { page_size: 100 })])
      setBackups(b)
      setVpsList(v.items)
      setError('')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load backups')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    const id = setInterval(load, 8000)
    return () => clearInterval(id)
  }, [])

  const create = async (kind: 'backup' | 'snapshot') => {
    if (!selected) {
      setError('Select a VPS first')
      return
    }
    setBusy(true)
    setError('')
    try {
      const res = await api.post<{ message: string }>(`/api/backups/vps/${selected}`, undefined, { backup_type: kind })
      setNotice(res.message)
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Backup job failed')
    } finally {
      setBusy(false)
    }
  }

  const restore = async () => {
    if (!toRestore) return
    setBusy(true)
    try {
      await api.post(`/api/backups/${toRestore.id}/restore`)
      setToRestore(null)
      setNotice('Restore queued')
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Restore failed')
    } finally {
      setBusy(false)
    }
  }

  const remove = async () => {
    if (!toDelete) return
    setBusy(true)
    try {
      await api.delete(`/api/backups/${toDelete.id}`)
      setToDelete(null)
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Delete failed')
    } finally {
      setBusy(false)
    }
  }

  if (loading) return <LoadingState label="Loading backups…" />

  return (
    <div>
      <PageHeader title="Backups" description="Verified disk backups and libvirt snapshots — snapshots are not independent backups" />

      {notice && <div className="mb-4 rounded-lg border border-electric/40 bg-electric/10 px-4 py-2.5 text-sm text-white">{notice}</div>}
      {error && <ErrorState message={error} onRetry={load} />}

      {can('backup:manage') && (
        <Card className="mb-6">
          <div className="flex flex-wrap items-end gap-3">
            <div className="min-w-[240px] flex-1">
              <Select label="Target VPS" value={selected} onChange={(e) => setSelected(e.target.value)}>
                <option value="">Select a VPS…</option>
                {vpsList.map((v) => (
                  <option key={v.public_id} value={v.public_id}>{v.name} ({v.status})</option>
                ))}
              </Select>
            </div>
            <Button variant="secondary" loading={busy} onClick={() => create('snapshot')}>
              <Camera className="h-4 w-4" /> Create snapshot
            </Button>
            <Button loading={busy} onClick={() => create('backup')}>
              <Archive className="h-4 w-4" /> Create full backup
            </Button>
          </div>
          <p className="mt-3 text-xs text-muted">
            A snapshot is a qcow2 delta tied to the running domain. A full backup is an independent, checksum-verified
            disk copy. Backups are marked successful only after the output file is verified.
          </p>
        </Card>
      )}

      {backups.length === 0 ? (
        <EmptyState title="No backups yet" hint="Full backups and snapshots created here appear with verification status and size." />
      ) : (
        <div className="card-base overflow-x-auto">
          <table className="table-base min-w-[760px]">
            <thead>
              <tr>
                <th>Type</th>
                <th>VPS</th>
                <th>Reference</th>
                <th>Size</th>
                <th>Created</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {backups.map((b) => (
                <tr key={b.id}>
                  <td>
                    <Badge value={b.backup_type} />
                  </td>
                  <td className="text-white">#{b.vps_id}</td>
                  <td className="max-w-[220px] truncate font-mono text-xs text-muted">{b.snapshot_name || b.path}</td>
                  <td>{formatBytes(b.size_bytes)}</td>
                  <td className="text-muted">{formatDate(b.created_at)}</td>
                  <td>
                    <Badge value={b.status} />
                    {b.error && <p className="mt-1 max-w-[160px] truncate text-xs text-danger" title={b.error}>{b.error}</p>}
                  </td>
                  <td>
                    {can('backup:manage') && (
                      <div className="flex gap-1">
                        {b.backup_type === 'backup' && b.status === 'ready' && (
                          <Button variant="ghost" className="px-2 py-1.5 text-xs" onClick={() => setToRestore(b)}>
                            <RefreshCw className="h-3.5 w-3.5" /> Restore
                          </Button>
                        )}
                        <Button variant="ghost" className="px-2 py-1.5 text-xs hover:text-danger" onClick={() => setToDelete(b)}>
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <ConfirmDialog
        open={!!toRestore}
        title="Restore backup"
        danger
        confirmLabel="Restore now"
        loading={busy}
        onClose={() => setToRestore(null)}
        onConfirm={restore}
        message={<>The current disk of VPS #{toRestore?.vps_id} will be overwritten with this backup. The VM is stopped and restarted during restore.</>}
      />
      <ConfirmDialog
        open={!!toDelete}
        title="Delete backup"
        danger
        confirmLabel="Delete"
        loading={busy}
        onClose={() => setToDelete(null)}
        onConfirm={remove}
        message={<>Delete {toDelete?.backup_type} <strong className="text-electric">{toDelete?.snapshot_name || toDelete?.path}</strong>?</>}
      />
    </div>
  )
}
