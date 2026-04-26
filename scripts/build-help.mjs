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
  const excludedSections = new Set(['Table of Contents', '1. Installation Options', 'References'])
  const excludedSubsections = new Set(['4.1 First-Run Setup Screen'])
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

function renderMarkdown(markdown) {
  const lines = markdown.split(/\r?\n/)
  const output = []
  const listStack = []
  let paragraph = []
  let inCodeBlock = false
  let codeLines = []
  let tableState = null

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
  return output.join('\n')
}

function extractHeadings(markdown) {
  return markdown
    .split(/\r?\n/)
    .map((line) => line.match(/^(#{2,4})\s+(.*)$/))
    .filter(Boolean)
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
        <div class="help-toc-header">
          <h2 id="help-toc-title">Quick Index</h2>
          <p>Jump directly to a task or section.</p>
        </div>
        <ol>
${items}
        </ol>
      </nav>`
}

function buildHtml(markdown, metadata) {
  const curated = curateMarkdown(markdown)
  const headings = extractHeadings(curated)
  const body = renderMarkdown(curated)
  const toc = renderTableOfContents(headings)
  const updatedLabel = metadata.updatedOn ? `<p class="help-meta">Updated: ${escapeHtml(metadata.updatedOn)}</p>` : ''
  return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>ECUBE Help</title>
    <style>
      :root {
        color-scheme: light;
        --help-bg: #f4efe7;
        --help-panel: #fffdf8;
        --help-border: #d8cbb7;
        --help-text: #2f261b;
        --help-muted: #6b5f51;
        --help-accent: #0f5c4d;
        --help-accent-soft: #e2f0ec;
        --help-code-bg: #f1e7d8;
        --help-shadow: 0 18px 48px rgba(47, 38, 27, 0.12);
        --help-radius: 18px;
        --help-font: Georgia, 'Times New Roman', serif;
        --help-ui-font: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
      }

      * { box-sizing: border-box; }

      body {
        margin: 0;
        padding: 24px;
        background:
          radial-gradient(circle at top left, rgba(15, 92, 77, 0.08), transparent 30%),
          linear-gradient(180deg, #f8f3ec 0%, var(--help-bg) 100%);
        color: var(--help-text);
        font-family: var(--help-font);
        line-height: 1.6;
      }

      main {
        max-width: 920px;
        margin: 0 auto;
        padding: 32px;
        background: var(--help-panel);
        border: 1px solid var(--help-border);
        border-radius: var(--help-radius);
        box-shadow: var(--help-shadow);
      }

      .help-kicker {
        margin: 0;
        font-family: var(--help-ui-font);
        font-size: 0.8rem;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--help-accent);
      }

      h1 {
        margin: 0.35rem 0 0.25rem;
        font-size: clamp(2rem, 3vw, 3rem);
        line-height: 1.1;
      }

      .help-meta,
      .help-lead {
        margin: 0.25rem 0 0;
        font-family: var(--help-ui-font);
        color: var(--help-muted);
      }

      .help-toc {
        margin: 1.5rem 0 2rem;
        padding: 1rem 1.25rem;
        background: #f7f1e6;
        border: 1px solid var(--help-border);
        border-radius: 14px;
      }

      .help-toc-header {
        margin-bottom: 0.75rem;
      }

      .help-toc-header h2,
      .help-toc-header p {
        margin: 0;
      }

      .help-toc-header p {
        margin-top: 0.25rem;
        font-family: var(--help-ui-font);
        color: var(--help-muted);
      }

      .help-toc ol {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
        gap: 0.35rem 1.5rem;
        margin: 0;
        padding: 0;
        list-style: none;
      }

      .help-toc li {
        font-family: var(--help-ui-font);
      }

      .help-toc .toc-level-3,
      .help-toc .toc-level-4 {
        padding-left: 1rem;
      }

      .help-toc a {
        display: inline-block;
        text-decoration: none;
      }

      .help-toc a:hover,
      .help-toc a:focus-visible {
        text-decoration: underline;
      }

      h1,
      h2,
      h3,
      h4 {
        color: #1e1a14;
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
        background: #2f261b;
        color: #fff8ee;
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
        background: #f1e7d8;
      }

      ul,
      ol {
        padding-left: 1.5rem;
      }

      @media (max-width: 720px) {
        body {
          padding: 12px;
        }

        main {
          padding: 20px;
        }
      }
    </style>
  </head>
  <body>
    <main>
      <p class="help-kicker">In-App Help</p>
      <h1>ECUBE User Guide</h1>
      ${updatedLabel}
      <p class="help-lead">Task-focused guidance for signed-in ECUBE users.</p>
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