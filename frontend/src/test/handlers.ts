import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import {
  createUser,
  createBillingSummary,
  createInvoiceListResponse,
  createInvoicePreview,
  paginate,
} from './factories'

const BASE_URL = 'http://localhost:8000'

const users = [
  createUser({ id: 1, first_name: 'Admin', last_name: 'User', email: 'admin@example.com', clerk_id: 'user_test123', role: 'org:admin', organisation: 'Test Org' }),
  createUser({ id: 2, first_name: 'Member', last_name: 'User', email: 'member@example.com', clerk_id: 'user_member1', role: 'org:member', organisation: 'Test Org' }),
  createUser({ id: 3, first_name: 'Inactive', last_name: 'User', email: 'inactive@example.com', clerk_id: 'user_inactive1', role: 'org:member', organisation: 'Test Org', is_active: false }),
]

export const handlers = [
  // Billing
  http.get(`${BASE_URL}/api/billing/summary/`, () => {
    return HttpResponse.json(createBillingSummary())
  }),

  http.get(`${BASE_URL}/api/billing/invoices/`, () => {
    return HttpResponse.json(createInvoiceListResponse())
  }),

  http.get(`${BASE_URL}/api/billing/invoice-preview/`, () => {
    return HttpResponse.json(createInvoicePreview())
  }),

  http.post(`${BASE_URL}/api/billing/buy-credits/`, () => {
    return HttpResponse.json({ checkout_url: 'https://checkout.stripe.com/cs_mock_123' })
  }),

  http.post(`${BASE_URL}/api/billing/invoice-download/`, () => {
    return new HttpResponse(new Blob(['%PDF-1.4 mock'], { type: 'application/pdf' }), {
      headers: {
        'Content-Type': 'application/pdf',
        'Content-Disposition': 'attachment; filename="invoice-2026-03.pdf"',
      },
    })
  }),

  // Users
  http.get(`${BASE_URL}/api/users/`, () => {
    return HttpResponse.json(paginate(users))
  }),

  http.patch(`${BASE_URL}/api/users/:id/role/`, async ({ request }) => {
    const body = (await request.json()) as Record<string, unknown>
    return HttpResponse.json({ status: 'updated', role: body.role })
  }),

  http.patch(`${BASE_URL}/api/users/:id/status/`, async ({ request }) => {
    const body = (await request.json()) as Record<string, unknown>
    const isActive = body.is_active as boolean
    if (isActive) {
      return HttpResponse.json({ status: 'invitation_sent', is_active: false })
    }
    return HttpResponse.json({ status: 'deactivated', is_active: false })
  }),

  http.post(`${BASE_URL}/api/users/invite/`, async ({ request }) => {
    const body = (await request.json()) as Record<string, unknown>
    return HttpResponse.json({ status: 'invitation_sent', email: body.email }, { status: 201 })
  }),
]

export const server = setupServer(...handlers)
