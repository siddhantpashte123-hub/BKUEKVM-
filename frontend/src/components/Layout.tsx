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
    <div className="flex items-center gap-3 px-5 py-5">
      <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-primary/50 bg-primary/10 text-lg font-extrabold text-electric shadow-glow">
        B
      </div>
      <div className="leading-tight">
        <p className="text-sm font-extrabold tracking-wider text-white">BLUEKVM</p>
        <p className="text-[10px] font-semibold uppercase tracking-[0.25em] text-electric">Pannel</p>
      </div>
    </div>
  )
}

function NavItems({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-2">
      {NAV.map(({ to, label, icon: Icon, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          onClick={onNavigate}
          className={({ isActive }) =>
            clsx(
              'group flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-all duration-150',
              isActive
                ? 'bg-primary/15 text-white shadow-[inset_2px_0_0_0_#008CFF]'
                : 'text-muted hover:bg-white/5 hover:text-white',
            )
          }
        >
          {({ isActive }) => (
            <>
              <Icon className={clsx('h-4.5 w-4.5 h-[18px] w-[18px]', isActive ? 'text-electric' : 'text-muted group-hover:text-white')} />
              <span>{label}</span>
            </>
          )}
        </NavLink>
      ))}
    </nav>
  )
}

export default function Layout({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [mobileOpen, setMobileOpen] = useState(false)

  const handleLogout = async () => {
    await logout()
    navigate('/login')
  }

  return (
    <div className="flex min-h-screen bg-black">
      {/* Desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 flex-col border-r border-line bg-sidebar lg:flex">
        <Brand />
        <NavItems />
        <div className="border-t border-line p-4">
          <div className="mb-3 truncate">
            <p className="text-sm font-semibold text-white">{user?.username}</p>
            <p className="truncate text-xs text-muted">{user?.email}</p>
          </div>
          <ButtonLogout onClick={handleLogout} />
        </div>
      </aside>

      {/* Mobile drawer */}
      {mobileOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div className="absolute inset-0 bg-black/80" onClick={() => setMobileOpen(false)} />
          <aside className="absolute inset-y-0 left-0 flex w-72 flex-col border-r border-line bg-sidebar animate-fade-in">
            <div className="flex items-center justify-between">
              <Brand />
              <button className="mr-4 text-muted hover:text-white" onClick={() => setMobileOpen(false)} aria-label="Close menu">
                <X className="h-5 w-5" />
              </button>
            </div>
            <NavItems onNavigate={() => setMobileOpen(false)} />
            <div className="border-t border-line p-4">
              <ButtonLogout onClick={handleLogout} />
            </div>
          </aside>
        </div>
      )}

      {/* Main column */}
      <div className="flex min-w-0 flex-1 flex-col lg:pl-64">
        <header className="sticky top-0 z-20 flex h-16 items-center gap-3 border-b border-line bg-panel/90 px-4 backdrop-blur sm:px-6">
          <button
            className="rounded-lg border border-line p-2 text-muted hover:text-white lg:hidden"
            onClick={() => setMobileOpen(true)}
            aria-label="Open navigation"
          >
            <Menu className="h-5 w-5" />
          </button>
          <div className="flex-1">
            <p className="text-sm font-semibold text-white">BLUEKVM PANNEL</p>
            <p className="text-xs text-muted">KVM Virtualization Management</p>
          </div>
          <div className="hidden items-center gap-2 rounded-full border border-line bg-input px-3 py-1.5 sm:flex">
            <span className="h-2 w-2 rounded-full bg-success animate-pulseglow" />
            <span className="text-xs font-medium text-muted">System Online</span>
          </div>
        </header>
        <main className="flex-1 px-4 py-6 sm:px-6 lg:px-8">{children}</main>
        <footer className="border-t border-line px-6 py-4 text-xs text-muted">
          BLUEKVM PANNEL — self-hosted KVM management · port 8080
        </footer>
      </div>
    </div>
  )
}

function ButtonLogout({ onClick }: { onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="flex w-full items-center gap-2 rounded-lg border border-line bg-input px-3 py-2 text-sm font-medium text-muted transition hover:border-danger/50 hover:text-danger"
    >
      <LogOut className="h-4 w-4" />
      Sign out
    </button>
  )
}
