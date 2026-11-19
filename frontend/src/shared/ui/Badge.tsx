import type { ReactNode } from "react";

export function Badge({ children, tone = "purple" }: { children: ReactNode; tone?: string }) {
  return <span className={`badge ${tone}`}>{children}</span>;
}
