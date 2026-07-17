import type { OrgUser } from '../types/user.types'
import type { BillingSummaryResponse, CreditTransaction, Invoice, InvoiceListResponse, InvoicePreviewResponse } from '../types/billing.types'
import type { Pagination } from '../types/pagination.types'

let _id = 1
function nextId() {
  return _id++
}

export function resetIdCounter() {
  _id = 1
}

const now = new Date().toISOString()

export function createUser(overrides: Partial<OrgUser> = {}): OrgUser {
  const id = overrides.id ?? nextId()
  return {
    id,
    first_name: 'Test',
    last_name: 'User',
    email: `user${id}@example.com`,
    clerk_id: `user_clerk${id}`,
    role: 'org:member',
    organisation: 'Test Org',
    is_active: true,
    created_at: now,
    updated_at: now,
    ...overrides,
  }
}

export function createCreditTransaction(overrides: Partial<CreditTransaction> = {}): CreditTransaction {
  const id = overrides.id ?? nextId()
  return {
    id,
    transaction_type: 'grant',
    amount: '5.00',
    balance_after: '5.00',
    description: 'Test grant',
    usage_type: null,
    reference: null,
    created_by: null,
    created_at: now,
    ...overrides,
  }
}

export function createBillingSummary(overrides: Partial<BillingSummaryResponse> = {}): BillingSummaryResponse {
  return {
    billing_mode: 'prepaid',
    balance: '8.50',
    monthly_limit: '50.00',
    total_monthly_spend: '1.50',
    monthly_usage_by_type: {
      api_call: { spend: '1.00', rate: '0.10' },
      report: { spend: '0.50', rate: '0.50' },
    },
    latest_invoice: null,
    results: [createCreditTransaction()],
    pagination: {
      total: 1,
      page: 1,
      limit: 50,
      totalPages: 1,
      hasNext: false,
      hasPrev: false,
    },
    ...overrides,
  }
}

export function createInvoice(overrides: Partial<Invoice> = {}): Invoice {
  const id = overrides.id ?? nextId()
  return {
    id,
    provider_invoice_id: `inv_${id}`,
    status: 'paid',
    amount: '5.00',
    invoice_url: `https://invoice.stripe.com/i/inv_${id}`,
    period_start: '2026-03-01T00:00:00+10:30',
    period_end: '2026-04-01T00:00:00+10:30',
    created_at: now,
    ...overrides,
  }
}

export function createInvoiceListResponse(
  invoices?: Invoice[],
  pagination?: Partial<Pagination>,
): InvoiceListResponse {
  const results = invoices ?? [createInvoice()]
  return {
    results,
    pagination: {
      total: results.length,
      page: 1,
      limit: 10,
      totalPages: 1,
      hasNext: false,
      hasPrev: false,
      ...pagination,
    },
  }
}

export function createInvoicePreview(overrides: Partial<InvoicePreviewResponse> = {}): InvoicePreviewResponse {
  return {
    total: '5.00',
    period_start: '2026-04-01T00:00:00+10:30',
    period_end: '2026-04-22T12:00:00+10:30',
    line_items: [
      { usage_type: 'api_call', quantity: 100, rate: '0.10', amount: '10.00' },
    ],
    ...overrides,
  }
}

export function createPagination(overrides: Partial<Pagination> = {}): Pagination {
  return {
    total: 10,
    page: 1,
    limit: 10,
    totalPages: 1,
    hasNext: false,
    hasPrev: false,
    ...overrides,
  }
}

export function paginate<T>(results: T[], pagination?: Partial<Pagination>) {
  return {
    results,
    pagination: createPagination({
      total: results.length,
      ...pagination,
    }),
  }
}
