import type { Metadata } from "next"
import { Geist, Geist_Mono } from "next/font/google"
import Link from "next/link"
import "./globals.css"

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] })
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] })

export const metadata: Metadata = {
  title: "ResearchGroup-Agent",
  description: "面向研究生课题组场景的多Agent协作系统",
}

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body className={`${geistSans.variable} ${geistMono.variable} antialiased bg-gray-50 min-h-screen`}>
        <header className="border-b bg-white sticky top-0 z-50">
          <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
            <Link href="/" className="font-bold text-lg text-gray-900">
              ResearchGroup-Agent
            </Link>
            <nav className="flex gap-6 text-sm">
              <Link href="/" className="text-gray-600 hover:text-gray-900">首页</Link>
              <Link href="/tasks" className="text-gray-600 hover:text-gray-900">任务板</Link>
              <Link href="/agents" className="text-gray-600 hover:text-gray-900">Agent</Link>
              <Link href="/outputs" className="text-gray-600 hover:text-gray-900">产出</Link>
            </nav>
          </div>
        </header>
        <main className="max-w-7xl mx-auto px-4 py-6">{children}</main>
      </body>
    </html>
  )
}
