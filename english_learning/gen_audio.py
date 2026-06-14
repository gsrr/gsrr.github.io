#!/usr/bin/env python3
"""用 edge-tts 把對話與聽寫句子預先轉成自然語音 mp3（男 Guy / 女 Jenny）。

安裝： pip install edge-tts
執行： python gen_audio.py            （已存在的語音檔會跳過，只產生新增/改過的）
       python gen_audio.py --force    （強制全部重新產生）

產出： audio/<hash>.mp3  與  audio/index.json（給網頁查表用）
檔名用「性別|句子」的雜湊，所以同一句永遠對到同一個檔，可安全地增量產生。
網頁會優先播這些 mp3，沒有對應檔時自動退回瀏覽器內建語音。
"""
import os
import re
import sys
import json
import hashlib
import asyncio

import edge_tts

HERE = os.path.dirname(os.path.abspath(__file__))
AUDIO_DIR = os.path.join(HERE, "audio")
VOICES = {"male": "en-US-GuyNeural", "female": "en-US-JennyNeural"}

# 特定角色的語音風格：用不同的內建 neural 語音 + 較低音高/較慢語速，
# 模擬「總統」較低沉、慎重的口吻。這只是角色化的內建語音，非真人聲音複製。
SPEAKER_STYLES = {
    "Trump": {"voice": "en-US-ChristopherNeural", "rate": "-8%", "pitch": "-12Hz"},
}


def key_of(gender, text):
    return "%s|%s" % (gender, text)


def file_of(gender, text):
    h = hashlib.sha1(key_of(gender, text).encode("utf-8")).hexdigest()[:12]
    return h + ".mp3"


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
        items.append((gender, m.group(2).strip(), who))
    return items


def collect_pairs():
    with open(os.path.join(HERE, "lessons.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    speakers = manifest.get("speakers", {})
    pairs = []  # (gender, text, who)
    for lv in manifest["levels"]:
        for a in lv.get("articles", []):
            path = os.path.join(HERE, *a["file"].split("/"))
            try:
                with open(path, encoding="utf-8") as f:
                    pairs += parse_dialogue(f.read(), speakers)
            except FileNotFoundError:
                print("略過（找不到檔案）:", a["file"])
            # Level 8 聽寫
            for s in a.get("dictation", []):
                pairs.append(("female", s, None))
            # Level 3/4 測驗題目
            for it in a.get("quiz3", []) + a.get("quiz4", []):
                pairs.append(("female", it["q"], None))
            # Level 7 WH：題目、答案、以及「N. 選項」編號朗讀
            for it in a.get("wh", []):
                opts = [it["a"]] + it.get("wrong", [])
                pairs.append(("female", it["q"], None))
                pairs.append(("female", it["a"], None))
                for n in range(1, len(opts) + 1):
                    for opt in opts:
                        pairs.append(("female", "%d. %s" % (n, opt), None))
            # Level 9 填空：空格唸成 blank 的版本，以及填好答案的完整句
            for it in a.get("cloze", []):
                pairs.append(("female", it["text"].replace("___", "blank", 1), None))
                pairs.append(("female", it["text"].replace("___", it["answer"], 1), None))
    # 去重、保留順序（以 性別|句子 為鍵，沿用第一次出現的角色）
    seen, uniq = set(), []
    for g, t, who in pairs:
        if t and (g, t) not in seen:
            seen.add((g, t))
            uniq.append((g, t, who))
    return uniq


async def main():
    force = "--force" in sys.argv
    os.makedirs(AUDIO_DIR, exist_ok=True)
    pairs = collect_pairs()
    index = {}
    made = skipped = 0
    for i, (gender, text, who) in enumerate(pairs, 1):
        fname = file_of(gender, text)
        index[key_of(gender, text)] = fname
        dest = os.path.join(AUDIO_DIR, fname)
        if os.path.exists(dest) and not force:
            skipped += 1
            print("[%d/%d] 跳過（已存在） %s" % (i, len(pairs), text))
            continue
        style = SPEAKER_STYLES.get(who or "")
        voice = (style or {}).get("voice") or VOICES.get(gender, VOICES["female"])
        kwargs = {}
        if style:
            if style.get("rate"):
                kwargs["rate"] = style["rate"]
            if style.get("pitch"):
                kwargs["pitch"] = style["pitch"]
        label = ("%s/%s" % (who, voice)) if style else gender
        print("[%d/%d] 產生 (%s) %s" % (i, len(pairs), label, text))
        await edge_tts.Communicate(text, voice, **kwargs).save(dest)
        made += 1
    with open(os.path.join(AUDIO_DIR, "index.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    print("完成：新產生 %d、跳過 %d，共 %d 句 -> %s" % (made, skipped, len(index), AUDIO_DIR))


if __name__ == "__main__":
    asyncio.run(main())
