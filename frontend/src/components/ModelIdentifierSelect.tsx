import { useEffect, useState } from "react";
import { apiGetPage } from "../services/api";
import { modelIdentities } from "../services/modelIdentities";

export function ModelIdentifierSelect({ value, onChange, disabled = false }: {
  value: string; onChange: (value: string) => void; disabled?: boolean;
}) {
  const [options, setOptions] = useState<string[]>(Object.keys(modelIdentities));
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      const ids = new Set(Object.keys(modelIdentities));
      for (const path of ["/models", ...(import.meta.env.DEV ? ["/data-workbench/entries"] : [])]) {
        let offset: number | null = 0;
        while (offset !== null) {
          const page: { data: { model_id?: string; entry?: { model_name: string } }[]; next_offset: number | null } = await apiGetPage(`${path}?offset=${offset}&limit=100`, controller.signal);
          for (const row of page.data) { const id = row.model_id || row.entry?.model_name; if (id) ids.add(id); }
          if (page.next_offset !== null && page.next_offset <= offset) throw Error("Invalid pagination");
          offset = page.next_offset;
        }
      }
      setOptions([...ids].sort());
    }
    load().catch(() => { if (!controller.signal.aborted) setError("模型列表加载不完整，请刷新后重试"); });
    return () => controller.abort();
  }, []);
  return <><select aria-label="模型标识" required value={value} disabled={disabled} onChange={(e) => onChange(e.target.value)}>
    <option value="">请选择模型标识</option>
    {value && !options.includes(value) && <option value={value} disabled>{value}（历史记录）</option>}
    {options.map((id) => <option key={id} value={id}>{id}</option>)}
  </select>{error && <small role="status">{error}</small>}</>;
}
