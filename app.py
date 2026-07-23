"""
视频分析小应用 —— 调用火山引擎方舟（Ark）豆包视频理解模型分析视频。

- 走 Ark 的 Responses API（/responses）。视频通过 content 里的 input_video 传入，
  字段 video_url 接受公网 URL 或 base64 data URL，可选 fps（每秒抽帧数）。
- 运行: python app.py  然后浏览器打开 http://127.0.0.1:7860
"""

import base64
import datetime
import mimetypes
import os
import re
import shutil
import subprocess
from pathlib import Path

import gradio as gr
import requests
from dotenv import load_dotenv

load_dotenv()

# 分析结果自动归档目录
RESULTS_DIR = Path(__file__).parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)

# 超限 URL 视频的下载/压缩暂存目录（已 gitignore，可定期手动清理）
TMP_DIR = Path(__file__).parent / "tmp"
TMP_DIR.mkdir(exist_ok=True)

# 剪辑手段库：从分析文档提炼的原子手段卡片，持续累积（入库，是核心资产）
SKILL_DIR = Path(__file__).parent / "skills" / "短剧剪辑手段库"
SKILL_PATH = SKILL_DIR / "SKILL.md"
# 原型配方：同来源手段卡按环节聚合（每条高热素材 = 一套验证过的整体配合）
RECIPES_PATH = SKILL_DIR / "RECIPES.md"

BASE_URL = os.getenv("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3").rstrip("/")
DEFAULT_MODEL = os.getenv("ARK_MODEL", "doubao-seed-2-1-pro-260628")

# Ark 是国内端点，走本机系统代理（如 Clash 127.0.0.1:7897）会间歇性 RemoteDisconnected。
# trust_env=False 让请求忽略环境变量与 macOS 系统代理，直连。需要代理时设 ARK_USE_PROXY=1。
_session = requests.Session()
_session.trust_env = os.getenv("ARK_USE_PROXY", "").strip() == "1"

DEFAULT_PROMPT = (
    "我当前是一个短剧素材投流的投手，上面这个视频是一个表现很好的投流素材，"
    "我想学习它的剪辑方式，并把结论沉淀为可复用的 agent skill。\n\n"
    "【输入说明】视频按抽帧（fps 可调）加音轨输入。画面或台词看不清、听不准的地方，"
    "直接标注「不确定」，严禁编造。\n\n"
    "【输出要求】用 Markdown 严格按以下结构输出，每节都必须有，某节确实没有内容就写「无」：\n"
    "1. 素材概览：题材、时长、目标人群、核心矛盾/卖点（一段话）。\n"
    "2. 分镜拆解：Markdown 表格，按时间顺序列关键镜头：时间区间 | 画面内容 | 台词/字幕 | 剪辑手法 | 作用。\n"
    "3. 剪辑手法清单：逐条拆解节奏、转场、字幕花字、BGM/音效、钩子设计，"
    "每条 = 具体做法 + 出现时间点 + 为什么有效。\n"
    "4. 可复用 SOP：把手法抽象成硬标准，每条 = 操作标准（尽量量化：秒数、字数、镜头数）"
    "+ 可直接照抄的示例 + 适用题材。\n"
    "5. 投产 Checklist：把 SOP 转成「如果…就…」的规则清单，方便直接写成 agent skill。\n\n"
    "【质量红线】只要能量化的就必须量化；禁止「注意节奏」「画面要有张力」这类无法执行的虚话；"
    "标注「不确定」不影响其余部分照常输出。"
)

# 分析模式：素材拆解（分析别人的高热素材）/ 原剧选段（从自己的原始短剧里找高能段落）
MODE_ANALYZE = "素材拆解"
MODE_SCOUT = "原剧选段"

# 选段模式指令。提交时会在末尾自动拼上当前手段库全文，作为选段的检索标准。
SCOUT_PROMPT = (
    "你是一名短剧投流素材的选段师。上面这个视频是一部原始短剧（未剪辑的正片），"
    "我要从里面挑出能剪进投流素材的高能段落。\n\n"
    "【输入说明】视频按抽帧（fps 可调）加音轨输入。画面或台词看不清、听不准的地方，"
    "直接标注「不确定」，严禁编造时间点和台词。\n\n"
    "【选段标准】末尾附上我的「剪辑手段库」，每张卡片描述了一类高能手段的特征，"
    "请逐条对照，找出原剧中符合这些特征的段落。\n\n"
    "【输出要求】用 Markdown 严格按以下结构输出：\n"
    "1. 剧情梗概：一段话讲清主线和核心矛盾；人物表（Markdown 表格：角色 | 身份 | 视觉标识）。\n"
    "2. 高能点位图：按以下环节分组，每组一张 Markdown 表格：钩子候选 / 共情候选 / 爽点候选 / "
    "虐点候选 / 悬念收尾候选。表的列：时间区间（精确到秒）| 画面内容 | 关键台词 | "
    "命中手段特征（填手段库里的手段名）| 能量评分（1-10）| 理解成本（脱离上下文能否 3 秒看懂）。\n"
    "能量评分标准：冲突烈度、情绪浓度、信息增量综合评定，10 分为全剧最高能。\n"
    "某环节确实没有合格段落就写「无」并一句话说明原因。\n\n"
    "【质量红线】时间区间必须来自实际画面；宁可少选不可编造；"
    "同一段落命中多个环节时归到评分最高的环节。\n\n"
    "【剪辑手段库】\n"
)

# Ark 服务端对输入视频的硬性上限是 50 MiB（实测：148 MiB 视频返回 HTTP 400）。
# 该限制与传入方式无关：base64 上传和公网 URL（Ark 服务端拉取）都受限。
# 超限视频只能先压缩/裁剪（如 ffmpeg）再分析。
MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MiB，与 Ark 上限对齐


def _api_key(override: str) -> str:
    key = (override or "").strip() or os.getenv("ARK_API_KEY", "").strip()
    if not key:
        raise gr.Error("未配置 API Key：请在下方填入，或在 .env 里设置 ARK_API_KEY")
    return key


def _file_to_data_url(path: str) -> str:
    size = os.path.getsize(path)
    if size > MAX_UPLOAD_BYTES:
        raise gr.Error(
            f"视频过大（{size / 1024 / 1024:.1f} MB，Ark 上限 {MAX_UPLOAD_BYTES // 1024 // 1024} MB，"
            "URL 方式同样受限）。请先压缩/裁剪再分析，例如：\n"
            "ffmpeg -i 原视频.mp4 -vf scale=-2:720 -crf 28 压缩后.mp4"
        )
    mime = mimetypes.guess_type(path)[0] or "video/mp4"
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return f"data:{mime};base64,{b64}"


# 下载体积安全上限，防止异常 URL 把磁盘打满
MAX_DOWNLOAD_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB


def _remote_size(url: str):
    """HEAD 探测远程视频体积（字节），失败或无 Content-Length 返回 None。"""
    try:
        r = _session.head(url, timeout=10, allow_redirects=True)
        n = r.headers.get("content-length", "")
        return int(n) if n.isdigit() else None
    except requests.RequestException:
        return None


def _download_video(url: str) -> str:
    """把远程视频流式下载到 tmp/，返回本地路径。"""
    dst = TMP_DIR / f"下载_{datetime.datetime.now():%Y%m%d_%H%M%S}.mp4"
    try:
        with _session.get(url, stream=True, timeout=(10, 60)) as r:
            if r.status_code != 200:
                raise gr.Error(f"视频下载失败（HTTP {r.status_code}）")
            downloaded = 0
            with open(dst, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    downloaded += len(chunk)
                    if downloaded > MAX_DOWNLOAD_BYTES:
                        raise gr.Error("视频超过 2GB，超出本 demo 的处理能力，请自行裁剪")
                    f.write(chunk)
    except requests.RequestException as e:
        raise gr.Error(f"视频下载失败：{e}")
    return str(dst)


def _probe_duration(path: str):
    """ffprobe 取视频时长（秒），失败返回 None。"""
    if not shutil.which("ffprobe"):
        return None
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=60,
        )
        return float(out.stdout.strip())
    except (subprocess.SubprocessError, ValueError):
        return None


def _compress_video(src: str) -> str:
    """把本地视频压到 50 MiB 以内（按时长反推码率，720p→480p 两轮保底），返回输出路径。"""
    if not shutil.which("ffmpeg"):
        raise gr.Error("视频超过 50MB 需要压缩，但本机未安装 ffmpeg（brew install ffmpeg）")
    dst = TMP_DIR / f"压缩_{datetime.datetime.now():%Y%m%d_%H%M%S}.mp4"
    duration = _probe_duration(src)
    for height, margin, crf in ((720, 0.9, 30), (480, 0.55, 36)):
        cmd = ["ffmpeg", "-y", "-i", src, "-vf", f"scale=-2:'min({height},ih)'"]
        if duration:
            # 目标码率 = 目标体积（留 margin 余量）/ 时长；音频 96k，其余给视频，150k 保底
            v_kbps = max(int(MAX_UPLOAD_BYTES * margin * 8 / duration / 1000) - 96, 150)
            cmd += ["-b:v", f"{v_kbps}k", "-maxrate", f"{v_kbps}k",
                    "-bufsize", f"{v_kbps * 2}k"]
        else:  # 拿不到时长就按固定 crf 压
            cmd += ["-crf", str(crf)]
        cmd += ["-b:a", "96k", "-movflags", "+faststart", str(dst)]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        if proc.returncode != 0:
            raise gr.Error(f"ffmpeg 压缩失败：{proc.stderr[-300:]}")
        if dst.stat().st_size <= MAX_UPLOAD_BYTES:
            return str(dst)
    raise gr.Error(
        f"压缩两轮后仍超 50MB（{dst.stat().st_size / 1048576:.0f}MB），"
        "视频可能太长，请手动裁剪/压缩后再试"
    )


def _extract_text(resp: dict) -> str:
    """从 Responses API 的 output 里取出助手文字（跳过 reasoning 项）。"""
    parts = []
    for item in resp.get("output", []):
        if item.get("type") != "message":
            continue
        for c in item.get("content", []):
            if c.get("type") == "output_text" and c.get("text"):
                parts.append(c["text"])
    return "\n".join(parts).strip() or "（模型未返回文字内容）"


def _post(payload: dict, api_key: str) -> str:
    """POST Ark Responses API 并取出助手文字，失败抛 gr.Error。"""
    try:
        r = _session.post(
            f"{BASE_URL}/responses",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            # 非流式响应：服务端生成完才返回，推理模型长输出可能远超 300s，放宽到 15 分钟
            timeout=900,
        )
    except requests.RequestException as e:
        raise gr.Error(f"网络请求失败：{e}")

    data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if r.status_code != 200 or "error" in data:
        err = data.get("error", {})
        msg = err.get("message") or r.text[:500]
        raise gr.Error(f"调用失败（HTTP {r.status_code}）：{msg}")

    return _extract_text(data)


def _call(url, prompt, model, fps, api_key):
    """组装视频请求并调用 Ark Responses API，返回模型文字分析。"""
    video_part = {"type": "input_video", "video_url": url}
    if fps and float(fps) > 0:
        video_part["fps"] = float(fps)

    payload = {
        "model": (model or "").strip() or DEFAULT_MODEL,
        "input": [
            {
                "role": "user",
                "content": [
                    video_part,
                    {"type": "input_text", "text": (prompt or "").strip() or DEFAULT_PROMPT},
                ],
            }
        ],
    }
    return _post(payload, api_key)


def _call_text(prompt, model, api_key):
    """纯文本调用 Ark Responses API（提炼手段库用），返回模型文字。"""
    payload = {
        "model": (model or "").strip() or DEFAULT_MODEL,
        "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
    }
    return _post(payload, api_key)


# 按钮的「就绪」「分析中」两种外观，供生成器切换。
BTN_READY = gr.update(value="🚀 开始分析", interactive=True)
BTN_BUSY = gr.update(value="⏳ 分析中…", interactive=False)


def _save_result(text, source, model, fps, prompt, prefix="分析"):
    """把一次分析结果连同元信息存为 Markdown，返回文件路径。

    prefix 区分产出类型：「分析」（素材拆解，进提炼）/「选段」（原剧点位图，不进提炼）。
    """
    now = datetime.datetime.now()
    stamp = now.strftime("%Y%m%d_%H%M%S")
    doc = (
        f"# 视频{prefix}结果\n\n"
        f"- 时间：{now.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"- 视频来源：{source}\n"
        f"- 模型：{(model or '').strip() or DEFAULT_MODEL}\n"
        f"- 抽帧 fps：{fps}\n"
        f"- 分析指令：{(prompt or '').strip() or DEFAULT_PROMPT}\n\n"
        f"---\n\n{text}\n"
    )
    path = RESULTS_DIR / f"{prefix}_{stamp}.md"
    path.write_text(doc, encoding="utf-8")
    return path


def analyze(video_file, video_url, prompt, model, fps, api_key, mode):
    """界面入口：先校验，再以加载态调用，最后吐结果并自动归档。

    yield 四元组 (结果 Markdown, 状态行, 按钮状态, 下载文件)，让前端有明确反馈。
    mode 为 MODE_SCOUT 时走原剧选段：prompt 末尾自动拼接手段库全文作为选段标准，
    产出存为 选段_*.md（不进手段库提炼）。
    """
    scout = mode == MODE_SCOUT
    # —— 即时校验（出错弹 toast，按钮维持就绪态）——
    url = (video_url or "").strip()
    source = url  # 归档时记录的视频来源
    if not url and video_file:
        source = f"上传文件 {os.path.basename(video_file)}"
        url = _file_to_data_url(video_file)
    if not url:
        raise gr.Error("请上传视频文件，或填入一个视频 URL")
    key = _api_key(api_key)

    # —— 组装最终指令：选段模式在文本框内容后拼接手段库 ——
    final_prompt = (prompt or "").strip() or (SCOUT_PROMPT if scout else DEFAULT_PROMPT)
    if scout:
        lib = SKILL_PATH.read_text(encoding="utf-8") if SKILL_PATH.exists() else "（手段库为空，请按通用短剧高能特征选段）"
        final_prompt += lib

    # —— 进入加载态：清空旧结果、显示进度提示、禁用按钮、隐藏旧下载 ——
    yield "", "⏳ 正在分析视频，请稍候…（通常 10–30 秒，长视频更久）", BTN_BUSY, gr.update(visible=False)

    # —— URL 视频预检：超过 50 MiB 先下载到本地压缩，再改走 base64 ——
    if url.startswith(("http://", "https://")):
        size = _remote_size(url)
        if size and size > MAX_UPLOAD_BYTES:
            yield (
                "",
                f"⏳ 视频约 {size / 1048576:.0f}MB，超过 50MB 上限，"
                "正在下载并压缩（可能需几分钟）…",
                BTN_BUSY,
                gr.update(visible=False),
            )
            try:
                packed = _compress_video(_download_video(url))
            except gr.Error as e:
                yield f"### ❌ 预处理失败\n\n{e.message}", "失败", BTN_READY, gr.update(visible=False)
                return
            packed_mb = os.path.getsize(packed) / 1048576
            source = f"{url}（原约 {size / 1048576:.0f}MB，已自动压缩至 {packed_mb:.1f}MB）"
            url = _file_to_data_url(packed)  # 压缩结果必然 ≤50 MiB，这里同时完成 base64 封装
            yield "", "⏳ 压缩完成，正在分析视频…", BTN_BUSY, gr.update(visible=False)

    try:
        text = _call(url, final_prompt, model, fps, key)
    except gr.Error as e:
        yield f"### ❌ 调用失败\n\n{e.message}", "失败", BTN_READY, gr.update(visible=False)
        return
    except Exception as e:  # 兜底，避免界面卡在加载态
        yield f"### ❌ 出错\n\n```\n{e}\n```", "失败", BTN_READY, gr.update(visible=False)
        return

    path = _save_result(text, source, model, fps, prompt, prefix="选段" if scout else "分析")
    yield (
        text,
        f"✅ {'选段' if scout else '分析'}完成 · 已自动保存到 `results/{path.name}`",
        BTN_READY,
        gr.update(value=str(path), visible=True),
    )


# 提炼手段库的指令。{existing} 和 {docs} 为占位符，用 replace 注入（避免 format 转义问题）。
DISTILL_PROMPT = """你在维护一个「短剧投流素材剪辑手段库」。下面给出手段库现状（可能为空）和若干份高热素材的分析文档，请从分析文档中提取剪辑手段，输出更新后的完整手段库。

【提取规则】
1. 每个手段是一张原子卡片，格式严格为：
### 手段名
- 类别：钩子 / 节奏 / 叙事结构 / 字幕 / 音效 / 转场 / 收尾 / 其他
- 做法：可执行的量化标准（秒数、字数、镜头数；与素材时长相关的数值一律换算成比例或公式）
- 适用：题材、素材时长范围
- 变体：可替换或可组合的方向
- 来源：分析文件名（多个来源用、分隔）
2. 与库中已有手段实质相同的，合并为一张卡片；来源必须累加列出所有有贡献的分析文件，不允许静默丢弃某份输入。做法不同甚至冲突、但各自有道理的，作为不同卡片并列保留——禁止取平均、禁止二选一。
3. 只提取可落地的硬标准，丢弃「注意节奏」「画面要有张力」这类虚话；分析中标注「不确定」的内容不要采用。
4. 卡片按类别分组（## 类别名），组内按来源数量降序。
5. 只输出手段库正文 Markdown（## 开头），不要输出任何解释性文字。

【手段库现状】
{existing}

【分析文档】
{docs}
"""


def _load_library() -> str:
    """读取手段库全文用于展示，不存在时返回引导语。"""
    if SKILL_PATH.exists():
        return SKILL_PATH.read_text(encoding="utf-8")
    return "*还没有手段库。先在「视频分析」页分析素材，再点上方「从分析结果提炼/更新」生成。*"


def distill_library(model, api_key):
    """界面入口：读 results/ 全部分析文档 + 现有手段库，调模型提炼，写回并展示。"""
    mds = sorted(RESULTS_DIR.glob("分析_*.md"))
    if not mds:
        raise gr.Error("results/ 下还没有分析结果，请先在「视频分析」页分析素材")
    key = _api_key(api_key)

    yield "（内容不变）", f"⏳ 正在从 {len(mds)} 份分析文档提炼手段库…"

    docs = "\n\n".join(f"=== {p.name} ===\n{p.read_text(encoding='utf-8')}" for p in mds)
    existing = SKILL_PATH.read_text(encoding="utf-8") if SKILL_PATH.exists() else "（空）"
    prompt = DISTILL_PROMPT.replace("{existing}", existing).replace("{docs}", docs)
    try:
        body = _call_text(prompt, model, key)
    except gr.Error as e:
        yield gr.update(), f"❌ 提炼失败：{e.message}"
        return

    SKILL_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    header = (
        "# 短剧剪辑手段库\n\n"
        "> 从 results/ 分析文档自动提炼：相同合并、冲突并存，随素材分析持续累积。\n"
        f"> 更新于 {stamp}，来源 {len(mds)} 份分析。\n\n"
    )
    SKILL_PATH.write_text(header + body + "\n", encoding="utf-8")
    _build_recipes()
    yield (
        _load_library(),
        f"✅ 手段库与原型配方已更新（来源 {len(mds)} 份分析，见 `skills/短剧剪辑手段库/`）",
    )


# —— 原型配方：同来源手段卡按剪辑环节聚合（机械生成，不耗模型） ——

_CATEGORY_ORDER = ["钩子", "节奏", "叙事结构", "字幕", "音效", "转场", "收尾", "其他"]


def _parse_cards(lib_text: str) -> list:
    """把 SKILL.md 解析成卡片列表：{name, category, action, variant, sources}。"""
    cards, category, cur = [], "", None
    for line in lib_text.splitlines():
        if line.startswith("## "):
            category = line[3:].strip()
        elif line.startswith("### "):
            cur = {"name": line[4:].strip(), "category": category,
                   "action": "", "variant": "", "sources": []}
            cards.append(cur)
        elif cur and line.startswith("- 做法："):
            cur["action"] = line[5:].strip()
        elif cur and line.startswith("- 变体："):
            cur["variant"] = line[5:].strip()
        elif cur and line.startswith("- 来源："):
            cur["sources"] = [s.strip() for s in line[5:].split("、") if s.strip()]
    return cards


# 从标签尾部剥掉的通用词（循环剥除直到稳定）
_LABEL_SUFFIX = re.compile(
    r"(投流素材|爆量拆解|可落地|剪辑SOP|直接复用|竖屏短剧|短剧投流|题材的|拆解|投产|投流|短剧|题材|素材|的)$"
)


def _strip_label_suffix(t: str) -> str:
    for _ in range(6):
        stripped = _LABEL_SUFFIX.sub("", t).strip("，。, ")
        if stripped == t:
            break
        t = stripped
    return t


def _topic_label(md_path: Path) -> str:
    """从分析文档取题材短标签：优先「素材概览」首句，其次文档第二个一级标题。"""
    try:
        text = md_path.read_text(encoding="utf-8")
    except OSError:
        return ""
    m = re.search(r"##\s*1[.、]?\s*素材概览\s*\n+(.+)", text)
    if m:
        line = re.sub(r"^这是", "", m.group(1).strip())
        line = re.split(r"[，。,]", line)[0]
        return _strip_label_suffix(line)[:24]
    titles = re.findall(r"^# (.+)$", text, re.M)
    if len(titles) >= 2:  # 第一个 # 是「视频分析结果」文件头，第二个才是模型拟的标题
        t = re.sub(r"（.*?）", "", titles[1]).strip()
        return _strip_label_suffix(t)[:24]
    return ""


def _build_recipes():
    """按来源把手段卡聚成原型配方写 RECIPES.md，返回配方套数（无手段库返回 0）。"""
    if not SKILL_PATH.exists():
        return 0
    cards = _parse_cards(SKILL_PATH.read_text(encoding="utf-8"))
    by_src = {}
    for c in cards:
        for s in c["sources"]:
            by_src.setdefault(s, []).append(c)

    parts = [
        "# 短剧剪辑原型配方",
        "",
        "> 每条高热素材 = 一套被验证过的整体配合：同来源的手段卡按剪辑环节排列即为一套配方。",
        "> 用作批量剪辑的基准；投放变体 = 基准配方 + 单环节替换。与手段库同步更新。",
    ]
    for src in sorted(by_src):
        label = _topic_label(RESULTS_DIR / src) or src
        parts += ["", f"## 配方 · {label}", "", f"来源：`{src}`"]
        groups = {}
        for c in by_src[src]:
            groups.setdefault(c["category"], []).append(c)
        for cat in _CATEGORY_ORDER:
            if cat not in groups:
                continue
            parts += ["", f"### {cat}"]
            for c in groups[cat]:
                line = f"- **{c['name']}**：{c['action']}"
                if c["variant"]:
                    line += f"（变体：{c['variant']}）"
                parts.append(line)
        parts.append("")
    RECIPES_PATH.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return len(by_src)


def _load_recipes() -> str:
    """读取原型配方全文用于展示，不存在时返回引导语。"""
    if RECIPES_PATH.exists():
        return RECIPES_PATH.read_text(encoding="utf-8")
    return "*还没有配方。先在「剪辑手段库」页点「从分析结果提炼/更新」，配方会随手段库一起生成。*"


with gr.Blocks(title="视频分析 · 豆包视频理解") as demo:
    with gr.Tabs():
        with gr.Tab("🎬 视频分析"):
            gr.Markdown(
                "调用火山引擎方舟（Ark）豆包视频理解模型，对视频做内容分析。"
                "上传本地视频，或填入一个公网视频 URL。"
            )

            with gr.Row():
                with gr.Column(scale=1):
                    mode_in = gr.Radio(
                        choices=[MODE_ANALYZE, MODE_SCOUT],
                        value=MODE_ANALYZE,
                        label="分析模式（原剧选段：从原始短剧里找高能段落，自动带上手段库做检索标准；长视频建议 fps 调低）",
                    )
                    video_in = gr.Video(label="上传视频", sources=["upload"])
                    url_in = gr.Textbox(
                        label="或：视频 URL（公网可访问，超 50MB 自动下载压缩）",
                        placeholder="https://example.com/demo.mp4",
                    )
                    prompt_in = gr.Textbox(
                        label="分析指令 / 你想问什么", value=DEFAULT_PROMPT, lines=3
                    )
                    mode_in.change(
                        lambda m: gr.update(value=SCOUT_PROMPT if m == MODE_SCOUT else DEFAULT_PROMPT),
                        inputs=mode_in,
                        outputs=prompt_in,
                    )
                    with gr.Accordion("高级设置", open=False):
                        model_in = gr.Textbox(label="模型 ID", value=DEFAULT_MODEL)
                        fps_in = gr.Slider(
                            label="抽帧 fps（每秒抽几帧给模型；越大越细但越贵/越慢）",
                            minimum=0, maximum=5, step=0.5, value=1,
                        )
                        key_in = gr.Textbox(
                            label="API Key（留空则用 .env 里的 ARK_API_KEY）",
                            type="password",
                        )
                    with gr.Row():
                        run_btn = gr.Button("🚀 开始分析", variant="primary", scale=3)
                        clear_btn = gr.Button("清空", scale=1)
                with gr.Column(scale=1):
                    status = gr.Markdown("", elem_id="status")
                    output = gr.Markdown(
                        value="*结果会显示在这里。上传视频或填 URL，点「开始分析」。*",
                        label="分析结果",
                    )
                    download_btn = gr.DownloadButton(
                        "⬇️ 下载结果 (.md)", visible=False
                    )

            run_btn.click(
                analyze,
                inputs=[video_in, url_in, prompt_in, model_in, fps_in, key_in, mode_in],
                outputs=[output, status, run_btn, download_btn],
                show_progress="minimal",
            )

            clear_btn.click(
                lambda: (None, "", "", "*结果会显示在这里。*", gr.update(visible=False)),
                outputs=[video_in, url_in, status, output, download_btn],
            )

        with gr.Tab("🧰 剪辑手段库") as lib_tab:
            gr.Markdown(
                "从 `results/` 的分析文档中提炼的原子剪辑手段：**相同合并、冲突并存**，"
                "随素材分析持续累积，供后续批量剪辑时抽样组合。模型与 API Key 沿用「视频分析」页的设置。"
            )
            with gr.Row():
                distill_btn = gr.Button("🔄 从分析结果提炼/更新", variant="primary", scale=3)
                reload_btn = gr.Button("↻ 刷新显示", scale=1)
            distill_status = gr.Markdown("")
            library_md = gr.Markdown(value=_load_library())

            distill_btn.click(
                distill_library,
                inputs=[model_in, key_in],
                outputs=[library_md, distill_status],
                show_progress="minimal",
            )
            reload_btn.click(_load_library, outputs=library_md)
            lib_tab.select(_load_library, outputs=library_md)

        with gr.Tab("🧬 原型配方") as recipe_tab:
            gr.Markdown(
                "每条高热素材 = 一套被验证过的整体配合：同来源的手段卡按剪辑环节排列即为一套配方。"
                "批量剪辑时选配方做基准，每条投放变体只替换一个环节的手段（便于效果归因）。"
                "配方随「剪辑手段库」页的提炼同步更新。"
            )
            with gr.Row():
                recipe_reload_btn = gr.Button("↻ 刷新显示", scale=1)
            recipe_md = gr.Markdown(value=_load_recipes())

            recipe_reload_btn.click(_load_recipes, outputs=recipe_md)
            recipe_tab.select(_load_recipes, outputs=recipe_md)


if __name__ == "__main__":
    demo.queue().launch()
