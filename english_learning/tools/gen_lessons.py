#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批次產生課程：對話檔、<file>.json 內容、scenes/*.svg、更新 lessons.json manifest。
   角色用「同一套小孩圖換色」：boy/girl 兩種骨架 + 每個角色一組顏色。
   從 english_learning/ 目錄執行：  python tools/gen_lessons.py
"""
import json, os

# ---------- 角色骨架（沿用 Tom/Anna 的 SVG，顏色抽成參數） ----------
BOY_BODY = """<ellipse cx="20" cy="80" rx="15" ry="3" fill="#000" opacity="0.10"/>
          <rect x="13" y="60" width="6" height="14" rx="3" fill="#ffe0bd"/><rect x="21" y="60" width="6" height="14" rx="3" fill="#ffe0bd"/>
          <rect x="10" y="73" width="11" height="6" rx="3" fill="{shoe}"/><rect x="19" y="73" width="11" height="6" rx="3" fill="{shoe}"/>
          <rect x="9" y="50" width="22" height="12" rx="4" fill="{shorts}"/><rect x="19.3" y="52" width="1.4" height="9" fill="{shorts_dk}"/>
          <rect x="7" y="28" width="26" height="24" rx="9" fill="{shirt}"/><rect x="7" y="39" width="26" height="3.5" fill="#fff" opacity="0.7"/>
          <rect x="2" y="29" width="8" height="11" rx="4" fill="{shirt}"/><rect x="1.5" y="37" width="6" height="11" rx="3" fill="#ffe0bd" transform="rotate(8 4 42)"/><circle cx="4" cy="49" r="3.3" fill="#ffe0bd"/>
          <rect x="30" y="29" width="8" height="11" rx="4" fill="{shirt}"/><rect x="32.5" y="37" width="6" height="11" rx="3" fill="#ffe0bd" transform="rotate(-8 36 42)"/><circle cx="36" cy="49" r="3.3" fill="#ffe0bd"/>
          <rect x="16.5" y="24" width="7" height="6" fill="#ffe0bd"/>
          <circle cx="20" cy="13" r="13" fill="{hair}"/><circle cx="20" cy="15" r="12" fill="#ffe0bd"/>
          <ellipse cx="7.7" cy="15" rx="2" ry="3" fill="#ffe0bd"/><ellipse cx="32.3" cy="15" rx="2" ry="3" fill="#ffe0bd"/>
          <path d="M8,12 Q20,2 32,12 Q20,8 8,12 Z" fill="{hair}"/>
          <circle cx="11" cy="19" r="2.5" fill="#fca5a5" opacity="0.55"/><circle cx="29" cy="19" r="2.5" fill="#fca5a5" opacity="0.55"/>
          <ellipse cx="14" cy="15" rx="2.2" ry="2.8" fill="#fff"/><circle cx="14.4" cy="15.4" r="1.4" fill="#3b2415"/>
          <ellipse cx="26" cy="15" rx="2.2" ry="2.8" fill="#fff"/><circle cx="25.6" cy="15.4" r="1.4" fill="#3b2415"/>
          <path d="M15,21 Q20,25 25,21" stroke="#b5503a" stroke-width="1.6" fill="none" stroke-linecap="round"/>"""

GIRL_BODY = """<ellipse cx="20" cy="80" rx="15" ry="3" fill="#000" opacity="0.10"/>
          <path d="M4,16 Q1,44 7,58 L33,58 Q39,44 36,16 Z" fill="{hair}"/>
          <rect x="13" y="58" width="6" height="14" rx="3" fill="#ffe0bd"/><rect x="21" y="58" width="6" height="14" rx="3" fill="#ffe0bd"/>
          <rect x="10" y="72" width="11" height="6" rx="3" fill="{shoe}"/><rect x="19" y="72" width="11" height="6" rx="3" fill="{shoe}"/>
          <path d="M9,30 Q5,48 2,60 L38,60 Q35,48 31,30 Z" fill="{dress}"/><rect x="9" y="30" width="22" height="7" rx="3" fill="{dress_dk}" opacity="0.45"/>
          <rect x="2" y="31" width="8" height="10" rx="4" fill="{dress}"/><rect x="1.5" y="38" width="6" height="11" rx="3" fill="#ffe0bd" transform="rotate(8 4 43)"/><circle cx="4" cy="50" r="3.3" fill="#ffe0bd"/>
          <rect x="30" y="31" width="8" height="10" rx="4" fill="{dress}"/><rect x="32.5" y="38" width="6" height="11" rx="3" fill="#ffe0bd" transform="rotate(-8 36 43)"/><circle cx="36" cy="50" r="3.3" fill="#ffe0bd"/>
          <rect x="16.5" y="24" width="7" height="6" fill="#ffe0bd"/>
          <ellipse cx="4" cy="27" rx="5" ry="10" fill="{hair}"/><ellipse cx="36" cy="27" rx="5" ry="10" fill="{hair}"/>
          <circle cx="5" cy="18" r="2" fill="{bow}"/><circle cx="35" cy="18" r="2" fill="{bow}"/>
          <circle cx="20" cy="13" r="13" fill="{hair}"/><circle cx="20" cy="15" r="12" fill="#ffe0bd"/>
          <ellipse cx="7.7" cy="15" rx="2" ry="3" fill="#ffe0bd"/><ellipse cx="32.3" cy="15" rx="2" ry="3" fill="#ffe0bd"/>
          <path d="M7,12 Q20,1 33,12 Q20,7 7,12 Z" fill="{hair}"/>
          <path d="M20,5 L13,2 L13,8 Z" fill="{bow}"/><path d="M20,5 L27,2 L27,8 Z" fill="{bow}"/><circle cx="20" cy="5" r="2.2" fill="{bow_dk}"/>
          <circle cx="11" cy="19" r="2.5" fill="#fca5a5" opacity="0.6"/><circle cx="29" cy="19" r="2.5" fill="#fca5a5" opacity="0.6"/>
          <ellipse cx="14" cy="15" rx="2.2" ry="2.9" fill="#fff"/><circle cx="14.4" cy="15.4" r="1.5" fill="#3b2415"/>
          <ellipse cx="26" cy="15" rx="2.2" ry="2.9" fill="#fff"/><circle cx="25.6" cy="15.4" r="1.5" fill="#3b2415"/>
          <path d="M15,21 Q20,25 25,21" stroke="#b5503a" stroke-width="1.6" fill="none" stroke-linecap="round"/>"""

CHARS = {
  "Tom":  {"sex":"male",  "kind":"boy",  "shirt":"#2563eb","shorts":"#1e3a8a","shorts_dk":"#172554","shoe":"#ef4444","hair":"#5b3a1f","bub":"#2563eb"},
  "Anna": {"sex":"female","kind":"girl", "dress":"#db2777","dress_dk":"#be185d","shoe":"#be185d","hair":"#6b4423","bow":"#f472b6","bow_dk":"#ec4899","bub":"#db2777"},
  "Ben":  {"sex":"male",  "kind":"boy",  "shirt":"#16a34a","shorts":"#14532d","shorts_dk":"#052e16","shoe":"#f59e0b","hair":"#1f2937","bub":"#15803d"},
  "Lily": {"sex":"female","kind":"girl", "dress":"#9333ea","dress_dk":"#6b21a8","shoe":"#6b21a8","hair":"#4b2e1a","bow":"#fbbf24","bow_dk":"#f59e0b","bub":"#9333ea"},
  "Sam":  {"sex":"male",  "kind":"boy",  "shirt":"#f97316","shorts":"#9a3412","shorts_dk":"#7c2d12","shoe":"#1e3a8a","hair":"#7c4a1e","bub":"#ea580c"},
  "Mia":  {"sex":"female","kind":"girl", "dress":"#0d9488","dress_dk":"#0f766e","shoe":"#0f766e","hair":"#2b1a0f","bow":"#f43f5e","bow_dk":"#e11d48","bub":"#0d9488"},
  "Leo":  {"sex":"male",  "kind":"boy",  "shirt":"#dc2626","shorts":"#7f1d1d","shorts_dk":"#450a0a","shoe":"#1f2937","hair":"#3b2415","bub":"#dc2626"},
  "Emma": {"sex":"female","kind":"girl", "dress":"#f59e0b","dress_dk":"#b45309","shoe":"#b45309","hair":"#6b4423","bow":"#ec4899","bow_dk":"#db2777","bub":"#d97706"},
}

def bw(text):
    return max(40, int(len(text) * 6.6) + 18)

def bubble(side, text, color):
    W = bw(text)
    if side == "L":
        tail = "M34,-3 L30,5 L42,-2 Z"; rx = 26; tx = round(26 + W / 2, 1); cls = "talkA"
    else:
        tail = "M6,-3 L10,5 L-2,-2 Z"; rx = round(16 - W, 1); tx = round(16 - W / 2, 1); cls = "talkB"
    return ('<g class="%s"><path d="%s" fill="#fff" stroke="%s" stroke-width="1.5"/>'
            '<rect x="%s" y="-24" width="%s" height="22" rx="11" fill="#fff" stroke="%s" stroke-width="1.5"/>'
            '<text x="%s" y="-9" font-size="11" font-weight="700" fill="%s" text-anchor="middle">%s</text></g>'
            % (cls, tail, color, rx, W, color, tx, color, text))

def figure(name, side, text):
    c = CHARS[name]
    body = BOY_BODY.format(**c) if c["kind"] == "boy" else GIRL_BODY.format(**c)
    x = 60 if side == "L" else 258
    cls = "bob-a" if side == "L" else "bob-b"
    return ('<g transform="translate(%d,55)"><g class="%s">\n          %s\n          %s\n        </g></g>'
            % (x, cls, bubble(side, text, c["bub"]), body))

def prop(emoji, x, y, size, jump=False):
    inner = '<text x="0" y="0" font-size="%d" text-anchor="middle">%s</text>' % (size, emoji)
    if jump:
        inner = '<g class="jump-a">%s</g>' % inner
    return '<g transform="translate(%d,%d)">%s</g>' % (x, y, inner)

SUN = ('<g transform="translate(312,30)"><g class="rays"><g stroke="#fbbf24" stroke-width="3" stroke-linecap="round">'
       '<line x1="0" y1="-26" x2="0" y2="-20"/><line x1="0" y1="26" x2="0" y2="20"/><line x1="-26" y1="0" x2="-20" y2="0"/>'
       '<line x1="26" y1="0" x2="20" y2="0"/><line x1="-18" y1="-18" x2="-14" y2="-14"/><line x1="18" y1="18" x2="14" y2="14"/>'
       '<line x1="-18" y1="18" x2="-14" y2="14"/><line x1="18" y1="-18" x2="14" y2="-14"/></g></g><circle r="15" fill="#fde047"/></g>')

def cloud(cx, cls="cloud1"):
    return ('<g class="%s" fill="#ffffff" opacity="0.9"><ellipse cx="%d" cy="32" rx="18" ry="10"/>'
            '<ellipse cx="%d" cy="34" rx="13" ry="8"/></g>' % (cls, cx, cx + 16))

def grey_cloud(cx, cls="cloud1"):
    return ('<g class="%s" fill="#cbd5e1" opacity="0.95"><ellipse cx="%d" cy="34" rx="20" ry="11"/>'
            '<ellipse cx="%d" cy="36" rx="14" ry="9"/></g>' % (cls, cx, cx + 18))

def moon(sky):
    return ('<g transform="translate(308,32)"><circle cx="0" cy="0" r="15" fill="#fef9c3"/>'
            '<circle cx="6" cy="-3" r="12" fill="%s"/></g>' % sky)

def stars(coords):
    return "".join('<circle cx="%d" cy="%d" r="%s" fill="#fde68a"/>' % (x, y, r) for x, y, r in coords)

RAIN = "".join('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#93c5fd" stroke-width="2" stroke-linecap="round" opacity="0.8"/>'
               % (x, y, x - 4, y + 9) for x, y in [(120,70),(150,90),(185,66),(215,95),(250,72),(95,100)])

def scene_svg(cfg):
    name = cfg["scene"]
    decor = cfg.get("decor", "")
    props = "".join(prop(*p) for p in cfg.get("props", []))
    g1, g2 = cfg.get("ground", ("#86efac", "#4ade80"))
    parts = [
      '<svg viewBox="0 0 360 170" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="%s">' % cfg["aria"],
      '<defs><linearGradient id="sky-%s" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="%s"/><stop offset="1" stop-color="%s"/></linearGradient></defs>' % (name, cfg["grad"][0], cfg["grad"][1]),
      '<rect x="0" y="0" width="360" height="170" fill="url(#sky-%s)"/>' % name,
      '<rect x="0" y="128" width="360" height="42" fill="%s"/>' % g1,
      '<rect x="0" y="128" width="360" height="6" fill="%s"/>' % g2,
      decor, props,
      figure(cfg["L"], "L", cfg["lbub"]),
      figure(cfg["R"], "R", cfg["rbub"]),
      '</svg>',
    ]
    return "\n        ".join(p for p in parts if p) + "\n"

SKY = ("#bae6fd", "#e0f2fe")

# ---------- 10 篇文章資料 ----------
ARTICLES = [
  {"id":"005","title":"005 · My Dog","scene":"dog-park","aria":"Ben shows Lily his dog Max",
   "grad":SKY,"decor":SUN+cloud(64),"L":"Ben","R":"Lily","lbub":"Dog!","rbub":"Wow!",
   "props":[("🐕",168,116,30,True),("⚽",40,142,22)],
   "dialogue":[("Ben","Look! I have a dog."),("Lily","Wow! What is its name?"),("Ben","Its name is Max."),
     ("Lily","Max is big. Can he run?"),("Ben","Yes, he can run fast."),("Lily","Can Max play with a ball?"),
     ("Ben","Yes! Max likes the ball."),("Lily","Max is a good dog."),("Ben","He is my best friend."),
     ("Lily","I want a dog, too.")],
   "content":{
     "quiz3":[{"q":"Ben has a dog.","answer":"Yes"},{"q":"The dog's name is Max.","answer":"Yes"},
       {"q":"Max can run fast.","answer":"Yes"},{"q":"Max likes the ball.","answer":"Yes"},
       {"q":"Lily wants a dog.","answer":"Yes"}],
     "quiz4":[{"q":"Lily has a dog.","answer":"No"},{"q":"Max is small.","answer":"No"},
       {"q":"Max can run fast.","answer":"Yes"},{"q":"Ben does not like Max.","answer":"No"},
       {"q":"Max is a good dog.","answer":"Yes"}],
     "vocab":[{"word":"Ben","pic":"👦"},{"word":"Lily","pic":"👧"},{"word":"dog","pic":"🐕"},
       {"word":"ball","pic":"⚽"},{"word":"run","pic":"🏃"},{"word":"friend","pic":"🤝"}],
     "wh":[{"q":"Who has a dog?","a":"Ben has a dog.","wrong":["Lily has a dog.","Mom has a dog."]},
       {"q":"What is the dog's name?","a":"Its name is Max.","wrong":["Its name is Coco.","Its name is Milo."]},
       {"q":"What can Max do?","a":"He can run fast.","wrong":["He can swim fast.","He can fly."]},
       {"q":"What does Max like?","a":"Max likes the ball.","wrong":["Max likes the book.","Max likes the car."]},
       {"q":"Who wants a dog?","a":"Lily wants a dog.","wrong":["Ben wants a dog.","Dad wants a dog."]}],
     "clozeType":"recognition",
     "cloze":[{"text":"Look! I have a ___.","answer":"dog","wrong":["run","fast"]},
       {"text":"Its ___ is Max.","answer":"name","wrong":["play","big"]},
       {"text":"Max can run ___.","answer":"fast","wrong":["dog","ball"]},
       {"text":"Max likes the ___.","answer":"ball","wrong":["run","fast"]}]}},

  {"id":"006","title":"006 · Balloons","scene":"balloons","aria":"Sam and Mia with colorful balloons",
   "grad":("#bfdbfe","#eff6ff"),"decor":SUN+cloud(70),"L":"Sam","R":"Mia","lbub":"Red!","rbub":"Blue!",
   "props":[("🎈",150,66,26),("🎈",182,52,28),("🎈",212,68,24)],
   "dialogue":[("Sam","Look at my balloons!"),("Mia","Wow! How many balloons?"),("Sam","I have three balloons."),
     ("Mia","I like the red balloon."),("Sam","I like the blue one."),("Mia","Look! The green balloon is big."),
     ("Sam","Can I have one?"),("Mia","Yes, you can. Here you are."),("Sam","Thank you! Red is my favorite."),
     ("Mia","Balloons are fun!")],
   "content":{
     "quiz3":[{"q":"Sam has balloons.","answer":"Yes"},{"q":"Sam has three balloons.","answer":"Yes"},
       {"q":"Mia likes the red balloon.","answer":"Yes"},{"q":"The green balloon is big.","answer":"Yes"},
       {"q":"Balloons are fun.","answer":"Yes"}],
     "quiz4":[{"q":"Mia has the balloons.","answer":"No"},{"q":"Sam has two balloons.","answer":"No"},
       {"q":"Sam likes the blue balloon.","answer":"Yes"},{"q":"The green balloon is little.","answer":"No"},
       {"q":"Mia likes the red balloon.","answer":"Yes"}],
     "vocab":[{"word":"Sam","pic":"👦"},{"word":"Mia","pic":"👧"},{"word":"balloon","pic":"🎈"},
       {"word":"red","pic":"🔴"},{"word":"blue","pic":"🔵"},{"word":"green","pic":"🟢"}],
     "wh":[{"q":"Who has balloons?","a":"Sam has balloons.","wrong":["Mia has balloons.","Dad has balloons."]},
       {"q":"How many balloons?","a":"He has three balloons.","wrong":["He has two balloons.","He has five balloons."]},
       {"q":"What color does Mia like?","a":"She likes red.","wrong":["She likes black.","She likes white."]},
       {"q":"What color does Sam like?","a":"He likes blue.","wrong":["He likes green.","He likes pink."]},
       {"q":"What is big?","a":"The green balloon is big.","wrong":["The red balloon is big.","The blue balloon is big."]}],
     "clozeType":"recognition",
     "cloze":[{"text":"I have three ___.","answer":"balloons","wrong":["red","fun"]},
       {"text":"I like the ___ balloon.","answer":"red","wrong":["have","big"]},
       {"text":"The green balloon is ___.","answer":"big","wrong":["red","balloon"]},
       {"text":"Balloons are ___.","answer":"fun","wrong":["red","three"]}]}},

  {"id":"007","title":"007 · My Family","scene":"family","aria":"Tom and Anna talking about their families",
   "grad":("#fed7aa","#fff7ed"),"decor":SUN+cloud(70),"L":"Tom","R":"Anna","lbub":"Family!","rbub":"Love!",
   "props":[("👩",40,150,26),("👨",90,150,26),("👶",330,152,22)],
   "dialogue":[("Tom","This is my family."),("Anna","Who is this?"),("Tom","This is my mom and my dad."),
     ("Anna","Is this your baby sister?"),("Tom","Yes, she is small."),("Anna","I have a big brother."),
     ("Tom","Do you have a pet?"),("Anna","Yes, I have a cat."),("Tom","I love my family."),("Anna","Me too!")],
   "content":{
     "quiz3":[{"q":"Tom has a family.","answer":"Yes"},{"q":"Tom has a baby sister.","answer":"Yes"},
       {"q":"The baby is small.","answer":"Yes"},{"q":"Anna has a big brother.","answer":"Yes"},
       {"q":"Anna has a cat.","answer":"Yes"}],
     "quiz4":[{"q":"Anna has a baby sister.","answer":"No"},{"q":"The baby is big.","answer":"No"},
       {"q":"Tom has a big brother.","answer":"No"},{"q":"Anna has a cat.","answer":"Yes"},
       {"q":"Tom loves his family.","answer":"Yes"}],
     "vocab":[{"word":"Tom","pic":"👦"},{"word":"Anna","pic":"👧"},{"word":"mom","pic":"👩"},
       {"word":"dad","pic":"👨"},{"word":"baby","pic":"👶"},{"word":"cat","pic":"🐈"}],
     "wh":[{"q":"Who is in Tom's family?","a":"His mom and dad.","wrong":["His teacher.","His friends."]},
       {"q":"Is the baby big or small?","a":"The baby is small.","wrong":["The baby is big.","The baby is tall."]},
       {"q":"Who has a big brother?","a":"Anna has a big brother.","wrong":["Tom has a big brother.","Mom has a big brother."]},
       {"q":"What pet does Anna have?","a":"She has a cat.","wrong":["She has a dog.","She has a fish."]},
       {"q":"Who loves his family?","a":"Tom loves his family.","wrong":["Anna loves the cat.","Dad loves the baby."]}],
     "clozeType":"recognition",
     "cloze":[{"text":"This is my mom and my ___.","answer":"dad","wrong":["small","love"]},
       {"text":"The baby is ___.","answer":"small","wrong":["mom","cat"]},
       {"text":"I have a ___ sister.","answer":"baby","wrong":["love","cat"]},
       {"text":"I love my ___.","answer":"family","wrong":["small","baby"]}]}},

  {"id":"008","title":"008 · Breakfast Time","scene":"breakfast","aria":"Emma and Leo eating breakfast",
   "grad":("#fef3c7","#fffbeb"),"ground":("#d6a87c","#b8855c"),"decor":SUN+cloud(68),"L":"Emma","R":"Leo","lbub":"Yum!","rbub":"Eggs!",
   "props":[("🍳",40,140,24),("🍞",168,120,26),("🥛",330,138,24)],
   "dialogue":[("Emma","I am hungry. It is breakfast time."),("Leo","What do you eat?"),("Emma","I eat eggs and bread."),
     ("Leo","I drink milk every day."),("Emma","Milk is good for you."),("Leo","Do you like eggs?"),
     ("Emma","Yes, I like eggs."),("Leo","Let us eat breakfast."),("Emma","Yum! This is good."),("Leo","I am happy now.")],
   "content":{
     "quiz3":[{"q":"Emma is hungry.","answer":"Yes"},{"q":"Emma eats eggs and bread.","answer":"Yes"},
       {"q":"Leo drinks milk.","answer":"Yes"},{"q":"Emma likes eggs.","answer":"Yes"},
       {"q":"Leo is happy.","answer":"Yes"}],
     "quiz4":[{"q":"Leo is hungry.","answer":"No"},{"q":"Emma eats cake.","answer":"No"},
       {"q":"Leo drinks water.","answer":"No"},{"q":"Emma likes eggs.","answer":"Yes"},
       {"q":"It is breakfast time.","answer":"Yes"}],
     "vocab":[{"word":"Emma","pic":"👧"},{"word":"Leo","pic":"👦"},{"word":"egg","pic":"🍳"},
       {"word":"bread","pic":"🍞"},{"word":"milk","pic":"🥛"},{"word":"eat","pic":"🍽️"}],
     "wh":[{"q":"Who is hungry?","a":"Emma is hungry.","wrong":["Leo is hungry.","Dad is hungry."]},
       {"q":"What does Emma eat?","a":"She eats eggs and bread.","wrong":["She eats rice.","She eats cake."]},
       {"q":"What does Leo drink?","a":"He drinks milk.","wrong":["He drinks juice.","He drinks tea."]},
       {"q":"Does Emma like eggs?","a":"Yes, she likes eggs.","wrong":["No, she does not.","She likes cake."]},
       {"q":"When is it?","a":"It is breakfast time.","wrong":["It is night.","It is bedtime."]}],
     "clozeType":"recognition",
     "cloze":[{"text":"I eat eggs and ___.","answer":"bread","wrong":["eat","good"]},
       {"text":"I drink ___ every day.","answer":"milk","wrong":["eat","hungry"]},
       {"text":"Do you like ___?","answer":"eggs","wrong":["good","hungry"]},
       {"text":"Let us eat ___.","answer":"breakfast","wrong":["milk","egg"]}]}},

  {"id":"009","title":"009 · At the Beach","scene":"beach","aria":"Mia and Ben playing at the beach",
   "grad":("#7dd3fc","#e0f2fe"),"ground":("#fde68a","#fcd34d"),"decor":SUN+cloud(70),"L":"Mia","R":"Ben","lbub":"Sea!","rbub":"Sand!",
   "props":[("⛵",168,116,26,True),("🐚",44,150,20),("🌴",322,118,32)],
   "dialogue":[("Mia","Look at the sea!"),("Ben","The sea is blue and big."),("Mia","I can see a boat."),
     ("Ben","Let us play in the sand."),("Mia","I have a little shell."),("Ben","The shell is pretty."),
     ("Mia","Can you swim?"),("Ben","Yes, I can swim."),("Mia","The beach is fun!"),("Ben","I like the beach.")],
   "content":{
     "quiz3":[{"q":"They are at the beach.","answer":"Yes"},{"q":"The sea is big.","answer":"Yes"},
       {"q":"Mia has a shell.","answer":"Yes"},{"q":"Ben can swim.","answer":"Yes"},
       {"q":"The beach is fun.","answer":"Yes"}],
     "quiz4":[{"q":"The sea is little.","answer":"No"},{"q":"Ben has the shell.","answer":"No"},
       {"q":"They play in the snow.","answer":"No"},{"q":"Ben can swim.","answer":"Yes"},
       {"q":"They are at the beach.","answer":"Yes"}],
     "vocab":[{"word":"Mia","pic":"👧"},{"word":"Ben","pic":"👦"},{"word":"sea","pic":"🌊"},
       {"word":"sand","pic":"🏖️"},{"word":"shell","pic":"🐚"},{"word":"boat","pic":"⛵"},{"word":"swim","pic":"🏊"}],
     "wh":[{"q":"Where are they?","a":"They are at the beach.","wrong":["They are at home.","They are at school."]},
       {"q":"What color is the sea?","a":"The sea is blue.","wrong":["The sea is red.","The sea is green."]},
       {"q":"What does Mia have?","a":"She has a shell.","wrong":["She has a ball.","She has a book."]},
       {"q":"Can Ben swim?","a":"Yes, he can swim.","wrong":["No, he can not.","He can run."]},
       {"q":"What can Mia see?","a":"She can see a boat.","wrong":["She can see a car.","She can see a bird."]}],
     "clozeType":"recognition",
     "cloze":[{"text":"Look at the ___!","answer":"sea","wrong":["big","blue"]},
       {"text":"Let us play in the ___.","answer":"sand","wrong":["swim","sea"]},
       {"text":"I have a little ___.","answer":"shell","wrong":["swim","big"]},
       {"text":"I can ___.","answer":"swim","wrong":["sea","sand"]}]}},

  {"id":"010","title":"010 · My Toys","scene":"toys","aria":"Sam and Lily playing with toys",
   "grad":("#ede9fe","#f5f3ff"),"ground":("#c4b5fd","#a78bfa"),"decor":SUN+cloud(70),"L":"Sam","R":"Lily","lbub":"Toys!","rbub":"Car!",
   "props":[("🚗",44,148,24),("🧸",168,118,26,True),("🤖",320,144,26)],
   "dialogue":[("Sam","Look at my toys!"),("Lily","Wow! You have many toys."),("Sam","This is my red car."),
     ("Lily","I like your toy car."),("Sam","This is my robot, too."),("Lily","I have a doll at home."),
     ("Sam","Can we play together?"),("Lily","Yes! Let us play."),("Sam","Toys are fun."),("Lily","I like toys!")],
   "content":{
     "quiz3":[{"q":"Sam has many toys.","answer":"Yes"},{"q":"Sam has a red car.","answer":"Yes"},
       {"q":"Sam has a robot.","answer":"Yes"},{"q":"Lily has a doll.","answer":"Yes"},
       {"q":"Toys are fun.","answer":"Yes"}],
     "quiz4":[{"q":"Lily has many toys.","answer":"No"},{"q":"Sam's car is blue.","answer":"No"},
       {"q":"Lily has a doll.","answer":"Yes"},{"q":"They will play together.","answer":"Yes"},
       {"q":"Sam has a robot.","answer":"Yes"}],
     "vocab":[{"word":"Sam","pic":"👦"},{"word":"Lily","pic":"👧"},{"word":"car","pic":"🚗"},
       {"word":"robot","pic":"🤖"},{"word":"doll","pic":"🪆"},{"word":"toy","pic":"🧸"}],
     "wh":[{"q":"Who has many toys?","a":"Sam has many toys.","wrong":["Lily has many toys.","Mom has many toys."]},
       {"q":"What color is the car?","a":"The car is red.","wrong":["The car is blue.","The car is green."]},
       {"q":"What does Lily have?","a":"She has a doll.","wrong":["She has a car.","She has a robot."]},
       {"q":"What do they want to do?","a":"They want to play together.","wrong":["They want to sleep.","They want to eat."]},
       {"q":"What is fun?","a":"Toys are fun.","wrong":["School is fun.","Beds are fun."]}],
     "clozeType":"recognition",
     "cloze":[{"text":"Look at my ___!","answer":"toys","wrong":["red","fun"]},
       {"text":"This is my red ___.","answer":"car","wrong":["play","fun"]},
       {"text":"I have a ___ at home.","answer":"doll","wrong":["play","fun"]},
       {"text":"Toys are ___.","answer":"fun","wrong":["car","toy"]}]}},

  {"id":"011","title":"011 · Rainy Day","scene":"rainy-day","aria":"Tom and Anna on a rainy day",
   "grad":("#94a3b8","#cbd5e1"),"decor":grey_cloud(110)+grey_cloud(240,"cloud2")+RAIN,"L":"Tom","R":"Anna","lbub":"Rain!","rbub":"Boots!",
   "props":[("☔",44,140,26),("💧",168,124,22,True)],
   "dialogue":[("Tom","Look! It is raining."),("Anna","Yes, the sky is grey."),("Tom","I have my umbrella."),
     ("Anna","I have my boots, too."),("Tom","We can jump in the water."),("Anna","Splash! This is fun."),
     ("Tom","Look at the big puddle!"),("Anna","I like rainy days."),("Tom","Let us go home now."),("Anna","Okay! I am wet.")],
   "content":{
     "quiz3":[{"q":"It is raining.","answer":"Yes"},{"q":"Tom has an umbrella.","answer":"Yes"},
       {"q":"Anna has boots.","answer":"Yes"},{"q":"Anna likes rainy days.","answer":"Yes"},
       {"q":"Anna is wet.","answer":"Yes"}],
     "quiz4":[{"q":"The sky is blue.","answer":"No"},{"q":"Anna has an umbrella.","answer":"No"},
       {"q":"It is a sunny day.","answer":"No"},{"q":"They jump in the water.","answer":"Yes"},
       {"q":"Anna likes rainy days.","answer":"Yes"}],
     "vocab":[{"word":"Tom","pic":"👦"},{"word":"Anna","pic":"👧"},{"word":"rain","pic":"🌧️"},
       {"word":"umbrella","pic":"☔"},{"word":"boots","pic":"🥾"},{"word":"jump","pic":"🦘"}],
     "wh":[{"q":"What is the weather?","a":"It is raining.","wrong":["It is sunny.","It is snowing."]},
       {"q":"What color is the sky?","a":"The sky is grey.","wrong":["The sky is blue.","The sky is red."]},
       {"q":"What does Tom have?","a":"He has an umbrella.","wrong":["He has a ball.","He has a book."]},
       {"q":"What does Anna have?","a":"She has boots.","wrong":["She has a hat.","She has a bag."]},
       {"q":"What do they do?","a":"They jump in the water.","wrong":["They sit at home.","They climb a tree."]}],
     "clozeType":"recognition",
     "cloze":[{"text":"Look! It is ___.","answer":"raining","wrong":["wet","grey"]},
       {"text":"I have my ___.","answer":"umbrella","wrong":["rain","wet"]},
       {"text":"I have my ___, too.","answer":"boots","wrong":["jump","wet"]},
       {"text":"I like ___ days.","answer":"rainy","wrong":["boots","water"]}]}},

  {"id":"012","title":"012 · Happy Birthday","scene":"birthday","aria":"Lily and Emma at a birthday party",
   "grad":("#fce7f3","#fdf2f8"),"decor":SUN+cloud(68),"L":"Lily","R":"Emma","lbub":"Cake!","rbub":"Yay!",
   "props":[("🎂",168,116,30,True),("🎁",44,145,24),("🎈",322,58,24)],
   "dialogue":[("Lily","Happy birthday, Emma!"),("Emma","Thank you, Lily!"),("Lily","Look at the big cake."),
     ("Emma","I see six candles."),("Lily","I have a gift for you."),("Emma","Wow! Thank you."),
     ("Lily","Let us sing a song."),("Emma","I am so happy."),("Lily","Make a wish, Emma!"),("Emma","This is the best day!")],
   "content":{
     "quiz3":[{"q":"It is Emma's birthday.","answer":"Yes"},{"q":"The cake is big.","answer":"Yes"},
       {"q":"There are six candles.","answer":"Yes"},{"q":"Lily has a gift.","answer":"Yes"},
       {"q":"Emma is happy.","answer":"Yes"}],
     "quiz4":[{"q":"It is Lily's birthday.","answer":"No"},{"q":"The cake is little.","answer":"No"},
       {"q":"Lily has a gift for Emma.","answer":"Yes"},{"q":"There are two candles.","answer":"No"},
       {"q":"Emma is sad.","answer":"No"}],
     "vocab":[{"word":"Lily","pic":"👧"},{"word":"Emma","pic":"👧"},{"word":"cake","pic":"🎂"},
       {"word":"candle","pic":"🕯️"},{"word":"gift","pic":"🎁"},{"word":"balloon","pic":"🎈"}],
     "wh":[{"q":"Whose birthday is it?","a":"It is Emma's birthday.","wrong":["It is Lily's birthday.","It is Tom's birthday."]},
       {"q":"How big is the cake?","a":"The cake is big.","wrong":["The cake is little.","The cake is old."]},
       {"q":"How many candles?","a":"There are six candles.","wrong":["There are two candles.","There are ten candles."]},
       {"q":"What does Lily have?","a":"She has a gift.","wrong":["She has a ball.","She has a book."]},
       {"q":"How does Emma feel?","a":"She is happy.","wrong":["She is sad.","She is angry."]}],
     "clozeType":"recognition",
     "cloze":[{"text":"Look at the big ___.","answer":"cake","wrong":["happy","sing"]},
       {"text":"I see six ___.","answer":"candles","wrong":["big","happy"]},
       {"text":"I have a ___ for you.","answer":"gift","wrong":["sing","happy"]},
       {"text":"I am so ___.","answer":"happy","wrong":["cake","gift"]}]}},

  {"id":"013","title":"013 · In the Garden","scene":"garden","aria":"Leo and Mia in a flower garden",
   "grad":SKY,"decor":SUN+cloud(66),"L":"Leo","R":"Mia","lbub":"Garden!","rbub":"Bee!",
   "props":[("🌷",44,150,24),("🌻",78,150,20),("🐝",158,82,18,True),("🌳",322,120,34)],
   "dialogue":[("Leo","Look at my garden."),("Mia","Wow! I see many flowers."),("Leo","This flower is red."),
     ("Mia","Look! A bee is on the flower."),("Leo","The bee is little."),("Mia","I can see a green tree."),
     ("Leo","Birds live in the tree."),("Mia","The garden is pretty."),("Leo","I water the flowers every day."),
     ("Mia","I like your garden!")],
   "content":{
     "quiz3":[{"q":"Leo has a garden.","answer":"Yes"},{"q":"There are many flowers.","answer":"Yes"},
       {"q":"A bee is on the flower.","answer":"Yes"},{"q":"There is a green tree.","answer":"Yes"},
       {"q":"Mia likes the garden.","answer":"Yes"}],
     "quiz4":[{"q":"Mia has a garden.","answer":"No"},{"q":"The bee is big.","answer":"No"},
       {"q":"The flower is red.","answer":"Yes"},{"q":"Birds live in the tree.","answer":"Yes"},
       {"q":"The garden is ugly.","answer":"No"}],
     "vocab":[{"word":"Leo","pic":"👦"},{"word":"Mia","pic":"👧"},{"word":"flower","pic":"🌷"},
       {"word":"bee","pic":"🐝"},{"word":"tree","pic":"🌳"},{"word":"bird","pic":"🐦"}],
     "wh":[{"q":"Who has a garden?","a":"Leo has a garden.","wrong":["Mia has a garden.","Dad has a garden."]},
       {"q":"What color is the flower?","a":"The flower is red.","wrong":["The flower is blue.","The flower is black."]},
       {"q":"What is on the flower?","a":"A bee is on the flower.","wrong":["A cat is on the flower.","A car is on the flower."]},
       {"q":"Where do birds live?","a":"Birds live in the tree.","wrong":["Birds live in the sea.","Birds live in the box."]},
       {"q":"How is the garden?","a":"The garden is pretty.","wrong":["The garden is ugly.","The garden is wet."]}],
     "clozeType":"recognition",
     "cloze":[{"text":"I see many ___.","answer":"flowers","wrong":["red","pretty"]},
       {"text":"This flower is ___.","answer":"red","wrong":["bee","tree"]},
       {"text":"A ___ is on the flower.","answer":"bee","wrong":["red","pretty"]},
       {"text":"I can see a green ___.","answer":"tree","wrong":["bee","red"]}]}},

  {"id":"014","title":"014 · Bedtime","scene":"bedtime","aria":"Ben and Anna at bedtime under the moon",
   "grad":("#1e293b","#334155"),"ground":("#1e293b","#0f172a"),
   "decor":moon("#1e293b")+stars([(60,40,1.8),(100,30,1.4),(150,48,1.6),(210,34,1.4),(280,52,1.8),(40,70,1.3)]),
   "L":"Ben","R":"Anna","lbub":"Night!","rbub":"Sleepy!",
   "props":[("🛏️",168,120,26),("⭐",320,46,20,True)],
   "dialogue":[("Ben","It is night. Look at the moon."),("Anna","I can see many stars."),("Ben","The moon is big and white."),
     ("Anna","I am sleepy now."),("Ben","It is time for bed."),("Anna","Good night, Ben."),("Ben","Good night, Anna."),
     ("Anna","I close my eyes."),("Ben","Sleep well!"),("Anna","See you in the morning.")],
   "content":{
     "quiz3":[{"q":"It is night.","answer":"Yes"},{"q":"The moon is big.","answer":"Yes"},
       {"q":"There are many stars.","answer":"Yes"},{"q":"Anna is sleepy.","answer":"Yes"},
       {"q":"It is time for bed.","answer":"Yes"}],
     "quiz4":[{"q":"It is morning.","answer":"No"},{"q":"The moon is little.","answer":"No"},
       {"q":"Anna is sleepy.","answer":"Yes"},{"q":"There are many stars.","answer":"Yes"},
       {"q":"Ben is hungry.","answer":"No"}],
     "vocab":[{"word":"Ben","pic":"👦"},{"word":"Anna","pic":"👧"},{"word":"moon","pic":"🌙"},
       {"word":"star","pic":"⭐"},{"word":"bed","pic":"🛏️"},{"word":"night","pic":"🌃"}],
     "wh":[{"q":"What time is it?","a":"It is night.","wrong":["It is morning.","It is noon."]},
       {"q":"What can Anna see?","a":"She can see many stars.","wrong":["She can see the sun.","She can see a boat."]},
       {"q":"What color is the moon?","a":"The moon is white.","wrong":["The moon is red.","The moon is green."]},
       {"q":"How does Anna feel?","a":"She is sleepy.","wrong":["She is hungry.","She is happy."]},
       {"q":"What is it time for?","a":"It is time for bed.","wrong":["It is time to play.","It is time to eat."]}],
     "clozeType":"recognition",
     "cloze":[{"text":"Look at the ___.","answer":"moon","wrong":["night","sleepy"]},
       {"text":"I can see many ___.","answer":"stars","wrong":["big","night"]},
       {"text":"I am ___ now.","answer":"sleepy","wrong":["moon","star"]},
       {"text":"It is time for ___.","answer":"bed","wrong":["moon","night"]}]}},
]

def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True) if os.path.dirname(path) else None
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)

def main():
    # 1) 對話檔、內容檔、場景檔
    for a in ARTICLES:
        file = "Pre-A1/" + a["id"]
        dialogue = "\n".join("%s: %s" % (who, txt) for who, txt in a["dialogue"])
        write(file, dialogue + "\n")
        write(file + ".json", json.dumps(a["content"], ensure_ascii=False, indent=2) + "\n")
        write("scenes/" + a["scene"] + ".svg", scene_svg(a))

    # 2) 更新 lessons.json：speakers + Pre-A1 manifest 條目
    m = json.load(open("lessons.json", encoding="utf-8"))
    for name, c in CHARS.items():
        m["speakers"].setdefault(name, c["sex"])
    pre = next(lv for lv in m["levels"] if lv["id"] == "Pre-A1")
    have = {x["id"] for x in pre["articles"]}
    for a in ARTICLES:
        if a["id"] in have:
            continue
        pre["articles"].append({"id": a["id"], "title": a["title"], "file": "Pre-A1/" + a["id"],
                                "scene": a["scene"], "levels": [1, 2, 3, 4, 5, 7, 9]})
    pre["articles"].sort(key=lambda x: x["id"])
    write("lessons.json", json.dumps(m, ensure_ascii=False, indent=2) + "\n")
    print("wrote", len(ARTICLES), "articles + scenes; speakers:", list(m["speakers"]))

if __name__ == "__main__":
    main()
