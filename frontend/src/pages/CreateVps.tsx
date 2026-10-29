import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  ArrowLeft,
  ArrowRight,
  Check,
  Copy,
  Cpu,
  Globe,
  HardDrive,
  KeyRound,
  MemoryStick,
  MonitorCog,
  Server,
} from 'lucide-react'
import { api, ApiError } from '../lib/api'
import { formatMb } from '../lib/format'
import type { NetworkInfo, Node, Template, User } from '../lib/types'
import { Badge, Button, Card, ErrorState, Input, PageHeader, Select, Textarea } from '../components/ui'
import { useAuth } from '../lib/auth'

const STEPS = ['Operating System', 'VPS Details', 'Resources', 'Networking', 'Node', 'Review']

export default function CreateVps() {
  const navigate = useNavigate()
  const { can } = useAuth()
  const [step, setStep] = useState(0)
  const [templates, setTemplates] = useState<Template[]>([])
  const [nodes, setNodes] = useState<Node[]>([])
  const [networks, setNetworks] = useState<NetworkInfo[]>([])
  const [users, setUsers] = useState<User[]>([])
  const [loadError, setLoadError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState('')

  const [form, setForm] = useState({
    template_id: 0,
    name: '',
    hostname: '',
    description: '',
    owner_id: '' as number | '',
    expires_at: '',
    vcpus: 2,
    ram_mb: 2048,
    disk_gb: 25,
    network_id: '' as number | '',
    ip_address: '',
    mac_address: '',
    ssh_public_key: '',
    cloud_init_password: '',
    confirm_password: '',
    node_id: '' as number | '', // empty = automatic placement
  })
  const [generatedPw, setGeneratedPw] = useState<string | null>(null)
  const [createdId, setCreatedId] = useState('')

  const set = <K extends keyof typeof form>(key: K, value: (typeof form)[K]) =>
    setForm((f) => ({ ...f, [key]: value }))

  useEffect(() => {
    Promise.all([
      api.get<Template[]>('/api/templates'),
      api.get<Node[]>('/api/nodes'),
      api.get<NetworkInfo[]>('/api/networks'),
      can('user:read') ? api.get<User[]>('/api/users') : Promise.resolve([]),
    ])
      .then(([t, n, net, u]) => {
        setTemplates(t)
        setNodes(n)
        setNetworks(net)
        setUsers(u)
        const firstReady = t.find((x) => x.status === 'ready')
        if (firstReady) set('template_id', firstReady.id)
        if (net[0]) set('network_id', net[0].id)
      })
      .catch((err) => setLoadError(err instanceof ApiError ? err.message : 'Failed to load wizard data'))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const selectedTemplate = templates.find((t) => t.id === form.template_id)
  const readyNodes = nodes.filter((n) => n.status === 'online' && n.kvm_ready)
  const idempotencyKey = useMemo(() => crypto.randomUUID(), [])

  const validateStep = (): string => {
    if (step === 0 && (!form.template_id || selectedTemplate?.status !== 'ready'))
      return 'Select a downloaded, verified OS template'
    if (step === 1) {
      if (form.name.trim().length < 2) return 'VPS name must be at least 2 characters'
      if (!/^[A-Za-z0-9._-]+$/.test(form.name)) return 'Name may only contain letters, numbers, dots, hyphens and underscores'
      if (form.hostname.trim().length < 2) return 'Hostname is required'
    }
    if (step === 2) {
      if (form.vcpus < 1) return 'At least 1 vCPU is required'
      if (form.ram_mb < 256) return 'At least 256 MB RAM is required'
      if (form.disk_gb < 5) return 'At least 5 GB disk is required'
      if (form.mac_address && !/^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$/.test(form.mac_address))
        return 'MAC address must look like 52:54:00:ab:cd:ef'
    }
    if (step === 3) {
      if (form.cloud_init_password) {
        if (form.cloud_init_password.length < 8) return 'VM password must be at least 8 characters'
        if (form.cloud_init_password !== form.confirm_password) return 'Passwords do not match'
      }
    }
    return ''
  }

  const next = () => {
    const err = validateStep()
    if (err) {
      setSubmitError(err)
      return
    }
    setSubmitError('')
    setStep((s) => Math.min(STEPS.length - 1, s + 1))
  }

  const submit = async () => {
    setSubmitting(true)
    setSubmitError('')
    try {
      const { confirm_password: _confirm, ...rest } = form
      const payload = {
        ...rest,
        hostname: form.hostname || form.name,
        owner_id: form.owner_id || undefined,
        network_id: form.network_id || undefined,
        node_id: form.node_id || undefined,
        expires_at: form.expires_at ? new Date(form.expires_at).toISOString() : undefined,
        idempotency_key: idempotencyKey,
      }
      const created = await api.post<{ public_id: string; generated_password?: string | null }>('/api/vps', payload)
      setCreatedId(created.public_id)
      if (created.generated_password) {
        // Shown exactly once — the panel never returns it again.
        setGeneratedPw(created.generated_password)
      } else {
        navigate(`/vps/${created.public_id}`)
      }
    } catch (err) {
      setSubmitError(err instanceof ApiError ? err.message : 'Provisioning request failed')
    } finally {
      setSubmitting(false)
    }
  }

  if (loadError) return <ErrorState message={loadError} />

  if (generatedPw) {
    return (
      <div className="mx-auto max-w-2xl">
        <PageHeader title="VPS provisioning started" description="Save the generated credential now — it is shown only once." />
        <Card>
          <div className="flex items-center gap-2 text-white">
            <KeyRound className="h-5 w-5 text-electric" />
            <h2 className="font-semibold">Generated VM password</h2>
          </div>
          <div className="mt-4 flex flex-wrap items-center gap-3 rounded-lg border border-warning/40 bg-warning/10 p-4">
            <code className="break-all font-mono text-base text-warning">{generatedPw}</code>
            <Button
              variant="secondary"
              onClick={() => navigator.clipboard?.writeText(generatedPw)}
            >
              <Copy className="h-4 w-4" /> Copy
            </Button>
          </div>
          <dl className="mt-4 grid gap-2 text-sm text-muted">
            <div>Login user: <span className="text-white">ubuntu</span></div>
            <div>Use: browser SSH terminal on the VPS page, or any SSH client once the guest has an IP.</div>
          </dl>
          <p className="mt-4 text-xs text-muted">
            The password is stored encrypted on the panel and used server-side by the SSH terminal. It cannot be
            retrieved from the API later.
          </p>
          <div className="mt-6">
            <Button onClick={() => navigate(`/vps/${createdId}`)}>
              Continue to VPS <ArrowRight className="h-4 w-4" />
            </Button>
          </div>
        </Card>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-4xl">
      <PageHeader title="Create VPS" description="Multi-step provisioning wizard — resources are validated before creation" />

      {/* Stepper */}
      <div className="mb-6 flex items-center gap-1 overflow-x-auto pb-2">
        {STEPS.map((label, i) => (
          <div key={label} className="flex items-center">
            <div
              className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full border text-xs font-bold transition ${
                i < step
                  ? 'border-success bg-success/15 text-success'
                  : i === step
                    ? 'border-electric bg-electric/15 text-electric shadow-glow'
                    : 'border-line bg-input text-muted'
              }`}
            >
              {i < step ? <Check className="h-4 w-4" /> : i + 1}
            </div>
            <span className={`ml-2 mr-3 hidden whitespace-nowrap text-xs font-semibold sm:block ${i === step ? 'text-white' : 'text-muted'}`}>
              {label}
            </span>
            {i < STEPS.length - 1 && <div className="h-px w-6 bg-line sm:w-10" />}
          </div>
        ))}
      </div>

      <Card>
        {submitError && (
          <div className="mb-5 rounded-lg border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-danger">{submitError}</div>
        )}

        {step === 0 && (
          <div className="space-y-3">
            <h3 className="flex items-center gap-2 font-semibold text-white"><HardDrive className="h-4 w-4 text-electric" /> Choose an operating system</h3>
            {templates.length === 0 && <p className="text-sm text-muted">Loading templates…</p>}
            <div className="grid gap-3 sm:grid-cols-2">
              {templates.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  disabled={t.status !== 'ready'}
                  onClick={() => set('template_id', t.id)}
                  className={`rounded-lg border p-4 text-left transition disabled:cursor-not-allowed disabled:opacity-50 ${
                    form.template_id === t.id ? 'border-electric bg-electric/10 shadow-glow' : 'border-line bg-input hover:border-electric/50'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <p className="font-semibold capitalize text-white">{t.os_family} {t.version}</p>
                    <Badge value={t.status} />
                  </div>
                  <p className="mt-1 text-xs text-muted">{t.name} · {t.arch}</p>
                  {t.status !== 'ready' && (
                    <p className="mt-2 text-xs text-warning">Download from OS Templates before use</p>
                  )}
                </button>
              ))}
            </div>
          </div>
        )}

        {step === 1 && (
          <div className="grid gap-4 sm:grid-cols-2">
            <Input label="VPS name" placeholder="web-server-01" value={form.name} onChange={(e) => set('name', e.target.value)} />
            <Input label="Hostname" placeholder="web-server-01.internal" value={form.hostname} onChange={(e) => set('hostname', e.target.value)} />
            <Textarea label="Description (optional)" className="sm:col-span-2" value={form.description} onChange={(e) => set('description', e.target.value)} />
            {can('user:read') && (
              <Select label="Owner" value={String(form.owner_id)} onChange={(e) => set('owner_id', e.target.value ? Number(e.target.value) : '')}>
                <option value="">Me ({'administrator'})</option>
                {users.map((u) => (
                  <option key={u.id} value={u.id}>{u.username}</option>
                ))}
              </Select>
            )}
            <Input label="Expiration date (optional)" type="date" value={form.expires_at} onChange={(e) => set('expires_at', e.target.value)} />
          </div>
        )}

        {step === 2 && (
          <div className="space-y-5">
            <h3 className="flex items-center gap-2 font-semibold text-white"><Cpu className="h-4 w-4 text-electric" /> Resource allocation</h3>
            <div className="grid gap-4 sm:grid-cols-3">
              <div>
                <label className="label-base flex items-center gap-1.5"><Cpu className="h-3.5 w-3.5" /> vCPUs</label>
                <input type="number" min={1} max={64} className="input-base" value={form.vcpus} onChange={(e) => set('vcpus', Number(e.target.value))} />
              </div>
              <div>
                <label className="label-base flex items-center gap-1.5"><MemoryStick className="h-3.5 w-3.5" /> RAM (MB)</label>
                <input type="number" min={256} step={256} className="input-base" value={form.ram_mb} onChange={(e) => set('ram_mb', Number(e.target.value))} />
                <p className="mt-1 text-xs text-muted">{formatMb(form.ram_mb)}</p>
              </div>
              <div>
                <label className="label-base flex items-center gap-1.5"><HardDrive className="h-3.5 w-3.5" /> Disk (GB)</label>
                <input type="number" min={5} className="input-base" value={form.disk_gb} onChange={(e) => set('disk_gb', Number(e.target.value))} />
              </div>
            </div>
            <div className="rounded-lg border border-line bg-input p-4 text-sm text-muted">
              <p className="font-semibold text-white">Capacity check</p>
              <p className="mt-1">
                {readyNodes.length} KVM-ready online node{readyNodes.length === 1 ? '' : 's'} available. The API rejects
                requests that exceed node capacity — nothing is over-provisioned silently.
              </p>
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="space-y-4">
            <h3 className="flex items-center gap-2 font-semibold text-white"><Globe className="h-4 w-4 text-electric" /> Networking</h3>
            <Select label="Virtual network" value={String(form.network_id)} onChange={(e) => set('network_id', e.target.value ? Number(e.target.value) : '')}>
              <option value="">No panel-managed network</option>
              {networks.map((n) => (
                <option key={n.id} value={n.id}>{n.name} ({n.network_type} · {n.bridge}) {n.dhcp_enabled ? '· DHCP' : ''}</option>
              ))}
            </Select>
            <div className="grid gap-4 sm:grid-cols-2">
              <Input label="Static IPv4 (optional — leave empty for DHCP)" placeholder="192.168.122.42" value={form.ip_address} onChange={(e) => set('ip_address', e.target.value)} />
              <Input label="MAC address (optional, auto-generated if empty)" placeholder="52:54:00:…" value={form.mac_address} onChange={(e) => set('mac_address', e.target.value)} />
            </div>
            <Textarea
              label="SSH public key (optional)"
              placeholder="ssh-ed25519 AAAA… user@laptop"
              value={form.ssh_public_key}
              onChange={(e) => set('ssh_public_key', e.target.value)}
            />
            <div className="grid gap-4 sm:grid-cols-2">
              <Input
                label="VM login password (blank = generate one)"
                type="password"
                placeholder="min 8 characters"
                autoComplete="new-password"
                value={form.cloud_init_password}
                onChange={(e) => set('cloud_init_password', e.target.value)}
                hint="Used by cloud-init and the browser SSH terminal"
              />
              <Input
                label="Confirm password"
                type="password"
                placeholder="repeat the password"
                autoComplete="new-password"
                value={form.confirm_password}
                onChange={(e) => set('confirm_password', e.target.value)}
              />
            </div>
            <p className="text-xs text-muted">
              Leave both blank and the panel generates a strong password, shown once after creation. The credential is
              stored encrypted and never sent back to the browser again.
            </p>
          </div>
        )}

        {step === 4 && (
          <div className="space-y-4">
            <h3 className="flex items-center gap-2 font-semibold text-white"><MonitorCog className="h-4 w-4 text-electric" /> Node selection</h3>
            <label className="flex cursor-pointer items-start gap-3 rounded-lg border border-line bg-input p-4 hover:border-electric/50">
              <input type="radio" name="node" checked={form.node_id === ''} onChange={() => set('node_id', '')} className="mt-1 accent-[#008CFF]" />
              <div>
                <p className="font-semibold text-white">Automatic placement</p>
                <p className="text-xs text-muted">Choose a healthy node with enough free CPU, RAM and disk</p>
              </div>
            </label>
            {nodes.map((n) => (
              <label key={n.id} className={`flex cursor-pointer items-start gap-3 rounded-lg border p-4 ${n.status === 'online' && n.kvm_ready ? 'border-line bg-input hover:border-electric/50' : 'border-line bg-panel opacity-60'}`}>
                <input
                  type="radio"
                  name="node"
                  disabled={n.status !== 'online' || !n.kvm_ready}
                  checked={form.node_id === n.id}
                  onChange={() => set('node_id', n.id)}
                  className="mt-1 accent-[#008CFF]"
                />
                <div className="flex-1">
                  <div className="flex items-center justify-between">
                    <p className="font-semibold text-white">{n.name} {n.is_local && <span className="text-xs text-muted">(local)</span>}</p>
                    <Badge value={n.status} />
                  </div>
                  <p className="mt-1 text-xs text-muted">
                    {n.cpu_cores} cores · {formatMb(n.ram_mb)} · KVM {n.kvm_ready ? 'ready' : 'unavailable'}
                  </p>
                  {n.last_error && <p className="mt-1 text-xs text-danger">{n.last_error}</p>}
                </div>
              </label>
            ))}
          </div>
        )}

        {step === 5 && (
          <div className="space-y-4">
            <h3 className="flex items-center gap-2 font-semibold text-white"><Server className="h-4 w-4 text-electric" /> Review and create</h3>
            <dl className="grid gap-3 sm:grid-cols-2">
              <ReviewItem label="Operating system" value={selectedTemplate?.name ?? '—'} />
              <ReviewItem label="VPS name" value={form.name} />
              <ReviewItem label="Hostname" value={form.hostname || form.name} />
              <ReviewItem label="Resources" value={`${form.vcpus} vCPU · ${formatMb(form.ram_mb)} · ${form.disk_gb} GB disk`} />
              <ReviewItem label="Network" value={networks.find((n) => n.id === form.network_id)?.name ?? 'None'} />
              <ReviewItem label="IP assignment" value={form.ip_address || 'DHCP'} />
              <ReviewItem label="Node" value={form.node_id ? nodes.find((n) => n.id === form.node_id)?.name ?? '—' : 'Automatic'} />
              <ReviewItem label="SSH key" value={form.ssh_public_key ? 'Configured' : 'Not set'} />
              <ReviewItem
                label="Login password"
                value={form.cloud_init_password ? 'Set (encrypted at rest)' : 'Random — shown once after create'}
              />
            </dl>
            <div className="rounded-lg border border-warning/40 bg-warning/10 p-4 text-sm text-warning">
              Provisioning runs as a background job: disk creation, cloud-init, startup and verification. You can watch
              live progress on the VPS detail page.
            </div>
          </div>
        )}

        <div className="mt-6 flex items-center justify-between">
          <Button variant="ghost" disabled={step === 0 || submitting} onClick={() => setStep((s) => s - 1)}>
            <ArrowLeft className="h-4 w-4" /> Back
          </Button>
          {step < STEPS.length - 1 ? (
            <Button onClick={next}>
              Next <ArrowRight className="h-4 w-4" />
            </Button>
          ) : (
            <Button loading={submitting} onClick={submit}>
              <Check className="h-4 w-4" /> Create VPS
            </Button>
          )}
        </div>
      </Card>
    </div>
  )
}

function ReviewItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-line bg-input p-3">
      <dt className="text-xs uppercase tracking-wider text-muted">{label}</dt>
      <dd className="mt-1 break-words text-sm font-medium text-white">{value}</dd>
    </div>
  )
}
