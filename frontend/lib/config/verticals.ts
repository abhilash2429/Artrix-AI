export const VERTICALS = {
  ecommerce: {
    slug: "ecommerce",
    label: "E-commerce",
    personaName: "Aria",
    companyName: "StyleCart",
    allowedTopics: ["orders", "returns", "refunds", "delivery", "products"],
    suggestedQueries: [
      "Track my order",
      "What is your return policy?",
      "How do I get a refund?",
      "Can I cancel my order?",
    ],
    accentColor: "#6366F1",
    description: "D2C e-commerce customer support",
  },
  healthcare: {
    slug: "healthcare",
    label: "Healthcare",
    personaName: "Medi",
    companyName: "CareFirst Clinics",
    allowedTopics: ["appointments", "clinic timings", "billing", "reports", "doctors"],
    suggestedQueries: [
      "How do I book an appointment?",
      "What are your clinic timings?",
      "How do I access my reports?",
      "Which doctors are available?",
    ],
    accentColor: "#10B981",
    description: "Healthcare clinic support automation",
  },
  bfsi: {
    slug: "bfsi",
    label: "BFSI",
    personaName: "Finn",
    companyName: "SwiftCapital",
    allowedTopics: ["loans", "eligibility", "documents", "interest rates", "application status"],
    suggestedQueries: [
      "Am I eligible for a loan?",
      "What are your interest rates?",
      "What documents do I need?",
      "Check my application status",
    ],
    accentColor: "#F59E0B",
    description: "Banking and lending support automation",
  },
} as const

export type VerticalSlug = keyof typeof VERTICALS
export type VerticalConfig = (typeof VERTICALS)[VerticalSlug]
