import { stat } from 'node:fs/promises'
import { extname, relative, resolve, sep } from 'node:path'

const staticRoot = resolve(import.meta.dir, '../dist/client')
const types: Record<string, string> = {
  '.css': 'text/css; charset=utf-8',
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.svg': 'image/svg+xml',
  '.woff2': 'font/woff2',
}

function safeFile(pathname: string): string | undefined {
  let decoded: string
  try {
    decoded = decodeURIComponent(pathname)
  } catch {
    return undefined
  }
  const candidate = resolve(staticRoot, `.${decoded}`)
  const rel = relative(staticRoot, candidate)
  if (rel === '..' || rel.startsWith(`..${sep}`) || rel.startsWith(sep)) return undefined
  return candidate
}

const port = Number(process.env.PORT ?? 4173)
if (!Number.isInteger(port) || port < 1 || port > 65535) {
  throw new Error('PORT must be a valid TCP port')
}

const server = Bun.serve({
  hostname: '127.0.0.1',
  port,
  async fetch(request) {
    if (request.method !== 'GET' && request.method !== 'HEAD') {
      return new Response('Method not allowed', { status: 405, headers: { Allow: 'GET, HEAD' } })
    }
    const url = new URL(request.url)
    let file = safeFile(url.pathname)
    if (!file) return new Response('Not found', { status: 404 })

    const info = await stat(file).catch(() => undefined)
    if (info?.isDirectory()) {
      file = resolve(file, 'index.html')
    } else if (!info && url.pathname.startsWith('/showcases/')) {
      file = resolve(staticRoot, 'index.html')
    }

    const item = Bun.file(file)
    if (!(await item.exists())) return new Response('Not found', { status: 404 })
    const headers = new Headers({
      'Content-Type': types[extname(file)] ?? 'application/octet-stream',
      'X-Content-Type-Options': 'nosniff',
    })
    return new Response(request.method === 'HEAD' ? null : item, { headers })
  },
})

console.log(`Static website preview: http://127.0.0.1:${server.port}/`)
