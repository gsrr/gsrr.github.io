const express = require("express");
const cors = require("cors");
const path = require("path");
const fs = require("fs");

const app = express();
app.use(cors());
app.use("/images", express.static(path.join(__dirname, "images")));
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
    return { img: `${story}/${img}`, answer, options };
  });

  res.json({ questions });
});

const PORT = 3000;
app.listen(PORT, "0.0.0.0", () => console.log(`Server running on http://0.0.0.0:${PORT}`));

