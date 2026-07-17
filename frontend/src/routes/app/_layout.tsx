import {
  createFileRoute,
  Outlet,
  useMatches,
  Link,
} from '@tanstack/react-router'
import { StackedLayout } from '../../ui/stacked-layout'
import {
  Navbar,
  NavbarItem,
  NavbarSection,
  NavbarSpacer,
} from '../../ui/navbar'
import { UserButton, useOrganization } from '@clerk/clerk-react'

export const Route = createFileRoute('/app/_layout')({
  component: AppLayout,
})

// Add app-specific nav items here. `adminOnly` items are hidden from
// non-admin members (Clerk org role !== 'org:admin').
const allNavItems = [
  { label: 'Users', to: '/app/users', match: '/app/_layout/users/', adminOnly: true },
  { label: 'Billing', to: '/app/billing', match: '/app/_layout/billing/', adminOnly: true },
] as const

export function AppLayout() {
  const matches = useMatches()
  const { membership } = useOrganization()
  const isAdmin = membership?.role === 'org:admin'

  const navItems = allNavItems.filter((item) => {
    if (item.adminOnly) {
      return isAdmin
    }
    return true
  })

  return (
    <StackedLayout
      navbar={
        <Navbar className="max-w-6xl m-auto">
          <Link to="/app/users" className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-purple">
              <span className="text-sm font-semibold text-white font-mono">A</span>
            </div>
            <span className="text-lg font-semibold text-zinc-950 dark:text-white font-mono tracking-tight">App</span>
          </Link>
          <NavbarSection className="">
            {navItems.map(({ label, to }) => (
              <NavbarItem
                key={label}
                to={to}
                current={matches.some((m) =>
                  m.pathname.startsWith(to),
                )}
              >
                {label}
              </NavbarItem>
            ))}
          </NavbarSection>
          <NavbarSpacer />
          <UserButton afterSignOutUrl="/" />
        </Navbar>
      }
      sidebar={null}
    >
      <Outlet />
    </StackedLayout>
  )
}
