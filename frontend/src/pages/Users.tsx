import { useEffect, useState } from 'react'
import { Plus, Trash2, UserX } from 'lucide-react'
import { api, ApiError } from '../lib/api'
import { formatDate } from '../lib/format'
import type { Role, User } from '../lib/types'
import { Badge, Button, Card, ConfirmDialog, EmptyState, ErrorState, Input, LoadingState, Modal, PageHeader, Select } from '../components/ui'
import { useAuth } from '../lib/auth'

export default function Users() {
  const { user: currentUser } = useAuth()
  const [users, setUsers] = useState<User[]>([])
  const [roles, setRoles] = useState<Role[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [showCreate, setShowCreate] = useState(false)
  const [busy, setBusy] = useState(false)
  const [toDelete, setToDelete] = useState<User | null>(null)
  const [form, setForm] = useState({ username: '', email: '', password: '', role_id: '' })

  const load = async () => {
    try {
      const [u, r] = await Promise.all([api.get<User[]>('/api/users'), api.get<Role[]>('/api/users/roles')])
      setUsers(u)
      setRoles(r)
      setError('')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load users')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const create = async () => {
    setBusy(true)
    setError('')
    try {
      await api.post('/api/users', { ...form, role_id: Number(form.role_id) })
      setShowCreate(false)
      setForm({ username: '', email: '', password: '', role_id: '' })
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'User creation failed')
    } finally {
      setBusy(false)
    }
  }

  const toggleActive = async (u: User) => {
    await api.patch(`/api/users/${u.id}`, { is_active: !u.is_active })
    await load()
  }

  const revokeSessions = async (u: User) => {
    await api.post(`/api/users/${u.id}/revoke-sessions`)
    setError('')
    load()
  }

  const remove = async () => {
    if (!toDelete) return
    setBusy(true)
    try {
      await api.delete(`/api/users/${toDelete.id}`)
      setToDelete(null)
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Delete failed')
    } finally {
      setBusy(false)
    }
  }

  if (loading) return <LoadingState label="Loading users…" />

  return (
    <div>
      <PageHeader
        title="Users & Permissions"
        description="Role-based access control with four seeded roles"
        actions={
          <Button onClick={() => setShowCreate(true)}>
            <Plus className="h-4 w-4" /> New user
          </Button>
        }
      />

      {error && <ErrorState message={error} onRetry={load} />}

      <Card className="mb-5">
        <h3 className="mb-3 font-semibold text-white">Roles</h3>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {roles.map((r) => (
            <div key={r.id} className="rounded-lg border border-line bg-input p-3">
              <p className="text-sm font-semibold text-white">{r.name}</p>
              <p className="mt-1 text-xs text-muted">
                {r.permissions.includes('*') ? 'Full access (wildcard)' : `${r.permissions.length} permissions`}
              </p>
            </div>
          ))}
        </div>
      </Card>

      {users.length === 0 ? (
        <EmptyState title="No users" />
      ) : (
        <div className="card-base overflow-x-auto">
          <table className="table-base min-w-[720px]">
            <thead>
              <tr>
                <th>User</th>
                <th>Role</th>
                <th>Status</th>
                <th>Last login</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id}>
                  <td>
                    <p className="font-semibold text-white">
                      {u.username}
                      {u.is_superuser && <span className="ml-2 rounded border border-electric/50 px-1.5 py-0.5 text-[10px] uppercase text-electric">super</span>}
                    </p>
                    <p className="text-xs text-muted">{u.email}</p>
                  </td>
                  <td className="text-muted">{roles.find((r) => r.id === u.role_id)?.name ?? u.role_id}</td>
                  <td>
                    <Badge value={u.is_active ? 'active' : 'offline'} />
                  </td>
                  <td className="text-xs text-muted">{formatDate(u.last_login_at)}</td>
                  <td>
                    <div className="flex gap-1">
                      <Button variant="ghost" className="px-2 py-1.5 text-xs" onClick={() => revokeSessions(u)}>
                        <UserX className="h-3.5 w-3.5" /> Revoke sessions
                      </Button>
                      <Button variant="ghost" className="px-2 py-1.5 text-xs" onClick={() => toggleActive(u)}>
                        {u.is_active ? 'Disable' : 'Enable'}
                      </Button>
                      {!u.is_superuser && u.id !== currentUser?.id && (
                        <Button variant="ghost" className="px-2 py-1.5 text-xs hover:text-danger" onClick={() => setToDelete(u)}>
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Modal open={showCreate} onClose={() => setShowCreate(false)} title="Create user">
        <div className="space-y-4">
          <Input label="Username" placeholder="jdoe" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} />
          <Input label="Email" type="email" placeholder="jdoe@example.com" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          <Input label="Password (min 12 chars, mixed classes)" type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
          <Select label="Role" value={form.role_id} onChange={(e) => setForm({ ...form, role_id: e.target.value })}>
            <option value="">Select role…</option>
            {roles.map((r) => (
              <option key={r.id} value={r.id}>{r.name}</option>
            ))}
          </Select>
          <Button className="w-full" loading={busy} onClick={create}>Create user</Button>
        </div>
      </Modal>

      <ConfirmDialog
        open={!!toDelete}
        title="Delete user"
        danger
        confirmLabel="Delete"
        loading={busy}
        onClose={() => setToDelete(null)}
        onConfirm={remove}
        message={<>Delete user <strong className="text-electric">{toDelete?.username}</strong>? Their audit history is retained.</>}
      />
    </div>
  )
}
