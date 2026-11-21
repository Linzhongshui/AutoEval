import { useEffect, useId, useRef, useState } from "react";
import { ChevronDown, X } from "lucide-react";
import "./ResourceMultiSelect.css";

type Option = { id: string; binding_key: string };

export function ResourceMultiSelect({ options, value, onChange }: {
  options: Option[];
  value: string[];
  onChange: (ids: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const id = useId();
  useEffect(() => {
    if (!open) return;
    const outside = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, [open]);
  const matches = options.filter(option => option.binding_key.toLowerCase().includes(query.trim().toLowerCase()));
  const selected = value.map(key => options.find(option => option.id === key)?.binding_key || key);
  return <div className="resource-multi-select" ref={root} onKeyDown={event => {
    if (event.key === "Escape") { setOpen(false); trigger.current?.focus(); }
  }}>
    <span id={`${id}-label`}>候选 SSH 主机</span>
    <button ref={trigger} type="button" className="resource-multi-trigger" aria-label="规划执行资源" aria-expanded={open} aria-controls={`${id}-options`} onClick={() => { setQuery(""); setOpen(current => !current); }}>
      <span title={selected.join("、")}>{selected.length ? "选择节点" : "请选择 SSH 主机"}</span>
      {selected.length > 0 && <small>已选 {selected.length} 项</small>}
      <ChevronDown size={18} aria-hidden="true" />
    </button>
    {!!selected.length && <div className="inline resource-selected">{value.map((key, index) => <button type="button" className="badge" key={key} aria-label={`移除 ${selected[index]}`} onClick={() => onChange(value.filter(id => id !== key))}>{selected[index]} <X size={14} aria-hidden="true" /></button>)}</div>}
    {open && <div id={`${id}-options`} className="resource-multi-menu" role="group" aria-labelledby={`${id}-label`}>
      <div className="resource-multi-toolbar"><span>可选择多个 SSH 节点</span><button type="button" disabled={!value.length} onClick={() => onChange([])}>清空</button></div>
      {!matches.length && <p className="muted">没有匹配的 SSH 节点。</p>}
      {options.length > 6 && <input aria-label="搜索 SSH 节点" placeholder="搜索节点名称" value={query} onChange={event => setQuery(event.target.value)} />}
      <div className="resource-multi-options">{matches.map(option => <label key={option.id}>
        <input type="checkbox" checked={value.includes(option.id)} disabled={value.length >= 16 && !value.includes(option.id)} onChange={event => onChange(event.target.checked ? [...value, option.id] : value.filter(key => key !== option.id))} />
        <span>{option.binding_key}</span>
      </label>)}</div>
      <button type="button" className="resource-multi-done" onClick={() => { setOpen(false); trigger.current?.focus(); }}>完成选择{value.length ? `（${value.length}）` : ""}</button>
    </div>}
  </div>;
}
