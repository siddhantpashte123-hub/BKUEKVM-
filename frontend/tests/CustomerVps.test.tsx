// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import VpsList from '../src/pages/VpsList'

const mocks = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('../src/lib/api', () => ({ api: mocks, ApiError: class ApiError extends Error {} }))
vi.mock('../src/lib/auth', () => ({ useAuth: () => ({ can: (p: string) => ['vps:read', 'vps:power'].includes(p) }) }))

afterEach(() => { cleanup(); vi.restoreAllMocks() })

it('shows power and SSHX controls but no create or delete control', async () => {
  mocks.get.mockResolvedValue({ items: [{
    id: 1, public_id: 'vps-123456789', name: 'customer-vm', hostname: 'customer-vm',
    template_name: 'Ubuntu', node_name: 'local', ip_address: '', vcpus: 1,
    ram_mb: 512, disk_gb: 10, status: 'running', created_at: '2026-01-01T00:00:00Z',
  }], page: 1, pages: 1, total: 1 })
  render(<MemoryRouter><VpsList /></MemoryRouter>)
  expect(await screen.findByTitle('Graceful shutdown')).toBeTruthy()
  expect(screen.getByTitle('Restart')).toBeTruthy()
  expect(screen.getByTitle('Open SSHX in new tab')).toBeTruthy()
  expect(screen.queryByTitle('Delete')).toBeNull()
  expect(screen.queryByText('Create VPS')).toBeNull()
})
