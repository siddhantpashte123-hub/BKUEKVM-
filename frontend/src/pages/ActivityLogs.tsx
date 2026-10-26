import { useEffect, useState } from 'react'
import { ScrollText, Search } from 'lucide-react'
import { api, ApiError } from '../lib/api'
import { formatDate, titleCase } from '../lib/format'
import type { AuditLog } from '../lib/types'
import { Card, EmptyState, ErrorState, LoadingState, PageHeader, TableShell } from '../components/ui'

export default function ActivityLogs() {
  const [logs, setLogs] = useState<AuditLog[]>([])
  const [filter, setFilter] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    api
      .get<AuditLog[]>('/api/audit-logs', { limit: 300, action: filter })
      .then(setLogs)
      .catch((err) => setError(err instanceof ApiError ? err.message : 'Failed to load logs'))
      .finally(() => setLoading(false))
  }, [filter])

  if (loading) return <LoadingState label="Loading audit trail…" />

  return (
    <div>
      <PageHeader title="Activity Logs" description="Tamper-evident record of authentication and administrative actions" />
      {error && <ErrorState message={error} />}

      <Card className="mb-4">
        <div className="relative max-w-sm">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
          <input
            className="input-base pl-10"
            placeholder="Filter by action, e.g. vps.create"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
        </div>
      </Card>

      {logs.length === 0 ? (
        <EmptyState title="No audit entries match" hint="Try clearing the action filter." />
      ) : (
        <div className="card-base overflow-x-auto">
          <TableShell headers={['Time', 'Action', 'Resource', 'User', 'IP', 'Details']}>
            {logs.map((log) => (
              <tr key={log.id}>
                <td className="whitespace-nowrap text-xs text-muted">{formatDate(log.created_at)}</td>
                <td>
                  <span className="flex items-center gap-1.5 font-medium text-electric">
                    <ScrollText className="h-3.5 w-3.5" />
                    {titleCase(log.action)}
                  </span>
                </td>
                <td className="text-muted">
                  {log.resource_type} {log.resource_id && <span className="font-mono text-xs">#{log.resource_id.slice(0, 12)}</span>}
                </td>
                <td className="text-muted">{log.user_id ? `User #${log.user_id}` : 'system'}</td>
                <td className="font-mono text-xs text-muted">{log.ip_address}</td>
                <td className="max-w-[260px] truncate text-xs text-muted" title={log.details}>{log.details}</td>
              </tr>
            ))}
          </TableShell>
        </div>
      )}
    </div>
  )
}
