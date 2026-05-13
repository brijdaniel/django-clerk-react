import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import {
  createContact,
  createTemplate,
  createSchedule,
  createGroup,
  createGroupSchedule,
  createSummaryData,
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

const contacts = [
  createContact({ id: 1, first_name: 'Alice', last_name: 'Smith', phone: '0412111111' }),
  createContact({ id: 2, first_name: 'Bob', last_name: 'Jones', phone: '0412222222' }),
  createContact({ id: 3, first_name: 'Charlie', last_name: 'Brown', phone: '0412333333' }),
]

const templates = [
  createTemplate({ id: 1, name: 'Welcome', text: 'Welcome to our service!' }),
  createTemplate({ id: 2, name: 'Reminder', text: 'This is a friendly reminder about your appointment.' }),
]

const schedules = [
  createSchedule({ id: 1, text: 'Hello Alice', phone: '0412111111', status: 'pending' }),
  createSchedule({ id: 2, text: 'Hello Bob', phone: '0412222222', status: 'sent' }),
]

const groups = [
  createGroup({ id: 1, name: 'VIP Customers', member_count: 3 }),
  createGroup({ id: 2, name: 'New Customers', member_count: 2 }),
]

export const handlers = [
  // Contacts
  http.get(`${BASE_URL}/api/contacts/`, ({ request }) => {
    const url = new URL(request.url)
    const search = url.searchParams.get('search')
    if (search) {
      const filtered = contacts.filter(
        (c) =>
          c.first_name.toLowerCase().includes(search.toLowerCase()) ||
          c.last_name.toLowerCase().includes(search.toLowerCase()) ||
          c.phone.includes(search)
      )
      return HttpResponse.json(paginate(filtered))
    }
    return HttpResponse.json(paginate(contacts))
  }),

  http.get(`${BASE_URL}/api/contacts/:id/`, ({ params }) => {
    const contact = contacts.find((c) => c.id === Number(params.id))
    if (!contact) return HttpResponse.json({ error: 'Contact not found' }, { status: 404 })
    return HttpResponse.json(contact)
  }),

  http.post(`${BASE_URL}/api/contacts/`, async ({ request }) => {
    const body = (await request.json()) as Record<string, unknown>
    const newContact = createContact({
      id: 100,
      first_name: body.first_name as string,
      last_name: body.last_name as string,
      phone: body.phone as string,
    })
    return HttpResponse.json(newContact, { status: 201 })
  }),

  http.put(`${BASE_URL}/api/contacts/:id/`, async ({ params, request }) => {
    const body = (await request.json()) as Record<string, unknown>
    const contact = contacts.find((c) => c.id === Number(params.id))
    if (!contact) return HttpResponse.json({ error: 'Contact not found' }, { status: 404 })
    return HttpResponse.json({ ...contact, ...body })
  }),

  http.get(`${BASE_URL}/api/contacts/:id/schedules/`, () => {
    return HttpResponse.json(paginate(schedules))
  }),

  http.post(`${BASE_URL}/api/contacts/import/`, () => {
    return HttpResponse.json({ status: 'success', message: 'Contacts imported', filename: 'contacts.csv' })
  }),

  // Templates
  http.get(`${BASE_URL}/api/templates/`, () => {
    return HttpResponse.json(paginate(templates))
  }),

  http.get(`${BASE_URL}/api/templates/:id/`, ({ params }) => {
    const template = templates.find((t) => t.id === Number(params.id))
    if (!template) return HttpResponse.json({ error: 'Template not found' }, { status: 404 })
    return HttpResponse.json(template)
  }),

  http.post(`${BASE_URL}/api/templates/`, async ({ request }) => {
    const body = (await request.json()) as Record<string, unknown>
    return HttpResponse.json(
      createTemplate({ id: 100, name: body.name as string, text: body.text as string }),
      { status: 201 }
    )
  }),

  http.put(`${BASE_URL}/api/templates/:id/`, async ({ params, request }) => {
    const body = (await request.json()) as Record<string, unknown>
    const template = templates.find((t) => t.id === Number(params.id))
    if (!template) return HttpResponse.json({ error: 'Template not found' }, { status: 404 })
    return HttpResponse.json({ ...template, ...body })
  }),

  // Schedules
  http.get(`${BASE_URL}/api/schedules/`, () => {
    return HttpResponse.json(paginate(schedules))
  }),

  http.post(`${BASE_URL}/api/schedules/`, async ({ request }) => {
    const body = (await request.json()) as Record<string, unknown>
    return HttpResponse.json(
      createSchedule({ id: 100, text: body.text as string, phone: body.phone as string }),
      { status: 201 }
    )
  }),

  http.put(`${BASE_URL}/api/schedules/:id/`, async ({ params, request }) => {
    const body = (await request.json()) as Record<string, unknown>
    const schedule = schedules.find((s) => s.id === Number(params.id))
    if (!schedule) return HttpResponse.json({ error: 'Schedule not found' }, { status: 404 })
    return HttpResponse.json({ ...schedule, ...body })
  }),

  http.delete(`${BASE_URL}/api/schedules/:id/`, ({ params }) => {
    const schedule = schedules.find((s) => s.id === Number(params.id))
    if (!schedule) return HttpResponse.json({ error: 'Schedule not found' }, { status: 404 })
    return new HttpResponse(null, { status: 204 })
  }),

  http.post(`${BASE_URL}/api/schedules/:id/retry/`, ({ params }) => {
    const schedule = schedules.find((s) => s.id === Number(params.id))
    if (!schedule) return HttpResponse.json({ error: 'Schedule not found' }, { status: 404 })
    return HttpResponse.json({ ...schedule, status: 'queued', error: null, retry_count: 0 })
  }),

  http.get(`${BASE_URL}/api/schedules/:id/recipients/`, () => {
    return HttpResponse.json([
      createSchedule({ id: 10, text: 'Hello Alice', phone: '0412111111', status: 'sent' }),
      createSchedule({ id: 11, text: 'Hello Bob', phone: '0412222222', status: 'sent' }),
      createSchedule({ id: 12, text: 'Hello Charlie', phone: '0412333333', status: 'failed' }),
    ])
  }),

  // Groups
  http.get(`${BASE_URL}/api/groups/`, ({ request }) => {
    const url = new URL(request.url)
    const search = url.searchParams.get('search')
    if (search) {
      const filtered = groups.filter((g) => g.name.toLowerCase().includes(search.toLowerCase()))
      return HttpResponse.json(paginate(filtered))
    }
    return HttpResponse.json(paginate(groups))
  }),

  http.get(`${BASE_URL}/api/groups/:id/`, () => {
    return HttpResponse.json({
      ...groups[0],
      members: contacts.slice(0, 3),
      pagination: { total: 3, page: 1, limit: 10, totalPages: 1, hasNext: false, hasPrev: false },
    })
  }),

  http.post(`${BASE_URL}/api/groups/`, async ({ request }) => {
    const body = (await request.json()) as Record<string, unknown>
    return HttpResponse.json(createGroup({ id: 100, name: body.name as string }), { status: 201 })
  }),

  http.put(`${BASE_URL}/api/groups/:id/`, async ({ params, request }) => {
    const body = (await request.json()) as Record<string, unknown>
    const group = groups.find((g) => g.id === Number(params.id))
    if (!group) return HttpResponse.json({ error: 'Group not found' }, { status: 404 })
    return HttpResponse.json({ ...group, ...body })
  }),

  http.delete(`${BASE_URL}/api/groups/:id/`, () => {
    return new HttpResponse(null, { status: 204 })
  }),

  http.post(`${BASE_URL}/api/groups/:id/members/`, () => {
    return HttpResponse.json({ message: 'Members added', added_count: 2 })
  }),

  http.delete(`${BASE_URL}/api/groups/:id/members/`, () => {
    return HttpResponse.json({ message: 'Members removed', removed_count: 1 })
  }),

  // Group Schedules
  http.get(`${BASE_URL}/api/group-schedules/`, () => {
    return HttpResponse.json(
      paginate([createGroupSchedule({ id: 1 }), createGroupSchedule({ id: 2 })])
    )
  }),

  http.get(`${BASE_URL}/api/group-schedules/:id/`, ({ params }) => {
    return HttpResponse.json(
      createGroupSchedule({
        id: Number(params.id),
        schedules: schedules.map((s) => ({
          id: s.id,
          contact_detail: { id: 1, first_name: 'Alice', last_name: 'Smith', phone: '0412111111' },
          phone: s.phone!,
          status: s.status,
        })),
      })
    )
  }),

  http.post(`${BASE_URL}/api/group-schedules/`, async ({ request }) => {
    const body = (await request.json()) as Record<string, unknown>
    return HttpResponse.json(
      createGroupSchedule({ id: 100, name: body.name as string }),
      { status: 201 }
    )
  }),

  http.put(`${BASE_URL}/api/group-schedules/:id/`, async ({ params, request }) => {
    const body = (await request.json()) as Record<string, unknown>
    return HttpResponse.json(createGroupSchedule({ id: Number(params.id), ...body }))
  }),

  http.delete(`${BASE_URL}/api/group-schedules/:id/`, () => {
    return new HttpResponse(null, { status: 204 })
  }),

  // SMS
  http.post(`${BASE_URL}/api/sms/send/`, () => {
    return HttpResponse.json(
      { success: true, message: 'Message queued for delivery', schedule_id: 1 },
      { status: 202 }
    )
  }),

  http.post(`${BASE_URL}/api/sms/send-to-group/`, () => {
    return HttpResponse.json(
      {
        success: true,
        message: 'SMS queued for 3 recipients',
        results: { successful: 0, failed: 0, total: 3 },
        group_name: 'VIP Customers',
        group_schedule_id: 1,
      },
      { status: 202 }
    )
  }),

  http.post(`${BASE_URL}/api/sms/send-mms/`, () => {
    return HttpResponse.json(
      { success: true, message: 'Message queued for delivery', schedule_id: 2 },
      { status: 202 }
    )
  }),

  http.post(`${BASE_URL}/api/sms/upload-file/`, () => {
    return HttpResponse.json({
      success: true,
      url: 'https://storage.example.com/image.jpg',
      file_id: 'file_123',
      size: 12345,
    })
  }),

  // Stats
  http.get(`${BASE_URL}/api/stats/monthly/`, () => {
    return HttpResponse.json(createSummaryData())
  }),

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

  http.patch(`${BASE_URL}/api/users/:id/role/`, async ({ params, request }) => {
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
