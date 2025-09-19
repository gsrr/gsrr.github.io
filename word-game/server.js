const express = require("express");
const cors = require("cors");
const path = require("path");
const fs = require("fs");
const sharp = require("sharp");

const app = express();
app.use(cors());
app.use(express.static(path.join(__dirname, "public"))); // 前端頁面

// API: 列出有哪些故事
app.get("/api/stories", (req, res) => {
  const baseDir = "./images";
  const dirs = fs.readdirSync(baseDir, { withFileTypes: true })
                .filter(d => d.isDirectory())
                .map(d => d.name);
  res.json({ stories: dirs });
});

// API: 取得指定故事的題目
app.get("/api/questions/:story", (req, res) => {
  const story = req.params.story;
  const dir = path.join(__dirname, "images", story);

  if (!fs.existsSync(dir)) {
    return res.status(404).json({ error: "Story not found" });
  }

  const files = fs.readdirSync(dir).filter(f => f.endsWith(".png"));
  const shuffled = files.sort(() => Math.random() - 0.5).slice(0, 10);

  const questions = shuffled.map(img => {
    const answer = img.replace(".png", "");
    const others = files.filter(f => f !== img).sort(() => Math.random() - 0.5).slice(0, 3);
    const options = [answer, ...others.map(f => f.replace(".png", ""))].sort(() => Math.random() - 0.5);
    // 注意這裡改成 /api/image/
    return { img: `/api/image/${story}/${img}`, answer, options };
  });

  res.json({ questions });
});

// API: 動態壓縮圖片並輸出 webp
app.get("/api/image/:story/:file", async (req, res) => {
  const { story, file } = req.params;
  const filePath = path.join(__dirname, "images", story, file);

  if (!fs.existsSync(filePath)) {
    return res.sendStatus(404);
  }

  try {
    res.type("image/webp");
    sharp(filePath)
      .resize(400, 400, { fit: "inside" })   // 最大 400px，保持比例
      .webp({ quality: 80 })                 // 壓縮品質 80
      .pipe(res);
  } catch (err) {
    console.error("Image processing error:", err);
    res.sendStatus(500);
  }
});

const PORT = 3000;
app.listen(PORT, "0.0.0.0", () => console.log(`Server running on http://0.0.0.0:${PORT}`));

