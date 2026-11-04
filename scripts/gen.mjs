#!/usr/bin/env node
/** Launch the schema-driven Python model generator and pin its implementation. */

import { createHash } from 'node:crypto'
import { spawnSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const generator = resolve(root, 'scripts/gen_models.py')
const expectedGeneratorHash = '7fbbbab091a0fe35dbbc2f8e2d3ec4ff70dba36c0b34150cb806a1e37479133b'
const actualGeneratorHash = createHash('sha256').update(readFileSync(generator)).digest('hex')
if (actualGeneratorHash !== expectedGeneratorHash) {
  throw new Error(`gen_models.py hash mismatch: expected ${expectedGeneratorHash}, got ${actualGeneratorHash}`)
}

const python = process.env.REGEN_PYTHON || 'python3'
const args = [generator]
if (process.argv[2]) args.push(process.argv[2])
const result = spawnSync(python, args, { cwd: root, stdio: 'inherit' })
if (result.error) throw result.error
process.exit(result.status ?? 1)
