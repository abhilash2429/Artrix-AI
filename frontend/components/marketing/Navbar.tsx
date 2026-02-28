"use client"

import Link from "next/link"
import { Button } from "@/components/ui/button"

export function Navbar() {
  return (
    <nav className="flex items-center justify-between px-6 py-4 md:px-12">
      <Link href="/" className="text-lg font-semibold text-gray-900">
        Agent.ai
      </Link>

      <div className="flex items-center gap-8">
        <div className="hidden items-center gap-6 md:flex">
          <Link
            href="#features"
            className="text-sm font-medium text-gray-600 transition-colors duration-150 hover:text-gray-900"
          >
            Features
          </Link>
          <Link
            href="/demo"
            className="text-sm font-medium text-gray-600 transition-colors duration-150 hover:text-gray-900"
          >
            Demo
          </Link>
          <Link
            href="#contact"
            className="text-sm font-medium text-gray-600 transition-colors duration-150 hover:text-gray-900"
          >
            Contact
          </Link>
        </div>

        <Link href="/demo">
          <Button size="sm">Try Demo</Button>
        </Link>
      </div>
    </nav>
  )
}
