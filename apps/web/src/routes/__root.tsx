import {
  createRootRoute,
  HeadContent,
  Outlet,
  Scripts,
} from '@tanstack/react-router'
import '@fontsource-variable/geist'
import '@fontsource-variable/geist-mono'
import '../styles/site.css'

export const Route = createRootRoute({
  head: () => ({
    meta: [
      { charSet: 'utf-8' },
      { name: 'viewport', content: 'width=device-width, initial-scale=1' },
      { name: 'color-scheme', content: 'light' },
      { name: 'theme-color', content: '#ffffff' },
      { title: 'ctrlc — Your screenshot. Every element.' },
      {
        name: 'description',
        content: 'A local CLI for turning screenshots into inspectable UI.',
      },
    ],
  }),
  notFoundComponent: () => (
    <main className="not-found">
      <h1>Page not found</h1>
      <p>The requested page is not part of this website.</p>
      <a className="text-link" href="/">Back to showcases</a>
    </main>
  ),
  component: RootDocument,
})

function RootDocument() {
  return (
    <html lang="en">
      <head>
        <HeadContent />
      </head>
      <body>
        <Outlet />
        <Scripts />
      </body>
    </html>
  )
}
