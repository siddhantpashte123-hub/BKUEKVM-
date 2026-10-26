// Shared API response types mirroring the backend Pydantic schemas.

export interface User {
  id: number
  username: string
  email: string
  role_id: number
  is_active: boolean
  is_superuser: boolean
  created_at: string
  last_login_at: string | null
}

export interface Role {
  id: number
  name: string
  permissions: string[]
  is_system: boolean
}

export type VPSStatus =
  | 'pending'
  | 'provisioning'
  | 'running'
  | 'stopped'
  | 'error'
  | 'deleting'
  | 'deleted'

export interface VPS {
  id: number
  public_id: string
  name: string
  hostname: string
  description: string
  owner_id: number | null
  node_id: number
  template_id: number
  vcpus: number
  ram_mb: number
  disk_gb: number
  status: VPSStatus
  power_state: string
  last_error: string
  ip_address: string
  mac_address: string
  network_id?: number | null
  expires_at: string | null
  created_at: string
  updated_at: string
  node_name?: string
  template_name?: string
  ssh_public_key?: string
  stats?: Record<string, unknown> | null
}

export interface Paginated<T> {
  items: T[]
  total: number
  page: number
  page_size: number
  pages: number
}

export interface Node {
  id: number
  name: string
  address: string
  libvirt_uri: string
  is_local: boolean
  status: 'online' | 'offline' | 'disabled' | 'unconfigured'
  hypervisor_version: string
  cpu_cores: number
  ram_mb: number
  kvm_ready: boolean
  last_health_at: string | null
  last_error: string
  created_at: string
  vm_count: number
  capabilities?: Record<string, unknown>
}

export interface Template {
  id: number
  name: string
  os_family: 'ubuntu' | 'debian' | string
  version: string
  arch: string
  image_url: string
  checksum_sha256: string
  size_bytes: number
  status: 'not_downloaded' | 'downloading' | 'ready' | 'verification_failed' | 'error'
  created_at: string
}

export interface NetworkInfo {
  id: number
  name: string
  network_type: string
  bridge: string
  subnet: string
  dhcp_enabled: boolean
  status: string
}

export interface StoragePool {
  id: number
  node_id: number | null
  name: string
  pool_type: string
  path: string
  capacity_bytes: number
  used_bytes: number
  status: string
}

export interface Backup {
  id: number
  vps_id: number
  backup_type: 'snapshot' | 'backup'
  status: string
  snapshot_name: string
  path: string
  size_bytes: number
  note: string
  error: string
  created_at: string
  finished_at: string | null
}

export interface TaskStep {
  name: string
  status: string
  detail?: string
  started_at?: string
  finished_at?: string
}

export interface Task {
  id: number
  vps_id: number | null
  task_type: string
  status: 'queued' | 'running' | 'succeeded' | 'failed' | 'canceled'
  progress: number
  steps: TaskStep[]
  logs: string
  error: string
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export interface AuditLog {
  id: number
  user_id: number | null
  action: string
  resource_type: string
  resource_id: string
  ip_address: string
  details: string
  created_at: string
}

export interface HostMetrics {
  cpu: {
    percent: number
    cores_logical: number
    cores_physical: number
    load_average: { '1m': number; '5m': number; '15m': number }
  }
  memory: { total_bytes: number; used_bytes: number; available_bytes: number; percent: number }
  disk: { total_bytes: number; used_bytes: number; free_bytes: number; percent: number }
  network: { bytes_sent: number; bytes_recv: number; packets_sent: number; packets_recv: number }
  timeseries?: { ts: number; cpu_percent: number; mem_percent: number }[]
  active_vps?: number
  queued_tasks?: number
  boot_time?: number
}

export interface DashboardSummary {
  vps_total: number
  vps_running: number
  vps_stopped: number
  vps_provisioning: number
  vps_error: number
  nodes_total: number
  nodes_online: number
  tasks_running: number
  tasks_queued: number
}

export interface LoginResponse {
  user: User
  csrf_token: string
  expires_at: string
}
