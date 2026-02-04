const express = require("express");
const fs = require("fs");
const path = require("path");
const https = require("https");

const options = {
  key: fs.readFileSync("/etc/letsencrypt/live/kyotozuiryu.com/privkey.pem"),
  cert: fs.readFileSync("/etc/letsencrypt/live/kyotozuiryu.com/fullchain.pem")
};



const app = express();
const PORT = 8000;


TICKET_CONF_PATH = "ticket.conf.json";

// ====== 基本設定 ======

// 前端靜態檔案根目錄（index.html / signup.html）
const WEB_ROOT = __dirname;

// 報名資料存放位置
const DATA_DIR = path.join(__dirname, "data");
const DATA_FILE = path.join(DATA_DIR, "signup.json");
const VISIT_FILE = path.join(DATA_DIR, "visit.json");

// 建立 data 資料夾
fs.mkdirSync(DATA_DIR, { recursive: true });

// 解析 JSON
app.use(express.json());

// CORS（目前全開，活動型網站夠用）
app.use((req, res, next) => {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");
  res.setHeader("Access-Control-Allow-Methods", "GET,POST,OPTIONS");
  if (req.method === "OPTIONS") return res.sendStatus(200);
  next();
});

// 提供靜態檔案（index.html / signup.html / 圖片 / CSS）
app.use(express.static(WEB_ROOT));

// ====== 前端頁面 ======

// 首頁
app.get("/", (req, res) => {
  res.sendFile(path.join(WEB_ROOT, "index.html"));
});

// 報名頁（保險起見，明確指定）
app.get("/signup.html", (req, res) => {
  res.sendFile(path.join(WEB_ROOT, "signup.html"));
});

// ====== API：報名 ======

/**
 * POST /api/signup
 * 接收報名資料並存成 JSON
 */
app.post("/api/signup", (req, res) => {
  const signup = {
    ...req.body,
    createdAt: new Date().toISOString(),
    ip: req.headers["x-forwarded-for"] || req.socket.remoteAddress
  };

  let list = [];
  if (fs.existsSync(DATA_FILE)) {
	  try {
		  const raw = fs.readFileSync(DATA_FILE, "utf8").trim();
		  list = raw ? JSON.parse(raw) : [];
	  } catch (err) {
		  console.error("signup.json parse failed, reset to []", err);
		  list = [];
	  }
  }

  list.push(signup);

  fs.writeFileSync(DATA_FILE, JSON.stringify(list, null, 2));

  res.json({ ok: true });
});

// ====== API：查看報名（管理用） ======

/**
 * GET /api/signup
 * 取得全部報名資料
 */
app.get("/api/signup", (req, res) => {
  if (!fs.existsSync(DATA_FILE)) return res.json([]);
  res.json(JSON.parse(fs.readFileSync(DATA_FILE, "utf8")));
});

/**
 * GET /api/stats
 * 簡單統計（人數 / 便當）
 */
app.get("/api/stats", (req, res) => {
  if (!fs.existsSync(DATA_FILE)) {
    return res.json({ totalPeople: 0 });
  }

  const list = JSON.parse(fs.readFileSync(DATA_FILE, "utf8"));

  let stats = {
    adult: 0,
    child: 0,
    care: 0,
    bento_chicken: 0,
    bento_pork: 0,
    bento_veg: 0,
    bento_rice: 0
  };

  list.forEach(r => {
    stats.adult += r.summary.adult || 0;
    stats.child += r.summary.child || 0;
    stats.care += r.summary.care || 0;
	  // 便當
    stats.bento_chicken += r.bento?.chicken || 0;
    stats.bento_pork    += r.bento?.pork || 0;
    stats.bento_veg     += r.bento?.veg || 0;
    stats.bento_rice    += r.bento?.rice || 0;
  });

  stats.totalPeople = stats.adult + stats.child + stats.care;

  res.json(stats);
});

// ====== 啟動伺服器 ======
const server = https.createServer(options, app).listen(PORT, "0.0.0.0", () => {
  console.log(`✅ HTTPS server running at https://0.0.0.0:${PORT}`);
});

// ====== 正常關機（很重要） ======

process.on("SIGTERM", () => {
  console.log("SIGTERM received, shutting down...");
  server.close(() => process.exit(0));
});

process.on("SIGINT", () => {
  console.log("SIGINT received (Ctrl+C)");
  server.close(() => process.exit(0));
});


/**
 * 工具函式：讀取 ticket conf
 * - 每次讀檔（安全、即時）
 * - 若你之後在意效能，再加 cache
 */
function loadTicketConf() {
  const raw = fs.readFileSync(TICKET_CONF_PATH, "utf8");
  return JSON.parse(raw);
}

/**
 * GET /api/config/ticket
 * 回傳票價設定
 */
app.get("/api/config/ticket", (req, res) => {
  try {
    const conf = loadTicketConf();
    res.json(conf);
  } catch (err) {
    console.error("load ticket conf failed:", err);
    res.status(500).json({
      error: "ticket config load failed"
    });
  }
});

/**
 * GET /api/visit
 * 首頁瀏覽次數 +1
 */
app.get("/api/visit", (req, res) => {
  let count = 0;

  if (fs.existsSync(VISIT_FILE)) {
    count = JSON.parse(fs.readFileSync(VISIT_FILE, "utf8")).count || 0;
  }

  count += 1;

  fs.writeFileSync(VISIT_FILE, JSON.stringify({ count }, null, 2));
  res.json({ count });
});



/**
 * POST /api/signup/note
 * body: { index, note }
 */
app.post("/api/signup/note", (req, res) => {
  const { index, note } = req.body;

  if (!fs.existsSync(DATA_FILE)) {
    return res.status(400).json({ error: "no data" });
  }

  const list = JSON.parse(fs.readFileSync(DATA_FILE, "utf8"));

  if (index < 0 || index >= list.length) {
    return res.status(400).json({ error: "invalid index" });
  }

  list[index].note = String(note || "");

  fs.writeFileSync(DATA_FILE, JSON.stringify(list, null, 2));
  res.json({ ok: true });
});

