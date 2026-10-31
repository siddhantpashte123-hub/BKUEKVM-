// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import VpsList from '../src/pages/VpsList'

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), delete: vi.fn() }))

vi.mock('../src/lib/api', () => ({
  api: mocks,
  ApiError: class ApiError extends Error {},
}))
vi.mock('../src/lib/auth', () => ({ useAuth: () => ({ can: () => true }) }))

const vps = {
  id: 1,
  public_id: 'vps-blue-123',
  name: 'blue',
  hostname: 'blue',
  template_id: 1,
  template_name: 'Ubuntu 22.04 cloud',
  node_id: 1,
  node_name: 'local-node',
  ip_address: '192.168.122.5',
  vcpus: 2,
  ram_mb: 2048,
  disk_gb: 25,
  status: 'running',
  last_error: '',
  created_at: '2026-01-01T00:00:00Z',
}

function renderList() {
  return render(
    <MemoryRouter initialEntries={['/vps']}>
      <Routes>
        <Route path="/vps" element={<VpsList />} />
        <Route path="/vps/:id" element={<div>VPS detail page</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  mocks.get.mockReset().mockResolvedValue({ items: [vps], page: 1, pages: 1, total: 1 })
  mocks.post.mockReset().mockResolvedValue({ message: 'Action queued' })
  mocks.delete.mockReset()
})
afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('VPS list navigation', () => {
  it('opens the VPS detail when a non-action cell in its row is clicked', async () => {
    const user = userEvent.setup()
    renderList()
    await user.click(await screen.findByText('192.168.122.5'))
    expect(await screen.findByText('VPS detail page')).toBeTruthy()
  })

  it('keeps the VPS name as a keyboard-accessible link to the detail page', async () => {
    const user = userEvent.setup()
    renderList()
    const link = await screen.findByRole('link', { name: 'blue' })
    expect(link.getAttribute('href')).toBe('/vps/vps-blue-123')
    link.focus()
    await user.keyboard('{Enter}')
    expect(await screen.findByText('VPS detail page')).toBeTruthy()
  })

  it('runs a lifecycle action without navigating to the detail page', async () => {
    const user = userEvent.setup()
    renderList()
    await user.click(await screen.findByTitle('Graceful shutdown'))
    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith('/api/vps/vps-blue-123/actions/shutdown', {}))
    expect(screen.queryByText('VPS detail page')).toBeNull()
  })

  it('opens SSHX in a new tab without navigating the list', async () => {
    const user = userEvent.setup()
    const open = vi.spyOn(window, 'open').mockReturnValue(null)
    renderList()
    await user.click(await screen.findByTitle('Open SSHX in new tab'))
    expect(open).toHaveBeenCalledWith('/vps/vps-blue-123/sshx', '_blank', 'noopener')
    expect(screen.queryByText('VPS detail page')).toBeNull()
  })

  it('opens the delete confirmation without navigating or deleting immediately', async () => {
    const user = userEvent.setup()
    renderList()
    await user.click(await screen.findByTitle('Delete'))
    expect(screen.getByText('Delete VPS')).toBeTruthy()
    expect(screen.queryByText('VPS detail page')).toBeNull()
    expect(mocks.delete).not.toHaveBeenCalled()
  })
})
