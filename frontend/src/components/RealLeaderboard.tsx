import { useEffect, useState } from "react";
import { apiGet } from "../services/api";

type Entry = { report_id: string; run_id: string; remote_model: string; created_at: string; value: number; rank: number };
type Group = {
  comparison: { dataset_key: string; manifest_id: string; manifest_sha256: string; tool_revision: string; parameters: Record<string, string | number> };
  metric_name: string;
  unit: string;
  direction: string;
  entries: Entry[];
};

export function RealLeaderboard({ open }: { open: (id: string) => void }) {
  const [dataset, setDataset] = useState("GPQA");
  const [groups, setGroups] = useState<Group[]>([]);
  const [message, setMessage] = useState("");
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setMessage(""); setGroups([]);
    apiGet<Group[]>(`/leaderboard?dataset_key=${encodeURIComponent(dataset)}&metric_name=accuracy`, controller.signal)
      .then(setGroups)
      .catch(() => { if (!controller.signal.aborted) setMessage("真实榜单加载失败；未使用示例数据替代。"); });
    return () => controller.abort();
  }, [dataset, revision]);
  return <section className="diagnostic-tasks" data-testid="real-leaderboard">
    <h2>真实内部榜单</h2>
    <p>仅纳入真实且完整的报告，按数据集、清单、工具提交和执行参数分组。保留同模型的全部完整报告，不隐式选择最新或最佳成绩；探索报告不作为正式发布结论。</p>
    <label>真实榜单数据集 <select aria-label="真实榜单数据集" value={dataset} onChange={(event) => setDataset(event.target.value)}>
      <option>GPQA</option><option>MMMU-Pro</option><option>AutomationBench</option>
    </select></label>
    <button onClick={() => setRevision((value) => value + 1)}>刷新真实榜单</button>
    <p role="status">{message}</p>
    {!groups.length && !message && <p>当前数据集暂无可比完整报告。性能指标尚无真实采集结果，不生成性能排名。</p>}
    {groups.map((group) => <section key={`${group.comparison.manifest_id}:${group.comparison.tool_revision}`}>
      <h3>{group.comparison.dataset_key} · accuracy</h3>
      <p>清单 {group.comparison.manifest_id}；工具 {group.comparison.tool_revision.slice(0, 12)}；参数 {JSON.stringify(group.comparison.parameters)}</p>
      <div style={{ overflowX: "auto" }}><table><thead><tr><th>排名</th><th>模型</th><th>成绩</th><th>测评时间</th><th>来源</th></tr></thead>
        <tbody>{group.entries.map((entry) => <tr key={entry.report_id} data-testid="leaderboard-entry">
          <td>{entry.rank}</td><td>{entry.remote_model}</td><td>{entry.value}{group.unit}</td><td>{entry.created_at}</td>
          <td><button onClick={() => open(entry.report_id)}>来源报告 {entry.report_id.slice(0, 8)}</button></td>
        </tr>)}</tbody></table></div>
    </section>)}
  </section>;
}
