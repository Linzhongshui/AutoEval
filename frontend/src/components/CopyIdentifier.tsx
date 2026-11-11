import { useState } from "react";

export function CopyIdentifier({ value, label = "复制完整标识" }: { value: string; label?: string }) {
  const [message, setMessage] = useState("");
  return <span className="inline"><button className="link" onClick={async () => {
    try { await navigator.clipboard.writeText(value); setMessage("已复制"); }
    catch { setMessage("复制失败，可在详情中手动选择标识"); }
  }}>{label}</button><small role="status">{message}</small></span>;
}
