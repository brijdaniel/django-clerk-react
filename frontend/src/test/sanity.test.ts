import { describe, it, expect } from 'vitest'

describe('Test setup', () => {
  it('should run tests', () => {
    expect(1 + 1).toBe(2)
  })

  it('should have access to environment variables', () => {
    expect(import.meta.env.VITE_API_BASE_URL).toBe('http://localhost:8000')
  })
})
