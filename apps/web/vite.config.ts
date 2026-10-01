import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { tanstackStart } from '@tanstack/react-start/plugin/vite'
import viteReact from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

type CatalogEntry = { slug: string }
const catalogPath = fileURLToPath(new URL('../../showcases/catalog.json', import.meta.url))
const catalog = JSON.parse(readFileSync(catalogPath, 'utf8')) as CatalogEntry[]

export default defineConfig({
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
  },
  plugins: [
    tanstackStart({
      prerender: {
        enabled: true,
        autoSubfolderIndex: true,
        autoStaticPathsDiscovery: false,
        crawlLinks: false,
        failOnError: true,
      },
      pages: [
        { path: '/', prerender: { enabled: true } },
        ...catalog.map(({ slug }) => ({
          path: `/showcases/${slug}`,
          prerender: { enabled: true },
        })),
      ],
    }),
    viteReact(),
  ],
})
