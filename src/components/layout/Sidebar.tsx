'use client'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { Activity, LayoutDashboard, FolderOpen, Settings, LogOut } from 'lucide-react'

const nav = [
  { label: 'Dashboard', href: '/projects', icon: LayoutDashboard },
  { label: 'Projects', href: '/projects', icon: FolderOpen },
  { label: 'Settings', href: '#', icon: Settings },
]

export default function Sidebar() {
  const pathname = usePathname()
  return (
    <aside className="fixed left-0 top-0 h-screen w-60 bg-[#080810] border-r border-white/5 flex flex-col px-4 py-6 z-40">
      <div className="flex items-center gap-2 mb-10 px-2">
        <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-indigo-500 to-cyan-400 flex items-center justify-center">
          <Activity className="w-4 h-4 text-white" />
        </div>
        <span className="font-display font-700 text-white">TheCee</span>
      </div>

      <nav className="flex-1 space-y-1">
        {nav.map(({ label, href, icon: Icon }) => (
          <Link key={label} href={href}
            className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-all duration-200 ${
              pathname.startsWith(href) && href !== '#'
                ? 'bg-indigo-600/15 text-indigo-400 border border-indigo-500/20'
                : 'text-slate-400 hover:text-white hover:bg-white/5'
            }`}
          >
            <Icon className="w-4 h-4" />{label}
          </Link>
        ))}
      </nav>

      <button className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm text-slate-600 hover:text-slate-400 transition-colors">
        <LogOut className="w-4 h-4" /> Sign out
      </button>
    </aside>
  )
}
