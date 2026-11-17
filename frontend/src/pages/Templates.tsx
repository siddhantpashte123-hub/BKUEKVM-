import { useEffect, useState } from 'react'
import { CheckCircle2, Download, HardDrive, ShieldCheck } from 'lucide-react'
import { api, ApiError } from '../lib/api'
import { formatBytes } from '../lib/format'
import type { Template } from '../lib/types'
import { Badge, Button, Card, EmptyState, ErrorState, LoadingState, PageHeader } from '../components/ui'
import { useAuth } from '../lib/auth'

export default function Templates() {
  const { can } = useAuth()
  const [templates, setTemplates] = useState<Template[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [downloading, setDownloading] = useState<number | null>(null)

  const load = async () => {
    try {
      setTemplates(await api.get<Template[]>('/api/templates'))
      setError('')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load templates')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    const id = setInterval(load, 5000)
    return () => clearInterval(id)
  }, [])

  const download = async (templateId: number) => {
    setDownloading(templateId)
    try {
      await api.post(`/api/templates/${templateId}/download`)
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Download failed')
    } finally {
      setDownloading(null)
    }
  }

  if (loading) return <LoadingState label="Loading OS templates…" />

  return (
    <div>
      <PageHeader title="OS Templates" description="Verified Ubuntu and Debian cloud images" />
      {error && <ErrorState message={error} onRetry={load} />}

      {templates.length === 0 ? (
        <EmptyState title="Template catalogue is empty" hint="Seed the curated catalogue from the API or re-run the installer bootstrap." />
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {templates.map((t) => (
            <Card key={t.id} className="flex flex-col justify-between">
              <div>
                <div className="flex items-start justify-between">
                  <div>
                    <h3 className="text-lg font-bold capitalize text-white">{t.os_family} {t.version}</h3>
                    <p className="mt-0.5 text-sm text-muted">{t.name}</p>
                  </div>
                  <Badge value={t.status} />
                </div>
                <dl className="mt-4 space-y-2 text-sm">
                  <div className="flex items-center gap-2 text-muted">
                    <HardDrive className="h-4 w-4 text-electric" />
                    Architecture: <span className="text-white">{t.arch}</span>
                  </div>
                  <div className="flex items-center gap-2 text-muted">
                    <ShieldCheck className="h-4 w-4 text-electric" />
                    Checksum: <span className="font-mono text-xs text-white">{t.checksum_sha256 ? `${t.checksum_sha256.slice(0, 18)}…` : 'not pinned'}</span>
                  </div>
                  <p className="text-muted">Image size: <span className="text-white">{t.size_bytes ? formatBytes(t.size_bytes) : 'unknown'}</span></p>
                </dl>
              </div>

              <div className="mt-4">
                {t.status === 'ready' ? (
                  <p className="flex items-center gap-2 text-sm font-medium text-success">
                    <CheckCircle2 className="h-4 w-4" /> Ready for provisioning
                  </p>
                ) : (
                  can('template:manage') && (
                    <Button
                      variant="secondary"
                      loading={downloading === t.id || t.status === 'downloading'}
                      onClick={() => download(t.id)}
                    >
                      <Download className="h-4 w-4" />
                      {t.status === 'downloading' ? 'Downloading…' : 'Download & verify image'}
                    </Button>
                  )
                )}
                {t.status === 'verification_failed' && (
                  <p className="mt-2 text-xs text-danger">Checksum verification failed — the image was rejected and cannot provision VMs.</p>
                )}
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
