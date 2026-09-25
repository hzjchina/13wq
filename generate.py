#!/usr/bin/env python3
"""
generate.py - 扫描3个自动化任务的HTML产出，增量同步到 site/ 并生成 manifest.json

源目录:
  - Claw/ai-info/         (每日AI情报)
  - Claw/bedtime-stories/ (儿童睡前故事)
  - Claw/classic-movies/  (经典电影推荐)

输出:
  - site/manifest.json    (数据索引)
  - site/{module}/*.html  (增量同步的HTML副本)
"""

import re
import json
import shutil
from pathlib import Path

# === 配置 ===
BASE_DIR = Path(__file__).parent.parent  # Claw/
SITE_DIR = Path(__file__).parent          # Claw/site/

MODULES = [
    {
        "key": "classic-movies",
        "name": "经典电影",
        "icon": "🎬",
        "source": BASE_DIR / "classic-movies",
        "dest": SITE_DIR / "classic-movies",
        "pattern": r"classic-movie-(\d{4}-\d{2}-\d{2})\.html",
    },
    {
        "key": "bedtime-stories",
        "name": "睡前故事",
        "icon": "🌙",
        "source": BASE_DIR / "bedtime-stories",
        "dest": SITE_DIR / "bedtime-stories",
        "pattern": r"bedtime-story-(\d{4}-\d{2}-\d{2})\.html",
    },
    {
        "key": "ai-info",
        "name": "AI情报",
        "icon": "🤖",
        "source": BASE_DIR / "ai-info",
        "dest": SITE_DIR / "ai-info",
        "pattern": r"ai-info-(\d{4}-\d{2}-\d{2})\.html",
    },
]

SUMMARY_LENGTH = 120  # 摘要字数

# 经典电影特殊兜底：title 无片名的文件，手动指定片名
MOVIE_TITLE_FALLBACK = {
    "classic-movie-2026-05-21.html": "教父",
}

# === 睡前故事音频 ===
# 音频文件标准命名: bedtime-story-YYYY-MM-DD.m4a，与故事HTML同名对应
# 其他命名(哈希名/分段/_副本)一律忽略，不参与同步
AUDIO_EXTS = {".m4a", ".mp3", ".wav", ".aac", ".ogg"}

AUDIO_PLAYER_CSS = """  /* === 音频播放器（generate.py 注入） === */
  .audio-box{display:flex;align-items:center;gap:14px;margin:0 0 18px;padding:14px 18px;background:rgba(255,225,160,.08);border:1px solid rgba(255,225,160,.22);border-radius:16px}
  .audio-btn{flex:0 0 auto;width:46px;height:46px;border-radius:50%;border:none;background:linear-gradient(135deg,#ffd98a,#b48cff);color:#2a1f4d;font-size:17px;cursor:pointer;box-shadow:0 0 16px rgba(255,220,150,.35);transition:transform .2s;display:flex;align-items:center;justify-content:center;padding:0}
  .audio-btn:hover{transform:scale(1.08)}
  .audio-btn.playing{animation:audioPulse 1.8s ease-in-out infinite}
  @keyframes audioPulse{0%,100%{box-shadow:0 0 10px 2px rgba(255,220,150,.3)}50%{box-shadow:0 0 24px 9px rgba(255,220,150,.55)}}
  .audio-meta{flex:1;min-width:0}
  .audio-title{font-size:13px;color:#ffe9b0;letter-spacing:2px;margin-bottom:7px}
  .audio-track{height:5px;background:rgba(255,255,255,.14);border-radius:3px;overflow:hidden;cursor:pointer}
  .audio-progress{height:100%;width:0;background:linear-gradient(90deg,#ffd98a,#b48cff);border-radius:3px;transition:width .2s linear}
  .audio-time{font-size:11px;color:#9d8fc7;margin-top:5px;text-align:right;font-variant-numeric:tabular-nums}
"""

AUDIO_PLAYER_HTML = """  <div class="audio-box" id="audioBox">
    <button class="audio-btn" id="audioBtn" aria-label="播放故事音频">▶</button>
    <div class="audio-meta">
      <div class="audio-title">🎧 听 · 今日故事</div>
      <div class="audio-track" id="audioTrack"><div class="audio-progress" id="audioProgress"></div></div>
      <div class="audio-time" id="audioTime">00:00 / 00:00</div>
    </div>
    <audio id="storyAudio" src="{src}" preload="metadata"></audio>
  </div>

"""

AUDIO_PLAYER_JS = """<script>
(function(){
  var box=document.getElementById('audioBox'),audio=document.getElementById('storyAudio');
  if(!box||!audio)return;
  var btn=document.getElementById('audioBtn'),prog=document.getElementById('audioProgress'),track=document.getElementById('audioTrack'),time=document.getElementById('audioTime');
  function fmt(s){if(!isFinite(s)||s<0)return'00:00';s=Math.floor(s);var m=Math.floor(s/60);return(m<10?'0':'')+m+':'+((s%60)<10?'0':'')+(s%60);}
  audio.addEventListener('loadedmetadata',function(){time.textContent='00:00 / '+fmt(audio.duration);});
  audio.addEventListener('timeupdate',function(){if(audio.duration){prog.style.width=(audio.currentTime/audio.duration*100)+'%';time.textContent=fmt(audio.currentTime)+' / '+fmt(audio.duration);}});
  audio.addEventListener('play',function(){btn.textContent='⏸';btn.classList.add('playing');});
  audio.addEventListener('pause',function(){btn.textContent='▶';btn.classList.remove('playing');});
  audio.addEventListener('ended',function(){btn.textContent='↻';btn.classList.remove('playing');prog.style.width='0%';});
  btn.addEventListener('click',function(){if(audio.paused){audio.play().catch(function(){box.style.display='none';});}else{audio.pause();}});
  track.addEventListener('click',function(e){if(!audio.duration)return;var r=track.getBoundingClientRect();audio.currentTime=Math.max(0,Math.min(1,(e.clientX-r.left)/r.width))*audio.duration;});
  audio.addEventListener('error',function(){box.style.display='none';});
})();
</script>
"""


def inject_audio_player(html: str, audio_src: str) -> str:
    """向故事HTML注入音频播放器（幂等：已注入则原样返回）"""
    if "storyAudio" in html:
        return html
    # 1. 注入CSS（放在 </style> 前）
    html = html.replace("</style>", AUDIO_PLAYER_CSS + "</style>", 1)
    # 2. 注入播放器盒子：标题与正文之间
    #    一级 marker 都是【正文容器】（story/article/card 等），插到其"之前"
    #    —— box 落在正文容器外、外层容器内，即标题区之后、正文之前 ✅
    #    注意：<div class="container">/<div class="wrap"> 是【外层容器】，
    #          若作为一级会因出现位置早而把 box 插到外层容器"之外"造成外溢，
    #          故只作二级兜底（插到其内部首位）。
    box_html = AUDIO_PLAYER_HTML.replace("{src}", audio_src)
    pos = -1
    for marker in (
        '<div class="card">', '<div class="poster">', '<div class="story">',
        '<div class="story-container">', '<div class="content">',
        '<article class="story">',
    ):
        p = html.find(marker)
        if p != -1 and (pos == -1 or p < pos):
            pos = p
    if pos != -1:
        html = html[:pos] + box_html + html[pos:]
    else:
        injected = False
        for outer in ('<div class="wrap">', '<div class="container">'):
            if outer in html:
                html = html.replace(outer, outer + box_html, 1)
                injected = True
                break
        if not injected:
            m = re.search(r"<body[^>]*>", html)
            if m:
                end = m.end()
                html = html[:end] + "\n" + box_html + html[end:]
    # 3. 注入JS（放在 </body> 前）
    html = html.replace("</body>", AUDIO_PLAYER_JS + "</body>", 1)
    return html


def audio_filename_for(html_name: str) -> str:
    """从故事HTML文件名推出标准音频文件名，非标准命名返回空"""
    m = re.match(r"(bedtime-story-\d{4}-\d{2}-\d{2})\.html$", html_name)
    return f"{m.group(1)}.m4a" if m else ""


def sync_audio(source_dir: Path) -> set:
    """
    增量同步音频目录到 site/bedtime-stories/audio/
    只同步标准命名的 bedtime-story-YYYY-MM-DD.m4a
    返回: 站点侧有音频的日期集合
    """
    src_audio = source_dir / "audio"
    dates = set()
    if not src_audio.is_dir():
        return dates
    dest_audio = SITE_DIR / "bedtime-stories" / "audio"
    dest_audio.mkdir(parents=True, exist_ok=True)
    for f in sorted(src_audio.iterdir()):
        if not f.is_file() or f.suffix.lower() not in AUDIO_EXTS:
            continue
        m = re.match(r"(bedtime-story-\d{4}-\d{2}-\d{2})\.m4a$", f.name, re.IGNORECASE)
        if not m:
            continue  # 非标准命名直接忽略
        df = dest_audio / f.name
        if not df.exists():
            shutil.copy2(f, df)
            print(f"  [音频] {f.name}")
        dates.add(m.group(1)[len("bedtime-story-"):])  # 只存纯日期 YYYY-MM-DD
    return dates


def extract_title(html: str) -> str:
    """从HTML中提取 <title> 标签内容"""
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return "无标题"


def extract_summary(html: str, length: int = SUMMARY_LENGTH) -> str:
    """
    从HTML中提取正文摘要:
    1. 移除 <style> 和 <script> 标签及内容
    2. 移除所有HTML标签
    3. 清理空白
    4. 取前 length 字
    """
    # 移除 style 和 script 标签及内容
    text = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
    # 移除 HTML 注释
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    # 移除所有 HTML 标签
    text = re.sub(r"<[^>]+>", " ", text)
    # 清理 HTML 实体
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&quot;", '"', text)
    # 清理多余空白
    text = re.sub(r"\s+", " ", text).strip()
    # 截取摘要
    if len(text) > length:
        return text[:length] + "..."
    return text


def extract_date(filename: str, pattern: str) -> str:
    """从文件名中提取日期（宽松匹配，兼容 classic-movie-2026-08-20-082228.html 这类带时间戳后缀的文件名）"""
    match = re.search(pattern, filename)
    if match:
        return match.group(1)
    match = re.search(r"(\d{4}-\d{2}-\d{2})", filename)
    if match:
        return match.group(1)
    return ""


def sync_incremental(source_dir: Path, dest_dir: Path, transform=None) -> list:
    """
    增量同步: 只复制目标目录中不存在的HTML文件
    transform: 可选函数(html:str, filename:str) -> str，复制时对内容做转换（如注入播放器）
    返回: 已同步的文件名列表
    """
    synced = []
    dest_dir.mkdir(parents=True, exist_ok=True)

    for html_file in sorted(source_dir.glob("*.html")):
        dest_file = dest_dir / html_file.name
        if not dest_file.exists():
            if transform:
                try:
                    html = html_file.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    html = html_file.read_text(encoding="gbk", errors="ignore")
                dest_file.write_text(transform(html, html_file.name), encoding="utf-8")
            else:
                shutil.copy2(html_file, dest_file)
            synced.append(html_file.name)
            print(f"  [同步] {html_file.name}")
        # 已存在的跳过（增量）

    return synced


def process_module(module: dict) -> dict:
    """处理单个模块: 增量同步 + 提取摘要"""
    print(f"\n处理模块: {module['name']} ({module['key']})")

    source_dir = module["source"]
    dest_dir = module["dest"]

    if not source_dir.exists():
        print(f"  [警告] 源目录不存在: {source_dir}")
        return {
            "name": module["name"],
            "icon": module["icon"],
            "items": [],
        }

    # 音频日期集合（睡前故事用）
    audio_dates = set()

    # 增量同步
    if module["key"] == "bedtime-stories":
        audio_dates = sync_audio(source_dir)
        if audio_dates:
            print(f"  音频: {len(audio_dates)} 天有配套音频")
            def story_transform(html: str, filename: str) -> str:
                audio_name = audio_filename_for(filename)
                if audio_name:
                    date = audio_name[len("bedtime-story-"):-len(".m4a")]
                    if date in audio_dates:
                        return inject_audio_player(html, f"audio/{audio_name}")
                return html
            synced = sync_incremental(source_dir, dest_dir, transform=story_transform)
        else:
            synced = sync_incremental(source_dir, dest_dir)
    else:
        synced = sync_incremental(source_dir, dest_dir)
    if not synced:
        print(f"  无新增文件（已全部同步）")

    # 扫描目标目录所有HTML，生成索引
    items = []
    for html_file in sorted(dest_dir.glob("*.html")):
        try:
            html = html_file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            html = html_file.read_text(encoding="gbk", errors="ignore")

        title = extract_title(html)
        # 睡前故事: 去掉 title 中 " — 儿童睡前故事" 后缀
        if module["key"] == "bedtime-stories":
            title = re.sub(r'\s*[—–\-]\s*儿童睡前故事\s*$', '', title)
        # 经典电影: 清理前缀，只保留片名
        if module["key"] == "classic-movies":
            # 1. 去掉尾部日期 (2026-06-01)
            title = re.sub(r'\s*[(（]\d{4}-\d{2}-\d{2}[)）]\s*$', '', title)
            # 2. 去掉 "经典电影推荐/每日经典电影推荐" 前缀 + 分隔符 + 期数 + 分隔符
            #    分隔符涵盖 · | ｜ — – - : ：，片名内部的 · 不会被误伤
            title = re.sub(
                r'^(每日)?经典电影推荐\s*(?:[·|｜—–\-：:]\s*)?(?:第\s*\d+\s*期\s*)?(?:[·|｜—–\-：:]\s*)?',
                '', title
            ).strip()
            # 3. 兜底：清理后为空 → 使用手动映射，仍无则用文件名
            if not title:
                title = MOVIE_TITLE_FALLBACK.get(html_file.name, html_file.name)
        summary = extract_summary(html)
        date = extract_date(html_file.name, module["pattern"])

        item = {
            "title": title,
            "date": date,
            "summary": summary,
            "path": f"{module['key']}/{html_file.name}",
        }
        # 睡前故事: 标记是否有配套音频（首页显示 🔊 有声标识）
        # audio_dates 中的页面会在本次运行末尾由 retrofit_audio 注入播放器
        if module["key"] == "bedtime-stories" and date in audio_dates:
            item["audio"] = True
        items.append(item)

    # 经典电影: 识别重复推荐，标记 "重温 x 次"
    # 同一片名按日期升序数出现次序，第 2 次及以后出现 → rewatch = 出现次序
    if module["key"] == "classic-movies":
        seen = {}  # title -> 已出现次数
        for item in sorted(items, key=lambda x: x["date"]):  # 日期升序
            seen[item["title"]] = seen.get(item["title"], 0) + 1
            if seen[item["title"]] >= 2:
                item["rewatch"] = seen[item["title"]]
        dup_titles = {t: c for t, c in seen.items() if c >= 2}
        if dup_titles:
            print(f"  重温标记: {len(dup_titles)} 部")
            for t, c in dup_titles.items():
                print(f"    [重温{c}次] {t}")

    # 按日期倒序
    items.sort(key=lambda x: x["date"], reverse=True)
    print(f"  总计: {len(items)} 篇, 新增: {len(synced)} 篇")

    return {
        "name": module["name"],
        "icon": module["icon"],
        "items": items,
    }


def retrofit_audio() -> int:
    """
    回填: 给 site 中已有但未注入播放器的故事页补注入
    （只处理站点侧已有对应标准命名音频的页面）
    返回: 注入的页面数
    """
    dest = SITE_DIR / "bedtime-stories"
    if not dest.is_dir():
        return 0
    audio_dir = dest / "audio"
    if not audio_dir.is_dir():
        return 0
    count = 0
    for m4a in sorted(audio_dir.glob("bedtime-story-????-??-??.m4a")):
        date = m4a.stem.replace("bedtime-story-", "")
        html_file = dest / f"bedtime-story-{date}.html"
        if not html_file.exists():
            continue
        html = html_file.read_text(encoding="utf-8")
        if "storyAudio" in html:
            continue
        html_file.write_text(
            inject_audio_player(html, f"audio/{m4a.name}"), encoding="utf-8"
        )
        print(f"  [回填播放器] bedtime-story-{date}.html")
        count += 1
    return count


def main():
    print("=" * 60)
    print("generate.py - 站点索引生成器")
    print(f"站点目录: {SITE_DIR}")
    print("=" * 60)

    manifest = {"modules": {}}

    for module in MODULES:
        result = process_module(module)
        manifest["modules"][module["key"]] = result

    # 存量故事页回填音频播放器
    injected = retrofit_audio()
    if injected:
        print(f"\n回填播放器: {injected} 页")

    # 写入 manifest.json
    manifest_path = SITE_DIR / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    # 统计
    total = sum(len(m["items"]) for m in manifest["modules"].values())
    print(f"\n{'=' * 60}")
    print(f"完成! manifest.json 已生成")
    print(f"总计: {total} 篇文章")
    for key, mod in manifest["modules"].items():
        print(f"  {mod['icon']} {mod['name']}: {len(mod['items'])} 篇")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
