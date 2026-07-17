import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '@clerk/clerk-react'
import { Dialog, DialogActions, DialogBody, DialogTitle } from '../../ui/dialog'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../../ui/table'
import { Badge } from '../../ui/badge'
import { Button } from '../../ui/button'
import { Checkbox } from '../../ui/checkbox'
import { isTrustedStripeUrl } from '../../utils/trustedUrls'
import LoadingSpinner from '../shared/LoadingSpinner'
import { useApiClient } from '../../lib/ApiClientProvider'
import { getInvoicesQueryOptions, getInvoicePreviewQueryOptions, downloadInvoices } from '../../api/billingApi'
import type { InvoiceStatus, BillingMode } from '../../types/billing.types'

const statusBadgeColor: Record<InvoiceStatus, 'green' | 'yellow' | 'zinc' | 'blue' | 'red'> = {
  paid: 'green',
  open: 'yellow',
  void: 'zinc',
  draft: 'blue',
  uncollectable: 'red',
}

export function InvoicesModal({
  open,
  onClose,
  billingMode,
}: {
  open: boolean
  onClose: () => void
  billingMode: BillingMode
}) {
  const client = useApiClient()
  const { getToken } = useAuth()
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [downloading, setDownloading] = useState(false)

  const invoicesQuery = useQuery({
    ...getInvoicesQueryOptions(client, page),
    enabled: open,
  })

  const previewQuery = useQuery({
    ...getInvoicePreviewQueryOptions(client),
    enabled: open && billingMode === 'subscribed',
  })

  const invoices = invoicesQuery.data?.results ?? []
  const pagination = invoicesQuery.data?.pagination
  const preview = previewQuery.data

  const allOnPageSelected = invoices.length > 0 && invoices.every((inv) => selected.has(inv.id))

  function toggleSelectAll() {
    if (allOnPageSelected) {
      const next = new Set(selected)
      for (const inv of invoices) next.delete(inv.id)
      setSelected(next)
    } else {
      const next = new Set(selected)
      for (const inv of invoices) next.add(inv.id)
      setSelected(next)
    }
  }

  function toggleSelect(id: number) {
    const next = new Set(selected)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    setSelected(next)
  }

  async function handleDownload() {
    if (selected.size === 0) return
    setDownloading(true)
    try {
      await downloadInvoices(getToken, [...selected])
    } catch (e) {
      console.error('Download failed:', e)
    } finally {
      setDownloading(false)
    }
  }

  function handlePageChange(newPage: number) {
    setPage(newPage)
    setSelected(new Set())
  }

  return (
    <Dialog open={open} onClose={onClose} size="3xl">
      <DialogTitle>Invoices</DialogTitle>
      <DialogBody>
        {/* Current Month Preview */}
        {billingMode === 'subscribed' && (
          <div className="mb-6 rounded-lg border border-dashed border-zinc-300 dark:border-white/10 bg-zinc-50 dark:bg-zinc-800/50 p-4">
            <h4 className="text-sm font-semibold text-zinc-900 dark:text-white mb-2">
              Current month estimate
            </h4>
            {previewQuery.isLoading ? (
              <div className="flex justify-center py-4"><LoadingSpinner /></div>
            ) : preview && preview.line_items.length > 0 ? (
              <>
                <div className="text-xs text-zinc-500 dark:text-zinc-400 mb-3">
                  {new Date(preview.period_start).toLocaleDateString()} &ndash; {new Date(preview.period_end).toLocaleDateString()}
                </div>
                <Table dense>
                  <TableHead>
                    <TableRow>
                      <TableHeader>Type</TableHeader>
                      <TableHeader className="text-right">Quantity</TableHeader>
                      <TableHeader className="text-right">Rate</TableHeader>
                      <TableHeader className="text-right">Amount</TableHeader>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {preview.line_items.map((item) => (
                      <TableRow key={item.usage_type}>
                        <TableCell>
                          <Badge color="zinc">{item.usage_type.toUpperCase()}</Badge>
                        </TableCell>
                        <TableCell className="text-right font-mono">{item.quantity}</TableCell>
                        <TableCell className="text-right font-mono">${item.rate}</TableCell>
                        <TableCell className="text-right font-mono">${item.amount}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
                <div className="mt-2 flex items-center justify-between">
                  <span className="text-xs text-zinc-400 dark:text-zinc-500 italic">
                    Based on usage so far this month
                  </span>
                  <span className="text-sm font-semibold text-zinc-900 dark:text-white font-mono">
                    Total: ${preview.total}
                  </span>
                </div>
              </>
            ) : (
              <p className="text-sm text-zinc-400 dark:text-zinc-500">No usage this month yet.</p>
            )}
          </div>
        )}

        {/* Invoice History */}
        <div className="flex items-center justify-between mb-3">
          <h4 className="text-sm font-semibold text-zinc-900 dark:text-white">Invoice history</h4>
          <Button
            color="purple"
            disabled={selected.size === 0 || downloading}
            onClick={handleDownload}
          >
            {downloading ? (
              <>
                <LoadingSpinner />
                Downloading...
              </>
            ) : (
              <>Download selected ({selected.size})</>
            )}
          </Button>
        </div>

        {invoicesQuery.isLoading ? (
          <div className="flex justify-center py-8"><LoadingSpinner /></div>
        ) : invoices.length === 0 ? (
          <p className="text-sm text-zinc-400 dark:text-zinc-500 text-center py-8">
            No invoices yet.
          </p>
        ) : (
          <>
            <Table>
              <TableHead>
                <TableRow>
                  <TableHeader className="w-8">
                    <Checkbox
                      checked={allOnPageSelected}
                      indeterminate={selected.size > 0 && !allOnPageSelected}
                      onChange={toggleSelectAll}
                      color="purple"
                    />
                  </TableHeader>
                  <TableHeader>Period</TableHeader>
                  <TableHeader>Status</TableHeader>
                  <TableHeader className="text-right">Amount</TableHeader>
                  <TableHeader className="text-right">View</TableHeader>
                </TableRow>
              </TableHead>
              <TableBody>
                {invoices.map((invoice) => (
                  <TableRow key={invoice.id}>
                    <TableCell className="w-8">
                      <Checkbox
                        checked={selected.has(invoice.id)}
                        onChange={() => toggleSelect(invoice.id)}
                        color="purple"
                      />
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-sm text-zinc-700 dark:text-zinc-300">
                      {new Date(invoice.period_start).toLocaleDateString()} &ndash;{' '}
                      {new Date(invoice.period_end).toLocaleDateString()}
                    </TableCell>
                    <TableCell>
                      <Badge color={statusBadgeColor[invoice.status]}>
                        {invoice.status}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right font-mono">${invoice.amount}</TableCell>
                    <TableCell className="text-right">
                      {isTrustedStripeUrl(invoice.invoice_url) ? (
                        <a
                          href={invoice.invoice_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-sm font-medium text-brand-purple hover:underline"
                        >
                          View &rarr;
                        </a>
                      ) : (
                        <span className="text-zinc-400">&mdash;</span>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>

            {/* Pagination */}
            {pagination && pagination.totalPages > 1 && (
              <div className="flex items-center justify-between mt-4 text-sm text-zinc-500 dark:text-zinc-400">
                <span>
                  Page {pagination.page} of {pagination.totalPages}
                </span>
                <div className="flex gap-2">
                  <Button
                    plain
                    disabled={!pagination.hasPrev}
                    onClick={() => handlePageChange(page - 1)}
                  >
                    Previous
                  </Button>
                  <Button
                    plain
                    disabled={!pagination.hasNext}
                    onClick={() => handlePageChange(page + 1)}
                  >
                    Next
                  </Button>
                </div>
              </div>
            )}
          </>
        )}
      </DialogBody>
      <DialogActions>
        <Button plain onClick={onClose}>Close</Button>
      </DialogActions>
    </Dialog>
  )
}
