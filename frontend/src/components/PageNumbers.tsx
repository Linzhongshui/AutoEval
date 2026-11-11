export function visiblePages(current: number, total: number): (number | string)[] {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);
  const start = current <= 4 ? 2 : current >= total - 3 ? total - 4 : current - 1;
  const end = current <= 4 ? 5 : current >= total - 3 ? total - 1 : current + 1;
  const pages: (number | string)[] = [1];
  if (start > 2) pages.push('leading');
  for (let page = start; page <= end; page++) pages.push(page);
  if (end < total - 1) pages.push('trailing');
  return [...pages, total];
}
export function PageNumbers({ current, total, onChange }: { current: number; total: number; onChange: (page: number) => void }) {
  return <div className="page-number-group">{visiblePages(current, total).map(page => typeof page === 'number' ? <button key={page} className={current === page ? 'primary' : ''} aria-label={`第 ${page} 页`} aria-current={current === page ? 'page' : undefined} onClick={() => onChange(page)}>{page}</button> : <span key={page} className="pagination-ellipsis" aria-hidden="true">…</span>)}</div>;
}
