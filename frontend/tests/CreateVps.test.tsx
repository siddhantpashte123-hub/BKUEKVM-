// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import CreateVps from '../src/pages/CreateVps'

const mocks = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('../src/lib/api', () => ({ api: mocks, ApiError: class ApiError extends Error {} }))
vi.mock('../src/lib/auth', () => ({ useAuth: () => ({ can: () => true }) }))

beforeEach(() => mocks.get.mockResolvedValue([]))
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

it('renders the wizard when randomUUID is unavailable, using secure random bytes', () => {
  const getRandomValues = vi.fn((bytes: Uint8Array) => { bytes.fill(42); return bytes })
  vi.stubGlobal('crypto', { getRandomValues })
  render(<MemoryRouter><CreateVps /></MemoryRouter>)
  expect(screen.getByRole('heading', { name: 'Create VPS' })).toBeTruthy()
  expect(getRandomValues).toHaveBeenCalledOnce()
})

it('shows a useful error instead of a blank screen if secure randomness is unavailable', () => {
  vi.stubGlobal('crypto', {})
  render(<MemoryRouter><CreateVps /></MemoryRouter>)
  expect(screen.getByText(/Secure random generation is unavailable/)).toBeTruthy()
})
