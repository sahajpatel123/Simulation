import type { Metadata } from 'next'
import { DM_Sans, DM_Serif_Display, Playfair_Display } from 'next/font/google'
import { Toaster } from 'sonner'
import Providers from './providers'
import HydrateAuth from '@/components/layout/HydrateAuth'
import ScrollChrome from '@/components/layout/ScrollChrome'
import './globals.css'

const playfair = Playfair_Display({
  subsets: ['latin'],
  variable: '--font-serif',
  weight: ['700', '800', '900'],
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

export const metadata: Metadata = {
  title: 'TheCee — Know Before You Build',
  description: 'Simulate your startup before you commit to it.',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      data-scroll-behavior="smooth"
      className={`${playfair.variable} ${dmSans.variable} ${dmSerifDisplay.variable}`}
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
