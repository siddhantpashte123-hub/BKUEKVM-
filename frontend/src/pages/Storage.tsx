import { useEffect, useState } from 'react'
import { HardDrive, Wallet } from 'lucide-react'
import { api, ApiError } from '../lib/api'
import { formatBytes } from '../lib/format'
import type { StoragePool } from '../lib/types'
import { Badge, Card, EmptyState, ErrorState, LoadingState, PageHeader, ProgressBar, TableShell } from '../components/ui'

interface Allocation {
  vps_id: string
  vps_name: string
  disk_gb: number
  node_id: number
}

export default function Storage() {
  const [pools, setPools] = useState<StoragePool[]>([])
  const [allocations, setAllocations] = useState<Allocation[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    Promise.all([api.get<StoragePool[]>('/api/storage/pools'), api.get<Allocation[]>('/api/storage/allocations')])
      .then(([p, a]) => {
        setPools(p)
        setAllocations(a)
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : 'Failed to load storage'))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <LoadingState label="Loading storage…" />
  if (error) return <ErrorState message={error} />

  return (
    <div>
      <PageHeader title="Storage" description="Libvirt storage pools and per-VPS disk allocations" />

      {pools.length === 0 ? (
        <EmptyState
          title="No storage pools registered"
          hint="Pools are discovered from connected nodes during health checks. Provisioning uses /var/lib/bluekvm/vms by default."
        />
      ) : (
        <div className="mb-6 grid gap-4 lg:grid-cols-2">
          {pools.map((pool) => {
            const percent = pool.capacity_bytes ? (pool.used_bytes / pool.capacity_bytes) * 100 : 0
            return (
              <Card key={pool.id}>
                <div className="flex items-start justify-between">
                  <div>
                    <h3 className="flex items-center gap-2 font-bold text-white">
                      <Wallet className="h-4 w-4 shrink-0" /> {pool.name}
                    </h3>
                    <p className="mt-1 font-mono text-xs text-secondary">{pool.path || pool.pool_type}</p>
                  </div>
                  <Badge value={pool.status} />
                </div>
                <div className="mt-4">
                  <div className="mb-2 flex justify-between text-sm text-secondary">
                    <span>{formatBytes(pool.used_bytes)} used</span>
                    <span>{formatBytes(pool.capacity_bytes)} total</span>
                  </div>
                  <ProgressBar percent={percent} />
                  <p className="mt-2 text-xs text-secondary">{formatBytes(pool.capacity_bytes - pool.used_bytes)} available</p>
                </div>
              </Card>
            )
          })}
        </div>
      )}

      <Card>
        <h3 className="mb-4 flex items-center gap-2 font-semibold text-white">
          <HardDrive className="h-4 w-4 shrink-0" /> VPS disk allocations
        </h3>
        {allocations.length === 0 ? (
          <p className="text-sm text-secondary">No VPS disks allocated yet</p>
        ) : (
          <TableShell headers={['VPS', 'Disk', 'Node']}>
            {allocations.map((a) => (
              <tr key={a.vps_id}>
                <td className="font-medium text-white">{a.vps_name}</td>
                <td>{a.disk_gb} GB qcow2</td>
                <td className="text-secondary">Node #{a.node_id}</td>
              </tr>
            ))}
          </TableShell>
        )}
      </Card>
    </div>
  )
}
