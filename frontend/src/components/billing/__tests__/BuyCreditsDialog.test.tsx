import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { http, HttpResponse } from 'msw'
import { renderWithProviders, screen, userEvent, waitFor, within } from '../../../test/test-utils'
import { server } from '../../../test/handlers'
import { BuyCreditsDialog } from '../BuyCreditsDialog'

const BASE_URL = 'http://localhost:8000'

// The component sets `window.location.href = result.checkout_url` to start the
// Stripe redirect. jsdom throws "Not implemented: navigation" on real assignment,
// so we override the property with a capturing setter. This also lets us assert
// that the trusted-URL guard blocks navigation for untrusted URLs.
let capturedHref: string
let originalLocation: Location

beforeEach(() => {
  capturedHref = ''
  originalLocation = window.location
  Object.defineProperty(window, 'location', {
    writable: true,
    configurable: true,
    value: {
      ...originalLocation,
      set href(url: string) {
        capturedHref = url
      },
      get href() {
        return capturedHref
      },
    },
  })
})

afterEach(() => {
  Object.defineProperty(window, 'location', {
    writable: true,
    configurable: true,
    value: originalLocation,
  })
})

// The custom amount field is an <input type="number"> identified by placeholder.
function getCustomInput() {
  return screen.getByPlaceholderText('5 – 10,000')
}

// The primary action button's accessible name changes between "Purchase",
// "Purchase $X" and "Redirecting...". Match all of those forms.
function getPurchaseButton() {
  return screen.getByRole('button', { name: /^(Purchase|Redirecting)/ })
}

describe('BuyCreditsDialog', () => {
  describe('rendering / open state', () => {
    it('renders the title and helper copy when open', () => {
      renderWithProviders(<BuyCreditsDialog open={true} onClose={vi.fn()} />)

      expect(screen.getByText('Buy Credits')).toBeInTheDocument()
      expect(
        screen.getByText(/Select an amount or enter a custom value to top up your balance/),
      ).toBeInTheDocument()
    })

    it('renders all six preset amount buttons', () => {
      renderWithProviders(<BuyCreditsDialog open={true} onClose={vi.fn()} />)

      for (const label of ['$10', '$25', '$50', '$100', '$500', '$1,000']) {
        expect(screen.getByText(label)).toBeInTheDocument()
      }
    })

    it('renders the custom amount input', () => {
      renderWithProviders(<BuyCreditsDialog open={true} onClose={vi.fn()} />)
      expect(getCustomInput()).toBeInTheDocument()
    })

    it('does not render dialog content when closed', () => {
      renderWithProviders(<BuyCreditsDialog open={false} onClose={vi.fn()} />)
      expect(screen.queryByText('Buy Credits')).not.toBeInTheDocument()
    })

    it('calls onClose when Cancel is clicked', async () => {
      const onClose = vi.fn()
      const user = userEvent.setup()
      renderWithProviders(<BuyCreditsDialog open={true} onClose={onClose} />)

      await user.click(screen.getByRole('button', { name: 'Cancel' }))
      expect(onClose).toHaveBeenCalledTimes(1)
    })
  })

  describe('amount validation', () => {
    it('disables Purchase when nothing is selected', () => {
      renderWithProviders(<BuyCreditsDialog open={true} onClose={vi.fn()} />)
      expect(getPurchaseButton()).toBeDisabled()
    })

    it('enables Purchase at the minimum boundary (5)', async () => {
      const user = userEvent.setup()
      renderWithProviders(<BuyCreditsDialog open={true} onClose={vi.fn()} />)

      await user.type(getCustomInput(), '5')

      const purchase = getPurchaseButton()
      expect(purchase).toBeEnabled()
      expect(purchase).toHaveTextContent('Purchase $5')
    })

    it('disables Purchase one below the minimum (4)', async () => {
      const user = userEvent.setup()
      renderWithProviders(<BuyCreditsDialog open={true} onClose={vi.fn()} />)

      await user.type(getCustomInput(), '4')
      expect(getPurchaseButton()).toBeDisabled()
    })

    it('enables Purchase at the maximum boundary (10000)', async () => {
      const user = userEvent.setup()
      renderWithProviders(<BuyCreditsDialog open={true} onClose={vi.fn()} />)

      await user.type(getCustomInput(), '10000')

      const purchase = getPurchaseButton()
      expect(purchase).toBeEnabled()
      expect(purchase).toHaveTextContent('Purchase $10,000')
    })

    it('disables Purchase one above the maximum (10001)', async () => {
      const user = userEvent.setup()
      renderWithProviders(<BuyCreditsDialog open={true} onClose={vi.fn()} />)

      await user.type(getCustomInput(), '10001')
      expect(getPurchaseButton()).toBeDisabled()
    })

    it('disables Purchase well above the maximum (20000)', async () => {
      const user = userEvent.setup()
      renderWithProviders(<BuyCreditsDialog open={true} onClose={vi.fn()} />)

      await user.type(getCustomInput(), '20000')
      expect(getPurchaseButton()).toBeDisabled()
    })

    it('treats a non-numeric custom value as no amount (NaN rejected)', async () => {
      const user = userEvent.setup()
      renderWithProviders(<BuyCreditsDialog open={true} onClose={vi.fn()} />)

      // A type=number input swallows letters; typing only a lone decimal point
      // leaves parseInt() returning NaN, which must keep Purchase disabled
      // rather than throwing or enabling the action.
      await user.type(getCustomInput(), '.')
      expect(getPurchaseButton()).toBeDisabled()
    })

    it('treats an empty custom value as no amount', async () => {
      const user = userEvent.setup()
      renderWithProviders(<BuyCreditsDialog open={true} onClose={vi.fn()} />)

      const input = getCustomInput()
      await user.type(input, '50')
      expect(getPurchaseButton()).toBeEnabled()

      await user.clear(input)
      expect(getPurchaseButton()).toBeDisabled()
    })
  })

  describe('preset vs custom toggle', () => {
    it('selecting a preset enables Purchase with that amount', async () => {
      const user = userEvent.setup()
      renderWithProviders(<BuyCreditsDialog open={true} onClose={vi.fn()} />)

      await user.click(screen.getByText('$50'))

      const purchase = getPurchaseButton()
      expect(purchase).toBeEnabled()
      expect(purchase).toHaveTextContent('Purchase $50')
    })

    it('typing a custom amount clears the selected preset', async () => {
      const user = userEvent.setup()
      renderWithProviders(<BuyCreditsDialog open={true} onClose={vi.fn()} />)

      await user.click(screen.getByText('$100'))
      expect(getPurchaseButton()).toHaveTextContent('Purchase $100')

      await user.type(getCustomInput(), '250')
      expect(getPurchaseButton()).toHaveTextContent('Purchase $250')
    })

    it('selecting a preset clears the custom amount input', async () => {
      const user = userEvent.setup()
      renderWithProviders(<BuyCreditsDialog open={true} onClose={vi.fn()} />)

      const input = getCustomInput()
      await user.type(input, '777')
      expect(input).toHaveValue(777)

      await user.click(screen.getByText('$25'))

      expect(input).toHaveValue(null)
      expect(getPurchaseButton()).toHaveTextContent('Purchase $25')
    })

    it('marks the chosen preset with the brand-purple selected styling', async () => {
      const user = userEvent.setup()
      renderWithProviders(<BuyCreditsDialog open={true} onClose={vi.fn()} />)

      const presetButton = screen.getByText('$500').closest('button')!
      // Unselected presets carry only the `hover:border-brand-purple/50`
      // hover variant — never the solid selected styling. Assert against the
      // background token that is exclusive to the selected state (the bare
      // `border-brand-purple` substring also appears inside the hover variant,
      // so it is not discriminating on its own).
      expect(presetButton.className).not.toContain('bg-brand-purple/10')
      expect(presetButton.className).toContain('hover:border-brand-purple/50')

      await user.click(within(presetButton).getByText('$500'))
      // Selected state replaces the hover variant with the solid border, an
      // accent background, and a ring.
      expect(presetButton.className).toContain('bg-brand-purple/10')
      expect(presetButton.className).toContain('ring-brand-purple/30')
      expect(presetButton.className).not.toContain('hover:border-brand-purple/50')
    })
  })

  describe('trusted Stripe URL guard + redirect', () => {
    it('redirects to a trusted Stripe checkout URL on success', async () => {
      const user = userEvent.setup()
      server.use(
        http.post(`${BASE_URL}/api/billing/buy-credits/`, () =>
          HttpResponse.json({ checkout_url: 'https://checkout.stripe.com/c/pay/cs_live_abc' }),
        ),
      )

      renderWithProviders(<BuyCreditsDialog open={true} onClose={vi.fn()} />)

      await user.click(screen.getByText('$50'))
      await user.click(getPurchaseButton())

      await waitFor(() => {
        expect(capturedHref).toBe('https://checkout.stripe.com/c/pay/cs_live_abc')
      })
      // A successful redirect surfaces no error.
      expect(screen.queryByText(/unexpected checkout URL/i)).not.toBeInTheDocument()
    })

    it('blocks redirect and surfaces an error for an untrusted host', async () => {
      const user = userEvent.setup()
      server.use(
        http.post(`${BASE_URL}/api/billing/buy-credits/`, () =>
          HttpResponse.json({ checkout_url: 'https://evil.example.com/phish' }),
        ),
      )

      renderWithProviders(<BuyCreditsDialog open={true} onClose={vi.fn()} />)

      await user.click(screen.getByText('$25'))
      await user.click(getPurchaseButton())

      await waitFor(() => {
        expect(
          screen.getByText(/Received an unexpected checkout URL — please contact support\./),
        ).toBeInTheDocument()
      })
      // No navigation occurred.
      expect(capturedHref).toBe('')
    })

    it('rejects a non-https URL even on a trusted Stripe host (protocol guard)', async () => {
      const user = userEvent.setup()
      server.use(
        http.post(`${BASE_URL}/api/billing/buy-credits/`, () =>
          HttpResponse.json({ checkout_url: 'http://checkout.stripe.com/c/pay/cs_live_abc' }),
        ),
      )

      renderWithProviders(<BuyCreditsDialog open={true} onClose={vi.fn()} />)

      await user.click(screen.getByText('$10'))
      await user.click(getPurchaseButton())

      await waitFor(() => {
        expect(screen.getByText(/Received an unexpected checkout URL/)).toBeInTheDocument()
      })
      expect(capturedHref).toBe('')
    })
  })

  describe('loading state', () => {
    it('shows "Redirecting..." and disables Cancel + Purchase while in flight', async () => {
      const user = userEvent.setup()
      let resolveRequest: (() => void) | undefined
      const gate = new Promise<void>((resolve) => {
        resolveRequest = resolve
      })

      server.use(
        http.post(`${BASE_URL}/api/billing/buy-credits/`, async () => {
          await gate
          return HttpResponse.json({ checkout_url: 'https://checkout.stripe.com/c/pay/cs_live_x' })
        }),
      )

      renderWithProviders(<BuyCreditsDialog open={true} onClose={vi.fn()} />)

      await user.click(screen.getByText('$100'))
      await user.click(getPurchaseButton())

      const loadingBtn = await screen.findByRole('button', { name: 'Redirecting...' })
      expect(loadingBtn).toBeDisabled()
      expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled()

      // Complete the request; the redirect then fires.
      resolveRequest?.()
      await waitFor(() => {
        expect(capturedHref).toBe('https://checkout.stripe.com/c/pay/cs_live_x')
      })
    })
  })

  describe('error surfacing', () => {
    it('surfaces the API error detail and re-enables Purchase', async () => {
      const user = userEvent.setup()
      server.use(
        http.post(`${BASE_URL}/api/billing/buy-credits/`, () =>
          HttpResponse.json(
            { detail: 'Past due accounts cannot buy credits.' },
            { status: 403 },
          ),
        ),
      )

      renderWithProviders(<BuyCreditsDialog open={true} onClose={vi.fn()} />)

      await user.click(screen.getByText('$50'))
      await user.click(getPurchaseButton())

      await waitFor(() => {
        expect(screen.getByText('Past due accounts cannot buy credits.')).toBeInTheDocument()
      })
      // purchasing reset → button is interactive again and no redirect happened.
      expect(getPurchaseButton()).toBeEnabled()
      expect(getPurchaseButton()).toHaveTextContent('Purchase $50')
      expect(capturedHref).toBe('')
    })

    it('clears a prior error when the amount changes', async () => {
      const user = userEvent.setup()
      server.use(
        http.post(`${BASE_URL}/api/billing/buy-credits/`, () =>
          HttpResponse.json({ detail: 'Something went wrong.' }, { status: 500 }),
        ),
      )

      renderWithProviders(<BuyCreditsDialog open={true} onClose={vi.fn()} />)

      await user.click(screen.getByText('$25'))
      await user.click(getPurchaseButton())

      await waitFor(() => {
        expect(screen.getByText('Something went wrong.')).toBeInTheDocument()
      })

      // Selecting a different preset resets the error via handlePresetClick.
      await user.click(screen.getByText('$100'))
      expect(screen.queryByText('Something went wrong.')).not.toBeInTheDocument()
    })
  })
})
