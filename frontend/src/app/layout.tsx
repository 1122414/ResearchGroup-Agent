import type { Metadata } from "next"
import Link from "next/link"
import { SettingsButton } from "@/components/settings-panel"
import "./globals.css"

export const metadata: Metadata = {
  title: "ResearchGroup-Agent",
  description: "多 Agent 模拟研究生课题组协作系统",
}

const NAV_ITEMS = [
  { href: "/", label: "工作台" },
  { href: "/tasks", label: "任务板" },
  { href: "/agents", label: "Agent" },
  { href: "/skills", label: "Skills" },
  { href: "/experiments", label: "实验" },
  { href: "/outputs", label: "输出" },
  { href: "/office", label: "办公室" },
]

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body className="min-h-screen font-sans antialiased" suppressHydrationWarning>
        <header className="app-header">
          <div className="app-container flex min-h-14 items-center justify-between gap-4 py-2">
            <Link href="/" className="flex items-center gap-2 text-sm font-semibold text-[var(--rg-ink)]">
              <span className="brand-mark">R</span>
              <span className="hidden sm:inline">ResearchGroup-Agent</span>
            </Link>
            <nav className="flex min-w-0 items-center gap-1 overflow-x-auto">
              {NAV_ITEMS.map((item) => (
                <Link key={item.href} href={item.href} className="nav-link">
                  {item.label}
                </Link>
              ))}
              <SettingsButton />
            </nav>
          </div>
        </header>
        <main className="app-container py-6">{children}</main>
      </body>
    </html>
  )
}
