const express = require("express");
const cors = require("cors");
const path = require("path");
const fs = require("fs");
const sharp = require("sharp");
const multer = require("multer");
const net = require("net");
const https = require("https");
const { exec } = require("child_process");

const app = express();
app.use(cors());

const upload = multer({ dest: "/tmp/uploads/" });

// ---- 確保 uploads 資料夾存在 ----
if (!fs.existsSync("/tmp/uploads")) {
  fs.mkdirSync("/tmp/uploads");
}

// ---- 靜態檔案 ----
const publicDir = path.join(__dirname, "public");
app.use(express.static(publicDir));

// ---- 瀏覽人數 ----
const visitorsFile = path.join(__dirname, "visitors.json");
let visitors = 0;
if (fs.existsSync(visitorsFile)) {
  try {
    visitors = JSON.parse(fs.readFileSync(visitorsFile, "utf-8")).visitors || 0;
  } catch {}
}
app.get("/api/visit", (req, res) => {
  visitors++;
  fs.writeFile(visitorsFile, JSON.stringify({ visitors }), () => {});
  res.json({ visitors });
});
app.get("/api/visitors", (req, res) => res.json({ visitors }));

// ---- 圖片轉 Base64 ----
function imgToBase64(filePath) {
  return sharp(filePath)
    .resize({ width: 400, height: 400, fit: "inside", withoutEnlargement: true })
    .webp({ quality: 80 })
    .toBuffer()
    .then(buf => `data:image/webp;base64,${buf.toString("base64")}`);
}

// ---- API: stories ----
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
        const imgBase64 = await imgToBase64(path.join(dir, img));
        const otherBase64 = await Promise.all(
          others.map(f => imgToBase64(path.join(dir, f)))
        );

        const q1 = {
          img: imgBase64,
          answer,
          options: shuffle([answer, ...others.map(f => path.basename(f, ".png"))])
        };

        const options2 = shuffle([imgBase64, ...otherBase64]);
        const q2 = { word: answer, answer: imgBase64, options: options2 };

        const q3 = { word: answer, img: imgBase64 }; // Phase3: 圖片 + 語音回答

        return { phase1: q1, phase2: q2, phase3: q3 };
      })
    );
    res.json({ questions });
  } catch (err) {
    console.error("Error generating questions:", err);
    res.status(500).json({ error: "Image processing failed" });
  }
});

// ---- API: speech-match (上傳 webm → 轉 wav → Socket 給 Python) ----
app.post("/api/speech-match/:story", upload.single("audio"), (req, res) => {
  if (!req.file) return res.status(400).json({ error: "No audio uploaded" });

  const story = req.params.story;
  let words = [];
  try {
    words = JSON.parse(req.body.words); // 前端送 JSON array
  } catch {
    return res.status(400).json({ error: "Invalid words format, must be JSON array" });
  }

  const wavPath = req.file.path + ".wav";

  // 把 webm 轉成 16kHz mono wav
  exec(`ffmpeg -y -i ${req.file.path} -ar 16000 -ac 1 ${wavPath}`, (err) => {
    fs.unlink(req.file.path, () => {}); // 刪掉原始 webm

    if (err) {
      console.error("ffmpeg convert error:", err);
      return res.status(500).json({ error: "Audio conversion failed" });
    }

    const requestJson = JSON.stringify({
      audio: wavPath,
      story,
      words
    });
    console.log("Request to speech_match server:", requestJson);
    const client = new net.Socket();
    client.connect(6000, "127.0.0.1", () => {
      client.write(requestJson);
    });

    client.on("data", data => {
      //fs.unlink(wavPath, () => {}); // 用完刪掉 wav
      try {
        const result = JSON.parse(data.toString());
        res.json(result);
    	console.log("Response from speech_match server:", result);
      } catch (e) {
        console.error("speech_match server response parse error:", data.toString());
        res.status(500).json({ error: "Invalid response from speech_match server" });
      }
      client.destroy();
    });

    client.on("error", err => {
      console.error("Socket error:", err);
      res.status(500).json({ error: "speech_match server unreachable" });
    });
  });
});

// ---- 頁面 ----
app.get("/", (req, res) => res.sendFile(path.join(publicDir, "index.html")));
app.get("/test.html", (req, res) => res.sendFile(path.join(publicDir, "test.html")));

// ---- HTTPS 啟動 (若有憑證) ----
const keyPath = path.join(__dirname, "localhost.key");
const certPath = path.join(__dirname, "localhost.crt");

if (fs.existsSync(keyPath) && fs.existsSync(certPath)) {
  const key = fs.readFileSync(keyPath);
  const cert = fs.readFileSync(certPath);
  const PORT = process.env.PORT || 443;

  https.createServer({ key, cert }, app).listen(PORT, () => {
    console.log(`✅ HTTPS Server running at https://localhost:${PORT}`);
  });
} else {
  const PORT = process.env.PORT || 80;
  app.listen(PORT, "0.0.0.0", () =>
    console.log(`⚠️ HTTPS cert not found, running HTTP at http://0.0.0.0:${PORT}`)
  );
}

