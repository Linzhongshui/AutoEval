import { useEffect, useRef, useState } from "react";
import { ArrowUp, FileCode2, RefreshCw, X } from "lucide-react";
import { apiGet } from "../../shared/api";

type Attempt = { id: string; dataset: string; round: number };
type FileEntry = { name: string; directory: boolean; metadata_only: boolean; size: number; mtime: number };
type Result =
  | { state: "directory"; entries: FileEntry[]; more: boolean }
  | { state: "text"; content: string; start: number; end: number; size: number }
  | { state: "binary" | "pending" | "removed" | "missing_file" | "unverified" | "unavailable" | "wrong_storage" | "protected"; size?: number | null };

const messages: Record<string, string> = {
  pending: "尚未生成文件", removed: "原始文件已人工清理", missing_file: "文件已移动或删除，请刷新目录",
  unverified: "历史任务没有可核验的现场", unavailable: "执行器暂时不可连接",
  wrong_storage: "当前挂载与任务记录不一致", binary: "二进制文件，仅展示元信息",
  protected: "无法安全预览此文件",
};

function useFileResult(base: string, query: string, revision: number) {
  const [result, setResult] = useState<Result>();
  useEffect(() => {
    const controller = new AbortController();
    setResult(undefined);
    apiGet<Result>(base + "?" + query, controller.signal)
      .then(data => { if (!controller.signal.aborted) setResult(data); })
      .catch(() => { if (!controller.signal.aborted) setResult({ state: "unavailable" }); });
    return () => controller.abort();
  }, [base, query, revision]);
  return result;
}

function PreviewContent({ base, path, revision }: { base: string; path: string; revision: number }) {
  const result = useFileResult(base, new URLSearchParams({ path }).toString(), revision);
  const preview = useRef<HTMLPreElement>(null);
  useEffect(() => {
    if (preview.current && path.toLowerCase().endsWith(".log")) {
      preview.current.scrollTop = preview.current.scrollHeight;
    }
  }, [path, result]);
  if (!result) return <p role="status">正在读取文件…</p>;
  if (result.state !== "text") return <p role="status">{messages[result.state] || "无法读取文件"}</p>;
  return <>
    <pre ref={preview} tabIndex={0} aria-label="文件内容" className="snapshot executor-file-preview">{result.content}</pre>
    <p className="executor-preview-range">字节范围 [{result.start}, {result.end})，共 {result.size} B{(result.start !== 0 || result.end !== result.size) && " · 已截断"}</p>
  </>;
}

function Browser({ base }: { base: string }) {
  const [outputs, setOutputs] = useState(true);
  const [directory, setDirectory] = useState("");
  const [offset, setOffset] = useState(0);
  const [revision, refresh] = useState(0);
  const [previewRevision, refreshPreview] = useState(0);
  const [selected, select] = useState<FileEntry>();
  const dialog = useRef<HTMLDialogElement>(null);
  const workspace = useRef<HTMLDivElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const previewOpen = Boolean(selected);
  const selectedPath = selected && [directory, selected.name].filter(Boolean).join("/");
  const query = new URLSearchParams({ path: directory, offset: String(offset), view: outputs ? "outputs" : "directory" });
  const result = useFileResult(base, query.toString(), revision);
  const metadata = result?.state === "directory" ? result.entries.find(entry => entry.name === selected?.name) : undefined;

  useEffect(() => {
    const panel = dialog.current;
    const container = workspace.current;
    if (!panel || !container || !previewOpen) return;
    function placePanel() {
      if (!panel || !container) return;
      const useDrawer = container.clientWidth < 700;
      if (panel.open && panel.matches(":modal") === useDrawer) return;
      if (panel.open) panel.close();
      if (useDrawer) panel.showModal();
      else panel.show();
    }
    placePanel();
    const resize = new ResizeObserver(placePanel);
    resize.observe(container);
    return () => resize.disconnect();
  }, [previewOpen]);

  function closePreview() {
    dialog.current?.close();
    select(undefined);
    trigger.current?.focus({ preventScroll: true });
  }

  function navigate(next: string, page = 0) {
    select(undefined);
    setDirectory(next);
    setOffset(page);
    if (list.current) list.current.scrollTop = 0;
  }

  return <>
    <div className="executor-file-controls">
      <div role="group" aria-label="文件列表视图" className="executor-file-modes">
        <button aria-pressed={outputs} onClick={() => { if (!outputs) { setOutputs(true); navigate(""); } }}>全部原始输出文件</button>
        <button aria-pressed={!outputs} onClick={() => { if (outputs) { setOutputs(false); navigate(""); } }}>作业目录</button>
      </div>
      <button className="executor-icon-button" aria-label="刷新文件" title="刷新文件" onClick={() => refresh(v => v + 1)}><RefreshCw size={16} /></button>
    </div>
    <div ref={workspace} className={`executor-file-workspace${previewOpen ? " with-preview" : ""}`}>
      <div className="executor-list-pane">
        {!outputs && <div className="executor-directory-path">
          {directory && <button className="executor-icon-button" aria-label="上一级" title="上一级" onClick={() => navigate(directory.split("/").slice(0, -1).join("/"))}><ArrowUp size={16} /></button>}
          <code>{directory || "/"}</code>
        </div>}
        <div className="executor-file-list" ref={list}>
          {!result ? <p role="status">正在读取执行器…</p> : result.state !== "directory" ? <p role="status">{messages[result.state] || "无法读取目录"}</p>
            : !result.entries.length ? <p>尚未生成文件</p> : <table>
              <thead><tr><th>{outputs ? "文件路径（相对作业目录）" : "名称"}</th><th>大小</th><th>修改时间</th></tr></thead>
              <tbody>{result.entries.map(entry => <tr key={entry.name} className={selected?.name === entry.name ? "selected-file" : undefined}>
                <td>{entry.metadata_only ? <span>{entry.name} · 仅元信息</span>
                  : <button className="link" aria-pressed={entry.directory ? undefined : selected?.name === entry.name}
                    onClick={event => {
                      if (entry.directory) navigate([directory, entry.name].filter(Boolean).join("/"));
                      else { trigger.current = event.currentTarget; select(entry); }
                    }}>
                    {entry.name}{entry.directory && "/"}
                  </button>}</td>
                <td>{entry.directory ? "—" : entry.size + " B"}</td><td>{new Date(entry.mtime * 1000).toLocaleString()}</td>
              </tr>)}</tbody>
            </table>}
        </div>
        {result?.state === "directory" && (offset > 0 || result.more) && <div className="executor-pagination">
          <button disabled={offset === 0} onClick={() => navigate(directory, offset - 100)}>上一页</button>
          <span>第 {offset / 100 + 1} 页</span>
          <button disabled={!result.more} onClick={() => navigate(directory, offset + 100)}>下一页</button>
        </div>}
      </div>
      {selected && selectedPath ? <dialog ref={dialog} aria-label="文件预览" className="executor-preview-pane"
        onCancel={event => { event.preventDefault(); closePreview(); }} onKeyDown={event => {
          if (event.key === "Escape") { event.preventDefault(); closePreview(); }
        }}>
        <header className="executor-preview-header">
          <FileCode2 size={18} aria-hidden="true" />
          <div className="executor-preview-title">
            <h4 title={selectedPath}>{selectedPath}</h4>
            {metadata && <small>{metadata.size} B · 修改于 {new Date(metadata.mtime * 1000).toLocaleString()}</small>}
          </div>
          <button className="executor-icon-button" title="刷新预览" aria-label="刷新预览" onClick={() => refreshPreview(v => v + 1)}><RefreshCw size={16} /></button>
          <button className="executor-icon-button" title="关闭预览" aria-label="关闭预览" onClick={closePreview}><X size={18} /></button>
        </header>
        <PreviewContent key={selectedPath} base={base} path={selectedPath} revision={revision + previewRevision} />
      </dialog> : null}
    </div>
  </>;
}

export function ExecutorFiles({ runId, currentRound }: { runId: string; currentRound?: number }) {
  const [attempts, setAttempts] = useState<Attempt[]>();
  const [selected, select] = useState("");
  const [error, setError] = useState(false);
  const [revision, refresh] = useState(0);
  const base = `/evaluation-tasks/${encodeURIComponent(runId)}/executor-files`;
  useEffect(() => {
    const controller = new AbortController();
    setError(false);
    apiGet<Attempt[]>(base, controller.signal).then(rows => {
      if (controller.signal.aborted) return;
      setAttempts(rows);
      const latest = currentRound ?? Math.max(...rows.map(r => r.round));
      select(id => rows.some(r => r.id === id) ? id : rows.find(r => r.round === latest)?.id || "");
    }).catch(() => { if (!controller.signal.aborted) setError(true); });
    return () => controller.abort();
  }, [base, currentRound, revision]);

  return <section className="stack executor-files" aria-label="执行器原始文件">
    <div className="executor-files-toolbar">
      {attempts && attempts.length > 0 && (
        <label>执行作业 <select value={selected} onChange={e => select(e.target.value)}>
          {currentRound && !attempts.some(r => r.round === currentRound) && <option value="">第 {currentRound} 轮 · 暂无执行作业</option>}
          {attempts.map(r => <option key={r.id} value={r.id}>第 {r.round} 轮 · {r.dataset} · {r.id.slice(0, 8)}</option>)}</select></label>
      )}
      <button className="executor-icon-button" aria-label="刷新作业列表" title="刷新作业列表" onClick={() => refresh(v => v + 1)}><RefreshCw size={16} /></button>
    </div>
    {error ? <p role="alert">无法读取执行轮次</p> : !attempts ? <p role="status">正在读取执行作业…</p>
      : !attempts.length ? <p>暂无可查看的执行作业</p>
      : selected && <Browser key={selected} base={base + "/" + selected} />}
  </section>;
}
