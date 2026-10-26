import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api'

interface PollState<T> {
  data: T | null
  error: string
  loading: boolean
  reload: () => void
}

/** Polls a GET endpoint on an interval with mounted-state protection. */
export function usePoll<T>(path: string, intervalMs = 10000, deps: unknown[] = []): PollState<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const mounted = useRef(true)

  const load = useCallback(async () => {
    try {
      const result = await api.get<T>(path)
      if (mounted.current) {
        setData(result)
        setError('')
      }
    } catch (err) {
      if (mounted.current) setError(err instanceof Error ? err.message : 'Request failed')
    } finally {
      if (mounted.current) setLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, ...deps])

  useEffect(() => {
    mounted.current = true
    load()
    const id = setInterval(load, intervalMs)
    return () => {
      mounted.current = false
      clearInterval(id)
    }
  }, [load, intervalMs])

  return { data, error, loading, reload: load }
}
