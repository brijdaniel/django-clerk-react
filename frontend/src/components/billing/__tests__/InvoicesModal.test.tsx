import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { http, HttpResponse } from 'msw'
import { InvoicesModal } from '../InvoicesModal'
import {
  createInvoice,
  createInvoiceListResponse,
  createInvoicePreview,
} from '../../../test/factories'
import { renderWithProviders, screen, waitFor, within, userEvent } from '../../../test/test-utils'
import { server } from '../../../test/handlers'

const INVOICES_URL = 'http://localhost:8000/api/billing/invoices/'
const PREVIEW_URL = 'http://localhost:8000/api/billing/invoice-preview/'
const DOWNLOAD_URL = 'http://localhost:8000/api/billing/invoice-download/'

const defaultProps = {
  open: true,
  onClose: vi.fn(),
  billingMode: 'prepaid' as const,
}

describe('InvoicesModal', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // jsdom does not implement object URLs; the download path calls these.
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:mock-url')
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('does not render the dialog when open is false', () => {
    renderWithProviders(<InvoicesModal {...defaultProps} open={false} />)
    expect(screen.queryByText('Invoices')).not.toBeInTheDocument()
  })

  it('renders the modal title and invoice history heading when open', async () => {
    renderWithProviders(<InvoicesModal {...defaultProps} />)
    expect(screen.getByText('Invoices')).toBeInTheDocument()
    expect(await screen.findByText('Invoice history')).toBeInTheDocument()
  })

  it('renders invoice rows from API data', async () => {
    server.use(
      http.get(INVOICES_URL, () =>
        HttpResponse.json(
          createInvoiceListResponse([
            createInvoice({
              id: 1,
              status: 'paid',
              amount: '12.34',
              period_start: '2026-03-01T00:00:00+10:30',
              period_end: '2026-04-01T00:00:00+10:30',
              invoice_url: 'https://invoice.stripe.com/i/inv_1',
            }),
            createInvoice({
              id: 2,
              status: 'open',
              amount: '7.00',
              invoice_url: 'https://invoice.stripe.com/i/inv_2',
            }),
          ]),
        ),
      ),
    )

    renderWithProviders(<InvoicesModal {...defaultProps} />)

    // Status badges render the raw status string.
    expect(await screen.findByText('paid')).toBeInTheDocument()
    expect(screen.getByText('open')).toBeInTheDocument()

    // Amounts render with a leading $ in their own cell.
    expect(screen.getByText('$12.34')).toBeInTheDocument()
    expect(screen.getByText('$7.00')).toBeInTheDocument()

    // Period column shows the locale-formatted date range. Use the actual
    // toLocaleDateString output so the assertion matches whatever the
    // runtime locale produces.
    const expectedStart = new Date('2026-03-01T00:00:00+10:30').toLocaleDateString()
    // The period cell is a <td> that renders "<start> – <end>" across text nodes;
    // match the <td> whose own (non-nested) text holds the formatted start date.
    const periodCell = screen
      .getAllByRole('cell')
      .find(
        (cell) =>
          cell.tagName === 'TD' &&
          cell.children.length === 0 &&
          cell.textContent?.includes(expectedStart),
      )
    expect(periodCell).toBeDefined()
  })

  it('renders a trusted View link for stripe-hosted invoices', async () => {
    server.use(
      http.get(INVOICES_URL, () =>
        HttpResponse.json(
          createInvoiceListResponse([
            createInvoice({ id: 1, invoice_url: 'https://invoice.stripe.com/i/inv_trusted' }),
          ]),
        ),
      ),
    )

    renderWithProviders(<InvoicesModal {...defaultProps} />)

    const link = await screen.findByRole('link')
    expect(link).toHaveAttribute('href', 'https://invoice.stripe.com/i/inv_trusted')
    expect(link).toHaveAttribute('target', '_blank')
  })

  it('does not render a View link for untrusted invoice urls', async () => {
    server.use(
      http.get(INVOICES_URL, () =>
        HttpResponse.json(
          createInvoiceListResponse([
            createInvoice({ id: 1, invoice_url: 'https://evil.example.com/phish' }),
          ]),
        ),
      ),
    )

    renderWithProviders(<InvoicesModal {...defaultProps} />)

    // Wait for the row to render, then assert no anchor exists.
    await screen.findByText('$5.00')
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
  })

  it('shows the empty state when there are no invoices', async () => {
    server.use(
      http.get(INVOICES_URL, () => HttpResponse.json(createInvoiceListResponse([]))),
    )

    renderWithProviders(<InvoicesModal {...defaultProps} />)

    expect(await screen.findByText('No invoices yet.')).toBeInTheDocument()
  })

  it('disables the download button when nothing is selected', async () => {
    server.use(
      http.get(INVOICES_URL, () =>
        HttpResponse.json(createInvoiceListResponse([createInvoice({ id: 1 })])),
      ),
    )

    renderWithProviders(<InvoicesModal {...defaultProps} />)

    const downloadBtn = await screen.findByRole('button', { name: /Download selected \(0\)/ })
    expect(downloadBtn).toBeDisabled()
  })

  it('selecting an invoice enables download and updates the count label', async () => {
    const user = userEvent.setup()
    server.use(
      http.get(INVOICES_URL, () =>
        HttpResponse.json(
          createInvoiceListResponse([
            createInvoice({ id: 1 }),
            createInvoice({ id: 2 }),
          ]),
        ),
      ),
    )

    renderWithProviders(<InvoicesModal {...defaultProps} />)

    // The "Invoice history" heading renders before the async table loads, so
    // wait until the row checkboxes have actually rendered.
    await waitFor(() => {
      // First checkbox is the header select-all; the rest are per-row.
      expect(screen.getAllByRole('checkbox')).toHaveLength(3)
    })
    const checkboxes = screen.getAllByRole('checkbox')

    await user.click(checkboxes[1])

    const downloadBtn = await screen.findByRole('button', { name: /Download selected \(1\)/ })
    expect(downloadBtn).toBeEnabled()
  })

  it('select-all toggles every row on the page', async () => {
    const user = userEvent.setup()
    server.use(
      http.get(INVOICES_URL, () =>
        HttpResponse.json(
          createInvoiceListResponse([
            createInvoice({ id: 1 }),
            createInvoice({ id: 2 }),
            createInvoice({ id: 3 }),
          ]),
        ),
      ),
    )

    renderWithProviders(<InvoicesModal {...defaultProps} />)
    // Header select-all + 3 row checkboxes render once the table data loads.
    await waitFor(() => {
      expect(screen.getAllByRole('checkbox')).toHaveLength(4)
    })

    const selectAll = screen.getAllByRole('checkbox')[0]
    await user.click(selectAll)

    expect(await screen.findByRole('button', { name: /Download selected \(3\)/ })).toBeInTheDocument()

    // Clicking again clears the selection.
    await user.click(screen.getAllByRole('checkbox')[0])
    expect(await screen.findByRole('button', { name: /Download selected \(0\)/ })).toBeInTheDocument()
  })

  it('downloads selected invoices: triggers fetch and a blob-backed anchor click', async () => {
    const user = userEvent.setup()

    server.use(
      http.get(INVOICES_URL, () =>
        HttpResponse.json(createInvoiceListResponse([createInvoice({ id: 42 })])),
      ),
    )

    // Capture the request body and the anchor that gets clicked.
    let requestedIds: number[] | undefined
    server.use(
      http.post(DOWNLOAD_URL, async ({ request }) => {
        const body = (await request.json()) as { invoice_ids: number[] }
        requestedIds = body.invoice_ids
        // Return a plain string body (downloadInvoices calls response.blob() on it).
        // A Blob body is not reliably accepted by MSW-node's HttpResponse and 500s.
        return new HttpResponse('%PDF-1.4 mock', {
          headers: {
            'Content-Type': 'application/pdf',
            'Content-Disposition': 'attachment; filename="invoice-42.pdf"',
          },
        })
      }),
    )

    // Capture the download by spying the anchor's click directly (rather than
    // document.createElement, which also intercepts React's render-time anchors
    // and races with the real download anchor). downloadInvoices sets the
    // `download` PROPERTY, so read this.download off the clicked anchor.
    let clickedDownloadName: string | undefined
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      clickedDownloadName = this.download || this.getAttribute('download') || undefined
    })

    renderWithProviders(<InvoicesModal {...defaultProps} />)
    // Header select-all + 1 row checkbox once the table data loads.
    await waitFor(() => {
      expect(screen.getAllByRole('checkbox')).toHaveLength(2)
    })

    // Select the single invoice row.
    await user.click(screen.getAllByRole('checkbox')[1])

    const downloadBtn = await screen.findByRole('button', { name: /Download selected \(1\)/ })
    await user.click(downloadBtn)

    await waitFor(() => {
      expect(requestedIds).toEqual([42])
    })
    // The browser download was triggered with the filename from the response.
    await waitFor(() => {
      expect(clickedDownloadName).toBe('invoice-42.pdf')
    })
    expect(URL.createObjectURL).toHaveBeenCalled()
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:mock-url')
  })

  it('swallows download errors without crashing the modal', async () => {
    const user = userEvent.setup()
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})

    server.use(
      http.get(INVOICES_URL, () =>
        HttpResponse.json(createInvoiceListResponse([createInvoice({ id: 9 })])),
      ),
      http.post(DOWNLOAD_URL, () =>
        HttpResponse.json({ detail: 'Not found' }, { status: 404 }),
      ),
    )

    renderWithProviders(<InvoicesModal {...defaultProps} />)
    // Header select-all + 1 row checkbox once the table data loads.
    await waitFor(() => {
      expect(screen.getAllByRole('checkbox')).toHaveLength(2)
    })

    await user.click(screen.getAllByRole('checkbox')[1])
    await user.click(await screen.findByRole('button', { name: /Download selected \(1\)/ }))

    // After the failed download the button settles back to its enabled state
    // (download flag reset in the finally block) and the modal still shows.
    await waitFor(() => {
      expect(consoleError).toHaveBeenCalledWith('Download failed:', expect.anything())
    })
    expect(screen.getByText('Invoice history')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Download selected \(1\)/ })).toBeEnabled()
  })

  it('renders pagination controls and advances pages', async () => {
    const user = userEvent.setup()

    server.use(
      http.get(INVOICES_URL, ({ request }) => {
        const url = new URL(request.url)
        const page = Number(url.searchParams.get('page') ?? '1')
        return HttpResponse.json(
          createInvoiceListResponse(
            [createInvoice({ id: page === 1 ? 1 : 2, amount: page === 1 ? '1.00' : '2.00' })],
            { page, totalPages: 2, hasNext: page < 2, hasPrev: page > 1 },
          ),
        )
      }),
    )

    renderWithProviders(<InvoicesModal {...defaultProps} />)

    expect(await screen.findByText('Page 1 of 2')).toBeInTheDocument()
    expect(screen.getByText('$1.00')).toBeInTheDocument()

    const prevBtn = screen.getByRole('button', { name: 'Previous' })
    const nextBtn = screen.getByRole('button', { name: 'Next' })
    expect(prevBtn).toBeDisabled()
    expect(nextBtn).toBeEnabled()

    await user.click(nextBtn)

    expect(await screen.findByText('Page 2 of 2')).toBeInTheDocument()
    expect(screen.getByText('$2.00')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Previous' })).toBeEnabled()
  })

  it('does not show pagination when there is only one page', async () => {
    server.use(
      http.get(INVOICES_URL, () =>
        HttpResponse.json(
          createInvoiceListResponse([createInvoice({ id: 1 })], { totalPages: 1 }),
        ),
      ),
    )

    renderWithProviders(<InvoicesModal {...defaultProps} />)
    await screen.findByText('Invoice history')
    expect(screen.queryByText(/Page \d+ of \d+/)).not.toBeInTheDocument()
  })

  it('shows the current-month preview for subscribed orgs', async () => {
    server.use(
      http.get(PREVIEW_URL, () =>
        HttpResponse.json(
          createInvoicePreview({
            total: '15.00',
            line_items: [
              { usage_type: 'api_call', quantity: 100, rate: '0.10', amount: '10.00' },
              { usage_type: 'report', quantity: 10, rate: '0.50', amount: '5.00' },
            ],
          }),
        ),
      ),
    )

    renderWithProviders(<InvoicesModal {...defaultProps} billingMode="subscribed" />)

    // The heading renders immediately (while the preview is still loading and a
    // spinner shows), so wait for the line-item rows to actually render.
    expect(await screen.findByText('Current month estimate')).toBeInTheDocument()
    // Line items render the usage type uppercased in a badge.
    expect(await screen.findByText('API_CALL')).toBeInTheDocument()
    expect(screen.getByText('REPORT')).toBeInTheDocument()
    expect(screen.getByText('Total: $15.00')).toBeInTheDocument()
  })

  it('does not show the current-month preview for prepaid orgs', async () => {
    renderWithProviders(<InvoicesModal {...defaultProps} billingMode="prepaid" />)
    await screen.findByText('Invoice history')
    expect(screen.queryByText('Current month estimate')).not.toBeInTheDocument()
  })

  it('shows a no-usage message when the preview has no line items', async () => {
    server.use(
      http.get(PREVIEW_URL, () =>
        HttpResponse.json(createInvoicePreview({ line_items: [] })),
      ),
    )

    renderWithProviders(<InvoicesModal {...defaultProps} billingMode="subscribed" />)

    expect(await screen.findByText('No usage this month yet.')).toBeInTheDocument()
  })

  it('calls onClose when the Close button is clicked', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()

    renderWithProviders(<InvoicesModal {...defaultProps} onClose={onClose} />)

    await screen.findByText('Invoice history')
    await user.click(screen.getByRole('button', { name: 'Close' }))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('scopes selection per row via the row checkbox', async () => {
    const user = userEvent.setup()
    server.use(
      http.get(INVOICES_URL, () =>
        HttpResponse.json(
          createInvoiceListResponse([
            createInvoice({ id: 1 }),
            createInvoice({ id: 2 }),
          ]),
        ),
      ),
    )

    renderWithProviders(<InvoicesModal {...defaultProps} />)
    // Wait for the table body rows to load (header row + 2 body rows).
    await waitFor(() => {
      expect(screen.getAllByRole('row')).toHaveLength(3)
    })

    const rows = screen.getAllByRole('row')
    // The body rows are everything after the header row.
    const firstBodyRow = rows[1]
    const rowCheckbox = within(firstBodyRow).getByRole('checkbox')
    await user.click(rowCheckbox)

    expect(await screen.findByRole('button', { name: /Download selected \(1\)/ })).toBeInTheDocument()
  })
})
