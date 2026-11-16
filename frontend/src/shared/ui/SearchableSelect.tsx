import { Children, isValidElement, useRef, useState, type ReactNode, type SelectHTMLAttributes } from "react";
function text(node: ReactNode): string {
  return Children.toArray(node).map((child) => isValidElement<{ children?: ReactNode }>(child) ? text(child.props.children) : String(child)).join("");
}
export function SearchableSelect({ children, value, defaultValue, onChange, disabled, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  const [query, setQuery] = useState("");
  const [count, setCount] = useState(20);
  const [local, setLocal] = useState(String(defaultValue || ""));
  const root = useRef<HTMLDetailsElement>(null);
  const options = Children.toArray(children).filter(isValidElement<{value?: string; children?: ReactNode}>);
  const selected = String(value ?? local);
  const filtered = options.filter((option) => String(option.props.value ?? text(option.props.children)) !== "" && text(option.props.children).toLowerCase().includes(query.toLowerCase()));
  const label = options.find((option) => String(option.props.value ?? text(option.props.children)) === selected);
  return <details className="searchable-select" ref={root} onToggle={() => { if (!root.current?.open) { setQuery(""); setCount(20); } }}>
    <summary aria-disabled={disabled} onClick={(event) => { if (disabled) event.preventDefault(); }}>{label ? text(label.props.children) : "请选择"}<span aria-hidden="true">⌄</span></summary>
    {!disabled && <div className="searchable-select-panel"><input aria-label={`${props["aria-label"] || "选项"}搜索`} placeholder="输入名称或标识搜索" value={query} onChange={(event) => { setQuery(event.target.value); setCount(20); }} onKeyDown={(event) => { if (event.key === "Escape") { event.stopPropagation(); if (root.current) root.current.open = false; } }} /><select {...props} value={selected} size={Math.min(8, Math.max(2, filtered.length))} onChange={(event) => { setLocal(event.target.value); onChange?.(event); if (root.current) root.current.open = false; }}><option value="" hidden>请选择</option>{filtered.slice(0, count)}</select>{!filtered.length && <p role="status">没有匹配选项</p>}{filtered.length > count && <button type="button" onClick={() => setCount((v) => v + 20)}>加载更多（已显示 {count} / {filtered.length}）</button>}</div>}
  </details>;
}
