export type BillingMode = 'prepaid' | 'subscribed' | 'past_due'
export type TransactionType = 'grant' | 'deduct' | 'usage' | 'refund'

export type CreditTransaction = {
  id: number
  transaction_type: TransactionType
  amount: string
  balance_after: string
  description: string
  usage_type: string | null
  reference: string | null
  created_by: number | null
  created_at: string
}

export type UsageTypeSummary = {
  spend: string
  rate: string
}

export type InvoiceStatus = 'draft' | 'open' | 'paid' | 'void' | 'uncollectable'

export type LatestInvoice = {
  status: InvoiceStatus
  amount: string
  invoice_url: string | null
  period_start: string
  period_end: string
}

export type Invoice = {
  id: number
  provider_invoice_id: string
  status: InvoiceStatus
  amount: string
  invoice_url: string | null
  period_start: string
  period_end: string
  created_at: string
}

export type InvoiceListResponse = {
  results: Invoice[]
  pagination: {
    total: number
    page: number
    limit: number
    totalPages: number
    hasNext: boolean
    hasPrev: boolean
  }
}

export type InvoicePreviewLineItem = {
  usage_type: string
  quantity: number
  rate: string
  amount: string
}

export type InvoicePreviewResponse = {
  total: string
  period_start: string
  period_end: string
  line_items: InvoicePreviewLineItem[]
}

export type BuyCreditsResponse = {
  checkout_url: string
}

export type BillingSummaryResponse = {
  billing_mode: BillingMode
  balance: string
  monthly_limit: string | null
  total_monthly_spend: string
  monthly_usage_by_type: Record<string, UsageTypeSummary>
  latest_invoice: LatestInvoice | null
  results: CreditTransaction[]
  pagination: {
    total: number
    page: number
    limit: number
    totalPages: number
    hasNext: boolean
    hasPrev: boolean
  }
}
