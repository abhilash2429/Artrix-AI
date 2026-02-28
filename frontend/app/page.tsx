import Link from "next/link"
import { Navbar } from "@/components/marketing/Navbar"
import { Hero } from "@/components/marketing/Hero"
import { Features } from "@/components/marketing/Features"
import { Footer } from "@/components/marketing/Footer"
import { VERTICALS } from "@/lib/config/verticals"

const verticalList = Object.values(VERTICALS)

export default function HomePage() {
  return (
    <div className="min-h-screen">
      <Navbar />
      <Hero />
      <Features />

      {/* Demo CTA Strip */}
      <section className="bg-[#F9FAFB] px-6 py-20 md:px-12">
        <div className="mx-auto max-w-5xl">
          <h2 className="mb-8 text-center text-xl font-semibold text-gray-900">
            See it live — pick your industry
          </h2>
          <div className="grid gap-4 md:grid-cols-3">
            {verticalList.map((v) => (
              <Link key={v.slug} href={`/demo/${v.slug}`}>
                <div className="flex items-center gap-4 rounded-card border bg-white p-5 shadow-card transition-shadow duration-150 hover:shadow-elevated">
                  <div
                    className="h-full w-1 shrink-0 self-stretch rounded-pill"
                    style={{ backgroundColor: v.accentColor }}
                  />
                  <div>
                    <p className="text-sm font-semibold text-gray-900">{v.label}</p>
                    <p className="text-xs text-gray-500">{v.personaName} · {v.companyName}</p>
                  </div>
                </div>
              </Link>
            ))}
          </div>
        </div>
      </section>

      <Footer />
    </div>
  )
}
