import { ReactNode, ButtonHTMLAttributes, InputHTMLAttributes, SelectHTMLAttributes, TextareaHTMLAttributes } from 'react'
import { AlertTriangle, Inbox, Loader2, X } from 'lucide-react'
import clsx from 'clsx'

// ---------------------------------------------------------------- buttons --
type Variant = 'primary' | 'secondary' | 'ghost'
type Size = 'default' | 'sm'

export function Button({
  variant = 'primary',
  size = 'default',
  loading,
  className,
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: Size; loading?: boolean }) {
  return (
    <button
      className={clsx(
        'btn transition-colors disabled:opacity-50 disabled:cursor-not-allowed',
        `btn-${variant}`,
        size === 'sm' ? 'btn-sm' : '',
        className,
      )}
      disabled={loading || props.disabled}
      {...props}
    >
      {loading && <Loader2 className="h-4 w-4 shrink-0 animate-spin" />}
      {children}
    </button>
  )
}

export function IconBtn({
  icon: Icon,
  title,
  variant = 'ghost',
  size = 'sm',
  className,
  onClick,
}: { icon: React.FC<{ className?: string }>; title?: string; variant?: Variant; size?: Size; className?: string; onClick?: () => void }) {
  return (
    <button
      onClick={onClick}
      className={clsx('btn transition-colors disabled:opacity-50 disabled:cursor-not-allowed', `btn-${variant}`, size === 'sm' ? 'btn-sm' : '', className)}
      aria-label={title}
      disabled={!onClick}
    >
      <Icon className="h-4 w-4 shrink-0" />
    </button>
  )
}

// ------------------------------------------------------------------ cards --
export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={clsx('card', className)}>{children}</div>
}

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string
  description?: string
  actions?: ReactNode
}) {
  return (
    <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-white">{title}</h1>
        {description && <p className="mt-1 text-sm text-secondary">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

// ------------------------------------------------------------------ inputs --
export function Input({ label, hint, className, ...props }: InputHTMLAttributes<HTMLInputElement> & { label?: string; hint?: string }) {
  return (
    <div>
      {label && <label className="label">{label}</label>}
      <input className={clsx('input', className)} {...props} />
      {hint && <p className="mt-1 text-xs text-muted">{hint}</p>}
    </div>
  )
}

export function Select({ label, hint, className, children, ...props }: SelectHTMLAttributes<HTMLSelectElement> & { label?: string; hint?: string }) {
  return (
    <div>
      {label && <label className="label">{label}</label>}
      <select className={clsx('input', className)} {...props}>
        {children}
      </select>
      {hint && <p className="mt-1 text-xs text-muted">{hint}</p>}
    </div>
  )
}

export function Textarea({ label, className, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement> & { label?: string }) {
  return (
    <div>
      {label && <label className="label">{label}</label>}
      <textarea className={clsx('input min-h-[90px] resize-y', className)} {...props} />
    </div>
  )
}

// ------------------------------------------------------------------ badges --
export function Badge({ value, className }: { value: string; className?: string }) {
  return (
    <span className={clsx('badge', className)}>{value.replace(/_/g, ' ')}</span>
  )
}

// ------------------------------------------------------------- stat cards --
export function StatCard({
  icon,
  label,
  value,
  sub,
}: {
  icon: ReactNode
  label: string
  value: ReactNode
  sub?: ReactNode
}) {
  return (
    <Card className="stat-card p-5">
      <div className="flex items-start justify-between">
        <div>
          <p className="stat-label">{label}</p>
          <p className="mt-1 stat-value">{value}</p>
          {sub && <p className="mt-0.5 stat-sub">{sub}</p>}
        </div>
        <div className="ml-4 flex-shrink-0 stat-icon">{icon}</div>
      </div>
    </Card>
  )
}

// ----------------------------------------------------------- progress bar --
export function ProgressBar({ percent }: { percent: number }) {
  const clamped = Math.max(0, Math.min(100, percent))
  return (
    <div className="progress">
      <div className="progress-bar" style={{ width: `${clamped}%` }} />
    </div>
  )
}

// ------------------------------------------------------------------ states --
export function LoadingState({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="flex min-h-[300px] flex-col items-center justify-center gap-3 py-24 text-muted">
      <Loader2 className="h-7 w-7 animate-spin" />
      <p className="text-sm">{label}</p>
    </div>
  )
}

export function EmptyState({ title, hint, action }: { title: string; hint?: string; action?: ReactNode }) {
  return (
    <div className="empty-state">
      <div className="icon-box">
        <Inbox className="h-6 w-6" />
      </div>
      <h3 className="title">{title}</h3>
      {hint && <p className="hint">{hint}</p>}
      {action && <div className="mt-3">{action}</div>}
    </div>
  )
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="empty-state">
      <div className="icon-box">
        <AlertTriangle className="h-6 w-6" />
      </div>
      <h3 className="title">Something went wrong</h3>
      <p className="hint max-w-md">{message}</p>
      {onRetry && (
        <div className="mt-3">
          <Button variant="secondary" onClick={onRetry}>
            Retry
          </Button>
        </div>
      )}
    </div>
  )
}

// ------------------------------------------------------------------- modal --
export function Modal({
  open,
  onClose,
  title,
  children,
  wide,
}: {
  open: boolean
  onClose: () => void
  title: string
  children: ReactNode
  wide?: boolean
}) {
  if (!open) return null

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className={clsx('modal-panel', wide ? 'wide' : '')} onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3 className="modal-title">{title}</h3>
          <button onClick={onClose} className="rounded-lg p-1.5 text-muted hover:bg-card hover:text-white" aria-label="Close">
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  )
}

export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = 'Confirm',
  loading,
  onConfirm,
  onClose,
}: {
  open: boolean
  title: string
  message: ReactNode
  confirmLabel?: string
  loading?: boolean
  onConfirm: () => void
  onClose: () => void
}) {
  return (
    <Modal open={open} onClose={onClose} title={title}>
      <div className="text-sm text-muted">{message}</div>
      <div className="mt-6 flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button variant="primary" loading={loading} onClick={onConfirm}>
          {confirmLabel}
        </Button>
      </div>
    </Modal>
  )
}

// ------------------------------------------------------------------- table --
export function TableShell({ headers, children }: { headers: string[]; children: ReactNode }) {
  return (
    <div className="table-wrap">
      <table className="data min-w-[720px]">
        <thead>
          <tr>
            {headers.map((h) => (
              <th key={h}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  )
}
