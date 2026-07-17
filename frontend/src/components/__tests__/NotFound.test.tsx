import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { NotFound } from '../NotFound'

describe('NotFound', () => {
  it('renders the 404 heading', () => {
    render(<NotFound />)
    expect(screen.getByText('Not Found!')).toBeInTheDocument()
  })

  it('renders the heading inside a main landmark', () => {
    render(<NotFound />)
    const main = screen.getByRole('main')
    expect(main).toBeInTheDocument()
    expect(main).toHaveTextContent('Not Found!')
  })

  it('renders the message as a heading element', () => {
    render(<NotFound />)
    // The Heading ui component renders an <h*> with role heading.
    expect(
      screen.getByRole('heading', { name: 'Not Found!' }),
    ).toBeInTheDocument()
  })
})
