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

import os
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
    """从文件名中提取日期"""
    match = re.search(pattern, filename)
    if match:
        return match.group(1)
    return ""


def sync_incremental(source_dir: Path, dest_dir: Path) -> list:
    """
    增量同步: 只复制目标目录中不存在的HTML文件
    返回: 已同步的文件名列表
    """
    synced = []
    dest_dir.mkdir(parents=True, exist_ok=True)

    for html_file in sorted(source_dir.glob("*.html")):
        dest_file = dest_dir / html_file.name
        if not dest_file.exists():
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

    # 增量同步
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

        items.append({
            "title": title,
            "date": date,
            "summary": summary,
            "path": f"{module['key']}/{html_file.name}",
        })

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


def main():
    print("=" * 60)
    print("generate.py - 站点索引生成器")
    print(f"站点目录: {SITE_DIR}")
    print("=" * 60)

    manifest = {"modules": {}}

    for module in MODULES:
        result = process_module(module)
        manifest["modules"][module["key"]] = result

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
