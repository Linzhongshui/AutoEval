import { useEffect, useState } from "react";
import { apiGet } from "../services/api";

type Entry = {
  report_id: string;
  run_id: string;
  remote_model: string;
  created_at: string;
  value: number;
  rank: number;
};

type Group = {
  comparison: {
    dataset_key: string;
    manifest_id: string;
    manifest_sha256: string;
    tool_revision: string;
    parameters: Record<string, string | number>;
  };
  metric_name: string;
  unit: string;
  direction: string;
  entries: Entry[];
};

export function RealLeaderboard({ open }: { open: (id: string) => void }) {
  const [dataset, setDataset] = useState("GPQA");
  const [groups, setGroups] = useState<Group[]>([]);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setMessage("");
    setGroups([]);
    setLoading(true);
    apiGet<Group[]>(`/leaderboard?dataset_key=${encodeURIComponent(dataset)}&metric_name=accuracy`, controller.signal)
      .then(setGroups)
      .catch(() => {
        if (!controller.signal.aborted) setMessage("真实榜单加载失败；未使用示例数据替代。");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [dataset, revision]);

  return (
    <div className="stack" data-testid="real-leaderboard">
      <section className="card">
        <div className="filters">
          <label className="select-field">
            <span>数据集</span>
            <select aria-label="真实榜单数据集" value={dataset} onChange={(event) => setDataset(event.target.value)}>
              <option>GPQA</option>
            </select>
          </label>
          <label className="select-field">
            <span>指标</span>
            <select aria-label="真实榜单指标" defaultValue="accuracy" disabled>
              <option>accuracy</option>
            </select>
          </label>
          <button onClick={() => setRevision((value) => value + 1)}>刷新真实榜单</button>
        </div>
      </section>

      <div className="notice">
        仅纳入真实且 validity=complete、accuracy 非空的报告，按数据集、清单、工具提交和执行参数分组；同模型的全部完整报告均保留。性能指标与未支持数据集不生成排名。
      </div>
      <p role="status">{message || (loading ? "真实榜单加载中…" : "")}</p>
      {!loading && !groups.length && !message && (
        <section className="card"><div className="empty">当前数据集暂无可比完整报告。</div></section>
      )}

      {groups.map((group) => (
        <section
          className="stack"
          data-testid="leaderboard-group"
          key={`${group.comparison.manifest_sha256}:${group.comparison.tool_revision}:${JSON.stringify(group.comparison.parameters)}`}
        >
          <div className="spread">
            <h3>{group.comparison.dataset_key} · {group.metric_name}</h3>
            <span className="badge">同条件报告 {group.entries.length}</span>
          </div>
          <section className="card table-card">
            <div className="table-wrap">
              <table className="leader-table">
                <thead>
                  <tr><th>排名</th><th>模型 / run_id</th><th>{group.metric_name}</th><th>created_at</th><th>报告</th></tr>
                </thead>
                <tbody>
                  {group.entries.map((entry) => (
                    <tr key={entry.report_id} data-testid="leaderboard-entry">
                      <td><span className={`rank rank-${entry.rank - 1}`}>{String(entry.rank).padStart(2, "0")}</span></td>
                      <td><b>{entry.remote_model}</b><small>run_id：{entry.run_id}</small></td>
                      <td>
                        <div className="inline score">
                          <b>{entry.value}{group.unit}</b>
                          <progress max="100" value={entry.value} />
                        </div>
                      </td>
                      <td>{entry.created_at}</td>
                      <td>
                        <button className="outline" onClick={() => open(entry.report_id)}>
                          来源报告 {entry.report_id.slice(0, 8)}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <div className="task-columns">
            <section className="card">
              <h2>对比条件</h2>
              <p>数据集：{group.comparison.dataset_key}；样本范围：{String(group.comparison.parameters.scope ?? "—")}</p>
              <pre className="snapshot">{JSON.stringify({
                manifest_id: group.comparison.manifest_id,
                manifest_sha256: group.comparison.manifest_sha256,
                tool_revision: group.comparison.tool_revision,
                parameters: group.comparison.parameters,
              }, null, 2)}</pre>
            </section>
            <section className="card">
              <h2>指标说明</h2>
              <p>{group.metric_name}：按后端返回值展示，单位 {group.unit}，方向 {group.direction}。</p>
              <p>排名仅在当前对比条件分组内计算；并列成绩保留后端返回的相同 rank，不跨数据集或清单生成综合分。</p>
            </section>
          </div>
        </section>
      ))}
    </div>
  );
}
