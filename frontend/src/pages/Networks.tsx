import { useEffect, useState } from 'react'
import { Network as NetworkIcon } from 'lucide-react'
import { api, ApiError } from '../lib/api'
import type { NetworkInfo } from '../lib/types'
import { Badge, Card, EmptyState, ErrorState, LoadingState, PageHeader, TableShell } from '../components/ui'

interface Allocation {
  id: number
  address: string
  mac_address: string
  allocation_type: string
  vps_id: number | null
  vps_name: string | null
}

export default function Networks() {
  const [networks, setNetworks] = useState<NetworkInfo[]>([])
  const [allocations, setAllocations] = useState<Record<number, Allocation[]>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    api
      .get<NetworkInfo[]>('/api/networks')
      .then(async (rows) => {
        setNetworks(rows)
        const entries = await Promise.all(
          rows.map(async (n) => [n.id, await api.get<Allocation[]>(`/api/networks/${n.id}/allocations`).catch(() => [])] as const),
        )
        setAllocations(Object.fromEntries(entries))
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : 'Failed to load networks'))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <LoadingState label="Loading networks…" />
  if (error) return <ErrorState message={error} />

  return (
    <div>
      <PageHeader
        title="Network Management"
        description="Virtual networks, bridges and IP allocations. Host networking is never modified automatically."
      />
      {networks.length === 0 ? (
        <EmptyState
          title="No virtual networks discovered"
          hint="Networks appear automatically after a node connects to libvirt. The default libvirt NAT network is 'default' on virbr0."
        />
      ) : (
        <div className="space-y-5">
          {networks.map((n) => (
            <Card key={n.id}>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h3 className="flex items-center gap-2 font-bold text-white">
                    <NetworkIcon className="h-4 w-4 shrink-0" /> {n.name}
                  </h3>
                  <p className="mt-1 font-mono text-xs text-secondary">
                    bridge {n.bridge} · {n.network_type} · {n.subnet || 'no subnet'}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <Badge value={n.dhcp_enabled ? 'active' : 'offline'} />
                  <span className="rounded-lg border border-color px-2.5 py-0.5 text-xs text-secondary">
                    {n.dhcp_enabled ? 'DHCP enabled' : 'Static only'}
                  </span>
                </div>
              </div>

              <div className="mt-4">
                <TableShell headers={['IP address', 'MAC', 'Type', 'Assigned VPS']}>
                  {(allocations[n.id] ?? []).length === 0 ? (
                    <tr>
                      <td colSpan={4} className="text-sm text-secondary">No IP allocations recorded</td>
                    </tr>
                  ) : (
                    allocations[n.id].map((a) => (
                      <tr key={a.id}>
                        <td className="font-mono text-xs text-white">{a.address}</td>
                        <td className="font-mono text-xs text-secondary">{a.mac_address}</td>
                        <td className="uppercase text-secondary">{a.allocation_type}</td>
                        <td className="text-white">{a.vps_name ?? '—'}</td>
                      </tr>
                    ))
                  )}
                </TableShell>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
