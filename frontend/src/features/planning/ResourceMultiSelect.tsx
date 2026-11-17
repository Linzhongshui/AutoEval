import { useEffect, useId, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import "./ResourceMultiSelect.css";

type Option = { id: string; binding_key: string };

export function ResourceMultiSelect({ options, value, onChange }: {
  options: Option[];
  value: string[];
  onChange: (ids: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
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
  const selected = value.map(key => options.find(option => option.id === key)?.binding_key || key);
  return <div className="resource-multi-select" ref={root} onKeyDown={event => {
    if (event.key === "Escape") { setOpen(false); trigger.current?.focus(); }
  }}>
    <span id={`${id}-label`}>执行资源</span>
    <button ref={trigger} type="button" className="resource-multi-trigger" aria-label="规划执行资源" aria-expanded={open} aria-controls={`${id}-options`} onClick={() => setOpen(current => !current)}>
      <span title={selected.join("、")}>{selected.length ? selected[0] : "请选择执行资源"}</span>
      {selected.length > 1 && <small>已选 {selected.length} 项</small>}
      <ChevronDown size={18} aria-hidden="true" />
    </button>
    {open && <div id={`${id}-options`} className="resource-multi-menu" role="group" aria-labelledby={`${id}-label`}>
      <div className="resource-multi-toolbar"><span>可选择多个资源</span><button type="button" disabled={!value.length} onClick={() => onChange([])}>清空</button></div>
      {!options.length && <p className="muted">暂无可用执行资源</p>}
      <div className="resource-multi-options">{options.map(option => <label key={option.id}>
        <input type="checkbox" checked={value.includes(option.id)} disabled={value.length >= 16 && !value.includes(option.id)} onChange={event => onChange(event.target.checked ? [...value, option.id] : value.filter(key => key !== option.id))} />
        <span>{option.binding_key}</span>
      </label>)}</div>
      <button type="button" className="resource-multi-done" onClick={() => { setOpen(false); trigger.current?.focus(); }}>完成选择{value.length ? `（${value.length}）` : ""}</button>
    </div>}
  </div>;
}
