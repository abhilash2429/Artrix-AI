import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"

const badgeVariants = cva(
  "inline-flex items-center rounded-pill border px-2.5 py-0.5 text-xs font-medium transition-colors duration-150",
  {
    variants: {
      variant: {
        default: "border-transparent bg-primary text-primary-foreground",
        secondary: "border-transparent bg-secondary text-secondary-foreground",
        outline: "text-foreground",
        blue: "border-transparent bg-blue-100 text-blue-700",
        violet: "border-transparent bg-violet-100 text-violet-700",
        orange: "border-transparent bg-orange-100 text-orange-700",
        green: "border-transparent bg-green-100 text-green-700",
        amber: "border-transparent bg-amber-100 text-amber-700",
        red: "border-transparent bg-red-100 text-red-700",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />
}

export { Badge, badgeVariants }
