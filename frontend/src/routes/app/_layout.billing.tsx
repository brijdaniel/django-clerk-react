import { createFileRoute } from '@tanstack/react-router'
import { useInfiniteQuery, useQueryClient } from '@tanstack/react-query'
import { useOrganization, PricingTable } from '@clerk/clerk-react'
import { useSubscription, SubscriptionDetailsButton } from '@clerk/clerk-react/experimental'
import { dark } from '@clerk/themes'
import { Suspense, useEffect, useRef, useState } from 'react'
import { usePrefersDark } from '../../hooks/usePrefersDark'
import { Badge } from '../../ui/badge'
import { Button } from '../../ui/button'
import { Dialog, DialogTitle, DialogBody } from '../../ui/dialog'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../../ui/table'
import LoadingSpinner from '../../components/shared/LoadingSpinner'
import { useApiClient } from '../../lib/ApiClientProvider'
import { getBillingTransactionsInfiniteOptions } from '../../api/billingApi'
import type { TransactionType } from '../../types/billing.types'
import RouteErrorComponent from '../../components/shared/RouteErrorComponent'
import { useInfiniteScroll } from '../../hooks/useInfiniteScroll'
import { InvoicesModal } from '../../components/billing/InvoicesModal'
import { BuyCreditsDialog } from '../../components/billing/BuyCreditsDialog'

export const Route = createFileRoute('/app/_layout/billing')({
  component: RouteComponent,
  pendingComponent: () => <LoadingSpinner />,
  errorComponent: RouteErrorComponent,
})

const txTypeBadgeColor: Record<TransactionType, 'green' | 'red' | 'blue' | 'indigo'> = {
  grant: 'green',
  deduct: 'red',
  usage: 'blue',
  refund: 'indigo',
}

export function BillingContent() {
  const client = useApiClient()
  const { membership } = useOrganization()
  const isAdmin = membership?.role === 'org:admin'
  const isDark = usePrefersDark()
  const { data: subscription } = useSubscription({ for: 'organization' })
  const activePlan = subscription?.subscriptionItems
    ?.filter((item: { status: string }) => item.status === 'active' || item.status === 'past_due')
    ?.sort((a: { plan: { fee: { amount: number } } }, b: { plan: { fee: { amount: number } } }) => b.plan.fee.amount - a.plan.fee.amount)
    ?.[0]
  const planName = activePlan?.plan?.name ?? 'Free'
  const clerkAppearance = isDark
    ? {
        baseTheme: dark,
        variables: {
          colorPrimary: '#7400f6',
          colorPrimaryForeground: 'white',
          colorDanger: '#FC7091',
          colorSuccess: '#2CDFB5',
          colorWarning: '#FEC200',
          colorBackground: '#18181b',
          colorInputBackground: '#27272a',
          colorNeutral: 'white',
          colorText: '#fafafa',
          colorTextSecondary: '#a1a1aa',
          colorForeground: '#fafafa',
          colorMutedForeground: '#a1a1aa',
        },
      }
    : {
        variables: {
          colorPrimary: '#7400f6',
          colorDanger: '#FC7091',
          colorSuccess: '#2CDFB5',
          colorWarning: '#FEC200',
        },
      }
  const [planDialogOpen, setPlanDialogOpen] = useState(false)
  const [invoicesOpen, setInvoicesOpen] = useState(false)
  const [buyCreditsOpen, setBuyCreditsOpen] = useState(false)
  const [purchaseSuccess] = useState(
    () => new URLSearchParams(window.location.search).get('purchase') === 'success',
  )
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const queryClient = useQueryClient()

  useEffect(() => {
    if (purchaseSuccess) {
      queryClient.invalidateQueries({ queryKey: ['billing'] })
      window.history.replaceState({}, '', window.location.pathname)
    }
  }, [purchaseSuccess, queryClient])

  const billingQuery = useInfiniteQuery(getBillingTransactionsInfiniteOptions(client, 50))

  const sentinelRef = useInfiniteScroll({
    scrollContainerRef,
    hasNextPage: billingQuery.hasNextPage,
    isFetchingNextPage: billingQuery.isFetchingNextPage,
    fetchNextPage: billingQuery.fetchNextPage,
  })

  const data = billingQuery.data?.pages[0]
  const allTransactions = billingQuery.data?.pages.flatMap((page) => page.results) ?? []

  if (!isAdmin) {
    return (
      <div className="bg-white dark:bg-zinc-900 rounded-lg shadow-lg border dark:border-white/10 p-8 text-center">
        <p className="text-zinc-500 dark:text-zinc-400">Access restricted to organisation admins.</p>
      </div>
    )
  }

  if (billingQuery.isLoading) {
    return <LoadingSpinner />
  }

  if (billingQuery.isError || !data) {
    return (
      <div className="bg-white dark:bg-zinc-900 rounded-lg shadow-lg border dark:border-white/10 p-8 text-center">
        <p className="text-red-600">Failed to load billing data.</p>
      </div>
    )
  }

  const isPastDue = data.billing_mode === 'past_due'
  const hasClerkSubscription = activePlan != null && activePlan.plan?.fee?.amount > 0
  const isSubscribed = data.billing_mode === 'subscribed' || hasClerkSubscription
  const balance = parseFloat(data.balance)
  const limit = data.monthly_limit ? parseFloat(data.monthly_limit) : null

  const balanceColor = balance <= 0 ? 'red' : balance < 1 ? 'yellow' : 'green'

  return (
    <div className="flex flex-col gap-6 h-[calc(100svh-9.5rem)]">
      {/* Mode + Balance */}
      <div className="bg-white dark:bg-zinc-900 rounded-lg shadow-lg border dark:border-white/10 p-6">
        <h2 className="text-lg font-semibold text-zinc-900 dark:text-white mb-4">Billing</h2>

        {purchaseSuccess && (
          <div className="mb-4 p-3 bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-lg">
            <p className="text-sm text-green-700 dark:text-green-400 font-medium">
              Credit purchase successful! Your balance has been updated.
            </p>
          </div>
        )}

        {isPastDue && (
          <div className="mb-4 p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg">
            <p className="text-sm text-red-700 dark:text-red-400 font-medium">
              Subscription payment is past due. All billable usage is currently blocked.
              Please click Manage Plan to update your payment details and restore service.
            </p>
          </div>
        )}

        <div className="grid grid-cols-3 gap-4">
          {/* Balance / Plan card */}
          <div className="p-3 bg-zinc-50 dark:bg-zinc-800 rounded-lg">
            <p className="text-sm text-zinc-500 dark:text-zinc-400">
              {isSubscribed || isPastDue ? 'Plan' : 'Prepaid balance'}
            </p>
            <p className="text-2xl font-bold mt-1 text-zinc-900 dark:text-white">
              {!isSubscribed && !isPastDue ? (
                <Badge color={balanceColor}>${data.balance}</Badge>
              ) : (
                <Badge color={isPastDue ? 'red' : 'green'}>
                  {isPastDue ? 'Past Due' : 'Subscribed'}
                </Badge>
              )}
            </p>
            {!isSubscribed && !isPastDue && balance <= 0 && (
              <p className="mt-1 text-xs text-red-600 dark:text-red-400">
                Balance exhausted. Purchase more credits to continue.
              </p>
            )}
          </div>

          {/* Monthly Spend card */}
          <div className="p-3 bg-zinc-50 dark:bg-zinc-800 rounded-lg">
            <p className="text-sm text-zinc-500 dark:text-zinc-400">Monthly spend</p>
            <p className="text-2xl font-bold mt-1 text-zinc-900 dark:text-white">${data.total_monthly_spend}</p>
            {limit !== null ? (
              <p className="text-xs text-zinc-500 dark:text-zinc-400">/ ${data.monthly_limit} limit</p>
            ) : (
              <p className="text-xs text-zinc-500 dark:text-zinc-400">no limit set</p>
            )}
          </div>

          {/* Subscription action card */}
          <div className="p-3 bg-zinc-50 dark:bg-zinc-800 rounded-lg flex flex-col justify-between">
            <p className="text-sm text-zinc-500 dark:text-zinc-400">
              Subscription: <span className="font-semibold text-zinc-900 dark:text-white">{planName}</span>
            </p>
            <div className="mt-2 flex gap-2">
              {isSubscribed || isPastDue ? (
                <>
                  <Button color="purple" className="flex-1" onClick={() => setInvoicesOpen(true)}>
                    Invoices
                  </Button>
                  <SubscriptionDetailsButton for="organization" subscriptionDetailsProps={{ appearance: clerkAppearance }} onSubscriptionCancel={() => { window.location.href = '/app/billing' }}>
                    <Button outline className="flex-1">
                      Manage Plan
                    </Button>
                  </SubscriptionDetailsButton>
                </>
              ) : (
                <>
                  <Button color="purple" className="flex-1" onClick={() => setBuyCreditsOpen(true)}>
                    Buy Credits
                  </Button>
                  <Button outline className="flex-1" onClick={() => setPlanDialogOpen(true)}>
                    Subscribe
                  </Button>
                </>
              )}
            </div>
          </div>
        </div>

        {/* Usage by type inline */}
        {Object.keys(data.monthly_usage_by_type).length > 0 && (
          <div className="mt-3 flex items-center gap-4 text-sm text-zinc-500 dark:text-zinc-400">
            <span className="font-medium text-zinc-700 dark:text-zinc-300">Usage:</span>
            {Object.entries(data.monthly_usage_by_type).map(([usageType, info]) => (
              <span key={usageType}>
                <Badge color="zinc">{usageType.toUpperCase()}</Badge>{' '}
                ${info.spend} (${info.rate}/unit)
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Transaction history */}
      <div className="bg-white dark:bg-zinc-900 rounded-lg shadow-lg border dark:border-white/10 p-6 flex-1 min-h-0 flex flex-col">
        <h3 className="text-base font-semibold text-zinc-900 dark:text-white mb-4">
          Transaction history
          {data.pagination.total > 0 && (
            <span className="text-sm font-normal text-zinc-500 dark:text-zinc-400 ml-2">
              Showing {allTransactions.length} of {data.pagination.total}
            </span>
          )}
        </h3>
        {allTransactions.length === 0 ? (
          <p className="text-sm text-zinc-400 dark:text-zinc-300 text-center py-4">No transactions yet.</p>
        ) : (
          <div ref={scrollContainerRef} className="flex-1 min-h-0 overflow-auto">
            <Table>
              <TableHead>
                <TableRow>
                  <TableHeader>Date</TableHeader>
                  <TableHeader>Type</TableHeader>
                  <TableHeader>Usage type</TableHeader>
                  <TableHeader>Description</TableHeader>
                  <TableHeader className="text-right">Amount</TableHeader>
                  <TableHeader className="text-right">Balance after</TableHeader>
                </TableRow>
              </TableHead>
              <TableBody>
                {allTransactions.map((tx) => (
                  <TableRow key={tx.id}>
                    <TableCell className="whitespace-nowrap text-sm text-zinc-500 dark:text-zinc-400">
                      {new Date(tx.created_at).toLocaleString()}
                    </TableCell>
                    <TableCell>
                      <Badge color={txTypeBadgeColor[tx.transaction_type]}>
                        {tx.transaction_type}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      {tx.usage_type ? (
                        <Badge color="zinc">{tx.usage_type.toUpperCase()}</Badge>
                      ) : (
                        <span className="text-zinc-400">—</span>
                      )}
                    </TableCell>
                    <TableCell className="text-sm">{tx.description}</TableCell>
                    <TableCell className="text-right font-mono">${tx.amount}</TableCell>
                    <TableCell className="text-right font-mono">${tx.balance_after}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <div ref={sentinelRef} className="h-1" />
            {billingQuery.isFetchingNextPage && (
              <div className="flex justify-center py-4">
                <LoadingSpinner />
              </div>
            )}
          </div>
        )}
      </div>

      <InvoicesModal open={invoicesOpen} onClose={() => setInvoicesOpen(false)} billingMode={data.billing_mode} />
      <BuyCreditsDialog open={buyCreditsOpen} onClose={() => setBuyCreditsOpen(false)} />

      <Dialog open={planDialogOpen} onClose={() => setPlanDialogOpen(false)} size="2xl">
        <DialogTitle>Manage Plan</DialogTitle>
        <DialogBody>
          <PricingTable for="organization" appearance={clerkAppearance} checkoutProps={{ appearance: clerkAppearance }} />
        </DialogBody>
      </Dialog>
    </div>
  )
}

function RouteComponent() {
  return (
    <Suspense fallback={<LoadingSpinner />}>
      <BillingContent />
    </Suspense>
  )
}
