// Attach the clerk session token to requests

export class ApiClient {
  private baseUrl: string
  private getToken: () => Promise<string | null>

  constructor(getToken: () => Promise<string | null>) {
    this.baseUrl = import.meta.env.VITE_API_BASE_URL
    this.getToken = getToken
  }

  async request<T>(
    path: string,
    options: RequestInit = {}
  ): Promise<T> {
    const token = await this.getToken()

    const response = await fetch(`${this.baseUrl}${path}`, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...options.headers,
      },
    })

    if (!response.ok) {
      throw await this.buildError(response)
    }

    if (response.status === 204) return undefined as T
    return response.json()
  }

  /** Build a typed error from a failed response, with session-expiry handling. */
  private async buildError(response: Response): Promise<Error> {
    const errorBody = await response.json().catch(() => ({}))
    const detail: string = errorBody.detail || errorBody.error ||
      (Array.isArray(errorBody) ? errorBody[0] : '') || ''

    let message = detail || `API error: ${response.status}`

    if (response.status === 401) {
      // A 401 means the session is gone (expired, or signed out in another
      // tab): say so clearly and return to the sign-in page, since every
      // subsequent call would fail the same way.
      message = 'Your session has expired — please sign in again.'
      window.location.assign('/')
    } else if (response.status === 403 && !detail) {
      message = "You don't have permission to perform this action."
    }

    const error = new Error(message) as Error & { status: number; body: unknown }
    error.status = response.status
    error.body = errorBody
    return error
  }

  get<T>(path: string) {
    return this.request<T>(path, { method: 'GET' })
  }

  post<T>(path: string, body?: unknown) {
    return this.request<T>(path, {
      method: 'POST',
      body: body ? JSON.stringify(body) : undefined,
    })
  }

  put<T>(path: string, body?: unknown) {
    return this.request<T>(path, {
      method: 'PUT',
      body: body ? JSON.stringify(body) : undefined,
    })
  }

  patch<T>(path: string, body?: unknown) {
    return this.request<T>(path, {
      method: 'PATCH',
      body: body ? JSON.stringify(body) : undefined,
    })
  }

  del<T>(path: string, body?: unknown) {
    return this.request<T>(path, {
      method: 'DELETE',
      body: body ? JSON.stringify(body) : undefined,
    })
  }

  async uploadFile<T>(path: string, file: File, fieldName = 'file'): Promise<T> {
    const token = await this.getToken()
    const formData = new FormData()
    formData.append(fieldName, file)

    const response = await fetch(`${this.baseUrl}${path}`, {
      method: 'POST',
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: formData,
    })

    if (!response.ok) {
      throw await this.buildError(response)
    }

    return response.json()
  }
}
