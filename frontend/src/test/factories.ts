import type { Contact, CreateContact } from '../types/contact.types'
import type { OrgUser } from '../types/user.types'
import type { Template } from '../types/template.types'
import type { Schedule, ScheduleStatus } from '../types/schedule.types'
import type { ContactGroup } from '../types/group.types'
import type { GroupSchedule } from '../types/groupSchedule.types'
import type { MonthlyStats, SummaryData } from '../types/stats.types'
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

export function createContact(overrides: Partial<Contact> = {}): Contact {
  const id = overrides.id ?? nextId()
  return {
    id,
    first_name: 'John',
    last_name: 'Doe',
    phone: '0412345678',
    email: `john.doe${id}@example.com`,
    company: 'Test Corp',
    is_active: true,
    opt_out: false,
    created_at: now,
    updated_at: now,
    ...overrides,
  }
}

export function createTemplate(overrides: Partial<Template> = {}): Template {
  const id = overrides.id ?? nextId()
  return {
    id,
    name: `Template ${id}`,
    text: 'Hello, this is a test message.',
    is_active: true,
    version: 1,
    created_at: now,
    updated_at: now,
    ...overrides,
  }
}

export function createSchedule(overrides: Partial<Schedule> = {}): Schedule {
  const id = overrides.id ?? nextId()
  return {
    id,
    text: 'Scheduled test message',
    message_parts: 1,
    phone: '0412345678',
    scheduled_time: new Date(Date.now() + 3600000).toISOString(),
    status: 'pending' as ScheduleStatus,
    format: 'SMS',
    created_at: now,
    updated_at: now,
    ...overrides,
  }
}

export function createGroup(overrides: Partial<ContactGroup> = {}): ContactGroup {
  const id = overrides.id ?? nextId()
  return {
    id,
    name: `Group ${id}`,
    description: 'A test group',
    is_active: true,
    member_count: 5,
    created_at: now,
    updated_at: now,
    ...overrides,
  }
}

export function createGroupSchedule(overrides: Partial<GroupSchedule> = {}): GroupSchedule {
  const id = overrides.id ?? nextId()
  return {
    id,
    name: `Group Schedule ${id}`,
    text: 'Group scheduled message',
    group: { id: 1, name: 'Test Group' },
    scheduled_time: new Date(Date.now() + 3600000).toISOString(),
    status: 'pending',
    created_at: now,
    updated_at: now,
    child_count: 5,
    ...overrides,
  }
}

export function createMonthlyStats(overrides: Partial<MonthlyStats> = {}): MonthlyStats {
  return {
    month: 'January 2026',
    sms_sent: 150,
    sms_message_parts: 200,
    mms_sent: 10,
    pending: 5,
    errored: 2,
    ...overrides,
  }
}

export function createSummaryData(overrides: Partial<SummaryData> = {}): SummaryData {
  return {
    monthly_stats: [
      createMonthlyStats({ month: 'January 2026' }),
      createMonthlyStats({ month: 'February 2026', sms_sent: 180 }),
    ],
    monthly_limit: '50.00',
    total_monthly_spend: '12.50',
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
    format: null,
    schedule: null,
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
    monthly_usage_by_format: {
      sms: { spend: '1.00', rate: '0.10' },
      mms: { spend: '0.50', rate: '0.50' },
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
      { format: 'sms', quantity: 100, rate: '0.10', amount: '10.00' },
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
