import { useEffect, useState } from "react";
import { TaskPlanning } from "./TaskPlanning";
import { PerformanceTaskForm } from "./PerformanceTaskForm";

type Props = { page: string; go: (page: string) => void; poolRevision: number; onManagePool: (add?: boolean) => void };

const tabs = [
  { path: "console", label: "精度测评", id: "accuracy" },
  { path: "console/performance", label: "性能测评", id: "performance" },
];

export function EvaluationConsoleTabs({ page, go, ...props }: Props) {
  const [visited, setVisited] = useState(() => new Set([page]));
  useEffect(() => {
    setVisited(previous => previous.has(page) ? previous : new Set([...previous, page]));
  }, [page]);
  return <>
    <div className="tabs configuration-tabs" role="tablist" aria-label="测评类型">
      {tabs.map((tab, index) => <button key={tab.id} id={`tab-${tab.id}`} role="tab"
        aria-selected={page === tab.path} aria-controls={`panel-${tab.id}`}
        tabIndex={page === tab.path ? 0 : -1} className={page === tab.path ? "active" : ""}
        onClick={() => go(tab.path)} onKeyDown={event => {
          if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
          event.preventDefault();
          const next = tabs[event.key === "Home" ? 0 : event.key === "End" ? 1 : 1 - index];
          document.getElementById(`tab-${next.id}`)?.focus();
          go(next.path);
        }}>{tab.label}</button>)}
    </div>
    {tabs.map(tab => <div key={tab.id} id={`panel-${tab.id}`} role="tabpanel"
      aria-labelledby={`tab-${tab.id}`} hidden={page !== tab.path}>
      {(visited.has(tab.path) || page === tab.path) && (tab.id === "accuracy"
        ? <TaskPlanning {...props} /> : <PerformanceTaskForm {...props} />)}
    </div>)}
  </>;
}
