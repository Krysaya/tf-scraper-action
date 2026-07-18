# 🤖 tf-scraper-action

每日自动抓取 App Store 限免 + TestFlight 链接，推送到公众号草稿箱和 Telegram 频道。

---

## 变更日志

### 2026-07-19 — 全面代码审计与修复

**P0 — 时区 bug 修复（关键）**

`datetime.now()` 取的是 GitHub Actions 服务器 UTC 时间，北京时间早 8 小时，
导致 UTC 零点附近触发生成/查找错误日期的文件。

| 文件 | 修复 |
|------|------|
| `daily_merger.py` | 文件名改用 `datetime.now(BEIJING)` |
| `tf_scraper.py` | TF 每日文件名改用北京时间 |
| `tg_push.py` | 所有文件查找与时间戳改用北京时间 |
| `local_wechat_publisher.py` | 文件查找改用北京时间 |
| `local_tf_publisher.py` | 日志时间戳改用北京时间 |

**P1 — 稳定性修复**

| 问题 | 修复 |
|------|------|
| `wechat_publish_ci.py` git 版缺 iTunes API 简介 | 同步本地增强版（自动获取 App 真实简介） |
| `local_wechat_publisher.py` PROJECT_DIR 指向不存在的旧目录 | 修正为 `/公众号自动/` |
| `local_tf_publisher.py` 同上 | 同上 |
| `tf_scraper.py` 死代码 `SENT_FILE` | 已移除 |

**基础设施**

| 变更 | 说明 |
|------|------|
| 新增 `trigger_workflow.py` | 本地 GitHub Actions 触发器，绕过 schedule 不稳定问题 |
| 新增每日 8:00 自动化 | WorkBuddy 定时任务，通过 API 精准触发 workflow_dispatch |
| 修正 shell 脚本 PROJECT_DIR | `一键发布文章.sh`、`手动拉取发布.sh`、`公众号守护进程.sh` |

### 2026-07-14

- TF scraper: 修复二源（departures.to + Brave Search）抓取失效
- 优化 departures.to HTML 解析适配新版页面结构

---

## 工作流

| Workflow | 触发 | 产出 |
|----------|------|------|
| `fetch-daily-free.yml` | 每日 8:00 (本地触发) | `每日限免MMDD.txt` |
| `fetch-daily-tf.yml` | 每日 8:00 (本地触发) | `tf_daily_links_MMDD.json` |
| `push-daily-free-tg.yml` | 每日 8:01 (本地触发) | TG 频道推送 |
| `push-daily-tf-tg.yml` | 每日 8:01 (本地触发) | TG 频道推送 |
| `fetch-weekly-tf.yml` | 每周日 | `TestFlight合集_第N期.txt` |
| `push-weekly-tf-tg.yml` | 每周日 | TG 频道周报 |
