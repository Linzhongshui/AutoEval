import { DATASET_TYPES } from "./datasets";

export function DatasetTree({
  items,
  selected,
  disabled = [],
  active,
  onSelect,
  onActive,
  scope,
}: {
  items: string[];
  selected?: string[];
  disabled?: string[];
  active?: string;
  onSelect?: (items: string[]) => void;
  onActive?: (name: string) => void;
  scope?: string;
}) {
  return (
    <div className="dataset-tree" aria-label="按类型分组的数据集">
      {DATASET_TYPES.map((group) => {
        const children = group.items.filter((d) => items.includes(d));
        if (!children.length) return null;
        return (
          <details open key={group.label} className="dataset-tree-group">
            <summary>{group.label}<span>{children.length}</span></summary>
            <div className="dataset-tree-children">
              {children.map((d) => (
                <div key={d} className={`dataset-tree-row ${active === d ? "is-active" : ""}`}>
                  {onSelect && (
                    <input
                      aria-label={`选择 ${d}`}
                      type="checkbox"
                      disabled={disabled.includes(d)}
                      checked={selected?.includes(d) || disabled.includes(d)}
                      onChange={(e) => onSelect(
                        e.target.checked
                          ? [...(selected || []).filter((x) => x !== d), d]
                          : (selected || []).filter((x) => x !== d),
                      )}
                    />
                  )}
                  {onActive ? (
                    <button className="dataset-tree-name" title={d} onClick={() => onActive(d)}>{d}</button>
                  ) : (
                    <label
                      className="dataset-tree-name"
                      onClick={() => {
                        if (onSelect && !disabled.includes(d)) onSelect(
                          selected?.includes(d) ? selected.filter((x) => x !== d) : [...(selected || []), d],
                        );
                      }}
                    >{d}</label>
                  )}
                  {scope && <span className="dataset-tree-meta">{scope}</span>}
                  {disabled.includes(d) && <span className="dataset-tree-meta">已添加</span>}
                </div>
              ))}
            </div>
          </details>
        );
      })}
      {!items.length && <div className="empty">未找到匹配的数据集</div>}
    </div>
  );
}

