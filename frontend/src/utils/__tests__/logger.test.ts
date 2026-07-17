import { describe, it, expect, vi, beforeEach } from 'vitest'

describe('Logger', () => {
  beforeEach(() => {
    vi.resetModules()
    vi.spyOn(console, 'debug').mockImplementation(() => {})
    vi.spyOn(console, 'info').mockImplementation(() => {})
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('calls console.info for info level', async () => {
    const { default: Logger } = await import('../logger')
    Logger.info('test message')
    expect(console.info).toHaveBeenCalledTimes(1)
    expect(console.info).toHaveBeenCalledWith(
      expect.stringContaining('INFO'),
      ''
    )
  })

  it('calls console.warn for warn level', async () => {
    const { default: Logger } = await import('../logger')
    Logger.warn('warning message')
    expect(console.warn).toHaveBeenCalledTimes(1)
    expect(console.warn).toHaveBeenCalledWith(
      expect.stringContaining('WARN'),
      ''
    )
  })

  it('calls console.error for error level', async () => {
    const { default: Logger } = await import('../logger')
    Logger.error('error message')
    expect(console.error).toHaveBeenCalledTimes(1)
    expect(console.error).toHaveBeenCalledWith(
      expect.stringContaining('ERROR'),
      ''
    )
  })

  it('includes component name in message when provided', async () => {
    const { default: Logger } = await import('../logger')
    Logger.info('test', { component: 'MyComponent' })
    expect(console.info).toHaveBeenCalledWith(
      expect.stringContaining('[MyComponent]'),
      ''
    )
  })

  it('includes data when provided', async () => {
    const { default: Logger } = await import('../logger')
    const data = { key: 'value' }
    Logger.info('test', { data })
    expect(console.info).toHaveBeenCalledWith(
      expect.stringContaining('INFO'),
      data
    )
  })

  it('does not call console.debug when log level is not debug', async () => {
    // Default level is 'error' from setup.ts vi.stubEnv
    const { default: Logger } = await import('../logger')
    Logger.debug('debug message')
    expect(console.debug).not.toHaveBeenCalled()
  })
})
