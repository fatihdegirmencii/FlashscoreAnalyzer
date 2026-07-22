from __future__ import annotations

import atexit
import json
import os
import re
import socket
import sqlite3
import sys
import threading
import time
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, jsonify, render_template_string, request
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from waitress import serve


APP_NAME = "FlashscoreAnalyzer"


def app_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        path = Path(base) / APP_NAME
    else:
        path = Path.home() / f".{APP_NAME.lower()}"
    path.mkdir(parents=True, exist_ok=True)
    return path


DATA_DIR = app_data_dir()
DB_PATH = DATA_DIR / "odds.db"

app = Flask(__name__)


HTML = r"""
<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Flashscore Analyzer</title>
<style>
:root{
  --bg:#f4f7fb;--panel:#fff;--text:#152033;--muted:#6f7c8e;
  --line:#e3e9f1;--accent:#ec174c;--ok:#087f5b;--bad:#c92a2a
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
font-family:Inter,Segoe UI,Arial,sans-serif}
.wrap{width:min(1100px,calc(100% - 28px));margin:34px auto 80px}
.hero{padding:10px 4px 6px}
h1{font-size:clamp(34px,6vw,60px);line-height:1;margin:8px 0 14px;letter-spacing:-.04em}
h2{font-size:21px;margin:0}
.lead{color:var(--muted);font-size:17px;line-height:1.6;max-width:820px}
.eyebrow{color:var(--accent);font-weight:900;font-size:12px;letter-spacing:.14em;margin:0}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:18px;
padding:22px;margin-top:18px;box-shadow:0 10px 30px rgba(31,45,61,.05)}
label{display:block;font-weight:800;margin-bottom:10px}
.input-row{display:grid;grid-template-columns:1fr auto;gap:10px}
input{width:100%;border:1px solid #ccd6e3;border-radius:12px;padding:15px 16px;
font-size:16px;outline:none}
input:focus{border-color:var(--accent);box-shadow:0 0 0 4px rgba(236,23,76,.1)}
button{border:0;border-radius:12px;padding:0 25px;background:var(--accent);color:white;
font-weight:900;font-size:15px;cursor:pointer}
button:disabled{opacity:.65;cursor:wait}
.status{margin-top:18px;padding:15px 18px;border-radius:12px;font-weight:800}
.status.info{background:#e7f5ff;color:#1864ab}
.status.success{background:#e6fcf5;color:var(--ok)}
.status.error{background:#fff5f5;color:var(--bad)}
.hidden{display:none}
.section-title{display:flex;justify-content:space-between;align-items:center;gap:16px;margin-bottom:15px}
.badge{background:#f1f3f5;color:#495057;border-radius:999px;padding:7px 10px;font-size:12px;font-weight:900}
.chips,.values{display:flex;flex-wrap:wrap;gap:8px}
.chips span,.values span{background:#fff0f4;color:#bd123d;border-radius:999px;padding:7px 10px;
font-size:12px;font-weight:900}
.cards{display:grid;gap:10px}
.card{display:grid;grid-template-columns:38px 1fr;gap:12px;border:1px solid var(--line);
border-radius:13px;padding:14px}
.num{width:32px;height:32px;display:grid;place-items:center;border-radius:9px;
background:#f1f3f5;color:#6c757d;font-weight:900}
.card p{margin:0 0 9px;line-height:1.45}
.hint,.warning,.empty{color:var(--muted);font-size:14px;line-height:1.55}
details{border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin-top:10px}
summary{cursor:pointer;font-weight:800}
.history-body{color:var(--muted);font-size:13px}
.note{border-left:5px solid #fab005}
@media(max-width:700px){
 .wrap{width:min(100% - 18px,1100px);margin-top:15px}
 .panel{padding:16px;border-radius:14px}
 .input-row{grid-template-columns:1fr}
 button{min-height:50px}
}
</style>
</head>
<body>
<main class="wrap">
  <section class="hero">
    <p class="eyebrow">WINDOWS • YEREL VERİTABANI</p>
    <h1>Flashscore Analyzer</h1>
    <p class="lead">Flashscore maç bağlantısını yapıştır. Program sayfayı Chrome ile açar, görünen oran satırlarını tarar ve aynı bağlantının önceki taramalarıyla karşılaştırmak için kaydeder.</p>
  </section>

  <section class="panel">
    <label for="url">Flashscore maç bağlantısı</label>
    <div class="input-row">
      <input id="url" type="url" placeholder="https://www.flashscore.co.uk/match/..." autocomplete="off">
      <button id="scan">Maçı Tara</button>
    </div>
    <p class="hint">Google Chrome bilgisayarda kurulu olmalıdır. Yoğun/toplu tarama yapılmamalıdır.</p>
  </section>

  <section id="status" class="status hidden"></section>

  <section id="summary" class="panel hidden">
    <div class="section-title">
      <div><p class="eyebrow">TARAMA SONUCU</p><h2 id="match">Maç</h2></div>
      <span id="marketCount" class="badge"></span>
    </div>
    <div id="markets" class="chips"></div>
    <p id="warning" class="warning"></p>
  </section>

  <section id="rowsPanel" class="panel hidden">
    <div class="section-title"><h2>Bulunan oran satırları</h2><span id="rowCount" class="badge"></span></div>
    <div id="rows" class="cards"></div>
  </section>

  <section id="historyPanel" class="panel hidden">
    <div class="section-title"><h2>Önceki taramalar</h2><span class="badge">SQLite</span></div>
    <p class="hint">Aynı maçı farklı saatlerde yeniden taradıkça değişim geçmişi oluşur.</p>
    <div id="history"></div>
  </section>

  <section class="panel note">
    <h2>Bilgi</h2>
    <p class="hint">Bu uygulama sayfada o anda görülebilen veriyi kaydeder. Flashscore'da mevcut olmayan altı yıllık geçmiş açılış-kapanış oranlarını geriye dönük olarak üretemez.</p>
  </section>
</main>
<script>
const $=s=>document.querySelector(s);
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
function status(t,k="info"){const e=$("#status");e.className=`status ${k}`;e.textContent=t}
function renderRows(rows){
 $("#rows").innerHTML=rows.map((r,i)=>`<article class="card"><div class="num">${i+1}</div><div>
 <p>${esc(r.text)}</p><div class="values">${(r.values||[]).map(v=>`<span>${Number(v).toFixed(2)}</span>`).join("")}</div>
 </div></article>`).join("");
 $("#rowCount").textContent=`${rows.length} satır`;
}
function renderHistory(items){
 if(!items||items.length<2){$("#history").innerHTML='<p class="empty">Karşılaştırma için aynı maçı daha sonra tekrar tara.</p>';return}
 $("#history").innerHTML=items.map((x,i)=>`<details ${i===0?"open":""}>
 <summary>${new Date(x.scan_time).toLocaleString("tr-TR")} — ${x.rows.length} örnek satır</summary>
 <div class="history-body">${x.rows.slice(0,8).map(r=>`<p>${esc(r.text)}</p>`).join("")}</div></details>`).join("");
}
$("#scan").onclick=async()=>{
 const url=$("#url").value.trim(); if(!url){status("Önce bir maç bağlantısı yapıştır.","error");return}
 const b=$("#scan"); b.disabled=true;b.textContent="Taranıyor…";status("Chrome arka planda açılıyor ve oranlar okunuyor…");
 try{
  const res=await fetch("/api/scan",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({url})});
  const d=await res.json(); if(!res.ok||!d.ok)throw new Error(d.error||"Bilinmeyen hata");
  const r=d.result; status("Tarama tamamlandı ve kaydedildi.","success");
  $("#match").textContent=r.match_name||"Maç";
  $("#markets").innerHTML=(r.markets_found||[]).map(x=>`<span>${esc(x)}</span>`).join("");
  $("#marketCount").textContent=`${(r.markets_found||[]).length} market`;
  $("#warning").textContent=r.warning||"";
  renderRows(r.rows||[]);renderHistory(d.history||[]);
  $("#summary").classList.remove("hidden");$("#rowsPanel").classList.remove("hidden");$("#historyPanel").classList.remove("hidden");
 }catch(e){status(e.message,"error")}
 finally{b.disabled=false;b.textContent="Maçı Tara"}
};
$("#url").addEventListener("keydown",e=>{if(e.key==="Enter")$("#scan").click()});
</script>
</body>
</html>
"""


def init_db() -> None:
    with sqlite3.connect(DB_PATH) as con:
        con.execute("""
        CREATE TABLE IF NOT EXISTS scans(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL,
            match_name TEXT,
            scan_time TEXT NOT NULL,
            odds_json TEXT NOT NULL
        )
        """)
        con.commit()


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def valid_flashscore_url(url: str) -> bool:
    try:
        p = urlparse(url)
        host = (p.hostname or "").lower()
        return p.scheme in {"http", "https"} and (
            host == "flashscore.co.uk" or host.endswith(".flashscore.co.uk")
        ) and "/match/" in p.path
    except Exception:
        return False


def decimal_value(token: str):
    token = clean(token).replace(",", ".")
    if not re.fullmatch(r"\d{1,3}(?:\.\d{1,3})?", token):
        return None
    value = float(token)
    return value if 1.01 <= value <= 1000 else None


def make_driver():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1440,1200")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-notifications")
    options.add_argument("--lang=en-GB")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
    # Selenium Manager, uyumlu ChromeDriver'ı otomatik bulur/indirir.
    return webdriver.Chrome(options=options)


def scrape(url: str) -> dict:
    driver = None
    try:
        driver = make_driver()
        driver.set_page_load_timeout(45)
        driver.get(url)
        time.sleep(6)

        # Çerez düğmeleri için birkaç genel deneme.
        for text in ("Accept", "I Accept", "Agree", "Allow all", "OK"):
            try:
                buttons = driver.find_elements(
                    By.XPATH,
                    f"//button[contains(translate(normalize-space(.),"
                    f"'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),"
                    f"'{text.lower()}')]"
                )
                if buttons:
                    buttons[0].click()
                    time.sleep(1)
                    break
            except Exception:
                pass

        title = clean(driver.title)
        body_text = clean(driver.find_element(By.TAG_NAME, "body").text)
        match_name = title.split("|")[0].strip() if title else "Bilinmeyen maç"

        script = """
        const visible = el => {
          const s=getComputedStyle(el), r=el.getBoundingClientRect();
          return s.display!=='none' && s.visibility!=='hidden' && r.width>0 && r.height>0;
        };
        const sel='[class*="odds"],[class*="bookmaker"],[class*="ui-table"],[class*="row"]';
        const out=[];
        for(const el of [...document.querySelectorAll(sel)].filter(visible)){
          const text=(el.innerText||'').replace(/\\s+/g,' ').trim();
          if(!text || text.length>500) continue;
          const nums=text.match(/\\b\\d{1,3}[.,]\\d{1,3}\\b/g)||[];
          if(nums.length) out.push({text});
          if(out.length>=900) break;
        }
        return out;
        """
        raw = driver.execute_script(script) or []

        seen = set()
        rows = []
        banned = ("claim", "free bet", "advertisement", "responsibly", "cookie")
        for item in raw:
            text = clean(item.get("text", ""))
            if not text or text in seen or len(text) < 8:
                continue
            seen.add(text)
            if any(word in text.lower() for word in banned):
                continue
            values = []
            for token in re.findall(r"\b\d{1,3}[.,]\d{1,3}\b", text):
                value = decimal_value(token)
                if value is not None:
                    values.append(value)
            if values:
                rows.append({"text": text, "values": values})
            if len(rows) >= 140:
                break

        known = [
            "1X2", "OVER/UNDER", "BOTH TEAMS TO SCORE", "DOUBLE CHANCE",
            "ASIAN HANDICAP", "EUROPEAN HANDICAP", "DRAW NO BET",
            "CORRECT SCORE", "HALF TIME/FULL TIME", "1ST HALF", "2ND HALF"
        ]
        upper = body_text.upper()
        markets = [m for m in known if m in upper]

        return {
            "match_name": match_name,
            "markets_found": markets,
            "rows": rows,
            "warning": (
                "Flashscore sayfa yapısını değiştirir, CAPTCHA gösterir veya otomatik "
                "erişimi sınırlandırırsa tarama başarısız olabilir."
            ),
        }
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass


def save_scan(url: str, result: dict) -> int:
    stamp = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(DB_PATH) as con:
        cur = con.execute(
            "INSERT INTO scans(url,match_name,scan_time,odds_json) VALUES(?,?,?,?)",
            (url, result.get("match_name"), stamp, json.dumps(result, ensure_ascii=False)),
        )
        con.commit()
        return int(cur.lastrowid)


def history(url: str, limit: int = 10):
    with sqlite3.connect(DB_PATH) as con:
        found = con.execute(
            "SELECT id,scan_time,odds_json FROM scans WHERE url=? ORDER BY id DESC LIMIT ?",
            (url, limit),
        ).fetchall()
    out = []
    for scan_id, scan_time, odds_json in found:
        try:
            data = json.loads(odds_json)
        except Exception:
            data = {}
        out.append({"id": scan_id, "scan_time": scan_time, "rows": data.get("rows", [])[:20]})
    return out


@app.get("/")
def home():
    return render_template_string(HTML)


@app.post("/api/scan")
def api_scan():
    payload = request.get_json(silent=True) or {}
    url = clean(payload.get("url", ""))
    if not valid_flashscore_url(url):
        return jsonify(ok=False, error="Geçerli bir flashscore.co.uk maç bağlantısı yapıştır."), 400
    try:
        result = scrape(url)
        scan_id = save_scan(url, result)
        return jsonify(ok=True, scan_id=scan_id, result=result, history=history(url, 8))
    except TimeoutException:
        return jsonify(ok=False, error="Sayfa zaman aşımına uğradı."), 504
    except WebDriverException as exc:
        return jsonify(
            ok=False,
            error=(
                "Chrome başlatılamadı. Google Chrome'un kurulu ve güncel olduğundan emin ol. "
                f"Teknik ayrıntı: {clean(str(exc))[:300]}"
            ),
        ), 500
    except Exception as exc:
        return jsonify(ok=False, error=f"Tarama başarısız: {type(exc).__name__}: {clean(str(exc))[:300]}"), 500


def free_port(preferred: int = 5000) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])


def open_later(url: str):
    time.sleep(1.2)
    webbrowser.open(url)


def main():
    init_db()
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    threading.Thread(target=open_later, args=(url,), daemon=True).start()
    serve(app, host="127.0.0.1", port=port, threads=6)


if __name__ == "__main__":
    main()
