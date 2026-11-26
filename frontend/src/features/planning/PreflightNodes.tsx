import { TableWrap } from "../../shared/ui/TableWrap";
import type { SshHost } from "./sshHosts";

const stages = {
  started: "Worker 已接手预检", resumed: "Worker 已恢复预检",
  preparing: "准备临时容器", checking: "校验工具与数据",
  cleaning: "回收临时容器", passed: "预检通过", reused: "复用已通过记录", blocked: "存在阻塞", failed: "预检失败",
};
export type PreflightEvidence = { container_id: string; checked_at: string; source_job_id: string };
type ProgressEvent = { stage: keyof typeof stages; at: string; dataset: string | null } & Partial<PreflightEvidence>;
export type PreflightProgress = { assignments: Record<string, string>; events: ProgressEvent[] };
type NodeJob = {
  id: string; state: string; created_at?: string; updated_at?: string;
  result?: {
    preflight_progress?: PreflightProgress;
    dataset_checks?: { dataset: string; assigned_resource_id?: string; blocking_reasons: string[]; preflight_evidence?: PreflightEvidence }[];
    execution_ready?: boolean;
  };
};

const clockTime = (at: string) => new Date(at).toLocaleTimeString("zh-CN", { hour12: false });

export function PreflightNodes({ hosts, selectedIds, datasets, job }: {
  hosts: SshHost[]; selectedIds: string[]; datasets: string[]; job: NodeJob;
}) {
  const progress = job.result?.preflight_progress;
  const events = progress?.events ?? [];
  const running = ["pending", "running"].includes(job.state);
  const awaitingAssignment = running && !progress && !job.result?.dataset_checks?.length;
  const latest = new Map<string, ProgressEvent>();
  const containers = new Map<string, string>();
  for (const event of events) {
    if (event.dataset) {
      latest.set(event.dataset, event);
      if (event.container_id) containers.set(event.dataset, event.container_id);
    } else if (event.stage === "resumed") {
      latest.clear();
      containers.clear();
    }
  }
  const nodes = datasets.map(dataset => {
    const check = job.result?.dataset_checks?.find(item => item.dataset === dataset);
    const resourceId = check?.assigned_resource_id ?? progress?.assignments[dataset];
    const event = latest.get(dataset);
    const stage = check && event?.stage !== "reused" ? (check.blocking_reasons.length ? "blocked" : "passed") : event?.stage;
    const status = stage ? stages[stage] : job.state === "pending" ? "排队中"
      : !running ? "无检查结果" : progress ? "等待检查" : "等待进度上报";
    const container = check?.preflight_evidence?.container_id ?? containers.get(dataset);
    return { dataset, resourceId, stage, status, at: event?.at, container };
  });
  const knownIds = new Set(hosts.flatMap(host => host.resources.map(resource => resource.id)));
  const unassigned = nodes.filter(node => !node.resourceId || !knownIds.has(node.resourceId));
  const groups = hosts.map(host => ({
    key: host.key, label: host.label,
    selected: host.resources.some(resource => selectedIds.includes(resource.id)),
    nodes: nodes.filter(node => host.resources.some(resource => resource.id === node.resourceId)),
  })).filter(group => !awaitingAssignment && (!running || group.selected || group.nodes.length));
  if (unassigned.length) groups.push({ key: "unassigned", label: "待确认主机", selected: false, nodes: unassigned });
  return <section aria-label="数据集执行节点">
    <h3>数据集执行节点</h3>
    <TableWrap><table><thead><tr>{!awaitingAssignment && <th>SSH 主机</th>}<th>执行节点（数据集）</th><th>预检进度</th><th>预检容器 ID</th><th>更新时间</th></tr></thead>
      {groups.map(group => <tbody key={group.key}>
        {group.nodes.length ? group.nodes.map((node, index) => <tr key={node.dataset}>
          {!awaitingAssignment && index === 0 && <th scope="rowgroup" rowSpan={group.nodes.length}>{group.label}</th>}
          <td>{node.dataset}</td>
          <td><span className={node.stage === "passed" || node.stage === "reused" ? "preflight-status passed" : node.stage === "blocked" || node.stage === "failed" ? "preflight-status blocked" : "muted"}>{node.status}</span></td>
          <td>{node.container ? <code title={node.container}>{node.container.slice(0, 12)}</code> : "—"}</td>
          <td>{node.at ? clockTime(node.at) : "—"}</td>
        </tr>) : <tr><th scope="rowgroup">{group.label}</th><td>—</td><td className="muted">{group.selected ? (running ? "等待分配信息" : "已选 · 未分配") : "未选择"}</td><td>—</td><td>—</td></tr>}
      </tbody>)}
    </table></TableWrap>
    {(job.created_at || events.length > 0) && <details className="planning-management preflight-log" open={running}>
      <summary>环境检查记录</summary>
      <ol aria-label="环境检查记录，最新在前">
        {!running && job.updated_at && <li><time>{clockTime(job.updated_at)}</time>预检结束</li>}
        {events.slice().reverse().map((event, index) => <li key={events.length - index}>
          <time dateTime={event.at}>{clockTime(event.at)}</time>{event.dataset && event.dataset + " · "}{stages[event.stage]}
          {event.stage === "reused" && event.checked_at && `（原检查 ${clockTime(event.checked_at)}）`}
        </li>)}
        {job.created_at && <li><time>{clockTime(job.created_at)}</time>预检已入队</li>}
      </ol>
    </details>}
  </section>;
}
