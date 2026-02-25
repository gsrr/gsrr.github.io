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

require("dotenv").config();

TICKET_CONF_PATH = "ticket.conf.json";

// ====== 基本設定 ======

// 前端靜態檔案根目錄（index.html / signup.html）
const WEB_ROOT = __dirname;

// 報名資料存放位置
const DATA_DIR = path.join(__dirname, "data");
const DATA_FILE = path.join(DATA_DIR, "signup.json");
const VISIT_FILE = path.join(DATA_DIR, "visit.json");
const META_FILE = path.join(DATA_DIR, "meta.json");

const ADMIN_TOKEN = process.env.ADMIN_TOKEN;

// 建立 data 資料夾
fs.mkdirSync(DATA_DIR, { recursive: true });

// 解析 JSON
app.use(express.json());

/* =========================
 * Admin 驗證 middleware
 * ========================= */
function requireAdmin(req, res, next) {
  const token = req.headers["x-admin-token"];

  if (!token || token !== ADMIN_TOKEN) {
    return res.status(403).json({ error: "forbidden" });
  }
  next();
}

/* =========================
 * 工具：讀檔
 * ========================= */
function loadJson(file, def) {
  if (!fs.existsSync(file)) return def;
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

function loadMeta() {
  if (!fs.existsSync(META_FILE)) return {};
  return JSON.parse(fs.readFileSync(META_FILE, "utf8"));
}

function saveMeta(meta) {
  fs.writeFileSync(META_FILE, JSON.stringify(meta, null, 2));
}

/*
* =========================
 * 管理者 API（可寫）
 * ========================= */

app.post("/api/admin/meta", requireAdmin, (req, res) => {
	console.log(req.body);
  const { id, paid, note } = req.body;

  if (!id) {
    return res.status(400).json({ error: "missing id" });
  }

  const meta = loadMeta();

  meta[id] = {
    ...(meta[id] || {}),
    paid: !!paid,
    note: note || "",
    updatedAt: new Date().toISOString()
  };

  saveMeta(meta);

  res.json({ ok: true });
});



/**
 * 取得完整資料（含 meta）
 */
app.get("/api/admin/signup", requireAdmin, (req, res) => {
  const list = loadJson(DATA_FILE, []);
  const meta = loadJson(META_FILE, {});

  const result = list.map(item => ({
    ...item,
    meta: meta[item.createdAt] || { paid: false, note: "" }
  }));

  res.json(result);
});

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

function maskValue(val, visible = 0) {
  if (!val) return val;
  return "*".repeat(Math.max(val.length - visible, 0));
}


/**
 * GET /api/signup
 * 取得全部報名資料（隱藏敏感資訊）
 */
app.get("/api/signup", (req, res) => {
  if (!fs.existsSync(DATA_FILE)) return res.json([]);

  const list = JSON.parse(fs.readFileSync(DATA_FILE, "utf8"));

  const masked = list.map(item => ({
    ...item,

    // 第一層
    phone: item.phone ? maskValue(item.phone) : item.phone,
    email: item.email ? maskValue(item.email) : item.email,

    // people 是 array，要再 map
    people: Array.isArray(item.people)
      ? item.people.map(p => ({
          ...p,
          idno: p.idno ? maskValue(p.idno) : p.idno
        }))
      : item.people
  }));

  res.json(masked);
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
    female: 0,
    horse_free: 0,
    bento_chicken: 0,
    bento_pork: 0,
    bento_veg: 0,
    bento_rice: 0,
    drivePeople: 0,
    busPeople: 0
  };

  list.forEach(r => {
    const adult = r.summary?.adult || 0;
    const child = r.summary?.child || 0;
    const female = r.summary?.female || 0;
    const horseFree = r.summary?.horse_free || 0;

    stats.adult += adult;
    stats.child += child;
    stats.female += female;
    stats.horse_free += horseFree;

    const peopleCount = adult + child + female + horseFree;
    if (r.transport === "bus") {
      stats.busPeople += peopleCount;
    } else if (r.transport === "drive") {
      stats.drivePeople += peopleCount;
    }

	  // 便當
    stats.bento_chicken += r.bento?.chicken || 0;
    stats.bento_pork    += r.bento?.pork || 0;
    stats.bento_veg     += r.bento?.veg || 0;
    stats.bento_rice    += r.bento?.rice || 0;
  });

  stats.totalPeople = stats.adult + stats.child + stats.female + stats.horse_free;

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

