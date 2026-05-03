import type { Metadata } from 'next'
import { DM_Sans, DM_Serif_Display, JetBrains_Mono, Playfair_Display } from 'next/font/google'
import { Toaster } from 'sonner'
import Providers from './providers'
import HydrateAuth from '@/components/layout/HydrateAuth'
import ScrollChrome from '@/components/layout/ScrollChrome'
import './globals.css'

const playfair = Playfair_Display({
  subsets: ['latin'],
  variable: '--font-serif',
  /** Body copy uses 400 in `.editorial-workspace`; headings use 700–900. Without 400, light weights fall back to Georgia. */
  weight: ['400', '700', '800', '900'],
  style: ['normal', 'italic'],
})

const dmSans = DM_Sans({
  subsets: ['latin'],
  variable: '--font-body',
  weight: ['300', '400', '500'],
})

const dmSerifDisplay = DM_Serif_Display({
  subsets: ['latin'],
  variable: '--font-keyperson',
  weight: '400',
})

const jetbrainsMono = JetBrains_Mono({
  subsets: ['latin'],
  variable: '--font-mono',
  display: 'swap',
})

const allowIndexing = process.env.NEXT_PUBLIC_ALLOW_INDEXING === 'true'

export const metadata: Metadata = {
  title: 'TheCee — Know Before You Build',
  description: 'Simulate your startup before you commit to it.',
  robots: allowIndexing
    ? { index: true, follow: true }
    : { index: false, follow: false },
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      data-scroll-behavior="smooth"
      className={`${playfair.variable} ${dmSans.variable} ${dmSerifDisplay.variable} ${jetbrainsMono.variable}`}
    >
      <body>
        <ScrollChrome />
        <div className="thecee-root-wrap">
          <Providers>
            <HydrateAuth />
            {children}
          </Providers>
        </div>
        <Toaster position="bottom-right" theme="light" />
      </body>
    </html>
  )
}
