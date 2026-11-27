# 批量整理历史 PR 标题

1. **确定清单。** 根据用户给的仓库和筛选条件收集编号、标题和状态。仅含 `is:pr` 的查询覆盖开放、已关闭及已合并的 PR。在 PowerShell 中可用以下命令分页盘点当前仓库：

   ```powershell
   $repo = 'llauren48/AutoEval-Platform'
   gh api --paginate "repos/$repo/pulls?state=all&per_page=100" --jq '.[] | [.number, .state, .merged_at, .title] | @tsv'
   ```

2. **逐条拟名。** 依据 [开发 Skill](../SKILL.md) 的标题规则，结合正文、相对 base 的改动和提交，列出需要更改的「编号、原标题、新标题」。正文缺失时用 `gh pr view <编号> --repo $repo --json files,commits` 查证。例如，改动涉及两个 OAuth 提供方和登录页面时，可将「登录功能开发」改为 `feat(identity): 接入双平台 OAuth 登录`。保留已准确表达改动且格式合规的标题。

3. **复核后写入。** 写入每条前用 `gh pr view $number --repo $repo --json title --jq .title` 回读。与拟定新标题相同则记为已满足；与盘点时的原标题相同时，执行 `gh pr edit $number --repo $repo --title $newTitle`。标题已被协作者改成第三个值时，重新审视该条。读取失败时跳过本条写入；写入响应不确定时先回读，再决定是否重试。

4. **核对结果。** 再次分页获取清单，按原编号比对实际与预期标题，汇报实改、保留和未完成数量。遇到并发更新或权限错误，列出受影响编号与原因；若期间新增 PR，单独标明。
