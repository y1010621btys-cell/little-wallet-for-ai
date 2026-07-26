# 教程 2 · 让 claude.ai 连上钱包（和四个大坑）

钱包的 MCP 端点跑在 `https://你的域名/wallet-mcp/`。在 claude.ai（手机App/网页都行）：
设置 → 连接器 → 添加自定义连接器 → 填这个地址 → **不用填 OAuth，直接 Add**。

加好之后，你的 AI 在 claude.ai 任何对话里都能：查余额、记账、递条子、交工资单、往暗格藏惊喜。

## 四个大坑（每个都能卡一下午，我们替你踩过了）

**坑① MCP 返回 421**
python 版 MCP SDK 有 DNS-rebinding 保护，nginx 转发时 `Host` 头必须写死成后端自己的地址（`proxy_set_header Host 127.0.0.1:8007;`），不能用 `$host`。

**坑② 连接器弹"Couldn't register with xx's sign-in service"**
你填的地址结尾少了 `/`，nginx 回了个 301 重定向，claude.ai 连接器不吃重定向，会误判成"这服务器要登录"然后跑去走 OAuth 注册流程摔死。解法：nginx 里带斜杠和不带斜杠的路径都配上（见配置示例），或者删掉连接器用带 `/` 的地址重加。

**坑③ 还是弹 OAuth**
claude.ai 添加连接器时会探测 `/.well-known/oauth-authorization-server` 等地址。如果你站点有兜底路由（比如 SPA 的 try_files 全部回 index.html），这些探测会拿到 200，claude.ai 就认为你的服务器支持 OAuth。解法：`location ^~ /.well-known/oauth- { return 404; }`。

**坑④ 加好了但工具调不动**
检查 nginx 有没有 `proxy_buffering off`——MCP 的流式响应被缓冲了就会卡住。

## 顺带一提

Claude Code / Cowork 也能连同一个地址（`claude mcp add` 或配置文件），一份钱包，所有窗口共享。
