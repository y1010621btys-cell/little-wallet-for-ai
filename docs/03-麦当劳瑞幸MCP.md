# 教程 3 · 让 AI 帮你点麦当劳和瑞幸

麦当劳和瑞幸都有**官方 MCP**，但它们用 Bearer Token 认证，而 claude.ai 的自定义连接器只支持 OAuth——所以需要一个"中间人"帮你把 token 悄悄塞进请求头。有 VPS 的话，nginx 就是最好的中间人，连代理代码都不用写。

## 第一步：拿 token

- 麦当劳：`open.mcd.cn` 登录、激活、拿 token（新账号可用）
- 瑞幸：`open.lkcoffee.com/mcp` 同上（注意：瑞幸对新注册账号可能暂未开放 MCP 权限，账号需要养一段时间）

⚠️ **token = 你的账号点单权，别发在帖子里，别给任何人。**

## 第二步：nginx 中转

用 `deploy/nginx-food-mcp.conf.example`，把里面的 `<随机后缀>` 和 `<你的token>` 换成自己的，加进 nginx 后 reload。

随机后缀这样生成（这条路径等于你的账号钥匙，要够随机）：
```bash
head -c4 /dev/urandom | od -An -tx1 | tr -d ' \n'
```

## 第三步：加连接器

claude.ai → 设置 → 连接器 → 添加自定义连接器：
- `https://你的域名/mcd-mcp-你的后缀/`
- `https://你的域名/luckin-mcp-你的后缀/`

不用填 OAuth。加好后 AI 就有了：麦当劳查店/点餐/自动领券/查订单/积分，瑞幸搜品/切规格/预览/下单/查单/取消。

## 我们踩过的坑

**坑① 麦当劳的端点不是文档站**
`open.mcd.cn/mcp` 是文档页面，POST 上去只有 405。真实端点是 **`https://mcp.mcd.cn/`（根路径）**，无状态 JSON，配合 Bearer 头直接可用。

**坑② 瑞幸官网 JS 里的网关是假的**
页面代码里出现的 `mcpgateway.lkcoffee.com` 解析出来是内网地址（10.x.x.x），全世界都连不上。真实生产网关是 **`gwmcp.lkcoffee.com/order/user/mcp`**（藏在他们前端代码的域名拼接函数里）。

**坑③ 结尾斜杠**
同教程 2 的坑②，带斜杠和不带斜杠的 location 都要配。

## 安全与心安

- 下单**不会自动扣款**：瑞幸 createOrder 返回微信支付链接（`needPay:true`），你不付款订单十几分钟自动过期。最后一道闸门永远在人类手上
- 配合钱包的玩法：AI 下单 → 把付款链接放进小条子（通知条）→ 你付完点"知道了"→ 钱包自动记账。全流程见教程 1
