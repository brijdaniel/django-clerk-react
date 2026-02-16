import './App.css'
import { useState } from 'react'
import { SignedIn, SignedOut, SignInButton, SignUpButton, UserButton, useAuth } from '@clerk/clerk-react'
import { ApiClient } from './lib/helper'
import { UserApi } from './lib/api'


function App() {
  const { getToken } = useAuth()

  const [response, setResponse] = useState<any>(null)

  const handleClick = async () => {
    const client = new ApiClient(getToken)
    const userApi = new UserApi(client)

    try {
      const data = await userApi.getMe()
      setResponse(data)
    } catch (err) {
      console.error(err)
      setResponse({ error: 'Request failed' })
    }
  }
  
  return (
    <header>
      {/* Show the sign-in and sign-up buttons when the user is signed out */}
      <SignedOut>
        <SignInButton />
        <SignUpButton />
      </SignedOut>
      {/* Show the user button when the user is signed in */}
      <SignedIn>
        <UserButton />

        <button onClick={handleClick} style={{ marginLeft: '1rem' }}>
          Whoami
        </button>

        {response && (
          <pre style={{ marginTop: '1rem' }}>
            {JSON.stringify(response, null, 2)}
          </pre>
        )}
      </SignedIn>
    </header>
  );
}

export default App