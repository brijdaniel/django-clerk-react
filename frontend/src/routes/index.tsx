import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { Heading } from '../ui/heading'
import { NotFound } from '../components/NotFound'
import { useEffect } from 'react'
import { useOrganization, useOrganizationList } from '@clerk/clerk-react'

export const Route = createFileRoute('/')({
  component: IndexPage,
  notFoundComponent: NotFound,
})

export function IndexPage() {
  const navigate = useNavigate()
  const { organization } = useOrganization()
  const { userMemberships, setActive, isLoaded } = useOrganizationList({ userMemberships: true })

  // Auto-activate the first org if none is active
  useEffect(() => {
    if (!isLoaded || organization) return
    const memberships = userMemberships?.data
    if (memberships && memberships.length > 0) {
      setActive({ organization: memberships[0].organization.id })
    }
  }, [isLoaded, organization, userMemberships?.data, setActive])

  useEffect(() => {
    navigate({
      to: '/app/users',
    })
  }, [navigate])

  return (
    <main className="flex flex-1 flex-col w-screen h-screen">
      <div className="grow p-6 lg:bg-white lg:p-10 lg:shadow-sm lg:ring-1 lg:ring-zinc-950/5 dark:lg:bg-zinc-900 dark:lg:ring-white/10">
        <div className="mx-auto max-w-6xl text-brand-amber text-center">
          <Heading className="text-2xl">
            Loading application...
          </Heading>
        </div>
      </div>
    </main>
  )
}
