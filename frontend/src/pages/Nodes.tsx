import { useEffect, useState } from 'react'
import { Cpu, MemoryStick, MonitorCog, Plus, RefreshCw, Server, Trash2 } from 'lucide-react'
import { api, ApiError } from '../lib/api'
import { formatMb, relativeTime } from '../lib/format'
import type { Node } from '../lib/types'
import { Badge, Button, Card, ConfirmDialog, EmptyState, ErrorState, Input, LoadingState, Modal, PageHeader } from '../components/ui'
import { useAuth } from '../lib/auth'

interface Capabilities {
  arch: string
  kvm_available: boolean
  kvm_reason: string
  nested_virtualization: boolean
  nested_detail: string
  libvirt_python: boolean
  libvirtd_running: boolean
  qemu_installed: boolean
  cloud_image_tools: string[]
}

export default function Nodes() {
  const { can } = useAuth()
  const [nodes, setNodes] = useState<Node[]>([])
  const [caps, setCaps] = useState<Capabilities | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [showRegister, setShowRegister] = useState(false)
  const [toRemove, setToRemove] = useState<Node | null>(null)
  const [busy, setBusy] = useState(false)
  const [form, setForm] = useState({ name: '', address: '', libvirt_uri: 'qemu+tls://host/system', credential: '', is_local: false })

  const load = async () => {
    try {
      const [n, c] = await Promise.all([api.get<Node[]>('/api/nodes'), api.get<Capabilities>('/api/nodes/capabilities')])
      setNodes(n)
      setCaps(c)
      setError('')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load nodes')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const healthCheck = async (nodeId: number) => {
    setBusy(true)
    try {
      await api.post(`/api/nodes/${nodeId}/health-check`)
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Health check failed')
    } finally {
      setBusy(false)
    }
  }

  const register = async () => {
    setBusy(true)
    try {
      await api.post('/api/nodes', form)
      setShowRegister(false)
      setForm({ name: '', address: '', libvirt_uri: 'qemu+tls://host/system', credential: '', is_local: false })
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Registration failed')
    } finally {
      setBusy(false)
    }
  }

  const remove = async () => {
    if (!toRemove) return
    setBusy(true)
    try {
      await api.delete(`/api/nodes/${toRemove.id}`)
      setToRemove(null)
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Remove failed')
    } finally {
      setBusy(false)
    }
  }

  if (loading) return <LoadingState label="Loading nodes…" />

  return (
    <div>
      <PageHeader
        title="Virtualization Nodes"
        description="Register KVM hosts and verify hypervisor connectivity"
        actions={
          can('node:manage') && (
            <Button onClick={() => setShowRegister(true)}>
              <Plus className="h-4 w-4" /> Register node
            </Button>
          )
        }
      />

      {error && <ErrorState message={error} onRetry={load} />}

      {caps && (
        <Card className="mb-5">
          <h3 className="mb-3 flex items-center gap-2 font-semibold text-white">
            <MonitorCog className="h-4 w-4 text-electric" /> Local host virtualization capabilities
          </h3>
          <div className="grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
            <Cap label="KVM" ok={caps.kvm_available} detail={caps.kvm_reason} />
            <Cap label="Nested virtualization" ok={caps.nested_virtualization} detail={caps.nested_detail} />
            <Cap label="libvirt binding" ok={caps.libvirt_python} detail={caps.libvirt_python ? 'python3-libvirt present' : 'package missing'} />
            <Cap label="QEMU" ok={caps.qemu_installed} detail={caps.qemu_installed ? 'qemu-system installed' : 'not installed'} />
          </div>
          {!caps.kvm_available && (
            <p className="mt-4 rounded-lg border border-warning/40 bg-warning/10 p-3 text-xs text-warning">
              This host cannot run KVM virtual machines. On a VPS without nested virtualization, register a separate
              KVM-capable node — the panel will never simulate a successful VM.
            </p>
          )}
        </Card>
      )}

      {nodes.length === 0 ? (
        <EmptyState title="No nodes registered" hint="The local node is created automatically on first boot." />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {nodes.map((node) => (
            <Card key={node.id} className="transition hover:border-electric/40">
              <div className="flex items-start justify-between">
                <div>
                  <h3 className="flex items-center gap-2 text-lg font-bold text-white">
                    <Server className="h-4 w-4 text-electric" /> {node.name}
                    {node.is_local && <span className="rounded border border-line px-1.5 py-0.5 text-[10px] uppercase text-muted">local</span>}
                  </h3>
                  <p className="mt-1 font-mono text-xs text-muted">{node.libvirt_uri}</p>
                </div>
                <Badge value={node.status} />
              </div>

              <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
                <p className="flex items-center gap-2 text-muted"><Cpu className="h-4 w-4 text-electric" /> {node.cpu_cores || '—'} cores</p>
                <p className="flex items-center gap-2 text-muted"><MemoryStick className="h-4 w-4 text-electric" /> {node.ram_mb ? formatMb(node.ram_mb) : '—'}</p>
                <p className="text-muted">Hypervisor: <span className="text-white">{node.hypervisor_version || 'unknown'}</span></p>
                <p className="text-muted">VMs hosted: <span className="text-white">{node.vm_count}</span></p>
                <p className="text-muted">KVM: <span className={node.kvm_ready ? 'text-success' : 'text-danger'}>{node.kvm_ready ? 'ready' : 'unavailable'}</span></p>
                <p className="text-muted">Checked: <span className="text-white">{relativeTime(node.last_health_at)}</span></p>
              </div>

              {node.last_error && (
                <p className="mt-3 rounded-lg border border-danger/30 bg-danger/10 p-2.5 text-xs text-danger">{node.last_error}</p>
              )}

              <div className="mt-4 flex gap-2">
                {can('node:manage') && (
                  <>
                    <Button variant="secondary" loading={busy} onClick={() => healthCheck(node.id)}>
                      <RefreshCw className="h-4 w-4" /> Verify connection
                    </Button>
                    {!node.is_local && (
                      <Button variant="ghost" onClick={() => setToRemove(node)}>
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    )}
                  </>
                )}
              </div>
            </Card>
          ))}
        </div>
      )}

      <Modal open={showRegister} onClose={() => setShowRegister(false)} title="Register virtualization node">
        <div className="space-y-4">
          <Input label="Node name" placeholder="kvm-node-01" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <Input label="Address" placeholder="10.0.0.12 or node1.example.com" value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} />
          <Input label="libvirt URI" placeholder="qemu+tls://10.0.0.12/system" value={form.libvirt_uri} onChange={(e) => setForm({ ...form, libvirt_uri: e.target.value })} />
          <Input label="Connection secret (stored encrypted)" type="password" value={form.credential} onChange={(e) => setForm({ ...form, credential: e.target.value })} />
          <label className="flex items-center gap-2 text-sm text-muted">
            <input type="checkbox" className="accent-[#008CFF]" checked={form.is_local} onChange={(e) => setForm({ ...form, is_local: e.target.checked })} />
            This is the local panel host
          </label>
          <p className="text-xs text-muted">
            Never expose a libvirt TCP socket to the public internet. Use TLS with restricted credentials or an SSH tunnel.
          </p>
          <Button className="w-full" loading={busy} onClick={register}>Register and verify</Button>
        </div>
      </Modal>

      <ConfirmDialog
        open={!!toRemove}
        title="Remove node"
        danger
        confirmLabel="Remove"
        loading={busy}
        onClose={() => setToRemove(null)}
        onConfirm={remove}
        message={<>Disconnect <strong className="text-electric">{toRemove?.name}</strong>? Hosted VMs must be migrated first — the API enforces this.</>}
      />
    </div>
  )
}

function Cap({ label, ok, detail }: { label: string; ok: boolean; detail: string }) {
  return (
    <div className="rounded-lg border border-line bg-input p-3">
      <div className="flex items-center justify-between">
        <span className="text-xs uppercase tracking-wider text-muted">{label}</span>
        <span className={`h-2.5 w-2.5 rounded-full ${ok ? 'bg-success' : 'bg-danger'}`} />
      </div>
      <p className="mt-1.5 text-xs text-white">{detail}</p>
    </div>
  )
}
