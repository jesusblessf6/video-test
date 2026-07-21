# Vibe Coding Log

> 本文件自动记录每次 AI 辅助开发的轨迹，作为项目演进的完整档案。

---

### Session: 2026-06-26

**User Prompt:**
> 我想创建一个小的应用，主要目的是调用 seedance 模型，分析视频

**AI Action:**
- 澄清需求：目标是「理解/分析已有视频」（非生成），平台用火山引擎方舟 Ark，形态选 Web。
- 指出 Seedance 是视频生成模型；视频理解应改用豆包视觉（doubao-seed）系列。
- 初版用 `chat/completions` 实现，搭好 `app.py`(Gradio) / `requirements.txt` / `.env.example` / `README.md`，通过导入与启动冒烟测试。

**User Prompt:**
> 模型用 doubao seed 2.1，并贴出 `/responses` 接口的图片示例

**AI Action:**
- 实测确认接口与格式：端点改为 Ark **Responses API** `POST /responses`，模型 `doubao-seed-2-1-pro-260628`。
- 探明视频内容块格式：`{"type":"input_video","video_url":"...","fps":1}`（`video_url` 接受 URL 或 base64 data URL）。
- 重写 `app.py` 改用 `requests` 直连 `/responses`，新增 `_extract_text()` 解析 `output[].content[].output_text`（跳过 reasoning）。
- 用样例视频端到端跑通，模型正确分析出内容。依赖由 openai 换为 requests。

**User Prompt:**
> 整个项目该做的初始化都做一下吧

**AI Action:**
- 新增 `.gitignore`（排除 `.env`/`.venv`/缓存等）、`CLAUDE.md`（项目快照）。
- `git init` 并完成首次提交（确认 `.env` 未入库）。

**User Prompt:**
> ark key 就用这个，没关系。另外补上 readme 和 vibe log

**AI Action:**
- 扩写 `README.md`：功能、项目结构、配置项表、接口 curl 示例、排查表。
- 创建本 `docs/vibe_coding_log.md`，并在 `CLAUDE.md` 写入日志记录纪律。
- 写入真实 `.env`（含可用的 ARK_API_KEY，git 忽略）使项目开箱即跑。

**User Prompt:**
> 你帮我把这个 web 服务起起来吧 / 点开始分析没有反应

**AI Action:**
- 后台启动 Gradio 服务（http://127.0.0.1:7860），确认存活。
- 定位「无反馈」实为缺少加载态：把 `analyze` 改为生成器，点击后按钮变「分析中…」并禁用、结果区显示进度提示、出错时页面内红字显示；新增「清空」按钮；启用 `demo.queue()`。

**User Prompt:**
> 分析的结果要怎么保存呢

**AI Action:**
- 新增结果归档：`_save_result()` 每次成功后写 Markdown 到 `results/`（含时间/来源/模型/fps/指令+正文）。
- 界面加「⬇️ 下载结果 (.md)」下载按钮；`results/` 加入 `.gitignore`。

---

### Session: 2026-06-29

**User Prompt:**
> 当前这个系统跑起来 / 一直报 RemoteDisconnected / 上传体积限制 / 改到 200m

**AI Action:**
- 搭运行环境：创建 `.venv`、装依赖、写 `.env`（已 gitignore），后台启动 Gradio。
- 修复出站请求被本机系统代理（Clash 127.0.0.1:7897）拦截导致的 `RemoteDisconnected`/`SSLError`：`app.py` 改用 `trust_env=False` 的 `requests.Session` 直连，新增 `ARK_USE_PROXY=1` 开关回退走代理。
- 按需求把 `MAX_UPLOAD_BYTES` 由 40MB 调到 200MB；并说明内联 base64 受服务端请求体上限约束，大视频仍建议走「视频 URL」。


---

### Session: 2026-07-20

**User Prompt:**
> 我从界面提供的提示词是视频分析的大方向，你看能不能在提示词中增加一些对输入输出的规范化要求

**AI Action:**
- 扩写 `app.py` 的 `DEFAULT_PROMPT`：新增【输入说明】（抽帧+音轨输入，看不清处标「不确定」禁止编造）、【输出要求】（固定 5 节：素材概览/分镜拆解表格/剪辑手法清单/可复用 SOP/投产 Checklist，每条含量化标准+示例）、【质量红线】（必须量化、禁止虚话）。

**User Prompt:**
> 调用失败（HTTP 400）：the size of the input video (148 MiB) exceeds the limit (50 MiB)

**AI Action:**
- 实测确认 Ark 服务端对输入视频硬性上限 50 MiB，base64 上传与公网 URL 均受限（README 此前「过大改 URL」建议无效）。
- `MAX_UPLOAD_BYTES` 由 200MB 下调为 50 MiB 对齐 Ark 上限，上传超限时报错信息改为提示先 ffmpeg 压缩。
- 同步修正 `README.md`（用法+排查表）与 `CLAUDE.md` 中过时的 40MB/200MB 说法。

**User Prompt:**
> 能不能直接在上传链接的时候，判断视频大小，如果超过限制就下载到本地压缩。整体做到这个demo页面中

**AI Action:**
- `app.py` 新增 URL 视频超限自动处理链：`_remote_size()`（HEAD 探测 Content-Length）→ 超 50 MiB 时 `_download_video()` 流式下载到 `tmp/`（2GB 安全上限）→ `_compress_video()` 用 ffmpeg 按时长反推码率压到限额内（720p→480p 两轮保底，拿不到时长退 crf 模式）→ 转 base64 提交；`analyze()` 生成器中途 yield「下载并压缩中」「压缩完成」状态。
- HEAD 探测不到大小时保持原直连行为；本地上传超限仍是直接报错提示。
- 离线实测通过：69.2MB/600s 测试视频经本地 http.server 走全流程，压到 20.7MB 且时长完整。
- `tmp/` 加入 `.gitignore`；README（功能/用法/排查表）与 CLAUDE.md 同步更新。
