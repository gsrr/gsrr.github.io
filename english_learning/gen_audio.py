#!/usr/bin/env python3
"""用 edge-tts 把對話與聽寫句子預先轉成自然語音 mp3（男 Guy / 女 Jenny）。

安裝： pip install edge-tts
執行： python gen_audio.py      （需連網，會打微軟的語音服務）
產出： audio/0001.mp3 ...        與 audio/index.json（給網頁查表用）

網頁會優先播這些 mp3，沒有對應檔時自動退回瀏覽器內建語音。
"""
import os
import re
import json
import asyncio

import edge_tts

HERE = os.path.dirname(os.path.abspath(__file__))
AUDIO_DIR = os.path.join(HERE, "audio")
VOICES = {"male": "en-US-GuyNeural", "female": "en-US-JennyNeural"}


def parse_dialogue(text, speakers):
    items = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^([^:：]+)[:：]\s*(.*)$", line)
        if not m:
            continue
        who = m.group(1).strip()
        gender = speakers.get(who, "female")
        items.append((gender, m.group(2).strip()))
    return items


def collect_pairs():
    with open(os.path.join(HERE, "lessons.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    speakers = manifest.get("speakers", {})
    pairs = []  # (gender, text)
    for lv in manifest["levels"]:
        for a in lv.get("articles", []):
            path = os.path.join(HERE, *a["file"].split("/"))
            try:
                with open(path, encoding="utf-8") as f:
                    pairs += parse_dialogue(f.read(), speakers)
            except FileNotFoundError:
                print("略過（找不到檔案）:", a["file"])
            for s in a.get("dictation", []):
                pairs.append(("female", s))
    # 去重、保留順序
    seen, uniq = set(), []
    for g, t in pairs:
        if t and (g, t) not in seen:
            seen.add((g, t))
            uniq.append((g, t))
    return uniq


async def main():
    os.makedirs(AUDIO_DIR, exist_ok=True)
    pairs = collect_pairs()
    index = {}
    for i, (gender, text) in enumerate(pairs, 1):
        fname = "%04d.mp3" % i
        voice = VOICES.get(gender, VOICES["female"])
        print("[%d/%d] (%s) %s" % (i, len(pairs), gender, text))
        await edge_tts.Communicate(text, voice).save(os.path.join(AUDIO_DIR, fname))
        index["%s|%s" % (gender, text)] = fname
    with open(os.path.join(AUDIO_DIR, "index.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    print("完成：%d 個語音檔 -> %s" % (len(index), AUDIO_DIR))


if __name__ == "__main__":
    asyncio.run(main())
