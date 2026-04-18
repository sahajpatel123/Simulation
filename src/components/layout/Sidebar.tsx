'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'

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
  onCollapse: () => void
  onExpand: () => void
}

export default function Sidebar({ collapsed, onCollapse, onExpand }: SidebarProps) {
  const pathname = usePathname()
  const isActive = (href: string) => {
    const base = href.split('?')[0]
    if (base === '#') return false
    if (base === '/projects') return pathname === '/projects' || pathname.startsWith('/project/')
    return pathname === base
  }

  return (
    <aside
      role="navigation"
      aria-label={collapsed ? 'Table of contents collapsed. Activate to expand.' : 'Workspace table of contents'}
      onClick={collapsed ? () => onExpand() : undefined}
      onKeyDown={
        collapsed
          ? (e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault()
                onExpand()
              }
            }
          : undefined
      }
      tabIndex={collapsed ? 0 : undefined}
      style={{
        position: 'sticky',
        top: 120,
        alignSelf: 'start',
        height: 'calc(100vh - 120px)',
        borderRight: '0.5px solid var(--border-color)',
        padding: collapsed ? '20px 0' : '40px 28px 32px 40px',
        display: 'flex',
        flexDirection: 'column',
        gap: collapsed ? 0 : 40,
        overflow: collapsed ? 'hidden' : 'auto',
        cursor: collapsed ? 'pointer' : 'default',
        outline: 'none',
      }}
      className={`archive-scroll${collapsed ? ' sidebar-collapsed-rail' : ''}`}
    >
      {collapsed ? (
        <div
          aria-hidden
          style={{
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            paddingTop: 12,
            gap: 14,
            pointerEvents: 'none',
            userSelect: 'none',
          }}
        >
          <div style={{ width: 2, height: 40, background: 'var(--red)', flexShrink: 0 }} />
          <span
            className="font-serif"
            style={{
              writingMode: 'vertical-rl',
              transform: 'rotate(180deg)',
              fontSize: 11,
              fontWeight: 800,
              fontStyle: 'italic',
              letterSpacing: '0.2em',
              textTransform: 'uppercase',
              color: 'var(--ink-tertiary)',
            }}
          >
            Open
          </span>
        </div>
      ) : (
        <>
          <div>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                onCollapse()
              }}
              aria-expanded={!collapsed}
              aria-controls="sidebar-toc-nav"
              id="sidebar-contents-toggle"
              style={{
                display: 'block',
                margin: 0,
                padding: 0,
                border: 'none',
                background: 'none',
                cursor: 'pointer',
                textAlign: 'left',
                fontFamily: 'var(--font-serif)',
                fontSize: 28,
                fontWeight: 800,
                fontStyle: 'italic',
                lineHeight: 1,
                letterSpacing: '-0.02em',
                color: 'var(--ink)',
              }}
              className="sidebar-contents-trigger"
            >
              Contents
            </button>
            <div style={{ height: 2, background: 'var(--red)', width: 40, marginTop: 12 }} />
          </div>

          <div id="sidebar-toc-nav">
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
          </div>
        </>
      )}
    </aside>
  )
}
