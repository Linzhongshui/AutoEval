import type { Param } from "../../shared/types/domain";
import { AdapterFields } from "./AdapterFields";
import { baseParams } from "../evaluation/logic";

export function ParameterCards({
  active,
  items,
  params,
  onChange,
  readonly = false,
}: {
  items: string[];
  params: Record<string, Param>;
  onChange: (p: Record<string, Param>) => void;
  readonly?: boolean;
  active: string;
}) {
  return (
    <div className="stack">
      {items.filter((d) => d === active).map((d) => {
        const value = params[d] || baseParams();
        return (
          <section className="card" key={d}>
            <h3>{d}{readonly ? " · 只读" : ""}</h3>
            <AdapterFields value={value} readonly={readonly} onChange={(next) => onChange({ ...params, [d]: next as Param })} />
          </section>
        );
      })}
      {!items.length && <div className="empty">请从左侧选择数据集</div>}
    </div>
  );
}

