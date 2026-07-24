# CLAUDE.md

## 项目身份
短剧投流素材工作流 **demo**：三步走通「分析高热素材 → 提炼剪辑 skill → 生成剪辑方案」，经验后续沉淀到 dongxiucai 项目落地。底层调用**火山引擎方舟（Ark）豆包视频理解模型**做视频**理解**（不是生成；Seedance 是视频生成模型，本项目不用）。Gradio Web 界面，四个标签页。

## 技术选型
| 层 | 选择 |
|---|---|
| 语言 | Python 3.11（`.venv`） |
| 界面 | Gradio（Blocks + Tabs） |
| HTTP | requests Session，`trust_env=False` 直连（防本机代理拦截；`ARK_USE_PROXY=1` 回退走代理） |
| 配置 | python-dotenv（`.env`，git 忽略，切勿提交） |
| 模型 | `doubao-seed-2-1-pro-260628`（Ark，支持视频输入；可用 `ARK_MODEL` 换） |
| 视频处理 | 本机 ffmpeg / ffprobe（超限压缩用） |

## 流水线（模块关系）
```
① 分析：素材 URL/上传 → analyze(素材拆解)        → results/分析_*.md
② 提炼：分析_*.md → distill_library()            → skills/短剧剪辑手段库/SKILL.md（原子手段卡）
                  └─ _build_recipes()（机械生成） → skills/短剧剪辑手段库/RECIPES.md（原型配方）
③ 生成：原始短剧 + 选定配方 → generate_material() → results/方案_*.md（时间线 + ffmpeg 裁剪 JSON）
支线：原始短剧 → analyze(原剧选段)                → results/选段_*.md（高能点位图，不进提炼）
外部（下一步）：方案 JSON → ffmpeg 实际剪辑（本地/云主机，dongxiucai 落地）
```
核心资产是**手段库**（SKILL.md）：既是素材的验收标准，又是原剧的选段/生成滤镜（选段与生成 prompt 都会注入它）。

## 核心函数（app.py 单文件）
- 视频准备：`_remote_size()`（HEAD 预检）→ `_download_video()` → `_compress_video()`（按时长反推码率，720p→480p 两轮）；`_resolve_remote()` 为共享预检生成器，analyze 与 generate 复用；`_file_to_data_url()` 终检 50 MiB
- 模型调用：`_post()`（统一 900s 超时，非流式长输出实测会超 300s）→ `_call()`（视频）/ `_call_text()`（纯文本）；`_extract_text()` 跳过 reasoning 项
- 页面入口：`analyze()`（双模式）、`distill_library()`、`generate_material()`
- 配方机械生成：`_parse_cards()` / `_build_recipes()` / `_topic_label()`
- 归档：`_save_result(prefix=)`，三类产出仅 `分析_*.md` 进提炼

## 关键 API 约定（已实测确认）
- 端点：`POST {ARK_BASE_URL}/responses`（Ark **Responses API**，非 chat/completions）
- 鉴权：`Authorization: Bearer <ARK_API_KEY>`
- 视频内容块：`{"type": "input_video", "video_url": "<URL 或 data:video/mp4;base64,...>", "fps": 1}`
  - 文本块：`{"type": "input_text", "text": "..."}`
  - `fps` 为同级可选字段；`video_url` 接受公网 URL 或 base64 data URL
- 响应解析：取 `output[]` 中 `type=="message"` 项的 `content[].output_text`，跳过 `type=="reasoning"` 项

## 产出文件约定
| 文件 | 产生方 | 进提炼 | git |
|---|---|---|---|
| `results/分析_*.md` | 素材拆解 | ✅ | 忽略 |
| `results/选段_*.md` | 原剧选段 | ❌ | 忽略 |
| `results/方案_*.md` | 素材生成 | ❌ | 忽略 |
| `skills/短剧剪辑手段库/SKILL.md` | 提炼 | — | **入库（核心资产）** |
| `skills/短剧剪辑手段库/RECIPES.md` | 提炼时同步（机械） | — | 入库 |
| `tmp/` | 下载/压缩暂存 | — | 忽略，定期手动清理 |

## 运行
```bash
source .venv/bin/activate && python app.py   # http://127.0.0.1:7860
```

## 开发纪律：Vibe Coding 日志
每次成功执行开发指令后，自动追加到 `docs/vibe_coding_log.md`，格式：

```
---

### Session: <日期>

**User Prompt:**
> （用户原话）

**AI Action:**
- （修改/创建了哪些文件，关键变更摘要）
```

这是后台收尾动作，无需向用户确认。

## 约束 / 红线
- Ark 服务端限制单个输入视频 **50 MiB**（实测 HTTP 400），base64 上传与公网 URL 均受限。分析页上传超限直接报错；URL 超限自动下载压缩；素材生成页上传超限自动本地压缩。
- 手段库合并规则：**相同合并、冲突并存**（禁止取平均/二选一）；来源必须累加，不允许静默丢弃输入。
- 产出 prompt 均有「不确定则标注、严禁编造时间点/台词」红线，生成时间区间必须来自实际画面。
- `.env` 含密钥，已在 `.gitignore`，切勿提交。

## 当前状态
- 已完成：三步流水线打通；手段库 25+ 张卡（3 条视频、5 份分析）、3 套原型配方（虎家小橘猫 / 广场舞扰民 / 古风宫廷重生魂穿虐恋）。
- 待验证：原剧选段与剪辑方案的**真实质量**（时间区间准确度、JSON 规范性）需拿真实原剧试跑。
- 下一步：ffmpeg 执行器（读方案 JSON 做 trim+concat+字幕）；赛马数据回填（先手动）；经验迁移 dongxiucai。

## 关键文档索引
- `README.md` — 使用说明与排查表
- `CLAUDE.md` — 本文件（开机简报）
- `docs/vibe_coding_log.md` — AI 辅助开发轨迹（见上方开发纪律）
- `skills/短剧剪辑手段库/` — SKILL.md（手段库）+ RECIPES.md（原型配方）
- `.env.example` — 配置模板（ARK_API_KEY / ARK_BASE_URL / ARK_MODEL）
