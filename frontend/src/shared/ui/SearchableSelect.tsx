import { ChevronDown } from "lucide-react";
import { Children, isValidElement, useEffect, useRef, useState, type KeyboardEvent, type ReactNode, type SelectHTMLAttributes } from "react";
function text(node: ReactNode): string {
  return Children.toArray(node).map((child) => isValidElement<{ children?: ReactNode }>(child) ? text(child.props.children) : String(child)).join("");
}
export function SearchableSelect({ children, value, defaultValue, onChange, disabled, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  const [query, setQuery] = useState("");
  const [count, setCount] = useState(20);
  const [local, setLocal] = useState(String(defaultValue || ""));
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDetailsElement>(null);
  const trigger = useRef<HTMLElement>(null);
  const search = useRef<HTMLInputElement>(null);
  const select = useRef<HTMLSelectElement>(null);
  const navigating = useRef(false);
  const options = Children.toArray(children).filter(isValidElement<{ value?: string; children?: ReactNode }>);
  const selected = String(value ?? local);
  const filtered = options.filter((option) => String(option.props.value ?? text(option.props.children)) !== "" && text(option.props.children).toLowerCase().includes(query.trim().toLowerCase()));
  const label = options.find((option) => String(option.props.value ?? text(option.props.children)) === selected);
  useEffect(() => { if (open) search.current?.focus(); }, [open]);
  useEffect(() => {
    const element = select.current;
    if (!element) return;
    const scroll = (event: WheelEvent) => {
      if (element.scrollHeight <= element.clientHeight) return;
      event.preventDefault();
      element.scrollTop += event.deltaY;
    };
    element.addEventListener("wheel", scroll, { passive: false });
    return () => element.removeEventListener("wheel", scroll);
  }, [disabled]);
  const close = () => {
    if (root.current) root.current.open = false;
    trigger.current?.focus();
  };
  const onSelectKeyDown = (event: KeyboardEvent<HTMLSelectElement>) => {
    if (event.key === "ArrowUp" || event.key === "ArrowDown") navigating.current = true;
    if (event.key === "Enter" || event.key === "Escape") { event.preventDefault(); event.stopPropagation(); close(); }
  };
  return <details className="searchable-select" ref={root} onToggle={(event) => {
    const next = event.currentTarget.open;
    setOpen(next);
    if (!next) { setQuery(""); setCount(20); navigating.current = false; }
  }}>
    <summary className="select-trigger" ref={trigger} aria-disabled={disabled} tabIndex={disabled ? -1 : 0}
      onClick={event => { if (disabled) event.preventDefault(); }}>
      <span className="select-value">{label ? text(label.props.children) : "请选择"}</span>
      <ChevronDown className="select-chevron" size={18} aria-hidden="true" />
    </summary>
    {!disabled && <div className="searchable-select-panel"><input ref={search} aria-label={`${props["aria-label"] || "选项"}搜索`} placeholder="输入名称或标识搜索" value={query} onChange={(event) => { setQuery(event.target.value); setCount(20); }} onKeyDown={(event) => { if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); close(); } }} />
      <select {...props} ref={select} value={selected} size={Math.min(8, Math.max(2, filtered.length))} onKeyDown={onSelectKeyDown} onChange={(event) => {
        setLocal(event.target.value); onChange?.(event);
        if (navigating.current) navigating.current = false; else close();
      }}><option value="" hidden>请选择</option>{filtered.slice(0, count)}</select>
      {!filtered.length && <p role="status">没有匹配选项</p>}
      {filtered.length > count && <button type="button" onClick={() => setCount((v) => v + 20)}>加载更多（已显示 {count} / {filtered.length}）</button>}
    </div>}
  </details>;
}
