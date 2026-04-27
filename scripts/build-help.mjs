#!/usr/bin/env node

import { access, mkdir, readFile, writeFile } from 'node:fs/promises'
import { constants as fsConstants } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const scriptPath = fileURLToPath(import.meta.url)
const repoRoot = resolve(dirname(scriptPath), '..')
const defaultSourcePath = resolve(repoRoot, 'docs/operations/13-user-manual.md')
const defaultOutputPath = resolve(repoRoot, 'frontend/public/help/manual.html')

function parseArgs(argv) {
  const options = {
    source: defaultSourcePath,
    output: defaultOutputPath,
    check: false,
  }

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index]
    if (arg === '--check') {
      options.check = true
      continue
    }
    if (arg === '--source') {
      const value = argv[index + 1]
      if (!value || value.startsWith('--')) {
        throw new Error('--source requires a path value')
      }
      options.source = resolve(repoRoot, value)
      index += 1
      continue
    }
    if (arg === '--output') {
      const value = argv[index + 1]
      if (!value || value.startsWith('--')) {
        throw new Error('--output requires a path value')
      }
      options.output = resolve(repoRoot, value)
      index += 1
      continue
    }
    if (arg === '-h' || arg === '--help') {
      printUsage()
      process.exit(0)
    }
    throw new Error(`Unknown option: ${arg}`)
  }

  return options
}

function printUsage() {
  process.stdout.write(`Usage: node scripts/build-help.mjs [--check] [--source PATH] [--output PATH]\n\n`)
}

function escapeHtml(value) {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
}

function slugify(value) {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
}

function renderInline(value) {
  let rendered = escapeHtml(value)
  rendered = rendered.replace(/`([^`]+)`/g, '<code>$1</code>')
  rendered = rendered.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
  rendered = rendered.replace(/\*([^*]+)\*/g, '<em>$1</em>')
  rendered = rendered.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_match, label, href) => {
    if (href.startsWith('http://') || href.startsWith('https://') || href.startsWith('#')) {
      return `<a href="${escapeHtml(href)}">${escapeHtml(label)}</a>`
    }
    return escapeHtml(formatDocReference(label, href))
  })
  return rendered
}

function formatDocReference(label, href) {
  const candidate = label && label !== href ? label : href
  const basename = candidate.split('/').pop() ?? candidate
  const withoutExtension = basename.replace(/\.md$/i, '')
  const withoutNumericPrefix = withoutExtension.replace(/^\d+[-_]?/, '')
  const normalized = withoutNumericPrefix
    .replace(/[-_]+/g, ' ')
    .replace(/\bapi\b/gi, 'API')
    .replace(/\becube\b/gi, 'ECUBE')
    .trim()

  if (!normalized) {
    return 'related documentation'
  }

  return normalized.charAt(0).toUpperCase() + normalized.slice(1)
}

function parseMetadata(markdown) {
  const updatedMatch = markdown.match(/\|\s*Updated on\s*\|\s*([^|]+)\|/)
  return {
    updatedOn: updatedMatch ? updatedMatch[1].trim() : '',
  }
}

function curateMarkdown(markdown) {
  const excludedSections = new Set([
    'Table of Contents',
    'Purpose',
    'Scope',
    '1. Installation Options',
    '2. Before You Begin',
    '4. First Access',
    'References',
  ])
  const excludedSubsections = new Set()
  const curated = []
  const lines = markdown.split(/\r?\n/)
  let skippingTitleBlock = true
  let skipUntilNextHeadingLevel = null

  for (const line of lines) {
    if (skippingTitleBlock) {
      if (line.startsWith('## ')) {
        skippingTitleBlock = false
      } else {
        continue
      }
    }

    const headingMatch = line.match(/^(#{2,4})\s+(.*)$/)
    if (headingMatch) {
      const headingLevel = headingMatch[1].length
      const headingText = headingMatch[2].trim()
      if (skipUntilNextHeadingLevel !== null && headingLevel <= skipUntilNextHeadingLevel) {
        skipUntilNextHeadingLevel = null
      }
      if (excludedSections.has(headingText) || excludedSubsections.has(headingText)) {
        skipUntilNextHeadingLevel = headingLevel
        continue
      }
    }

    if (skipUntilNextHeadingLevel !== null) {
      continue
    }

    if (line.startsWith('![')) {
      continue
    }

    curated.push(line)
  }

  return curated.join('\n').trim()
}

function parseNumberedHeading(text) {
  const match = text.trim().match(/^(\d+)((?:\.[0-9A-Za-z]+)*)\.?\s+(.+)$/)
  if (!match) {
    return null
  }

  return {
    major: Number.parseInt(match[1], 10),
    suffix: match[2] ?? '',
    title: match[3].trim(),
  }
}

function renumberCuratedMarkdown(markdown) {
  const lines = markdown.split(/\r?\n/)
  const headingIdMap = new Map()
  const headingTextMap = new Map()
  const majorNumberMap = new Map()
  let nextMajorNumber = 1

  for (const line of lines) {
    const headingMatch = line.match(/^(#{2,4})\s+(.*)$/)
    if (!headingMatch || headingMatch[1].length !== 2) {
      continue
    }

    const numberedHeading = parseNumberedHeading(headingMatch[2].trim())
    if (!numberedHeading) {
      continue
    }

    if (!majorNumberMap.has(numberedHeading.major)) {
      majorNumberMap.set(numberedHeading.major, nextMajorNumber)
      nextMajorNumber += 1
    }
  }

  for (const line of lines) {
    const headingMatch = line.match(/^(#{2,4})\s+(.*)$/)
    if (!headingMatch) {
      continue
    }

    const originalText = headingMatch[2].trim()
    const numberedHeading = parseNumberedHeading(originalText)
    if (!numberedHeading) {
      continue
    }

    const renumberedMajor = majorNumberMap.get(numberedHeading.major)
    const renumberedText = numberedHeading.suffix
      ? `${renumberedMajor}${numberedHeading.suffix} ${numberedHeading.title}`
      : `${renumberedMajor}. ${numberedHeading.title}`
    headingTextMap.set(originalText, renumberedText)
    headingIdMap.set(slugify(originalText), slugify(renumberedText))
  }

  return lines
    .map((line) => {
      const headingMatch = line.match(/^(#{2,4})\s+(.*)$/)
      if (headingMatch) {
        const originalText = headingMatch[2].trim()
        const renumberedText = headingTextMap.get(originalText)
        if (renumberedText) {
          return `${headingMatch[1]} ${renumberedText}`
        }
      }

      return line.replace(/\[([^\]]+)\]\((#[^)]+)\)/g, (_match, label, href) => {
        const originalId = href.slice(1)
        const updatedHref = headingIdMap.has(originalId) ? `#${headingIdMap.get(originalId)}` : href
        const updatedLabel = headingTextMap.get(label) ?? label
        return `[${updatedLabel}](${updatedHref})`
      })
    })
    .join('\n')
}

function renderMarkdown(markdown) {
  const lines = markdown.split(/\r?\n/)
  const output = []
  const listStack = []
  let paragraph = []
  let inCodeBlock = false
  let codeLines = []
  let tableState = null
  const backToTopHtml = '<p class="help-back-to-top"><a href="#help-toc-title">Back to top</a></p>'

  function flushParagraph() {
    if (!paragraph.length) return
    output.push(`<p>${renderInline(paragraph.join(' '))}</p>`)
    paragraph = []
  }

  function closeLists(targetDepth = 0) {
    while (listStack.length > targetDepth) {
      const tag = listStack.pop()
      output.push(`</li></${tag}>`)
    }
  }

  function flushTable() {
    if (!tableState) return
    const [headerRow, ...bodyRows] = tableState.rows
    output.push('<table><thead><tr>')
    for (const cell of headerRow) {
      output.push(`<th>${renderInline(cell)}</th>`)
    }
    output.push('</tr></thead>')
    if (bodyRows.length) {
      output.push('<tbody>')
      for (const row of bodyRows) {
        output.push('<tr>')
        for (const cell of row) {
          output.push(`<td>${renderInline(cell)}</td>`)
        }
        output.push('</tr>')
      }
      output.push('</tbody>')
    }
    output.push('</table>')
    tableState = null
  }

  function ensureList(depth, tag) {
    while (listStack.length < depth + 1) {
      listStack.push(tag)
      output.push(`<${tag}><li>`)
    }
    while (listStack.length > depth + 1) {
      const closingTag = listStack.pop()
      output.push(`</li></${closingTag}>`)
    }
    if (listStack[listStack.length - 1] !== tag) {
      const closingTag = listStack.pop()
      output.push(`</li></${closingTag}>`)
      listStack.push(tag)
      output.push(`<${tag}><li>`)
      return
    }
    if (!output.at(-1)?.endsWith('<li>')) {
      output.push('</li><li>')
    }
  }

  for (const rawLine of lines) {
    const line = rawLine.replace(/\t/g, '    ')

    if (inCodeBlock) {
      if (line.startsWith('```')) {
        output.push(`<pre><code>${escapeHtml(codeLines.join('\n'))}</code></pre>`)
        codeLines = []
        inCodeBlock = false
      } else {
        codeLines.push(rawLine)
      }
      continue
    }

    if (line.startsWith('```')) {
      flushParagraph()
      flushTable()
      closeLists()
      inCodeBlock = true
      codeLines = []
      continue
    }

    if (!line.trim()) {
      flushParagraph()
      flushTable()
      closeLists()
      continue
    }

    if (/^\|/.test(line) && /\|$/.test(line.trim())) {
      flushParagraph()
      closeLists()
      const cells = line
        .trim()
        .slice(1, -1)
        .split('|')
        .map((cell) => cell.trim())
      if (cells.every((cell) => /^:?-{3,}:?$/.test(cell))) {
        if (!tableState) {
          throw new Error('Markdown table separator found before header row')
        }
        tableState.separatorSeen = true
      } else {
        if (!tableState) {
          tableState = { rows: [], separatorSeen: false }
        }
        tableState.rows.push(cells)
      }
      continue
    }

    flushTable()

    const headingMatch = line.match(/^(#{2,4})\s+(.*)$/)
    if (headingMatch) {
      flushParagraph()
      closeLists()
      const level = headingMatch[1].length
      const text = headingMatch[2].trim()
      const id = slugify(text)
      output.push(`<h${level - 1} id="${id}">${renderInline(text)}</h${level - 1}>`)
      continue
    }

    if (/^---+$/.test(line.trim())) {
      flushParagraph()
      closeLists()
      output.push(backToTopHtml)
      output.push('<hr />')
      continue
    }

    if (line.startsWith('> ')) {
      flushParagraph()
      closeLists()
      output.push(`<blockquote><p>${renderInline(line.slice(2).trim())}</p></blockquote>`)
      continue
    }

    const listMatch = line.match(/^(\s*)([-*]|\d+\.)\s+(.*)$/)
    if (listMatch) {
      flushParagraph()
      const depth = Math.floor(listMatch[1].length / 2)
      const tag = /\d+\./.test(listMatch[2]) ? 'ol' : 'ul'
      ensureList(depth, tag)
      output.push(renderInline(listMatch[3].trim()))
      continue
    }

    paragraph.push(line.trim())
  }

  if (inCodeBlock) {
    output.push(`<pre><code>${escapeHtml(codeLines.join('\n'))}</code></pre>`)
  }
  flushParagraph()
  flushTable()
  closeLists()
  if (output.length && output.at(-1) !== '<hr />') {
    output.push(backToTopHtml)
  }
  return output.join('\n')
}

function extractHeadings(markdown) {
  return markdown
    .split(/\r?\n/)
    .map((line) => line.match(/^(#{2,4})\s+(.*)$/))
    .filter(Boolean)
    .filter((match) => match[1].length === 2)
    .filter((match) => {
      const numberedHeading = parseNumberedHeading(match[2].trim())
      return !numberedHeading || numberedHeading.suffix === ''
    })
    .map((match) => ({
      level: match[1].length - 1,
      text: match[2].trim(),
      id: slugify(match[2].trim()),
    }))
}

function renderTableOfContents(headings) {
  if (!headings.length) {
    return ''
  }

  const items = headings
    .map(
      (heading) =>
        `<li class="toc-level-${heading.level}"><a href="#${heading.id}">${escapeHtml(heading.text)}</a></li>`,
    )
    .join('\n')

    return `<nav class="help-toc" aria-labelledby="help-toc-title">
      <h2 id="help-toc-title">Table of Contents</h2>
        <ol>
${items}
        </ol>
      </nav>`
}

function buildHtml(markdown, metadata) {
  const curated = renumberCuratedMarkdown(curateMarkdown(markdown))
  const headings = extractHeadings(curated)
  const body = renderMarkdown(curated)
  const toc = renderTableOfContents(headings)
  return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>ECUBE Help</title>
    <link id="ecube-theme-stylesheet" rel="stylesheet" href="../themes/default.css" />
    <script>
      (() => {
        const themeStorageKey = 'ecube_theme'
        const validThemeName = /^[a-z0-9][a-z0-9-]*$/
        let themeName = 'default'

        try {
          const storedTheme = localStorage.getItem(themeStorageKey)
          if (storedTheme && validThemeName.test(storedTheme)) {
            themeName = storedTheme
          }
        } catch {
          // Ignore storage access failures and keep the default theme.
        }

        const themeLink = document.getElementById('ecube-theme-stylesheet')
        if (themeLink) {
          themeLink.href = '../themes/' + themeName + '.css'
        }
      })()
    </script>
    <style>
      :root {
        color-scheme: light dark;
        --help-bg: var(--color-bg-secondary, #f8f9fa);
        --help-panel: var(--color-bg-primary, #ffffff);
        --help-border: var(--color-border, #e2e8f0);
        --help-text: var(--color-text-primary, #1e293b);
        --help-muted: var(--color-text-secondary, #64748b);
        --help-accent: var(--color-text-link, #2563eb);
        --help-accent-soft: var(--color-bg-selected, #dbeafe);
        --help-code-bg: var(--color-bg-hover, #e2e8f0);
        --help-shadow: var(--shadow-lg, 0 10px 15px rgba(0, 0, 0, 0.1));
        --help-radius: var(--border-radius-lg, 8px);
        --help-font: var(--font-family, 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif);
        --help-ui-font: var(--font-family, 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif);
      }

      * { box-sizing: border-box; }

      html {
        overflow-y: scroll;
        scrollbar-gutter: stable;
        scrollbar-width: auto;
        scrollbar-color: var(--color-border) var(--color-bg-secondary);
      }

      body {
        margin: 0;
        padding: 0;
        background: var(--help-panel);
        color: var(--help-text);
        font-family: var(--help-font);
        line-height: 1.6;
      }

      html::-webkit-scrollbar {
        width: 12px;
        height: 12px;
      }

      html::-webkit-scrollbar-track {
        background: var(--color-bg-secondary);
        border-left: 1px solid var(--color-border);
      }

      html::-webkit-scrollbar-thumb {
        background: var(--color-border);
        border-radius: 999px;
        border: 2px solid var(--color-bg-secondary);
      }

      html::-webkit-scrollbar-thumb:hover {
        background: var(--color-text-secondary);
      }

      main {
        max-width: 920px;
        margin: 0 auto;
        padding: 32px;
      }

      h1 {
        margin: 0.35rem 0 0.25rem;
        font-size: clamp(2rem, 3vw, 3rem);
        line-height: 1.1;
      }

      .help-toc {
        margin: 1.5rem 0 2rem;
        padding: 0;
      }

      .help-toc h2 {
        margin: 0 0 0.75rem;
        font-size: clamp(2rem, 3vw, 3rem);
        line-height: 1.1;
      }

      .help-toc ol {
        display: block;
        margin: 0;
        padding: 0;
        list-style: none;
      }

      .help-toc li {
        font-family: var(--help-ui-font);
        margin: 0.25rem 0;
      }

      .help-toc .toc-level-3,
      .help-toc .toc-level-4 {
        padding-left: 1rem;
      }

      .help-toc a {
        text-decoration: none;
      }

      .help-toc a:hover,
      .help-toc a:focus-visible {
        text-decoration: underline;
      }

      .help-back-to-top {
        margin: 1.5rem 0 0.75rem;
        font-family: var(--help-ui-font);
        font-size: 0.95rem;
        text-align: right;
      }

      .help-back-to-top a {
        text-decoration: none;
      }

      .help-back-to-top a:hover,
      .help-back-to-top a:focus-visible {
        text-decoration: underline;
      }

      h1,
      h2,
      h3,
      h4 {
        color: var(--help-text);
      }

      h2,
      h3,
      h4 {
        margin-top: 2rem;
        font-family: var(--help-ui-font);
      }

      a {
        color: var(--help-accent);
      }

      hr {
        border: 0;
        border-top: 1px solid var(--help-border);
        margin: 2rem 0;
      }

      blockquote {
        margin: 1rem 0;
        padding: 0.9rem 1rem;
        border-left: 4px solid var(--help-accent);
        background: var(--help-accent-soft);
        border-radius: 0 12px 12px 0;
        font-family: var(--help-ui-font);
      }

      code,
      pre {
        font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
      }

      code {
        padding: 0.1rem 0.3rem;
        background: var(--help-code-bg);
        border-radius: 4px;
      }

      pre {
        overflow-x: auto;
        padding: 1rem;
        background: var(--color-bg-sidebar, #1e293b);
        color: var(--help-text);
        border-radius: 14px;
      }

      table {
        width: 100%;
        border-collapse: collapse;
        margin: 1rem 0;
        font-family: var(--help-ui-font);
      }

      th,
      td {
        padding: 0.75rem;
        border: 1px solid var(--help-border);
        text-align: left;
        vertical-align: top;
      }

      th {
        background: var(--help-bg);
      }

      ul,
      ol {
        padding-left: 1.5rem;
      }

      @media (max-width: 720px) {
        main {
          padding: 20px;
        }
      }
    </style>
  </head>
  <body>
    <main>
      ${toc}
      ${body}
    </main>
  </body>
</html>
`
}

async function ensureReadable(path) {
  try {
    await access(path, fsConstants.R_OK)
  } catch {
    throw new Error(`Required file not found or unreadable: ${path}`)
  }
}

async function main() {
  try {
    const options = parseArgs(process.argv.slice(2))
    await ensureReadable(options.source)
    const markdown = await readFile(options.source, 'utf8')
    const html = buildHtml(markdown, parseMetadata(markdown))

    if (options.check) {
      await ensureReadable(options.output)
      const existing = await readFile(options.output, 'utf8')
      if (existing !== html) {
        process.stderr.write(`ERROR: ${options.output} is out of date. Run node scripts/build-help.mjs and review the generated help before packaging.\n`)
        process.exit(1)
      }
      process.stdout.write(`verified: ${options.output}\n`)
      return
    }

    await mkdir(dirname(options.output), { recursive: true })
    await writeFile(options.output, html, 'utf8')
    process.stdout.write(`generated: ${options.output}\n`)
  } catch (error) {
    process.stderr.write(`ERROR: ${error.message}\n`)
    process.exit(1)
  }
}

await main()