import { queryOptions, infiniteQueryOptions } from '@tanstack/react-query'
import type { BillingSummaryResponse, BuyCreditsResponse, InvoiceListResponse, InvoicePreviewResponse } from '../types/billing.types'
import type { ApiClient } from '../lib/helper'

export function getBillingSummaryQueryOptions(client: ApiClient, page = 1, pageSize = 50) {
  return queryOptions({
    queryKey: ['billing', 'summary', page, pageSize],
    queryFn: (): Promise<BillingSummaryResponse> =>
      client.get<BillingSummaryResponse>(
        `/api/billing/summary/?page=${page}&page_size=${pageSize}`,
      ),
    staleTime: 0,
    refetchOnMount: true,
  })
}

export function getInvoicesQueryOptions(client: ApiClient, page = 1, pageSize = 10) {
  return queryOptions({
    queryKey: ['billing', 'invoices', page, pageSize],
    queryFn: (): Promise<InvoiceListResponse> =>
      client.get<InvoiceListResponse>(
        `/api/billing/invoices/?page=${page}&limit=${pageSize}`,
      ),
  })
}

export function getInvoicePreviewQueryOptions(client: ApiClient) {
  return queryOptions({
    queryKey: ['billing', 'invoice-preview'],
    queryFn: (): Promise<InvoicePreviewResponse> =>
      client.get<InvoicePreviewResponse>('/api/billing/invoice-preview/'),
    staleTime: 30_000,
  })
}

export async function downloadInvoices(
  getToken: () => Promise<string | null>,
  invoiceIds: number[],
): Promise<void> {
  const baseUrl = import.meta.env.VITE_API_BASE_URL
  const token = await getToken()

  const response = await fetch(`${baseUrl}/api/billing/invoice-download/`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ invoice_ids: invoiceIds }),
  })

  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({}))
    throw new Error(errorBody.detail || `Download failed: ${response.status}`)
  }

  const blob = await response.blob()
  const disposition = response.headers.get('Content-Disposition') || ''
  const filenameMatch = disposition.match(/filename="?([^"]+)"?/)
  const contentType = response.headers.get('Content-Type') || ''
  const fallbackFilename = contentType.includes('pdf') ? 'invoice.pdf' : 'invoices.zip'
  const filename = filenameMatch?.[1] || fallbackFilename

  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

export async function buyCredits(client: ApiClient, amount: number): Promise<BuyCreditsResponse> {
  return client.post<BuyCreditsResponse>('/api/billing/buy-credits/', { amount })
}

export function getBillingTransactionsInfiniteOptions(client: ApiClient, pageSize: number = 50) {
  return infiniteQueryOptions({
    queryKey: ['billing', 'summary', 'infinite', pageSize],
    queryFn: async ({ pageParam }): Promise<BillingSummaryResponse> =>
      client.get<BillingSummaryResponse>(
        `/api/billing/summary/?page=${pageParam}&page_size=${pageSize}`,
      ),
    initialPageParam: 1,
    getNextPageParam: (lastPage) =>
      lastPage.pagination.hasNext ? lastPage.pagination.page + 1 : undefined,
    staleTime: 0,
    refetchOnMount: true,
  })
}
