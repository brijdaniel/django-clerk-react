#!/usr/bin/env node

/**
 * Assembles the final staticwebapp.config.json for deployment by merging
 * the base config with an environment-specific CSP policy.
 *
 * Usage: SWA_ENV=prod node scripts/build-swa-config.js
 *        SWA_ENV=dev  node scripts/build-swa-config.js   (default)
 */

import { readFileSync, writeFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const root = join(__dirname, '..')

const env = process.env.SWA_ENV || 'dev'
const validEnvs = ['dev', 'prod']
if (!validEnvs.includes(env)) {
  console.error(`Invalid SWA_ENV="${env}". Must be one of: ${validEnvs.join(', ')}`)
  process.exit(1)
}

const base = JSON.parse(readFileSync(join(root, 'staticwebapp.config.base.json'), 'utf-8'))
const csp = JSON.parse(readFileSync(join(root, `csp.${env}.json`), 'utf-8'))

// Build CSP string from directive object
const cspString = Object.entries(csp)
  .map(([directive, values]) => `${directive} ${values.join(' ')}`)
  .join('; ')

base.globalHeaders['Content-Security-Policy'] = cspString

const outPath = join(root, 'dist', 'staticwebapp.config.json')
writeFileSync(outPath, JSON.stringify(base, null, 2) + '\n')

console.log(`[build-swa-config] Written ${env} config to dist/staticwebapp.config.json`)
