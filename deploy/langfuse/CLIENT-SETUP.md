# Windows 首次访问：只需一个脚本

把 `setup-client.ps1` 单独发给首次访问用户即可，不需要 Python、项目代码或额外证书文件。脚本只包含入口的公开证书，不含私钥、服务器密码或平台登录凭据。

## 用户操作

1. 连接公司 VPN。
2. 使用自己的 Windows 账号，以管理员身份打开 PowerShell，进入脚本所在文件夹。
3. 执行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup-client.ps1
```

该执行策略仅作用于本次进程，不修改系统执行策略；组织组策略仍然有效。不要使用另一位管理员的账号运行，否则用户代理及证书会配置到另一位用户。

4. 完全退出 Chrome 并重新启动，打开：
   - Demo：https://179.214.2.3/
   - Langfuse：https://langfuse.autoeval.local/

登录账号由管理员单独提供。Demo 检查返回 HTTP 401 表示服务器可达且正在等待登录，不是安装失败。

## 脚本做什么

- 保留 VPN、默认代理服务器和 PAC 地址，仅向静态代理绕过列表添加两个地址。
- 对本地文件型 PAC 添加两个精确主机的 DIRECT 规则；远程受管理的 PAC 不会被替换，会提示联系 VPN 管理员。
- 添加 `179.214.2.3 langfuse.autoeval.local` hosts 记录；发现冲突会停止，不覆盖已有映射。
- 校验内置证书 SHA256 和有效期，将证书安装到当前用户的受信任根证书存储，不全局跳过 TLS 验证。当前入口证书到期时间为 2027-11-16，续期或更换证书后需要维护者重新发布脚本。
- 修改前备份代理字段、hosts 和本地 PAC 到 `%LOCALAPPDATA%\AutoEvalirst-visit-时间戳`，重复执行不会重复添加规则或证书。操作中断时已完成的设置保留，可重新执行。
- 自动检查两个 HTTPS 入口。VPN 未连接、公司策略阻止修改或远程 PAC 忽略绕过规则时，会报告具体失败阶段，不关闭 VPN 或防火墙。

可先预览，预览不要求管理员权限、不写配置：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup-client.ps1 -WhatIf
```

若 UniVPN 重连后重新生成 PAC，可再次运行脚本。回退时按备份恢复本次修改的代理字段、hosts 和 PAC；仅在确认不再使用入口时移除当前用户 Root 中指纹 `7A8EC21CEE300D7EC6AAC6B7DFBDBE319B1D7DEF` 的证书。恢复整份 hosts/PAC 前核对其后是否发生其他修改。

## 本次验证边界

已检查 PowerShell 语法，并运行 -WhatIf 确认未写入配置。证书和代理规则来自此前本机已验证的配置；脚本尚未在全新 Windows 用户下执行管理员安装。HTTPS 入口已在部署验收中验证。
