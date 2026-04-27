import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import { access, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { constants as fsConstants } from 'node:fs'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { tmpdir } from 'node:os'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { build } from 'vite'

const execFileAsync = promisify(execFile)
const testsRoot = dirname(fileURLToPath(import.meta.url))
const frontendRoot = resolve(testsRoot, '../../..')
const repoRoot = resolve(frontendRoot, '..')
let outputDir = ''
let fixtureRoot = ''

beforeAll(async () => {
  await execFileAsync('node', ['scripts/build-help.mjs'], { cwd: repoRoot })
  outputDir = await mkdtemp(resolve(tmpdir(), 'ecube-help-build-'))
  fixtureRoot = await mkdtemp(resolve(tmpdir(), 'ecube-help-fixture-'))
  await writeFile(
    resolve(fixtureRoot, 'index.html'),
    '<!doctype html><html lang="en"><body><div id="app"></div><script type="module" src="/main.js"></script></body></html>',
    'utf8',
  )
  await writeFile(resolve(fixtureRoot, 'main.js'), 'document.getElementById("app").textContent = "fixture"\n', 'utf8')
})

afterAll(async () => {
  if (outputDir) {
    await rm(outputDir, { recursive: true, force: true })
  }
  if (fixtureRoot) {
    await rm(fixtureRoot, { recursive: true, force: true })
  }
})

describe('generated help asset', () => {
  it('is copied into Vite build output', async () => {
    await build(
      {
        root: fixtureRoot,
        publicDir: resolve(frontendRoot, 'public'),
        logLevel: 'silent',
        build: {
          outDir: outputDir,
          emptyOutDir: true,
        },
      },
    )

    const builtHelpPath = resolve(outputDir, 'help/manual.html')
    await access(builtHelpPath, fsConstants.R_OK)
    const html = await readFile(builtHelpPath, 'utf8')

    expect(html).toContain('id="ecube-theme-stylesheet"')
    expect(html).toContain('href="../themes/default.css"')
    expect(html).toContain("localStorage.getItem(themeStorageKey)")
    expect(html).toContain("themeLink.href = '../themes/' + themeName + '.css'")
    expect(html).toContain('--help-bg: var(--color-bg-secondary, #f8f9fa);')
    expect(html).toContain('<h2 id="help-toc-title">Table of Contents</h2>')
    expect(html).toContain('aria-labelledby="help-toc-title"')
    expect(html).toContain('display: block;')
    expect(html).toContain('href="#1-roles-and-access"')
    expect(html).toContain('<h1 id="5-mounts">5. Mounts</h1>')
    expect(html).toContain('<h2 id="5-4-directory-browser">5.4 Directory Browser</h2>')
    expect(html).not.toContain('<h1 id="5-4-directory-browser">5.4 Directory Browser</h1>')
    expect(html).toContain('<h3 id="5-1-1-editing-a-mount">5.1.1 Editing a Mount</h3>')
    expect(html).not.toContain('class="help-kicker"')
    expect(html).toContain('class="help-back-to-top"')
    expect(html).toContain('href="#help-toc-title">Back to top</a>')
  })
})