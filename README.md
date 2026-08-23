# VIX 微信提醒器

每天在 VIX 正式收盘后读取 Cboe 官方历史数据。当日收盘价满足以下条件时，通过 Server酱 Turbo 推送到微信：

- 连续两个交易日收盘价不高于某档位；
- 最新收盘价严格向上穿过 `20`、`25`、`30` 或 `40`；
- 若同一天跳过多个档位，只发一条合并消息；
- `state.json` 保存最后检查日期，重复运行不会重复提醒。

程序只使用 Python 标准库，无需安装第三方依赖。

## 部署到 GitHub Actions

### 1. 创建仓库

在 GitHub 新建一个仓库，把本目录内的所有文件上传到仓库根目录。务必包含隐藏目录 `.github`。

### 2. 获取微信 SendKey

1. 打开 [Server酱 Turbo](https://sct.ftqq.com)，使用微信扫码登录。
2. 按网站提示绑定微信推送通道。
3. 在 `SendKey` 页面复制以 `SCT` 开头的密钥。

免费账户目前每天可推送 5 条；本程序会把同一天的多个档位合并为一条消息。

### 3. 保存密钥

进入 GitHub 仓库：

`Settings → Secrets and variables → Actions → New repository secret`

创建：

- Name：`SERVERCHAN_SENDKEY`
- Secret：粘贴以 `SCT` 开头的 SendKey

不要把 SendKey 写进代码、README 或 `state.json`。

### 4. 允许工作流保存检查状态

进入：

`Settings → Actions → General → Workflow permissions`

选择 `Read and write permissions` 并保存。工作流只会提交 `state.json` 中的最后检查日期，不会修改程序。

如果仓库默认分支启用了禁止机器人直接推送的分支保护，需要允许 GitHub Actions 推送，或者不要在这个仓库启用该保护规则。

### 5. 发送测试消息

1. 打开仓库的 `Actions` 页面。
2. 选择 `VIX WeChat Monitor`。
3. 点击 `Run workflow`。
4. 将 `send_test` 设为 `true` 后运行。

微信收到“VIX监控测试成功”即部署完成。

第一次正常检查只会把 `state.json` 初始化到最新交易日，不发送历史信号，避免刚部署就收到过期提醒。

## 运行时间

工作流在每个周一至周五运行两次：

- UTC 22:47（北京时间次日 06:47）
- UTC 23:47（北京时间次日 07:47）

两次运行是为了应对 Cboe 数据文件或 GitHub 定时任务偶尔延迟。状态文件会阻止重复推送。美国或中国节假日没有新数据时，不会通知。

GitHub 官方说明：定时任务可能因平台负载延迟，因此监控适合每日收盘信号，不适合需要秒级响应的盘中交易。

## 本地运行

PowerShell：

```powershell
$env:SERVERCHAN_SENDKEY = "你的SCT密钥"
python monitor.py --test-notification
python monitor.py
```

只检查但不发消息、不更新状态：

```powershell
python monitor.py --dry-run
```

运行测试：

```powershell
python -m unittest discover -s tests -v
```

## 修改阈值

编辑 `monitor.py` 顶部：

```python
THRESHOLDS = (20.0, 25.0, 30.0, 40.0)
```

## 数据和安全

- VIX数据：[Cboe官方历史CSV](https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv)
- 微信推送：[Server酱Turbo](https://sct.ftqq.com)
- SendKey通过GitHub Actions Secrets注入，代码不会输出密钥。
- 提醒仅供信息参考，不构成投资建议。
