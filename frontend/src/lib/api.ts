import { ApiClient } from './helper'


export class UserApi {
  private client: ApiClient

  constructor(client: ApiClient) {
    this.client = client
  }

  async getMe() {
    return this.client.request('/api/me/', {
      method: 'GET',
    })
  }
}
