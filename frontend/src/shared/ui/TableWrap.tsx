import type { ComponentPropsWithoutRef } from "react";

export function TableWrap(props: ComponentPropsWithoutRef<"div">) {
  return <div {...props} className="table-wrap" />;
}
