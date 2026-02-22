// SPDX-FileCopyrightText: 2026 Evan McKeown
// SPDX-License-Identifier: Apache-2.0

import { defineConfig } from 'vite'

export default defineConfig({
  test: {
    environment: 'jsdom',
    globals: true,
  },
})
