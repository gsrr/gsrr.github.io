const express = require("express");
const cors = require("cors");
const path = require("path");
const fs = require("fs");

const app = express();
app.use(cors());
app.use("/images", express.static(path.join(__dirname, "images"))); // 提供圖片靜態服務
app.use(express.static(path.join(__dirname, "public"))); // 前端頁面

// API: 取得題目
app.get("/api/questions", (req, res) => {
  const files = fs.readdirSync("./images").filter(f => f.endsWith(".png"));
  const shuffled = files.sort(() => Math.random() - 0.5).slice(0, 10);

  const questions = shuffled.map(img => {
    const answer = img.replace(".png", "");
    const others = files.filter(f => f !== img).sort(() => Math.random() - 0.5).slice(0, 3);
    const options = [answer, ...others.map(f => f.replace(".png", ""))].sort(() => Math.random() - 0.5);
    return { img, answer, options };
  });

  res.json({ questions });
});

const PORT = 3000;
app.listen(PORT, "0.0.0.0", () => {
  console.log(`Server running on http://0.0.0.0:${PORT}`);
});
