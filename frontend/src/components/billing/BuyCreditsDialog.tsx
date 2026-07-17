import { useState } from 'react'
import { Dialog, DialogBody, DialogTitle } from '../../ui/dialog'
import { Button } from '../../ui/button'
import { useApiClient } from '../../lib/ApiClientProvider'
import { buyCredits } from '../../api/billingApi'
import { isTrustedStripeUrl } from '../../utils/trustedUrls'

const PRESETS = [10, 25, 50, 100, 500, 1000]

export function BuyCreditsDialog({
  open,
  onClose,
}: {
  open: boolean
  onClose: () => void
}) {
  const client = useApiClient()
  const [selectedPreset, setSelectedPreset] = useState<number | null>(null)
  const [customAmount, setCustomAmount] = useState('')
  const [purchasing, setPurchasing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const amount = selectedPreset ?? (customAmount ? parseInt(customAmount, 10) : null)
  const isValid = amount !== null && amount >= 5 && amount <= 10000

  const handlePresetClick = (value: number) => {
    setSelectedPreset(value)
    setCustomAmount('')
    setError(null)
  }

  const handleCustomChange = (value: string) => {
    setCustomAmount(value)
    setSelectedPreset(null)
    setError(null)
  }

  const handlePurchase = async () => {
    if (!amount || !isValid) return
    setPurchasing(true)
    setError(null)
    try {
      const result = await buyCredits(client, amount)
      // Never navigate a billing flow to an unexpected host
      if (!isTrustedStripeUrl(result.checkout_url)) {
        throw new Error('Received an unexpected checkout URL — please contact support.')
      }
      window.location.href = result.checkout_url
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to start checkout')
      setPurchasing(false)
    }
  }

  return (
    <Dialog open={open} onClose={onClose} size="xl">
      <DialogTitle>Buy Credits</DialogTitle>
      <DialogBody>
        <p className="text-sm text-zinc-500 dark:text-zinc-400 mb-4">
          Select an amount or enter a custom value to top up your balance.
        </p>
        <div className="grid grid-cols-3 gap-3">
          {PRESETS.map((value) => (
            <button
              key={value}
              type="button"
              onClick={() => handlePresetClick(value)}
              className={`rounded-lg border p-4 text-center transition-all cursor-pointer ${
                selectedPreset === value
                  ? 'border-brand-purple bg-brand-purple/10 ring-1 ring-brand-purple/30'
                  : 'border-zinc-200 dark:border-zinc-700 hover:border-brand-purple/50'
              }`}
            >
              <p className="text-xl font-bold text-zinc-900 dark:text-white">${value.toLocaleString()}</p>
            </button>
          ))}
        </div>

        <div className="mt-4">
          <label className="block text-sm font-medium text-zinc-700 dark:text-zinc-300 mb-1">
            Custom amount
          </label>
          <div className="relative">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400">$</span>
            <input
              type="number"
              min={5}
              max={10000}
              placeholder="5 – 10,000"
              value={customAmount}
              onChange={(e) => handleCustomChange(e.target.value)}
              className="w-full rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 pl-7 pr-3 py-2 text-zinc-900 dark:text-white placeholder:text-zinc-400 focus:border-brand-purple focus:ring-1 focus:ring-brand-purple/30 focus:outline-none"
            />
          </div>
        </div>

        {error && (
          <p className="mt-3 text-sm text-red-600 dark:text-red-400">{error}</p>
        )}

        <div className="mt-6 flex justify-end gap-3">
          <Button outline onClick={onClose} disabled={purchasing}>
            Cancel
          </Button>
          <Button
            color="purple"
            disabled={!isValid || purchasing}
            onClick={handlePurchase}
          >
            {purchasing ? 'Redirecting...' : `Purchase ${isValid ? `$${amount!.toLocaleString()}` : ''}`}
          </Button>
        </div>
      </DialogBody>
    </Dialog>
  )
}
