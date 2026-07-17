import { describe, it, expect } from 'vitest'
import { http, HttpResponse } from 'msw'
import { renderHook, waitFor } from '@testing-library/react'
import {
  getAllUsersQueryOptions,
  useToggleUserStatusMutation,
  useInviteUserMutation,
  useUpdateUserRoleMutation,
} from '../usersApi'
import { createMockApiClient, createWrapper } from '../../test/test-utils'
import { server } from '../../test/handlers'

describe('usersApi', () => {
  const client = createMockApiClient()

  describe('getAllUsersQueryOptions', () => {
    it('returns correct query key', () => {
      const options = getAllUsersQueryOptions(client)
      expect(options.queryKey).toEqual(['users'])
    })

    it('has a queryFn', () => {
      const options = getAllUsersQueryOptions(client)
      expect(options.queryFn).toBeDefined()
    })

    it('fetches users from API', async () => {
      const options = getAllUsersQueryOptions(client)
      const result = await options.queryFn!({} as any)
      expect(Array.isArray(result)).toBe(true)
      expect(result.length).toBeGreaterThan(0)
      expect(result[0]).toHaveProperty('first_name')
      expect(result[0]).toHaveProperty('email')
      expect(result[0]).toHaveProperty('role')
      expect(result[0]).toHaveProperty('organisation')
      expect(result[0]).toHaveProperty('is_active')
    })

    it('returns users with expected structure', async () => {
      const options = getAllUsersQueryOptions(client)
      const result = await options.queryFn!({} as any)
      const admin = result.find((u: any) => u.role === 'org:admin')
      expect(admin).toBeDefined()
      expect(admin).toHaveProperty('clerk_id')
    })
  })

  describe('error handling', () => {
    it('getAllUsersQueryOptions rejects when API returns 500', async () => {
      server.use(
        http.get('http://localhost:8000/api/users/', () =>
          HttpResponse.json({ detail: 'Internal Server Error' }, { status: 500 })
        )
      )
      const options = getAllUsersQueryOptions(client)
      await expect(options.queryFn!({} as any)).rejects.toThrow()
    })
  })

  describe('useToggleUserStatusMutation', () => {
    it('PATCHes the user status endpoint and succeeds', async () => {
      server.use(
        http.patch('http://localhost:8000/api/users/:id/status/', async ({ params, request }) => {
          expect(params.id).toBe('5')
          const body = (await request.json()) as Record<string, unknown>
          expect(body).toEqual({ is_active: false })
          return HttpResponse.json({ status: 'deactivated', is_active: false })
        })
      )
      const { Wrapper } = createWrapper()
      const { result } = renderHook(() => useToggleUserStatusMutation(client), { wrapper: Wrapper })

      result.current.mutate({ userId: 5, isActive: false })

      // onSuccess returns a 2s setTimeout promise; v5 keeps the mutation pending
      // until it resolves, so allow >2s for isSuccess to flip.
      await waitFor(() => expect(result.current.isSuccess).toBe(true), { timeout: 2500 })
      expect(result.current.data).toEqual({ status: 'deactivated', is_active: false })
    })

    it('sets isError when the API returns 500', async () => {
      server.use(
        http.patch('http://localhost:8000/api/users/:id/status/', () =>
          HttpResponse.json({ detail: 'Internal Server Error' }, { status: 500 })
        )
      )
      const { Wrapper } = createWrapper()
      const { result } = renderHook(() => useToggleUserStatusMutation(client), { wrapper: Wrapper })

      result.current.mutate({ userId: 5, isActive: true })

      await waitFor(() => expect(result.current.isError).toBe(true))
      expect(result.current.error).toBeInstanceOf(Error)
    })
  })

  describe('useInviteUserMutation', () => {
    it('POSTs the invite endpoint with the given role and succeeds', async () => {
      server.use(
        http.post('http://localhost:8000/api/users/invite/', async ({ request }) => {
          const body = (await request.json()) as Record<string, unknown>
          expect(body).toEqual({ email: 'new@example.com', role: 'org:admin' })
          return HttpResponse.json({ status: 'invitation_sent', email: body.email }, { status: 201 })
        })
      )
      const { Wrapper } = createWrapper()
      const { result } = renderHook(() => useInviteUserMutation(client), { wrapper: Wrapper })

      result.current.mutate({ email: 'new@example.com', role: 'org:admin' })

      await waitFor(() => expect(result.current.isSuccess).toBe(true))
      expect(result.current.data).toEqual({ status: 'invitation_sent', email: 'new@example.com' })
    })

    it('defaults the role to org:member when omitted', async () => {
      server.use(
        http.post('http://localhost:8000/api/users/invite/', async ({ request }) => {
          const body = (await request.json()) as Record<string, unknown>
          expect(body).toEqual({ email: 'member@example.com', role: 'org:member' })
          return HttpResponse.json({ status: 'invitation_sent', email: body.email }, { status: 201 })
        })
      )
      const { Wrapper } = createWrapper()
      const { result } = renderHook(() => useInviteUserMutation(client), { wrapper: Wrapper })

      result.current.mutate({ email: 'member@example.com' })

      await waitFor(() => expect(result.current.isSuccess).toBe(true))
    })

    it('sets isError when the API returns 400', async () => {
      server.use(
        http.post('http://localhost:8000/api/users/invite/', () =>
          HttpResponse.json({ detail: 'User already exists' }, { status: 400 })
        )
      )
      const { Wrapper } = createWrapper()
      const { result } = renderHook(() => useInviteUserMutation(client), { wrapper: Wrapper })

      result.current.mutate({ email: 'dupe@example.com', role: 'org:member' })

      await waitFor(() => expect(result.current.isError).toBe(true))
      expect(result.current.error).toBeInstanceOf(Error)
    })
  })

  describe('useUpdateUserRoleMutation', () => {
    it('PATCHes the user role endpoint and succeeds', async () => {
      server.use(
        http.patch('http://localhost:8000/api/users/:id/role/', async ({ params, request }) => {
          expect(params.id).toBe('7')
          const body = (await request.json()) as Record<string, unknown>
          expect(body).toEqual({ role: 'org:admin' })
          return HttpResponse.json({ status: 'updated', role: body.role })
        })
      )
      const { Wrapper } = createWrapper()
      const { result } = renderHook(() => useUpdateUserRoleMutation(client), { wrapper: Wrapper })

      result.current.mutate({ userId: 7, role: 'org:admin' })

      // onSuccess returns a 2s setTimeout promise; v5 keeps the mutation pending
      // until it resolves, so allow >2s for isSuccess to flip.
      await waitFor(() => expect(result.current.isSuccess).toBe(true), { timeout: 2500 })
      expect(result.current.data).toEqual({ status: 'updated', role: 'org:admin' })
    })

    it('sets isError when the API returns 403', async () => {
      server.use(
        http.patch('http://localhost:8000/api/users/:id/role/', () =>
          HttpResponse.json({ detail: 'Forbidden' }, { status: 403 })
        )
      )
      const { Wrapper } = createWrapper()
      const { result } = renderHook(() => useUpdateUserRoleMutation(client), { wrapper: Wrapper })

      result.current.mutate({ userId: 7, role: 'org:member' })

      await waitFor(() => expect(result.current.isError).toBe(true))
      expect(result.current.error).toBeInstanceOf(Error)
    })
  })
})
