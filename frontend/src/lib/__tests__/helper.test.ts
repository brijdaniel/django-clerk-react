import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ApiClient } from '../helper'

describe('ApiClient', () => {
  let client: ApiClient
  const mockGetToken = vi.fn().mockResolvedValue('test-token')

  beforeEach(() => {
    client = new ApiClient(mockGetToken)
    vi.restoreAllMocks()
  })

  it('constructs correct URL from base URL and path', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ data: 'test' }), { status: 200 })
    )

    await client.get('/api/users/')
    expect(fetchSpy).toHaveBeenCalledWith(
      'http://localhost:8000/api/users/',
      expect.any(Object)
    )
  })

  it('attaches Bearer token to requests', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({}), { status: 200 })
    )

    await client.get('/api/test/')
    expect(global.fetch).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: 'Bearer test-token',
        }),
      })
    )
  })

  it('does not attach Authorization header when token is null', async () => {
    const clientNoAuth = new ApiClient(vi.fn().mockResolvedValue(null))
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({}), { status: 200 })
    )

    await clientNoAuth.get('/api/test/')
    const callArgs = vi.mocked(global.fetch).mock.calls[0]
    const headers = callArgs[1]?.headers as Record<string, string>
    expect(headers.Authorization).toBeUndefined()
  })

  it('sends GET request', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ id: 1 }), { status: 200 })
    )

    const result = await client.get('/api/test/')
    expect(result).toEqual({ id: 1 })
    expect(global.fetch).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({ method: 'GET' })
    )
  })

  it('sends POST request with body', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ id: 1 }), { status: 201 })
    )

    const body = { name: 'test' }
    await client.post('/api/test/', body)
    expect(global.fetch).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify(body),
      })
    )
  })

  it('sends PUT request with body', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ id: 1 }), { status: 200 })
    )

    const body = { name: 'updated' }
    await client.put('/api/test/1/', body)
    expect(global.fetch).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        method: 'PUT',
        body: JSON.stringify(body),
      })
    )
  })

  it('sends PATCH request with body', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ id: 1 }), { status: 200 })
    )

    await client.patch('/api/test/1/', { name: 'patched' })
    expect(global.fetch).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({ method: 'PATCH' })
    )
  })

  it('sends DELETE request', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(null, { status: 204 })
    )

    await client.del('/api/test/1/')
    expect(global.fetch).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({ method: 'DELETE' })
    )
  })

  it('returns undefined for 204 responses', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(null, { status: 204 })
    )

    const result = await client.del('/api/test/1/')
    expect(result).toBeUndefined()
  })

  it('throws on non-OK response with error details', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ error: 'Not found' }), { status: 404 })
    )

    await expect(client.get('/api/test/999/')).rejects.toThrow('Not found')
  })

  it('throws with status code on non-OK response', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Forbidden' }), { status: 403 })
    )

    try {
      await client.get('/api/test/')
      expect.fail('Should have thrown')
    } catch (error: any) {
      expect(error.status).toBe(403)
      expect(error.message).toBe('Forbidden')
    }
  })

  it('handles non-JSON error body gracefully', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response('Internal Server Error', {
        status: 500,
        headers: { 'Content-Type': 'text/plain' },
      })
    )

    await expect(client.get('/api/test/')).rejects.toThrow('API error: 500')
  })

  it('uploads file with FormData', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ success: true, url: 'https://example.com/file.jpg' }), { status: 200 })
    )

    const file = new File(['content'], 'test.jpg', { type: 'image/jpeg' })
    await client.uploadFile('/api/upload/', file)

    const callArgs = vi.mocked(global.fetch).mock.calls[0]
    expect(callArgs[1]?.method).toBe('POST')
    expect(callArgs[1]?.body).toBeInstanceOf(FormData)
    // No Content-Type header (browser sets it with boundary for FormData)
    const headers = callArgs[1]?.headers as Record<string, string>
    expect(headers['Content-Type']).toBeUndefined()
  })

  it('uploads file with custom field name', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ success: true }), { status: 200 })
    )

    const file = new File(['content'], 'test.csv', { type: 'text/csv' })
    await client.uploadFile('/api/upload/', file, 'document')

    const callArgs = vi.mocked(global.fetch).mock.calls[0]
    const formData = callArgs[1]?.body as FormData
    expect(formData.get('document')).toBeTruthy()
  })

  it('throws on failed file upload', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ detail: 'File too large' }), { status: 413 })
    )

    const file = new File(['content'], 'large.jpg', { type: 'image/jpeg' })
    await expect(client.uploadFile('/api/upload/', file)).rejects.toThrow('File too large')
  })
})
