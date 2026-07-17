import { queryOptions, useMutation, useQueryClient } from '@tanstack/react-query'
import type { OrgUser } from '../types/user.types'
import type { PaginatedResponse } from '../types/pagination.types'
import type { ApiClient } from '../lib/helper'
import Logger from '../utils/logger'

export function getAllUsersQueryOptions(client: ApiClient) {
  return queryOptions({
    queryKey: ['users'],
    queryFn: async (): Promise<OrgUser[]> => {
      Logger.debug('Fetching all users', { component: 'usersApi.getAllUsers' })
      // Server caps page size at 50, so walk the pages until exhausted.
      const users: OrgUser[] = []
      let page = 1
      let hasNext = true
      while (hasNext) {
        const data = await client.get<PaginatedResponse<OrgUser>>(`/api/users/?limit=50&page=${page}`)
        users.push(...data.results)
        hasNext = data.pagination.hasNext
        page += 1
      }
      Logger.debug('Successfully fetched users', {
        component: 'usersApi.getAllUsers',
        data: { count: users.length },
      })
      return users
    },
  })
}

export function useToggleUserStatusMutation(client: ApiClient) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ userId, isActive }: { userId: number; isActive: boolean }) => {
      Logger.debug('Toggling user status', { component: 'usersApi.toggleUserStatus', data: { userId, isActive } })
      return client.patch<{ status: string; is_active: boolean }>(`/api/users/${userId}/status/`, { is_active: isActive })
    },
    onSuccess: () => {
      Logger.info('User status updated successfully', { component: 'usersApi.toggleUserStatus' })
      return new Promise((resolve) =>
        setTimeout(() => resolve(queryClient.invalidateQueries({ queryKey: ['users'] })), 2000),
      )
    },
    onError: (error) => {
      Logger.error('Failed to toggle user status', {
        component: 'usersApi.toggleUserStatus',
        data: { error: error.message },
      })
    },
  })
}

export function useInviteUserMutation(client: ApiClient) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ email, role }: { email: string; role?: string }) => {
      Logger.debug('Inviting user', { component: 'usersApi.inviteUser', data: { email, role } })
      return client.post<{ status: string; email: string }>('/api/users/invite/', { email, role: role || 'org:member' })
    },
    onSuccess: () => {
      Logger.info('User invitation sent successfully', { component: 'usersApi.inviteUser' })
      return queryClient.invalidateQueries({ queryKey: ['users'] })
    },
    onError: (error) => {
      Logger.error('Failed to invite user', {
        component: 'usersApi.inviteUser',
        data: { error: error.message },
      })
    },
  })
}

export function useUpdateUserRoleMutation(client: ApiClient) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ userId, role }: { userId: number; role: string }) => {
      Logger.debug('Updating user role', { component: 'usersApi.updateUserRole', data: { userId, role } })
      return client.patch<{ status: string; role: string }>(`/api/users/${userId}/role/`, { role })
    },
    onSuccess: () => {
      Logger.info('User role updated successfully', { component: 'usersApi.updateUserRole' })
      return new Promise((resolve) =>
        setTimeout(() => resolve(queryClient.invalidateQueries({ queryKey: ['users'] })), 2000),
      )
    },
    onError: (error) => {
      Logger.error('Failed to update user role', {
        component: 'usersApi.updateUserRole',
        data: { error: error.message },
      })
    },
  })
}
