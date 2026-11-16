import { useEffect, useState } from "react";

type Progress = { stage: string; current_concurrency?: number | null; completed_levels: number; total_levels: number; observed_at?: string };
export function ProbeProgress({ job }: { job: { id: string; state: string; created_at?: string; updated_at?: string; result?: { progress?: Progress | null; reason?: string; dispatch_blocked?: boolean; remote_check?: { state: string; checked_at: string } } } }) {
  const [now, setNow] = useState(Date.now);
  const active = ["pending", "running"].includes(job.state);
  useEffect(() => { if (!active) return; const timer = setInterval(() => { if (!document.hidden) setNow(Date.now()); }, 1000); return () => clearInterval(timer); }, [active, job.id]);
  const progress = job.result?.progress;
  const total = progress?.total_levels;
  const done = progress?.completed_levels;
  const known = typeof total === "number" && total > 0 && typeof done === "number" && done >= 0 && done <= total;
  const percent = known ? Math.round(done / total * 100) : undefined;
  const start = Date.parse(job.created_at || "");
  const end = active ? now : Date.parse(job.updated_at || "");
  const seconds = Number.isFinite(start) && Number.isFinite(end) ? Math.max(0, Math.floor((end - start) / 1000)) : null;
  const elapsed = seconds == null ? "暂无记录" : seconds >= 86400 ? `${Math.floor(seconds / 86400)}天 ${Math.floor(seconds % 86400 / 3600)}小时 ${Math.floor(seconds % 3600 / 60)}分` : seconds >= 3600 ? `${Math.floor(seconds / 3600)}小时 ${Math.floor(seconds % 3600 / 60)}分` : `${Math.floor(seconds / 60)}分${String(seconds % 60).padStart(2, "0")}秒`;
  const timeLabel = job.state === "pending" ? "已等待" : job.state === "unresolved" ? "执行耗时" : active ? "当前耗时" : "任务历时";
  const stale = active && job.state === "running" && (!job.updated_at || now - Date.parse(job.updated_at) > 10000);
  const labels: Record<string, string> = { pending: "等待调度", running: "容器执行中", completed: "探测完成", failed: "探测失败", cancelled: "已取消", unresolved: "执行状态待查证" };
  const stage: Record<string, string> = { preparing: "容器准备", probing: "吞吐探测", level_completed: "档位已完成", archiving: "结果归档" };
  return <section className={`probe-progress-card ${job.state}`} aria-label="吞吐探测进度">
    <div className="probe-progress-heading"><strong>{job.result?.dispatch_blocked ? "探测执行器未启用" : labels[job.state] || job.state}{active && progress ? ` · ${stage[progress.stage] || progress.stage}` : ""}</strong><span>{timeLabel}：{job.state === "unresolved" ? "未确认" : elapsed}</span></div>
    <small className="probe-progress-id">探测任务：{job.id}</small>
    {job.state === "pending" && <small>尚未执行，以上为排队等待时间，不是模型执行耗时。创建于 {job.created_at ? new Date(job.created_at).toLocaleString("zh-CN") : "未知"}</small>}
    <div>{progress?.current_concurrency ? `当前并发档位：${progress.current_concurrency} · ` : ""}{known ? `已完成 ${done}/${total} 档` : active ? "等待档位进度，不估算百分比" : "未记录档位进度"}</div>
    <div className={`run-progress-track ${known ? "" : "unknown"}`} role="progressbar" aria-label="吞吐探测档位进度" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent}><i style={{ width: `${percent || 0}%` }} /></div>
    <small>{stale ? "采集数据已过期，保留最后进度" : job.state === "pending" ? "等待协调进程接收，尚未开始模型请求" : `最近采集：${job.updated_at ? new Date(job.updated_at).toLocaleString("zh-CN") : "暂无记录"}`}</small>
    {job.result?.remote_check && <small>最近远程查证：{new Date(job.result.remote_check.checked_at).toLocaleString("zh-CN")} · {job.result.remote_check.state === "unknown" ? "当前固定环境未找到原作业" : job.result.remote_check.state}</small>}
    {job.result?.reason && <p role="status">{job.result.reason}</p>}
  </section>;
}
