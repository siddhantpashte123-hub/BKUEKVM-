import { ReactNode, ButtonHTMLAttributes, InputHTMLAttributes, SelectHTMLAttributes, TextareaHTMLAttributes, useEffect } from 'react'
import { AlertTriangle, Inbox, Loader2, X } from 'lucide-react'
import clsx from 'clsx'

// ---------------------------------------------------------------- buttons --
type Variant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'success'

const variantClasses: Record<Variant, string> = {
  primary:
    'bg-primary text-white hover:bg-electric hover:shadow-glow disabled:bg-primary/40',
  secondary:
    'border border-line bg-input text-white hover:border-electric/60 hover:text-electric',
  ghost: 'text-muted hover:bg-white/5 hover:text-white',
  danger: 'bg-danger/90 text-white hover:bg-danger disabled:opacity-40',
  success: 'bg-success/90 text-black hover:bg-success',
}

export function Button({
  variant = 'primary',
  loading,
  className,
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; loading?: boolean }) {
  return (
    <button
      className={clsx(
        'inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold transition-all duration-150 disabled:cursor-not-allowed',
        variantClasses[variant],
        className,
      )}
      disabled={loading || props.disabled}
      {...props}
    >
      {loading && <Loader2 className="h-4 w-4 animate-spin" />}
      {children}
    </button>
  )
}

// ------------------------------------------------------------------ cards --
export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={clsx('card-base p-5', className)}>{children}</div>
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
        {description && <p className="mt-1 text-sm text-muted">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

// ------------------------------------------------------------------ inputs --
export function Input({ label, hint, className, ...props }: InputHTMLAttributes<HTMLInputElement> & { label?: string; hint?: string }) {
  return (
    <div>
      {label && <label className="label-base">{label}</label>}
      <input className={clsx('input-base', className)} {...props} />
      {hint && <p className="mt-1 text-xs text-muted/80">{hint}</p>}
    </div>
  )
}

export function Select({ label, className, children, ...props }: SelectHTMLAttributes<HTMLSelectElement> & { label?: string }) {
  return (
    <div>
      {label && <label className="label-base">{label}</label>}
      <select className={clsx('input-base appearance-none', className)} {...props}>
        {children}
      </select>
    </div>
  )
}

export function Textarea({ label, className, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement> & { label?: string }) {
  return (
    <div>
      {label && <label className="label-base">{label}</label>}
      <textarea className={clsx('input-base min-h-[90px] resize-y', className)} {...props} />
    </div>
  )
}

// ------------------------------------------------------------------ badges --
const badgeTones: Record<string, string> = {
  running: 'bg-success/15 text-success border-success/30',
  ready: 'bg-success/15 text-success border-success/30',
  online: 'bg-success/15 text-success border-success/30',
  succeeded: 'bg-success/15 text-success border-success/30',
  active: 'bg-success/15 text-success border-success/30',
  stopped: 'bg-muted/15 text-muted border-line',
  shutoff: 'bg-muted/15 text-muted border-line',
  offline: 'bg-muted/15 text-muted border-line',
  pending: 'bg-warning/15 text-warning border-warning/30',
  queued: 'bg-warning/15 text-warning border-warning/30',
  provisioning: 'bg-electric/15 text-electric border-electric/30 animate-pulseglow',
  downloading: 'bg-electric/15 text-electric border-electric/30 animate-pulseglow',
  running_task: 'bg-electric/15 text-electric border-electric/30 animate-pulseglow',
  error: 'bg-danger/15 text-danger border-danger/30',
  failed: 'bg-danger/15 text-danger border-danger/30',
  verification_failed: 'bg-danger/15 text-danger border-danger/30',
  disabled: 'bg-muted/10 text-muted border-line',
  unconfigured: 'bg-warning/15 text-warning border-warning/30',
  not_downloaded: 'bg-muted/15 text-muted border-line',
  deleting: 'bg-danger/15 text-danger border-danger/30 animate-pulseglow',
}

export function Badge({ value, className }: { value: string; className?: string }) {
  const tone = badgeTones[value] ?? 'bg-white/5 text-muted border-line'
  return (
    <span className={clsx('inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold capitalize', tone, className)}>
      {value.replace(/_/g, ' ')}
    </span>
  )
}

// ------------------------------------------------------------- stat cards --
export function StatCard({
  icon,
  label,
  value,
  sub,
  tone = 'text-electric',
}: {
  icon: ReactNode
  label: string
  value: ReactNode
  sub?: ReactNode
  tone?: string
}) {
  return (
    <Card className="transition hover:border-electric/40">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-muted">{label}</p>
          <p className="mt-2 text-2xl font-bold text-white">{value}</p>
          {sub && <div className="mt-1 text-xs text-muted">{sub}</div>}
        </div>
        <div className={clsx('rounded-lg border border-line bg-input p-2.5', tone)}>{icon}</div>
      </div>
    </Card>
  )
}

export function ProgressBar({ percent, tone = 'bg-electric' }: { percent: number; tone?: string }) {
  const clamped = Math.max(0, Math.min(100, percent))
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-input">
      <div
        className={clsx('h-full rounded-full transition-all duration-500', tone)}
        style={{ width: `${clamped}%` }}
      />
    </div>
  )
}

// ------------------------------------------------------------------ states --
export function LoadingState({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-20 text-muted">
      <Loader2 className="h-7 w-7 animate-spin text-electric" />
      <p className="text-sm">{label}</p>
    </div>
  )
}

export function EmptyState({ title, hint, action }: { title: string; hint?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-line bg-panel/50 px-6 py-16 text-center">
      <div className="rounded-full border border-line bg-input p-3 text-muted">
        <Inbox className="h-6 w-6" />
      </div>
      <h3 className="mt-2 font-semibold text-white">{title}</h3>
      {hint && <p className="max-w-md text-sm text-muted">{hint}</p>}
      {action && <div className="mt-3">{action}</div>}
    </div>
  )
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-danger/30 bg-danger/5 px-6 py-16 text-center">
      <AlertTriangle className="h-7 w-7 text-danger" />
      <p className="max-w-lg text-sm text-white">{message}</p>
      {onRetry && (
        <Button variant="secondary" onClick={onRetry}>
          Retry
        </Button>
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
  useEffect(() => {
    const handler = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    if (open) window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [open, onClose])

  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/80 backdrop-blur-sm" onClick={onClose} />
      <div
        className={clsx(
          'relative z-10 w-full animate-fade-in rounded-xl border border-line bg-card shadow-glow',
          wide ? 'max-w-2xl' : 'max-w-md',
        )}
      >
        <div className="flex items-center justify-between border-b border-line px-5 py-4">
          <h3 className="font-semibold text-white">{title}</h3>
          <button onClick={onClose} className="rounded-md p-1 text-muted hover:bg-white/5 hover:text-white" aria-label="Close">
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="max-h-[75vh] overflow-y-auto p-5">{children}</div>
      </div>
    </div>
  )
}

export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = 'Confirm',
  danger,
  loading,
  onConfirm,
  onClose,
}: {
  open: boolean
  title: string
  message: ReactNode
  confirmLabel?: string
  danger?: boolean
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
        <Button variant={danger ? 'danger' : 'primary'} loading={loading} onClick={onConfirm}>
          {confirmLabel}
        </Button>
      </div>
    </Modal>
  )
}

// ------------------------------------------------------------------- table --
export function TableShell({ headers, children }: { headers: string[]; children: ReactNode }) {
  return (
    <div className="card-base overflow-x-auto">
      <table className="table-base min-w-[720px]">
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
