import { useEffect, useState } from 'react'
import { api, ApiError } from '../lib/api'
import { formatDate, titleCase } from '../lib/format'
import type { Task } from '../lib/types'
import { Badge, Card, EmptyState, ErrorState, LoadingState, PageHeader, ProgressBar } from '../components/ui'

export default function Tasks() {
  const [tasks, setTasks] = useState<Task[]>([])
  const [open, setOpen] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = async () => {
    try {
      setTasks(await api.get<Task[]>('/api/tasks', { limit: 200 }))
      setError('')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load tasks')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    const id = setInterval(load, 5000)
    return () => clearInterval(id)
  }, [])

  if (loading) return <LoadingState label="Loading background tasks…" />

  return (
    <div>
      <PageHeader title="Background Tasks" description="Durable provisioning, lifecycle and backup jobs with timestamped step logs" />
      {error && <ErrorState message={error} onRetry={load} />}

      {tasks.length === 0 ? (
        <EmptyState title="No tasks yet" hint="Creating a VPS or running a lifecycle action queues a task here." />
      ) : (
        <div className="space-y-3">
          {tasks.map((task) => (
            <Card key={task.id}>
              <button className="flex w-full items-center justify-between gap-3 text-left" onClick={() => setOpen(open === task.id ? null : task.id)}>
                <div>
                  <p className="font-semibold text-white">
                    {titleCase(task.task_type.replace(/_/g, ' '))} <span className="text-muted">#{task.id}</span>
                    {task.vps_id && <span className="ml-2 text-xs text-muted">VPS #{task.vps_id}</span>}
                  </p>
                  <p className="mt-1 text-xs text-muted">{formatDate(task.created_at)}</p>
                </div>
                <div className="flex items-center gap-3">
                  <div className="hidden w-40 sm:block"><ProgressBar percent={task.progress} /></div>
                  <Badge value={task.status} />
                </div>
              </button>

              {open === task.id && (
                <div className="mt-4 space-y-3 border-t border-line pt-4">
                  <div className="grid gap-2 sm:grid-cols-2">
                    {task.steps.map((step, i) => (
                      <div key={i} className="rounded-lg border border-line bg-input p-2.5 text-xs">
                        <div className="flex items-center justify-between">
                          <span className="font-medium text-white">{step.name}</span>
                          <Badge value={step.status} />
                        </div>
                        {step.detail && <p className="mt-1 break-all text-muted">{step.detail}</p>}
                      </div>
                    ))}
                  </div>
                  {task.logs && (
                    <pre className="max-h-64 overflow-auto rounded-lg bg-black p-3 font-mono text-xs text-muted">{task.logs}</pre>
                  )}
                  {task.error && <p className="rounded-lg border border-danger/40 bg-danger/10 p-3 text-xs text-danger">{task.error}</p>}
                </div>
              )}
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
