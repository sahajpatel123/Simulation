'use client'

import Sidebar from '@/components/layout/Sidebar'
import ProtectedRoute from '@/components/layout/ProtectedRoute'
import UserMenu from '@/components/layout/UserMenu'

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <ProtectedRoute>
      <div className="min-h-screen bg-[#080810] flex">
        <Sidebar />
        <div className="flex-1 ml-60 min-h-screen flex flex-col">
          <div className="flex justify-end items-center px-8 py-4 border-b border-white/5">
            <UserMenu />
          </div>
          <main className="flex-1">{children}</main>
        </div>
      </div>
    </ProtectedRoute>
  )
}
