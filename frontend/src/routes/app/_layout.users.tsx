import { createFileRoute } from '@tanstack/react-router'
import { useSuspenseQuery } from '@tanstack/react-query'
import { useOrganization, useUser } from '@clerk/clerk-react'
import { Suspense, useState } from 'react'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../../ui/table'
import { Badge } from '../../ui/badge'
import { Button } from '../../ui/button'
import { Dialog, DialogActions, DialogBody, DialogTitle } from '../../ui/dialog'
import { Field, Label } from '../../ui/fieldset'
import { Input } from '../../ui/input'
import LoadingSpinner from '../../components/shared/LoadingSpinner'
import { useApiClient } from '../../lib/ApiClientProvider'
import {
  getAllUsersQueryOptions,
  useUpdateUserRoleMutation,
  useToggleUserStatusMutation,
  useInviteUserMutation,
} from '../../api/usersApi'
import RouteErrorComponent from '../../components/shared/RouteErrorComponent'
import { toast } from 'sonner'

export const Route = createFileRoute('/app/_layout/users')({
  component: RouteComponent,
  pendingComponent: () => <LoadingSpinner />,
  errorComponent: RouteErrorComponent,
})

function InviteUserDialog({
  isOpen,
  setIsOpen,
}: {
  isOpen: boolean
  setIsOpen: (value: boolean) => void
}) {
  const client = useApiClient()
  const inviteUser = useInviteUserMutation(client)
  const [email, setEmail] = useState('')
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)

    if (!email.trim()) {
      setError('Email is required.')
      return
    }

    inviteUser.mutate(
      { email: email.trim() },
      {
        onSuccess: () => {
          toast.success('Invitation sent')
          setEmail('')
          setIsOpen(false)
        },
        onError: (err) => {
          toast.error('Failed to send invitation')
          setError(err.message || 'Failed to send invitation.')
        },
      },
    )
  }

  return (
    <Dialog open={isOpen} onClose={() => setIsOpen(false)} size="sm">
      <form onSubmit={handleSubmit}>
        <DialogTitle>Invite User</DialogTitle>
        <DialogBody>
          <Field>
            <Label>Email address</Label>
            <Input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="user@example.com"
              autoFocus
            />
          </Field>
          {error && (
            <p className="mt-2 text-sm text-red-600 dark:text-red-400">{error}</p>
          )}
        </DialogBody>
        <DialogActions>
          <Button plain onClick={() => setIsOpen(false)}>
            Cancel
          </Button>
          <Button type="submit" color="purple" disabled={inviteUser.isPending}>
            {inviteUser.isPending ? (
              <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
            ) : 'Send Invite'}
          </Button>
        </DialogActions>
      </form>
    </Dialog>
  )
}

export function UsersContent() {
  const client = useApiClient()
  const { data: users } = useSuspenseQuery(getAllUsersQueryOptions(client))
  const { membership } = useOrganization()
  const { user: clerkUser } = useUser()
  const updateRole = useUpdateUserRoleMutation(client)
  const toggleStatus = useToggleUserStatusMutation(client)
  const [inviteOpen, setInviteOpen] = useState(false)

  const isAdmin =
    import.meta.env.VITE_E2E_TEST_MODE === 'true' || membership?.role === 'org:admin'

  const [pendingRoleUserId, setPendingRoleUserId] = useState<number | null>(null)
  const [pendingStatusUserId, setPendingStatusUserId] = useState<number | null>(null)

  const handleToggleRole = (userId: number, currentRole: string) => {
    const newRole = currentRole === 'org:admin' ? 'org:member' : 'org:admin'
    setPendingRoleUserId(userId)
    updateRole.mutate(
      { userId, role: newRole },
      {
        onSuccess: () => toast.success(`Role updated to ${newRole === 'org:admin' ? 'Admin' : 'Member'}`),
        onError: () => toast.error('Failed to update role'),
        onSettled: () => setPendingRoleUserId(null),
      },
    )
  }

  const handleToggleStatus = (userId: number, currentlyActive: boolean) => {
    setPendingStatusUserId(userId)
    toggleStatus.mutate(
      { userId, isActive: !currentlyActive },
      {
        onSuccess: () => toast.success(!currentlyActive ? 'User re-invited' : 'User deactivated'),
        onError: () => toast.error('Failed to update user status'),
        onSettled: () => setPendingStatusUserId(null),
      },
    )
  }

  return (
    <div className="bg-white dark:bg-zinc-900 rounded-lg shadow-lg border dark:border-white/10 p-4">
      {isAdmin && (
        <div className="mb-4 flex justify-end">
          <Button color="purple" onClick={() => setInviteOpen(true)}>
            Invite User
          </Button>
          <InviteUserDialog isOpen={inviteOpen} setIsOpen={setInviteOpen} />
        </div>
      )}
      <Table className="max-h-[80vh]">
        <TableHead>
          <TableRow>
            <TableHeader>Name</TableHeader>
            <TableHeader>Email</TableHeader>
            <TableHeader>Organisation</TableHeader>
            <TableHeader>Role</TableHeader>
            <TableHeader>Status</TableHeader>
            {isAdmin && <TableHeader className="text-center">Actions</TableHeader>}
          </TableRow>
        </TableHead>
        <TableBody>
          {users.length === 0 && (
            <TableRow>
              <TableCell colSpan={6} className="text-center py-8 text-zinc-400 dark:text-zinc-300">
                No users yet. Invite someone to get started.
              </TableCell>
            </TableRow>
          )}
          {users.map((user) => {
            const isSelf = clerkUser?.id === user.clerk_id
            return (
              <TableRow key={user.id} className={!user.is_active ? 'opacity-50' : ''}>
                <TableCell>
                  {user.first_name} {user.last_name}
                  {isSelf && (
                    <span className="ml-2 text-xs text-zinc-400 dark:text-zinc-300">(you)</span>
                  )}
                </TableCell>
                <TableCell>{user.email}</TableCell>
                <TableCell>{user.organisation}</TableCell>
                <TableCell>
                  <Badge color={user.role === 'org:admin' ? 'purple' : 'zinc'}>
                    {user.role === 'org:admin' ? 'Admin' : 'Member'}
                  </Badge>
                </TableCell>
                <TableCell>
                  <Badge color={user.is_active ? 'green' : 'red'}>
                    {user.is_active ? 'Active' : 'Inactive'}
                  </Badge>
                </TableCell>
                {isAdmin && (
                  <TableCell className="text-center">
                    {!isSelf && (
                      <div className="flex gap-2 justify-center">
                        <Button
                          outline
                          onClick={() => handleToggleRole(user.id, user.role)}
                          disabled={pendingRoleUserId !== null || pendingStatusUserId !== null}
                        >
                          {pendingRoleUserId === user.id ? (
                            <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
                          ) : user.role === 'org:admin' ? (
                            'Revoke Admin'
                          ) : (
                            'Make Admin'
                          )}
                        </Button>
                        <Button
                          outline
                          onClick={() => handleToggleStatus(user.id, user.is_active)}
                          disabled={pendingStatusUserId !== null || pendingRoleUserId !== null}
                        >
                          {pendingStatusUserId === user.id ? (
                            <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
                          ) : user.is_active ? (
                            'Deactivate'
                          ) : (
                            'Re-invite'
                          )}
                        </Button>
                      </div>
                    )}
                  </TableCell>
                )}
              </TableRow>
            )
          })}
        </TableBody>
      </Table>
    </div>
  )
}

function RouteComponent() {
  return (
    <Suspense fallback={<LoadingSpinner />}>
      <UsersContent />
    </Suspense>
  )
}
