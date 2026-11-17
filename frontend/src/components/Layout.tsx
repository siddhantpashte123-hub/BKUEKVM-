import { ReactNode, useState } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import {
  Activity,
  Boxes,
  HardDrive,
  LayoutDashboard,
  LogOut,
  Menu,
  MonitorCog,
  Network,
  ScrollText,
  Server,
  Settings as SettingsIcon,
  ShieldCheck,
  Users,
  Wallet,
  X,
} from 'lucide-react'
import clsx from 'clsx'
import { useAuth } from '../lib/auth'

const NAV = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true },
  { to: '/vps', label: 'VPS Instances', icon: Server },
  { to: '/vps/create', label: 'Create VPS', icon: Boxes },
  { to: '/nodes', label: 'Virtualization Nodes', icon: MonitorCog },
  { to: '/templates', label: 'OS Templates', icon: HardDrive },
  { to: '/network', label: 'Network Management', icon: Network },
  { to: '/storage', label: 'Storage', icon: Wallet },
  { to: '/backups', label: 'Backups', icon: ShieldCheck },
  { to: '/users', label: 'Users & Permissions', icon: Users },
  { to: '/logs', label: 'Activity Logs', icon: ScrollText },
  { to: '/monitoring', label: 'System Monitoring', icon: Activity },
  { to: '/settings', label: 'Settings', icon: SettingsIcon },
]

function Brand() {
  return (
    <div className="flex items-center gap-3 px-6 py-6">
      <div className="flex h-9 w-9 items-center justify-center rounded-lg border bg-card text-lg font-extrabold text-white">
        B
      </div>
      <div className="leading-tight">
        <p className="text-sm font-extrabold tracking-wider text-white">BLUEKVM</p>
        <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-muted">
          Panel
        </p>
      </div>
    </div>
  )
}

function NavItems({ onNavigate }: { onNavigate?: () => void }) {
  const { can } = useAuth()
  const required: Record<string, string> = {
    '/': 'monitoring:read',
    '/vps': 'vps:read',
    '/vps/create': 'vps:manage',
    '/nodes': 'node:read',
    '/templates': 'template:read',
    '/network': 'network:read',
    '/storage': 'storage:read',
    '/backups': 'backup:read',
    '/users': 'user:read',
    '/logs': 'audit:read',
    '/monitoring': 'monitoring:read',
    '/settings': 'settings:read',
  }
  return (
    <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-2">
      {NAV.filter(({ to }) => can(required[to])).map(({ to, label, icon: Icon, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          onClick={onNavigate}
          className={({ isActive }) =>
            clsx(
              'group flex items-center gap-3 rounded-lg border px-3 py-2.5 text-sm font-medium transition-colors duration-150',
              isActive
                ? 'border-transparent bg-card text-white'
                : 'border-transparent text-muted hover:bg-card hover:text-white',
            )
          }
        >
          {({ isActive }) => (
            <>
              <Icon
                className={clsx(
                  'h-4.5 w-4.5 shrink-0',
                  isActive ? 'text-white' : 'text-muted group-hover:text-white',
                )}
              />
              <span>{label}</span>
            </>
          )}
        </NavLink>
      ))}
    </nav>
  )
}

function UserMenu({ user, onLogout }: { user: { username?: string; email?: string } | null; onLogout: () => void }) {
  const initials = user?.username
    ? user.username
        .split(' ')
        .map((part) => part[0])
        .join('')
        .toUpperCase()
        .slice(0, 2)
    : 'UU'

  return (
    <div className="border-t border-color pt-6 pb-6 px-6 flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <p className="truncate text-sm font-semibold text-white">{user?.username ?? 'User'}</p>
      </div>
      <p className="truncate text-xs text-muted">{user?.email ?? ''}</p>
      <button
        onClick={onLogout}
        className="btn btn-ghost w-full justify-start"
      >
        <LogOut className="h-4 w-4 shrink-0" /> Sign out
      </button>
    </div>
  )
}

export default function Layout({ children }: { children: ReactNode }) {
  const { user, logout, loading } = useAuth()
  const navigate = useNavigate()
  const [mobileOpen, setMobileOpen] = useState(false)

  if (loading) return null

  const handleLogout = async () => {
    await logout()
    navigate('/login')
  }

  return (
    <div className="flex min-h-screen bg-main">
      {/* Desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 z-30 w-64 flex-col border-r border border-color bg-sidebar lg:flex">
        <Brand />
        <NavItems />
        {user && <UserMenu user={user} onLogout={handleLogout} />}
      </aside>

      {/* Mobile drawer */}
      {mobileOpen && (
        <>
          <div
            className="fixed inset-0 z-40 bg-main opacity-90 lg:hidden"
            onClick={() => setMobileOpen(false)}
          />
          <aside className="fixed inset-y-0 left-0 z-50 w-72 flex-col border-r border border-color bg-sidebar lg:hidden">
            <div className="flex items-center justify-between px-6 py-6">
              <Brand />
              <button className="rounded-lg p-1.5 text-muted hover:bg-card hover:text-white" onClick={() => setMobileOpen(false)} aria-label="Close menu">
                <X className="h-5 w-5" />
              </button>
            </div>
            <NavItems onNavigate={() => setMobileOpen(false)} />
            {user && <UserMenu user={user} onLogout={handleLogout} />}
          </aside>
        </>
      )}

      {/* Main column */}
      <div className="flex min-w-0 flex-1 flex-col lg:pl-64">
        <header className="sticky top-0 z-20 flex h-16 shrink-0 items-center gap-4 border-b border-color bg-sidebar px-4 sm:px-6">
          <button
            className="rounded-lg border p-2 text-muted hover:text-white lg:hidden"
            onClick={() => setMobileOpen(true)}
            aria-label="Open navigation"
          >
            <Menu className="h-5 w-5" />
          </button>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold text-white truncate">BLUEKVM Panel</p>
            <p className="text-xs text-muted truncate">KVM Virtualization Management</p>
          </div>
          <div className="flex items-center gap-3">
            <div className="hidden items-center gap-1.5 rounded-lg border px-2.5 py-1 sm:flex">
              <span className="flex h-2 w-2 rounded-full border" />
              <span className="text-xs font-medium text-muted">System Online</span>
            </div>
            <button className="flex items-center gap-2 rounded-lg border px-2.5 py-1.5 text-sm font-medium text-white hover:bg-card sm:ml-3">
              {user?.username ? user.username.charAt(0).toUpperCase() : 'U'}
              <span className="hidden sm:inline text-sm font-medium text-white">{user?.username}</span>
            </button>
          </div>
        </header>
        <main className="flex-1 px-6 py-6 sm:px-6 lg:px-8">{children}</main>
        <footer className="border-t border-color bg-main px-6 py-4 sm:px-6 lg:px-8 text-xs text-muted">
          BLUEKVM Panel — self-hosted KVM management
        </footer>
      </div>
    </div>
  )
}
