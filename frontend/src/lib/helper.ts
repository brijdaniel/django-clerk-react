// attach the clerk session token to requests

export class ApiClient {
  private baseUrl: string
  private getToken: () => Promise<string | null>

  constructor(getToken: () => Promise<string | null>) {
    this.baseUrl = import.meta.env.VITE_API_BASE_URL
    this.getToken = getToken
  }

  public async request<T>(
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
      throw new Error(`API error: ${response.status}`)
    }

    return response.json()
  }
}
