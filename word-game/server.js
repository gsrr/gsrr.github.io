const express = require("express");
const cors = require("cors");
const path = require("path");
const fs = require("fs");
const sharp = require("sharp");

const app = express();
app.use(cors());

// ---- 靜態檔案 ----
const publicDir = path.join(__dirname, "public");
app.use(express.static(publicDir));

// ---- 瀏覽人數計算 ----
const visitorsFile = path.join(__dirname, "visitors.json");
let visitors = 0;
if (fs.existsSync(visitorsFile)) {
  try {
    const data = JSON.parse(fs.readFileSync(visitorsFile, "utf-8"));
    visitors = data.visitors || 0;
  } catch (err) {
    console.error("Error reading visitors.json:", err);
  }
}
app.get("/api/visit", (req, res) => {
  visitors++;
  fs.writeFile(visitorsFile, JSON.stringify({ visitors }), "utf-8", err => {
    if (err) console.error("Error writing visitors.json:", err);
  });
  res.json({ visitors });
});
app.get("/api/visitors", (req, res) => {
  res.json({ visitors });
});

// ---- 工具: 圖片轉 Base64 ----
function imgToBase64(filePath) {
  return sharp(filePath)
    .resize({ width: 400, height: 400, fit: "inside", withoutEnlargement: true })
    .webp({ quality: 80 })
    .toBuffer()
    .then(buf => `data:image/webp;base64,${buf.toString("base64")}`);
}

// ---- API: stories + 最後更新時間 ----
app.get("/api/stories", (req, res) => {
  const baseDir = "./images";
  if (!fs.existsSync(baseDir)) return res.json({ stories: [] });

  const dirs = fs.readdirSync(baseDir, { withFileTypes: true })
    .filter(d => d.isDirectory())
    .map(d => {
      const dirPath = path.join(baseDir, d.name);
      const files = fs.readdirSync(dirPath).map(f => path.join(dirPath, f));
      let latest = 0;
      files.forEach(f => {
        const stat = fs.statSync(f);
        if (stat.mtimeMs > latest) latest = stat.mtimeMs;
      });
      return { name: d.name, updated: latest };
    });

  // 依照更新時間排序 (最新在前)
  dirs.sort((a, b) => b.updated - a.updated);

  res.json({ stories: dirs });
});

// ---- API: questions ----
app.get("/api/questions/:story", async (req, res) => {
  const story = req.params.story;
  const dir = path.join(__dirname, "images", story);
  if (!fs.existsSync(dir)) return res.status(404).json({ error: "Story not found" });

  const files = fs.readdirSync(dir).filter(f => f.endsWith(".png"));

  function shuffle(array) {
    for (let i = array.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [array[i], array[j]] = [array[j], array[i]];
    }
    return array;
  }

  const QUESTION_LIMIT = 10;
  const shuffled = shuffle([...files]).slice(0, QUESTION_LIMIT);

  try {
    const questions = await Promise.all(
      shuffled.map(async img => {
        const answer = path.basename(img, ".png");
        const others = shuffle(files.filter(f => f !== img)).slice(0, 3);

        // Base64
        const imgBase64 = await imgToBase64(path.join(dir, img));
        const otherBase64 = await Promise.all(
          others.map(f => imgToBase64(path.join(dir, f)))
        );

        // Phase1: 圖片題目 + 文字選項
        const q1 = {
          img: imgBase64,
          answer,
          options: shuffle([answer, ...others.map(f => path.basename(f, ".png"))])
        };

        // Phase2: 文字題目 + 圖片選項
        const options2 = shuffle([imgBase64, ...otherBase64]);
        const q2 = { word: answer, answer: imgBase64, options: options2 };

        return { phase1: q1, phase2: q2 };
      })
    );
    res.json({ questions });
  } catch (err) {
    console.error("Error generating questions:", err);
    res.status(500).json({ error: "Image processing failed" });
  }
});

// ---- 頁面 ----
app.get("/", (req, res) => res.sendFile(path.join(publicDir, "index.html")));
app.get("/test.html", (req, res) => res.sendFile(path.join(publicDir, "test.html")));

const PORT = process.env.PORT || 3000;
app.listen(PORT, "0.0.0.0", () =>
  console.log(`Server running on http://0.0.0.0:${PORT}`)
);

