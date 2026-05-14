import type { Metadata } from "next"
import Link from "next/link"
import { SettingsButton } from "@/components/settings-panel"
import "./globals.css"

export const metadata: Metadata = {
  title: "ResearchGroup-Agent",
  description: "多 Agent 模拟研究生课题组协作系统",
}

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body className="min-h-screen bg-gray-50 font-sans antialiased text-gray-900" suppressHydrationWarning>
        <header className="sticky top-0 z-50 border-b bg-white/95 backdrop-blur">
          <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3">
            <Link href="/" className="text-lg font-bold text-gray-900">
              ResearchGroup-Agent
            </Link>
            <nav className="flex items-center gap-6 text-sm">
              <Link href="/" className="text-gray-600 hover:text-gray-900">首页</Link>
              <Link href="/tasks" className="text-gray-600 hover:text-gray-900">任务板</Link>
              <Link href="/agents" className="text-gray-600 hover:text-gray-900">Agent</Link>
              <Link href="/skills" className="text-gray-600 hover:text-gray-900">Skills</Link>
              <Link href="/experiments" className="text-gray-600 hover:text-gray-900">Experiments</Link>
              <Link href="/outputs" className="text-gray-600 hover:text-gray-900">输出</Link>
              <Link href="/office" className="text-gray-600 hover:text-gray-900">像素办公室</Link>
              <SettingsButton />
            </nav>
          </div>
        </header>
        <main className="mx-auto max-w-7xl px-4 py-6">{children}</main>
      </body>
    </html>
  )
}
