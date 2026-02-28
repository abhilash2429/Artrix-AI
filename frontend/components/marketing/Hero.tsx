"use client"

import Link from "next/link"
import { Button } from "@/components/ui/button"

export function Hero() {
  return (
    <section className="flex flex-col items-center px-6 pb-24 pt-20 text-center md:px-12 md:pt-32">
      <h1 className="max-w-2xl text-4xl font-semibold leading-tight tracking-tight text-gray-900 md:text-5xl">
        AI Agents for Indian Enterprise Support
      </h1>
      <p className="mt-6 max-w-lg text-lg text-gray-500">
        Automate 60–75% of customer support with intelligent chat agents built for Indian
        enterprises.
      </p>
      <div className="mt-10 flex gap-4">
        <Link href="/demo">
          <Button size="lg">Try Live Demo</Button>
        </Link>
        <Link href="#features">
          <Button variant="outline" size="lg">
            View Docs
          </Button>
        </Link>
      </div>
    </section>
  )
}
