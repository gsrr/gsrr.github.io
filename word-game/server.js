const express = require("express");
const cors = require("cors");
const path = require("path");
const fs = require("fs");
const sharp = require("sharp");

const app = express();
app.use(cors());

// ---- 靜態檔案 ----
const publicDir = path.join(__dirname, "public");
app.use(express.static(publicDir)); // /public 底下的靜態檔案

// ---- 瀏覽人數計算 ----
const visitorsFile = path.join(__dirname, "visitors.json");

// 初始化
let visitors = 0;
if (fs.existsSync(visitorsFile)) {
  try {
    const data = JSON.parse(fs.readFileSync(visitorsFile, "utf-8"));
    visitors = data.visitors || 0;
  } catch (err) {
    console.error("Error reading visitors.json:", err);
  }
}

// API: 計算瀏覽人數 (+1)
app.get("/api/visit", (req, res) => {
  visitors++;
  fs.writeFileSync(visitorsFile, JSON.stringify({ visitors }), "utf-8");
  res.json({ visitors });
});

// API: 取得目前人數 (不+1)
app.get("/api/visitors", (req, res) => {
  res.json({ visitors });
});

// ---- 遊戲 API ----

// API: 列出所有 stories
app.get("/api/stories", (req, res) => {
  const baseDir = "./images";
  if (!fs.existsSync(baseDir)) {
    return res.json({ stories: [] });
  }

  const dirs = fs.readdirSync(baseDir, { withFileTypes: true })
                .filter(d => d.isDirectory())
                .map(d => d.name);
  res.json({ stories: dirs });
});

// API: 取得某個 story 的題目
app.get("/api/questions/:story", (req, res) => {
  const story = req.params.story;
  const dir = path.join(__dirname, "images", story);

  if (!fs.existsSync(dir)) {
    return res.status(404).json({ error: "Story not found" });
  }

  const files = fs.readdirSync(dir).filter(f => f.endsWith(".png"));

  // shuffle function
  function shuffle(array) {
    for (let i = array.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [array[i], array[j]] = [array[j], array[i]];
    }
    return array;
  }

  const QUESTION_LIMIT = 10;
  const shuffled = shuffle([...files]).slice(0, QUESTION_LIMIT);

  const questions = shuffled.map(img => {
    const answer = img.replace(".png", "");
    const others = shuffle(files.filter(f => f !== img)).slice(0, 3);
    const options = shuffle([answer, ...others.map(f => f.replace(".png", ""))]);
    return { img: `/api/image/${story}/${img}`, answer, options };
  });

  res.json({ questions });
});

// API: 動態壓縮圖片 (輸出 webp)
app.get("/api/image/:story/:file", async (req, res) => {
  const { story, file } = req.params;
  const filePath = path.join(__dirname, "images", story, file);

  if (!fs.existsSync(filePath)) {
    return res.status(404).json({ error: "Image not found" });
  }

  try {
    res.type("image/webp");
    sharp(filePath)
      .resize(400, 400, { fit: "inside" })
      .webp({ quality: 80 })
      .pipe(res);
  } catch (err) {
    console.error("Image processing error:", err);
    res.sendStatus(500);
  }
});

// ---- 頁面路由 ----

// 首頁 → story 列表 (index.html)
app.get("/", (req, res) => {
  res.sendFile(path.join(publicDir, "index.html"));
});

// 單一 story 測驗頁 (test.html?story=xxx)
app.get("/test.html", (req, res) => {
  res.sendFile(path.join(publicDir, "test.html"));
});

// ---- 啟動伺服器 ----
const PORT = process.env.PORT || 80;
app.listen(PORT, "0.0.0.0", () =>
  console.log(`Server running on http://0.0.0.0:${PORT}`)
);

