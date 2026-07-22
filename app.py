from __future__ import annotations

import csv
import io
import json
import math
import os
import re
import socket
import sqlite3
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
DATA_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / APP_NAME
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "analyzer.db"

app = Flask(__name__)

HTML = r"""
<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Flashscore Analyzer</title>
<style>
:root{--bg:#f4f7fb;--panel:#fff;--text:#152033;--muted:#6f7c8e;--line:#e3e9f1;--a:#ec174c;--ok:#087f5b;--bad:#c92a2a}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:Segoe UI,Arial,sans-serif}
.wrap{width:min(1120px,calc(100% - 28px));margin:32px auto 70px}.hero{padding:8px 4px}
h1{font-size:clamp(36px,6vw,62px);line-height:1;margin:8px 0 14px;letter-spacing:-.04em}h2{margin:0 0 14px}
.lead,.hint{color:var(--muted);line-height:1.6}.ey{color:var(--a);font-size:12px;font-weight:900;letter-spacing:.14em}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:18px;padding:22px;margin-top:18px;box-shadow:0 10px 30px rgba(31,45,61,.05)}
.row{display:grid;grid-template-columns:1fr auto;gap:10px}input[type=url],input[type=file]{width:100%;border:1px solid #ccd6e3;border-radius:12px;padding:14px;font-size:16px}
button{border:0;border-radius:12px;padding:0 24px;min-height:50px;background:var(--a);color:white;font-weight:900;cursor:pointer}
button.secondary{background:#1f2937}.status{padding:14px 17px;border-radius:12px;margin-top:18px;font-weight:800}.info{background:#e7f5ff;color:#1864ab}.ok{background:#e6fcf5;color:var(--ok)}.bad{background:#fff5f5;color:var(--bad)}.hidden{display:none}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}.card{border:1px solid var(--line);border-radius:14px;padding:16px}
.card h3{margin:0 0 12px;font-size:16px}.metric{display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px dashed var(--line)}
.metric:last-child{border:0}.pct{font-weight:900;color:var(--a)}.badge{display:inline-block;border-radius:999px;background:#f1f3f5;padding:7px 10px;font-size:12px;font-weight:800}
pre{white-space:pre-wrap;word-break:break-word;background:#f8fafc;padding:12px;border-radius:12px;max-height:280px;overflow:auto}
@media(max-width:700px){.row{grid-template-columns:1fr}.panel{padding:16px}}
</style>
</head>
<body>
<main class="wrap">
<section class="hero"><div class="ey">WINDOWS • GEÇMİŞ VERİ ANALİZİ</div><h1>Flashscore Analyzer</h1>
<p class="lead">Önce geçmiş maç CSV dosyanı içe aktar. Sonra Flashscore maç bağlantısını tara; program benzer oranlı geçmiş maçları bulup olasılıkları hesaplar.</p></section>

<section class="panel">
<h2>1. Geçmiş veriyi içe aktar</h2>
<div class="row"><input id="csv" type="file" accept=".csv"><button class="secondary" id="importBtn">CSV'yi İçe Aktar</button></div>
<p class="hint">Gerekli sütunlar: date, home_odds, draw_odds, away_odds, ht_home_goals, ht_away_goals, ft_home_goals, ft_away_goals. İlk yarı oranları varsa ayrıca ht_home_odds, ht_draw_odds, ht_away_odds kullanılır.</p>
<div id="importStatus" class="status hidden"></div>
</section>

<section class="panel">
<h2>2. Güncel maçı tara</h2>
<div class="row"><input id="url" type="url" placeholder="https://www.flashscore.co.uk/match/..."><button id="scanBtn">Maçı Tara ve Analiz Et</button></div>
<p class="hint">Google Chrome kurulu olmalıdır. Tarama sonunda bulunan 1X2 oranları, geçmiş verideki en yakın maçlarla eşleştirilir.</p>
<div id="scanStatus" class="status hidden"></div>
</section>

<section id="analysisPanel" class="panel hidden">
<div style="display:flex;justify-content:space-between;gap:12px;align-items:center"><h2 id="matchName">Analiz</h2><span id="sample" class="badge"></span></div>
<div id="analysis" class="grid"></div>
</section>

<section id="rawPanel" class="panel hidden"><h2>Sayfadan bulunan oran satırları</h2><pre id="raw"></pre></section>
</main>
<script>
const $=s=>document.querySelector(s);
function stat(el,text,type){el.className=`status ${type}`;el.textContent=text}
function card(title,items){return `<div class="card"><h3>${title}</h3>${items.map(x=>`<div class="metric"><span>${x[0]}</span><span class="pct">%${x[1]}</span></div>`).join("")}</div>`}
$("#importBtn").onclick=async()=>{
 const f=$("#csv").files[0], s=$("#importStatus"); if(!f){stat(s,"CSV dosyası seç.","bad");return}
 const fd=new FormData();fd.append("file",f);stat(s,"Veri içe aktarılıyor…","info");
 try{const r=await fetch("/api/import",{method:"POST",body:fd});const d=await r.json();if(!r.ok)throw new Error(d.error);stat(s,`${d.inserted} maç içe aktarıldı. Toplam: ${d.total}`,"ok")}
 catch(e){stat(s,e.message,"bad")}
};
$("#scanBtn").onclick=async()=>{
 const url=$("#url").value.trim(),s=$("#scanStatus");if(!url){stat(s,"Maç linkini yapıştır.","bad");return}
 stat(s,"Sayfa taranıyor ve geçmiş veriyle eşleştiriliyor…","info");
 try{
  const r=await fetch("/api/scan",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({url})});
  const d=await r.json();if(!r.ok)throw new Error(d.error);
  stat(s,"Analiz tamamlandı.","ok");$("#matchName").textContent=d.match_name;$("#sample").textContent=`${d.analysis.sample_size} benzer maç`;
  const a=d.analysis;
  $("#analysis").innerHTML=[
   card("Maç Sonucu",[["1",a.ft_result.home],["X",a.ft_result.draw],["2",a.ft_result.away]]),
   card("İlk Yarı Sonucu",[["İY 1",a.ht_result.home],["İY X",a.ht_result.draw],["İY 2",a.ht_result.away]]),
   card("HT / FT",Object.entries(a.htft).map(([k,v])=>[k,v])),
   card("Toplam Gol",[["0.5 Üst",a.goals.over_0_5],["1.5 Üst",a.goals.over_1_5],["2.5 Üst",a.goals.over_2_5],["3.5 Üst",a.goals.over_3_5]]),
   card("İlk Yarı Gol",[["0.5 Üst",a.ht_goals.over_0_5],["1.5 Üst",a.ht_goals.over_1_5],["2.5 Üst",a.ht_goals.over_2_5]]),
   card("İkinci Yarı Gol",[["0.5 Üst",a.sh_goals.over_0_5],["1.5 Üst",a.sh_goals.over_1_5],["2.5 Üst",a.sh_goals.over_2_5]]),
   card("KG Var / Yok",[["Genel KG Var",a.btts.full_yes],["Genel KG Yok",a.btts.full_no],["İY KG Var",a.btts.ht_yes],["İY KG Yok",a.btts.ht_no],["2Y KG Var",a.btts.sh_yes],["2Y KG Yok",a.btts.sh_no]])
  ].join("");
  $("#analysisPanel").classList.remove("hidden");$("#raw").textContent=d.raw_rows.map(x=>x.text).join("\n\n");$("#rawPanel").classList.remove("hidden");
 }catch(e){stat(s,e.message,"bad")}
};
</script></body></html>
"""

def init_db():
    with sqlite3.connect(DB_PATH) as con:
        con.execute("""CREATE TABLE IF NOT EXISTS historical_matches(
          id INTEGER PRIMARY KEY AUTOINCREMENT,date TEXT,home_odds REAL,draw_odds REAL,away_odds REAL,
          ht_home_odds REAL,ht_draw_odds REAL,ht_away_odds REAL,
          ht_home_goals INTEGER,ht_away_goals INTEGER,ft_home_goals INTEGER,ft_away_goals INTEGER
        )""")
        con.commit()

def clean(s): return re.sub(r"\s+"," ",str(s or "")).strip()

def fnum(v):
    try: return float(str(v).replace(",","."))
    except: return None

def inum(v):
    try: return int(float(v))
    except: return None

def valid_url(url):
    try:
        p=urlparse(url);h=(p.hostname or "").lower()
        return p.scheme in {"http","https"} and (h=="flashscore.co.uk" or h.endswith(".flashscore.co.uk")) and "/match/" in p.path
    except:return False

def make_driver():
    o=Options()
    for arg in ["--headless=new","--window-size=1440,1200","--disable-gpu","--no-sandbox","--disable-dev-shm-usage","--lang=en-GB"]:
        o.add_argument(arg)
    return webdriver.Chrome(options=o)

def scrape(url):
    d=None
    try:
        d=make_driver();d.set_page_load_timeout(45);d.get(url);time.sleep(6)
        title=clean(d.title);body=clean(d.find_element(By.TAG_NAME,"body").text)
        script="""const vis=e=>{const s=getComputedStyle(e),r=e.getBoundingClientRect();return s.display!='none'&&s.visibility!='hidden'&&r.width>0&&r.height>0};
        const out=[];for(const e of [...document.querySelectorAll('[class*="odds"],[class*="bookmaker"],[class*="ui-table"],[class*="row"]')].filter(vis)){
        const t=(e.innerText||'').replace(/\\s+/g,' ').trim();if(!t||t.length>500)continue;const n=t.match(/\\b\\d{1,3}[.,]\\d{1,3}\\b/g)||[];if(n.length)out.push({text:t});if(out.length>700)break}return out"""
        raw=d.execute_script(script) or []
        seen=set();rows=[]
        for x in raw:
            t=clean(x.get("text",""))
            if not t or t in seen or any(w in t.lower() for w in ["free bet","claim","advertisement","cookie"]):continue
            seen.add(t);vals=[]
            for tok in re.findall(r"\b\d{1,3}[.,]\d{1,3}\b",t):
                v=fnum(tok)
                if v and 1.01<=v<=1000:vals.append(v)
            if vals:rows.append({"text":t,"values":vals})
            if len(rows)>=140:break
        # best-effort 1X2: choose a row containing exactly three plausible odds, preferring bookmaker rows
        candidates=[r for r in rows if len(r["values"])>=3]
        if not candidates: raise ValueError("1X2 oran satırı bulunamadı.")
        candidates.sort(key=lambda r:(0 if any(b in r["text"].lower() for b in ["bet365","betmgm","betfred","unibet"]) else 1,len(r["text"])))
        odds=candidates[0]["values"][:3]
        return title.split("|")[0].strip() or "Maç",odds,rows
    finally:
        if d:
            try:d.quit()
            except:pass

def outcome(h,a): return "home" if h>a else "away" if h<a else "draw"
def pct(n,d): return round(100*n/d,1) if d else 0.0

def analyze(odds):
    with sqlite3.connect(DB_PATH) as con:
        rows=con.execute("""SELECT home_odds,draw_odds,away_odds,ht_home_goals,ht_away_goals,ft_home_goals,ft_away_goals
                            FROM historical_matches WHERE home_odds IS NOT NULL AND draw_odds IS NOT NULL AND away_odds IS NOT NULL""").fetchall()
    if len(rows)<30: raise ValueError("Analiz için en az 30 geçmiş maç gerekir. Önce CSV içe aktar.")
    scored=[]
    for r in rows:
        dist=math.sqrt(sum(((r[i]-odds[i])/max(odds[i],1.01))**2 for i in range(3)))
        scored.append((dist,r))
    scored.sort(key=lambda x:x[0]);sample=[r for _,r in scored[:min(500,max(50,len(scored)//20))]]
    n=len(sample)
    ft={"home":0,"draw":0,"away":0};ht={"home":0,"draw":0,"away":0};htft={k:0 for k in ["1/1","1/X","1/2","X/1","X/X","X/2","2/1","2/X","2/2"]}
    g={k:0 for k in ["over_0_5","over_1_5","over_2_5","over_3_5"]};hg={k:0 for k in ["over_0_5","over_1_5","over_2_5"]};sg={k:0 for k in ["over_0_5","over_1_5","over_2_5"]}
    b={"full_yes":0,"ht_yes":0,"sh_yes":0}
    symbol={"home":"1","draw":"X","away":"2"}
    for _,_,_,hh,ha,fh,fa in sample:
        fo=outcome(fh,fa);ho=outcome(hh,ha);ft[fo]+=1;ht[ho]+=1;htft[f"{symbol[ho]}/{symbol[fo]}"]+=1
        total=fh+fa;htotal=hh+ha;stotal=(fh-hh)+(fa-ha)
        for line,key in [(0.5,"over_0_5"),(1.5,"over_1_5"),(2.5,"over_2_5"),(3.5,"over_3_5")]:
            if total>line:g[key]+=1
        for line,key in [(0.5,"over_0_5"),(1.5,"over_1_5"),(2.5,"over_2_5")]:
            if htotal>line:hg[key]+=1
            if stotal>line:sg[key]+=1
        if fh>0 and fa>0:b["full_yes"]+=1
        if hh>0 and ha>0:b["ht_yes"]+=1
        if fh-hh>0 and fa-ha>0:b["sh_yes"]+=1
    conv=lambda d:{k:pct(v,n) for k,v in d.items()}
    return {"sample_size":n,"ft_result":conv(ft),"ht_result":conv(ht),"htft":conv(htft),"goals":conv(g),"ht_goals":conv(hg),"sh_goals":conv(sg),
            "btts":{"full_yes":pct(b["full_yes"],n),"full_no":pct(n-b["full_yes"],n),"ht_yes":pct(b["ht_yes"],n),"ht_no":pct(n-b["ht_yes"],n),"sh_yes":pct(b["sh_yes"],n),"sh_no":pct(n-b["sh_yes"],n)}}

@app.get("/")
def home(): return render_template_string(HTML)

@app.post("/api/import")
def import_csv():
    f=request.files.get("file")
    if not f:return jsonify(error="CSV dosyası bulunamadı."),400
    text=f.read().decode("utf-8-sig",errors="replace")
    reader=csv.DictReader(io.StringIO(text))
    required={"date","home_odds","draw_odds","away_odds","ht_home_goals","ht_away_goals","ft_home_goals","ft_away_goals"}
    if not required.issubset(set(reader.fieldnames or [])):
        return jsonify(error="CSV sütunları eksik: "+", ".join(sorted(required-set(reader.fieldnames or [])))),400
    vals=[]
    for r in reader:
        row=(r.get("date"),fnum(r.get("home_odds")),fnum(r.get("draw_odds")),fnum(r.get("away_odds")),
             fnum(r.get("ht_home_odds")),fnum(r.get("ht_draw_odds")),fnum(r.get("ht_away_odds")),
             inum(r.get("ht_home_goals")),inum(r.get("ht_away_goals")),inum(r.get("ft_home_goals")),inum(r.get("ft_away_goals")))
        if None not in (row[1],row[2],row[3],row[7],row[8],row[9],row[10]):vals.append(row)
    with sqlite3.connect(DB_PATH) as con:
        con.executemany("""INSERT INTO historical_matches(date,home_odds,draw_odds,away_odds,ht_home_odds,ht_draw_odds,ht_away_odds,ht_home_goals,ht_away_goals,ft_home_goals,ft_away_goals)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",vals);con.commit()
        total=con.execute("SELECT COUNT(*) FROM historical_matches").fetchone()[0]
    return jsonify(inserted=len(vals),total=total)

@app.post("/api/scan")
def scan_api():
    url=clean((request.get_json(silent=True) or {}).get("url"))
    if not valid_url(url):return jsonify(error="Geçerli Flashscore maç bağlantısı yapıştır."),400
    try:
        name,odds,rows=scrape(url);a=analyze(odds)
        return jsonify(match_name=name,current_odds=odds,analysis=a,raw_rows=rows)
    except Exception as e:return jsonify(error=f"{type(e).__name__}: {clean(e)}"),500

def port():
    s=socket.socket();s.bind(("127.0.0.1",0));p=s.getsockname()[1];s.close();return p
def main():
    init_db();p=port();url=f"http://127.0.0.1:{p}";threading.Thread(target=lambda:(time.sleep(1),webbrowser.open(url)),daemon=True).start();serve(app,host="127.0.0.1",port=p,threads=6)
if __name__=="__main__":main()
