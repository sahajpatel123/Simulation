'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { PanelLeftClose, PanelLeftOpen } from 'lucide-react'

type Item = { num: string; label: string; href: string; hint?: string }

const sections: { title: string; items: Item[] }[] = [
  {
    title: 'The Desk',
    items: [
      { num: '01', label: 'Dossiers', href: '/projects', hint: 'Your filed ideas' },
      { num: '02', label: 'Dashboard', href: '/dashboard', hint: 'Overview' },
    ],
  },
  {
    title: 'Field Work',
    items: [
      { num: '03', label: 'Drafts', href: '/projects?filter=draft' },
      { num: '04', label: 'In Simulation', href: '/projects?filter=running' },
      { num: '05', label: 'Archived', href: '/projects?filter=done' },
    ],
  },
  {
    title: 'Operations',
    items: [
      { num: '06', label: 'Settings', href: '#' },
      { num: '07', label: 'Help & Style Guide', href: '#' },
    ],
  },
]

type SidebarProps = {
  collapsed: boolean
  onToggle: () => void
}

export default function Sidebar({ collapsed, onToggle }: SidebarProps) {
  const pathname = usePathname()
  const isActive = (href: string) => {
    const base = href.split('?')[0]
    if (base === '#') return false
    if (base === '/projects') return pathname === '/projects' || pathname.startsWith('/project/')
    return pathname === base
  }

  return (
    <aside
      style={{
        position: 'sticky',
        top: 120,
        alignSelf: 'start',
        height: 'calc(100vh - 120px)',
        borderRight: '0.5px solid var(--border-color)',
        padding: collapsed ? '24px 0 24px 0' : '40px 28px 32px 40px',
        display: 'flex',
        flexDirection: 'column',
        gap: collapsed ? 28 : 40,
        overflow: 'auto',
        transition: 'padding 320ms cubic-bezier(0.2, 0.7, 0.2, 1), gap 320ms cubic-bezier(0.2, 0.7, 0.2, 1)',
      }}
      className="archive-scroll"
    >
      {/* Toggle — small ink-bordered square, stays out of the way. */}
      <div
        style={{
          display: 'flex',
          justifyContent: collapsed ? 'center' : 'flex-end',
          transition: 'justify-content 320ms ease',
        }}
      >
        <button
          onClick={onToggle}
          aria-label={collapsed ? 'Expand contents' : 'Collapse contents'}
          aria-expanded={!collapsed}
          title={collapsed ? 'Expand contents' : 'Collapse contents'}
          style={{
            width: 28,
            height: 28,
            border: '0.5px solid var(--border-strong)',
            background: 'transparent',
            color: 'var(--ink)',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            transition: 'border-color 180ms ease, color 180ms ease, background 180ms ease',
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.borderColor = 'var(--ink)'
            e.currentTarget.style.color = 'var(--red)'
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.borderColor = 'var(--border-strong)'
            e.currentTarget.style.color = 'var(--ink)'
          }}
        >
          {collapsed ? (
            <PanelLeftOpen style={{ width: 14, height: 14 }} />
          ) : (
            <PanelLeftClose style={{ width: 14, height: 14 }} />
          )}
        </button>
      </div>

      {/* ─── COLLAPSED: numerals-only rail ─────────────────────── */}
      {collapsed && (
        <nav
          style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: 4,
          }}
        >
          {sections.map((section, si) => (
            <div
              key={section.title}
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                gap: 4,
                paddingTop: si === 0 ? 0 : 14,
                marginTop: si === 0 ? 0 : 10,
                borderTop: si === 0 ? 'none' : '0.5px solid var(--border-color)',
                width: 28,
              }}
            >
              {section.items.map((item) => {
                const active = isActive(item.href)
                return (
                  <Link
                    key={item.num + item.label}
                    href={item.href}
                    title={item.label}
                    aria-label={item.label}
                    style={{
                      width: 28,
                      height: 28,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      textDecoration: 'none',
                      borderLeft: active ? '2px solid var(--red)' : '2px solid transparent',
                      transition: 'background 180ms ease, color 180ms ease',
                    }}
                    className="numeral"
                  >
                    <span
                      style={{
                        fontFamily: 'var(--font-serif)',
                        fontSize: 13,
                        fontWeight: active ? 800 : 700,
                        color: active ? 'var(--red)' : 'var(--ink-tertiary)',
                        letterSpacing: '-0.01em',
                      }}
                    >
                      {item.num}
                    </span>
                  </Link>
                )
              })}
            </div>
          ))}
        </nav>
      )}

      {/* ─── EXPANDED: full contents page ──────────────────────── */}
      {!collapsed && (
        <>
          {/* Masthead */}
          <div>
            <div
              style={{
                fontSize: 9,
                letterSpacing: '0.3em',
                textTransform: 'uppercase',
                color: 'var(--ink-tertiary)',
                marginBottom: 8,
              }}
            >
              Section Index
            </div>
            <div
              style={{
                fontFamily: 'var(--font-serif)',
                fontSize: 28,
                fontWeight: 800,
                fontStyle: 'italic',
                lineHeight: 1,
                letterSpacing: '-0.02em',
                color: 'var(--ink)',
              }}
            >
              Contents
            </div>
            <div style={{ height: 2, background: 'var(--red)', width: 40, marginTop: 12 }} />
          </div>

          {sections.map((section) => (
            <nav key={section.title}>
              <div
                style={{
                  fontSize: 9,
                  letterSpacing: '0.3em',
                  textTransform: 'uppercase',
                  color: 'var(--ink-secondary)',
                  fontWeight: 600,
                  marginBottom: 14,
                  paddingBottom: 10,
                  borderBottom: '0.5px solid var(--border-color)',
                }}
              >
                {section.title}
              </div>

              <ul style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 2 }}>
                {section.items.map((item) => {
                  const active = isActive(item.href)
                  return (
                    <li key={item.num + item.label}>
                      <Link
                        href={item.href}
                        style={{
                          display: 'grid',
                          gridTemplateColumns: '28px 1fr',
                          alignItems: 'baseline',
                          gap: 10,
                          padding: '8px 0',
                          textDecoration: 'none',
                          color: active ? 'var(--red)' : 'var(--ink)',
                          borderLeft: active ? '2px solid var(--red)' : '2px solid transparent',
                          paddingLeft: active ? 10 : 0,
                          transition: 'all 220ms ease',
                        }}
                      >
                        <span
                          className="numeral"
                          style={{
                            fontSize: 13,
                            fontWeight: 700,
                            color: active ? 'var(--red)' : 'var(--ink-tertiary)',
                          }}
                        >
                          {item.num}
                        </span>
                        <span style={{ display: 'flex', flexDirection: 'column' }}>
                          <span
                            style={{
                              fontFamily: 'var(--font-serif)',
                              fontSize: 17,
                              fontWeight: active ? 800 : 700,
                              fontStyle: active ? 'italic' : 'normal',
                              lineHeight: 1.15,
                              letterSpacing: '-0.01em',
                            }}
                          >
                            {item.label}
                          </span>
                          {item.hint && (
                            <span
                              style={{
                                fontSize: 10,
                                letterSpacing: '0.14em',
                                textTransform: 'uppercase',
                                color: 'var(--ink-secondary)',
                                marginTop: 3,
                                fontWeight: 400,
                              }}
                            >
                              {item.hint}
                            </span>
                          )}
                        </span>
                      </Link>
                    </li>
                  )
                })}
              </ul>
            </nav>
          ))}

          {/* Colophon */}
          <div
            style={{
              marginTop: 'auto',
              paddingTop: 24,
              borderTop: '0.5px solid var(--border-color)',
              fontSize: 9,
              letterSpacing: '0.22em',
              textTransform: 'uppercase',
              color: 'var(--ink-tertiary)',
              lineHeight: 1.7,
            }}
          >
            Printed in the browser<br />
            Est. 2026 · Ed.&nbsp;I
          </div>
        </>
      )}
    </aside>
  )
}
