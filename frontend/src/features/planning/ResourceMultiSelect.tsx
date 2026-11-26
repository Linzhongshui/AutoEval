import { useEffect, useId, useRef, useState } from "react";
import { ChevronDown, X } from "lucide-react";
import type { SshHost } from "./sshHosts";
import "./ResourceMultiSelect.css";

export function ResourceMultiSelect({ hosts, value, showChips, onChange }: {
  hosts: SshHost[];
  showChips: boolean;
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
  const term = query.trim().toLowerCase();
  const matches = hosts.map(host => ({ ...host, resources: host.resources.filter(option =>
    host.label.toLowerCase().includes(term) || option.binding_key.toLowerCase().includes(term)) })).filter(host => host.resources.length);
  const selected = hosts.filter(host => host.resources.some(resource => value.includes(resource.id)));
  return <div className="resource-multi-select" ref={root} onKeyDown={event => {
    if (event.key === "Escape") { setOpen(false); trigger.current?.focus(); }
  }}>
    <span id={`${id}-label`}>候选 SSH 主机</span>
    <button ref={trigger} type="button" className="resource-multi-trigger select-trigger" aria-label="规划执行资源" aria-expanded={open} aria-controls={`${id}-options`} onClick={() => { setQuery(""); setOpen(current => !current); }}>
      <span>{selected.length ? "调整资源配置" : "请选择 SSH 主机"}</span>
      {selected.length > 0 && <small>已选 {selected.length} 台主机</small>}
      <ChevronDown className="select-chevron" size={18} aria-hidden="true" />
    </button>
    {showChips && !!selected.length && <div className="inline resource-selected">{selected.map(host => <button type="button" className="badge" key={host.key} aria-label={`移除主机 ${host.label}`} onClick={() => onChange(value.filter(id => !host.resources.some(resource => resource.id === id)))}>{host.label} <X size={14} aria-hidden="true" /></button>)}</div>}
    {open && <div id={`${id}-options`} className="resource-multi-menu" role="group" aria-labelledby={`${id}-label`}>
      <div className="resource-multi-toolbar"><span>按主机选择资源配置</span><button type="button" disabled={!value.length} onClick={() => onChange([])}>清空</button></div>
      {!matches.length && <p className="muted">没有匹配的 SSH 节点。</p>}
      {hosts.reduce((n, host) => n + host.resources.length, 0) > 6 && <input aria-label="搜索主机或资源配置" placeholder="搜索主机或资源配置" value={query} onChange={event => setQuery(event.target.value)} />}
      <div className="resource-multi-options">{matches.map(host => <div key={host.key}><strong>{host.label}</strong>{host.resources.map(option => <label key={option.id}>
        <input type="checkbox" checked={value.includes(option.id)} disabled={value.length >= 16 && !value.includes(option.id)} onChange={event => onChange(event.target.checked ? [...value, option.id] : value.filter(key => key !== option.id))} />
        <span>{option.binding_key}</span>
      </label>)}</div>)}</div>
      <button type="button" className="resource-multi-done" onClick={() => { setOpen(false); trigger.current?.focus(); }}>完成选择</button>
    </div>}
  </div>;
}
