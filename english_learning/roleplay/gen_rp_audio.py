#!/usr/bin/env python3
"""Batch-TTS for Role Play scenarios (spec §10, §14).

Reuses the SAME audio scheme as gen_audio.py: every NPC line becomes
audio/<sha1("<gender>|<text>")>.mp3 and is registered in audio/index.json, so
the browser's RP.tts (and the main app) find clips by (gender, text) with zero
per-node bookkeeping. Merges into the shared ../audio/index.json — it never
clobbers the lesson audio already there.

Install:  pip install edge-tts
Run:      python roleplay/gen_rp_audio.py            (skips clips that exist)
          python roleplay/gen_rp_audio.py --force    (regenerate everything)

It voices, for every node in every scenario:
  - npc.text
  - fallback.partial.message / fallback.off_topic.message   (the waiter's nudges)
  - each route's `hint`                                      (spoken on PARTIAL)
"""
import os
import sys
import json
import glob
import hashlib
import asyncio

import edge_tts

HERE = os.path.dirname(os.path.abspath(__file__))
AUDIO_DIR = os.path.join(HERE, "..", "audio")
SCEN_DIR = os.path.join(HERE, "scenarios")
VOICES = {"male": "en-US-GuyNeural", "female": "en-US-JennyNeural"}


def key_of(gender, text):
    return "%s|%s" % (gender, text)


def file_of(gender, text):
    h = hashlib.sha1(key_of(gender, text).encode("utf-8")).hexdigest()[:12]
    return h + ".mp3"


def collect_pairs():
    """Return ordered unique (gender, text) for every spoken NPC line."""
    pairs, seen = [], set()

    def add(text, gender):
        text = (text or "").strip()
        if not text:
            return
        gender = gender or "female"
        if (gender, text) in seen:
            return
        seen.add((gender, text))
        pairs.append((gender, text))

    for path in sorted(glob.glob(os.path.join(SCEN_DIR, "*.json"))):
        with open(path, encoding="utf-8") as f:
            g = json.load(f)
        default_gender = g.get("npc_gender", "female")
        for node in g.get("nodes", []):
            npc = node.get("npc") or {}
            add(npc.get("text"), npc.get("gender", default_gender))
            fb = node.get("fallback") or {}
            for key in ("partial", "off_topic"):
                msg = (fb.get(key) or {}).get("message")
                add(msg, default_gender)
            for route in node.get("routes") or []:
                add(route.get("hint"), default_gender)
    return pairs


async def main():
    force = "--force" in sys.argv
    os.makedirs(AUDIO_DIR, exist_ok=True)
    index_path = os.path.join(AUDIO_DIR, "index.json")
    index = {}
    if os.path.exists(index_path):
        with open(index_path, encoding="utf-8") as f:
            index = json.load(f)   # merge into the existing lesson-audio map

    pairs = collect_pairs()
    made = skipped = 0
    for i, (gender, text) in enumerate(pairs, 1):
        fname = file_of(gender, text)
        index[key_of(gender, text)] = fname
        dest = os.path.join(AUDIO_DIR, fname)
        if os.path.exists(dest) and not force:
            skipped += 1
            continue
        voice = VOICES.get(gender, VOICES["female"])
        print("[%d/%d] (%s) %s" % (i, len(pairs), gender, text))
        await edge_tts.Communicate(text, voice).save(dest)
        made += 1

    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    print("Done: %d generated, %d skipped, %d role-play lines -> %s"
          % (made, skipped, len(pairs), AUDIO_DIR))


if __name__ == "__main__":
    asyncio.run(main())
