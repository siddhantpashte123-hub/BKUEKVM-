import { FormEvent, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Eye, EyeOff, Lock, ShieldCheck, User } from 'lucide-react'
import { useAuth } from '../lib/auth'
import { ApiError } from '../lib/api'
import { Button, Card, Input, PageHeader } from '../components/ui'

export default function Login() {
  const { login, user } = useAuth()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  useEffect(() => {
    if (user) navigate('/', { replace: true })
  }, [user, navigate])

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setError('')
    setSuccess('')
    setLoading(true)
    try {
      await login(username.trim(), password)
      setSuccess('Authentication successful — opening dashboard…')
      navigate('/', { replace: true })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Login failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center bg-main px-6">
        <div className="relative w-full max-w-md mx-auto">
        <div className="mb-8 text-center">
          <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-lg border bg-card text-xl font-extrabold text-white">
            B
          </div>
          <h1 className="text-2xl font-extrabold tracking-wider text-white">BLUEKVM PANNEL</h1>
          <p className="mt-1 text-sm text-secondary">Secure KVM virtualization management</p>
        </div>

        <Card className="p-6 sm:p-8">
          <form onSubmit={submit} className="space-y-5">
            {error && (
              <div className="rounded-lg border border-color bg-card px-4 py-3 text-xs text-secondary">
                {error}
              </div>
            )}
            {success && (
              <div className="rounded-lg border border-color bg-card px-4 py-3 text-xs text-secondary">
                {success}
              </div>
            )}

            <div>
              <label className="label">Username or email</label>
              <div className="relative">
                <User className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
                <input
                  className="input pl-10"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  autoComplete="username"
                  required
                  autoFocus
                  placeholder="admin"
                />
              </div>
            </div>

            <div>
              <label className="label">Password</label>
              <div className="relative">
                <Lock className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
                <input
                  className="input pl-10 pr-11"
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="current-password"
                  required
                  placeholder="••••••••••••"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 rounded-lg p-1 text-muted hover:bg-card hover:text-white"
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                >
                  {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            </div>

            <Button type="submit" loading={loading} className="w-full py-2.5">
              {loading ? 'Signing in…' : 'Sign In'}
            </Button>

            <p className="flex items-center justify-center gap-1.5 text-center text-xs text-secondary">
              <ShieldCheck className="h-3.5 w-3.5 shrink-0" />
              Public registration is disabled. Accounts are created by administrators.
            </p>
          </form>
        </Card>

        <p className="mt-8 text-center text-xs text-secondary opacity-70">
          Restricted access · All actions are audit logged
        </p>
      </div>
    </div>
  )
}
