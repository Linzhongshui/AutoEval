# AutoEval Demo

React + TypeScript + Vite 前端静态原型。依据项目 PRD 和六张当前原型图实现五个菜单及报告详情，统一紫色主题。

## 运行

需要 Node.js 22+ 和 npm。

```sh
npm ci
npm run dev
```

- `npm run typecheck`：TypeScript 检查。
- `npm run build`：类型检查及生产构建。
- `npm run preview`：预览构建产物。

## 页面与交互

- `#console`：模型接入表单、API / IP-Port 切换、配置摘要、数据集勾选、全量 / Lite 切换。
- `#config`：模型选择、各数据集独立参数编辑、配置结构与重置。
- `#tasks`：任务列表筛选、详情选择、进度 / 日志 / 轨迹 / 配置快照。
- `#reports`：报告列表筛选与搜索，进入对应报告详情。
- `#detail`：指标概览、结果标签、基准对比图表、分析状态与证据示例。
- `#leaderboard`：精度 / 性能榜单、吞吐 / 延迟指标切换及报告入口。

所有数据、配置、图表、进度、日志、分析结论与证据均为静态示例，不代表实测结果。前端不调用模型，不执行测评，不创建真实任务，不保存配置或密钥，不触发报告分析。保存、连接测试和发起测评均明确提示静态预览边界。未确定的 Lite 样本量等信息显示待配置。

## 结构

- `src/app/App.tsx`：页面、示例数据及本地交互。
- `src/app/app.css`：主题、布局、组件样式与响应式规则。
- `src/main.tsx`：React 挂载入口。
- `src/components`、`hooks`、`utils`、`types`：后续模块拆分预留。

## 验证

类型检查及生产构建已通过。视觉和浏览器交互验证受当前浏览器环境缺失文件阻塞，见 `design-qa.md`；不以构建成功替代视觉验收。
