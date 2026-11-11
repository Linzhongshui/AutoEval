export const REGISTRY_PAGE_SIZE = 20;

export function OffsetPagination({ label, offset, nextOffset, onChange, disabled = false }: {
  label: string;
  offset: number;
  nextOffset: number | null;
  onChange: (offset: number) => void;
  disabled?: boolean;
}) {
  if (offset === 0 && nextOffset === null) return null;
  return <div className="inline" aria-label={`${label}分页`}>
    <button disabled={disabled || offset === 0}
      onClick={() => onChange(Math.max(0, offset - REGISTRY_PAGE_SIZE))}>上一页</button>
    <span>第 {Math.floor(offset / REGISTRY_PAGE_SIZE) + 1} 页</span>
    <button disabled={disabled || nextOffset === null}
      onClick={() => nextOffset !== null && onChange(nextOffset)}>下一页</button>
  </div>;
}
