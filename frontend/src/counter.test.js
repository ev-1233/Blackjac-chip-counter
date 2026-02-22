// SPDX-FileCopyrightText: 2026 Evan McKeown
// SPDX-License-Identifier: Apache-2.0

import { setupCounter } from './counter'

describe('setupCounter', () => {
  it('renders initial count and increments on click', () => {
    document.body.innerHTML = '<button id="counter"></button>'
    const button = document.getElementById('counter')

    setupCounter(button)
    expect(button.textContent).toBe('count is 0')

    button.click()
    expect(button.textContent).toBe('count is 1')
  })
})
