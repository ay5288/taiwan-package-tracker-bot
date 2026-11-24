import os, re, json, datetime, urllib.parse, requests
from fastapi import FastAPI, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, FollowEvent, TextMessage,
    TextSendMessage, FlexSendMessage, BubbleContainer, CarouselContainer,
    BoxComponent, TextComponent, ButtonComponent, URIAction, MessageAction
)

app = FastAPI()
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "")

# ⚠️ 1. 請填入「網購取貨與包裹代收管家資料庫」的 Google Apps Script /exec 網址
GOOGLE_SHEET_API = "https://script.google.com/macros/s/AKfycbwcGdq2DqYRAM7-t8rcfjetfF2USbgW7maJaRCskjU7Q2cW7UYLV3rE5MWSBShQQrCptw/exec"
# ⚠️ 2. 請填入這個包裹管家機器人的 LINE 官方帳號 ID（包含 @ 符號，例如 @123abcde）
LINE_BOT_BASIC_ID = "@699zmvvf"
# ⚠️ 3. 請填入這個包裹管家機器人的 Render 公開網址（結尾不要加斜線）
RENDER_BASE_URL = "https://taiwan-package-tracker-bot.onrender.com"
# ⚠️ 4. 可填入您的 Notion 網購高回饋信用卡／居家收納／開箱好物嚴選館網址（未填自動隱藏）
NOTION_SHOPPING_URL = ""

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

LOCAL_PACKAGES = [
    {"pkg_id": "P1001", "store": "7-11超商", "item": "蝦皮生活百貨包裹", "code3": "852", "cod": 390, "due": "明日 23:59 截止", "urgent": True},
    {"pkg_id": "P1002", "store": "蝦皮店到店", "item": "手機殼與充電線", "code3": "109", "cod": 0, "due": "3天內取貨（已付款）", "urgent": False},
    {"pkg_id": "P1003", "store": "社區警衛室", "item": "momo 衛生紙箱購", "code3": "A04", "cod": 0, "due": "管理室代收中", "urgent": False}
]

def parse_pickup_sms(text: str):
    t = text.strip()
    store = "7-11超商"
    if any(k in t for k in ["全家", "FamilyMart", "Fami"]):
        store = "全家超商"
    elif any(k in t for k in ["蝦皮店到店", "智取店"]):
        store = "蝦皮店到店"
    elif any(k in t for k in ["萊爾富", "Hi-Life"]):
        store = "萊爾富超商"
    elif any(k in t for k in ["OK", "ok超商"]):
        store = "OK超商"
    elif any(k in t for k in ["警衛", "管理室", "社區", "櫃台"]):
        store = "社區警衛室"
    elif any(k in t for k in ["黑貓", "宅配", "新竹物流", "嘉里"]):
        store = "宅配到府"

    m_cod = re.search(r"(?:金額|應付|代收|貨到付款|NT\$|\$)\s*[:：]?\s*(\d{2,6})", t)
    cod = int(m_cod.group(1)) if m_cod else 0

    m_code = re.search(r"(?:末三碼|末3碼|取貨碼|編號|貨號|號碼)\s*[:：#]?\s*([A-Za-z0-9]{3,6})", t)
    if m_code:
        code3 = m_code.group(1)[-3:].upper()
    else:
        nums = re.findall(r"\b\d{3}\b", t)
        code3 = nums.pop(0) if nums else "888"

    m_due = re.search(r"(\d{1,2}[/月-]\d{1,2}日?)", t)
    due = f"{m_due.group(1)} 前取貨" if m_due else "5日內截止取貨"

    item_name = "網購包裹"
    for kw in ["蝦皮", "momo", "酷澎", "Coupang", "PChome", "淘寶", "博客來", "Uniqlo", "生活市集"]:
        if kw.lower() in t.lower():
            item_name = f"{kw} 網購包裹"
            break
    if len(t) <= 30 and not any(x in t for x in ["簡訊", "門市", "請於", "截止"]):
        cleaned = re.sub(r"\d{2,6}元?", "", t).strip()
        if cleaned:
            item_name = cleaned[:18]

    return {"store": store, "item": item_name, "code3": code3, "cod": cod, "due": due}
def call_sheet(payload: dict):
    try:
        r = requests.post(GOOGLE_SHEET_API, json=payload, timeout=12)
        return r.json()
    except Exception:
        return {}

def get_user_name(uid: str):
    try:
        return line_bot_api.get_profile(uid).display_name
    except Exception:
        return "買家"

@app.get("/")
def root():
    return {"status": "Online", "service": "Taiwan Package Tracker Pro App 2.0"}

@app.post("/api/pkg_add")
async def web_pkg_add(
    store: str = Form("7-11超商"),
    item: str = Form("網購包裹"),
    code3: str = Form("888"),
    cod: int = Form(0),
    due: str = Form("5日內取貨"),
    urgent: str = Form("")
):
    pid = f"P{int(datetime.datetime.utcnow().timestamp() * 1000)}"
    is_urg = (urgent == "1") or ("明" in due) or ("今" in due)
    pkg = {
        "pkg_id": pid,
        "store": store.strip() or "7-11超商",
        "item": item.strip() or "網購包裹",
        "code3": (code3.strip() or "888")[-3:].upper(),
        "cod": int(cod or 0),
        "due": due.strip() or "5日內取貨",
        "urgent": is_urg
    }
    LOCAL_PACKAGES.insert(0, pkg)
    call_sheet({
        "action": "add_pkg",
        "pkg_id": pid,
        "user_id": "web_app",
        "user_name": "戰情室用戶",
        "store": pkg["store"],
        "item_name": pkg["item"],
        "code3": pkg["code3"],
        "cod_amount": pkg["cod"],
        "due_date": pkg["due"]
    })
    return RedirectResponse(url="/pkg_app?msg=added", status_code=303)

@app.post("/api/pkg_done")
async def web_pkg_done(pkg_id: str = Form(...)):
    for idx, p in enumerate(LOCAL_PACKAGES):
        if p.get("pkg_id") == pkg_id:
            LOCAL_PACKAGES.pop(idx)
            break
    call_sheet({"action": "done_pkg", "pkg_id": pkg_id})
    return RedirectResponse(url="/pkg_app?msg=done", status_code=303)
@app.get("/pkg_app", response_class=HTMLResponse)
def package_tracker_web_app(msg: str = ""):
    S = chr(47)
    pkgs_json = json.dumps(LOCAL_PACKAGES, ensure_ascii=False)
    total_cnt = len(LOCAL_PACKAGES)
    total_cod = sum(int(x.get("cod", 0)) for x in LOCAL_PACKAGES)
    urgent_cnt = sum(1 for x in LOCAL_PACKAGES if x.get("urgent"))
    toast_map = {
        "added": "📦 新包裹已成功加入取貨倒數戰情室！",
        "done": "✅ 太棒了！已完成取貨核銷（記得開箱全程錄影喔）！"
    }
    toast_html = f'<div class="toast">{toast_map[msg]}</div>' if msg in toast_map else ""

    html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
    <meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no"/>
    <title>📦 網購取貨倒數 ＆ 包裹代收戰情室 Pro</title>
    <style>
      * {{ box-sizing: border-box; -webkit-tap-highlight-color: transparent; }}
      body {{ margin: 0; padding: 0 0 92px 0; font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", sans-serif; background: radial-gradient(circle at top right, #162238, #0B0E14 55%); color: #F8F9FA; min-height: 100vh; }}
      .topbar {{ background: rgba(13, 17, 26, 0.9); backdrop-filter: blur(16px); padding: 15px 18px; position: sticky; top: 0; z-index: 100; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid rgba(56, 189, 248, 0.22); }}
      .topbar h1 {{ margin: 0; font-size: 16px; font-weight: 800; color: #E0F2FE; }}
      .badge-pro {{ font-size: 11px; background: linear-gradient(135deg, #0284C7, #2563EB); color: #fff; padding: 4px 10px; border-radius: 20px; font-weight: 800; }}
      .wrap {{ max-width: 540px; margin: 0 auto; padding: 14px; }}
      .toast {{ background: rgba(16, 185, 129, 0.22); border: 1px solid #10B981; color: #A7F3D0; padding: 12px; border-radius: 14px; font-size: 13px; font-weight: 700; margin-bottom: 12px; text-align: center; }}
      .kpi-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-bottom: 14px; }}
      .kpi {{ background: rgba(22, 28, 42, 0.85); border: 1px solid rgba(255,255,255,0.1); border-radius: 16px; padding: 12px 8px; text-align: center; }}
      .kpi-num {{ font-size: 18px; font-weight: 900; color: #38BDF8; margin-top: 4px; }}
      .chips {{ display: flex; gap: 8px; overflow-x: auto; padding-bottom: 12px; scrollbar-width: none; }}
      .chip {{ white-space: nowrap; background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.12); color: #CBD5E1; padding: 8px 14px; border-radius: 20px; font-size: 13px; font-weight: 700; cursor: pointer; }}
      .chip.active {{ background: linear-gradient(135deg, #0284C7, #2563EB); border-color: #7DD3FC; color: #fff; box-shadow: 0 4px 14px rgba(37, 99, 235, 0.4); }}
      .pkg-card {{ background: rgba(22, 28, 42, 0.82); backdrop-filter: blur(16px); border: 1px solid rgba(255,255,255,0.12); border-radius: 20px; padding: 16px; margin-bottom: 12px; box-shadow: 0 10px 26px rgba(0,0,0,0.4); }}
      .pkg-card.urgent {{ border-color: rgba(245, 158, 11, 0.55); background: linear-gradient(135deg, rgba(245, 158, 11, 0.12), rgba(22, 28, 42, 0.88)); }}
      .code-box {{ background: #0B0E14; border: 1px dashed #38BDF8; border-radius: 12px; padding: 8px 12px; display: flex; justify-content: space-between; align-items: center; margin: 10px 0; }}
      .btn-row {{ display: flex; gap: 8px; margin-top: 10px; }}
      .btn {{ flex: 1; text-align: center; text-decoration: none; padding: 11px 6px; border-radius: 12px; font-size: 12px; font-weight: 800; cursor: pointer; border: none; color: #fff; }}
      .btn-green {{ background: linear-gradient(135deg, #10B981, #059669); }}
      .btn-blue {{ background: linear-gradient(135deg, #0284C7, #2563EB); }}
      .btn-glass {{ background: rgba(255,255,255,0.1); color: #E0F2FE; border: 1px solid rgba(255,255,255,0.16); }}
      .field {{ width: 100%; background: rgba(11, 14, 20, 0.85); border: 1px solid rgba(255,255,255,0.18); color: #fff; padding: 12px; border-radius: 12px; font-size: 14px; margin-top: 8px; }}
      .page {{ display: none; }}
      .page.active {{ display: block; }}
      .tabbar {{ position: fixed; bottom: 0; left: 0; right: 0; background: rgba(13, 17, 26, 0.95); backdrop-filter: blur(18px); border-top: 1px solid rgba(255,255,255,0.12); display: flex; padding: 8px 10px 14px; z-index: 120; }}
      .tab {{ flex: 1; text-align: center; color: #94A3B8; font-size: 12px; font-weight: 800; cursor: pointer; padding-top: 4px; }}
      .tab.active {{ color: #38BDF8; }}
      .tab-cta {{ background: linear-gradient(135deg, #0284C7, #2563EB); color: #fff; padding: 8px 14px; border-radius: 20px; font-size: 12px; }}
    </style></head><body>
    <div class="topbar"><h1>📦 取貨倒數 ＆ 包裹戰情室</h1><span class="badge-pro">物流管家 Pro</span></div>
    <div id="page-list" class="page active"><div class="wrap">
      {toast_html}
      <div class="kpi-grid">
        <div class="kpi"><div style="font-size:11px;color:#94A3B8;">📦 待領包裹</div><div class="kpi-num">{total_cnt} 件</div></div>
        <div class="kpi"><div style="font-size:11px;color:#94A3B8;">💵 需備現金</div><div class="kpi-num" style="color:#FBBF24;">${total_cod}</div></div>
        <div class="kpi"><div style="font-size:11px;color:#94A3B8;">🔥 急件提醒</div><div class="kpi-num" style="color:#F87171;">{urgent_cnt} 件</div></div>
      </div>
      <div class="chips">
        <div class="chip active" onclick="setFilter('all', this)">📦 全部待領</div>
        <div class="chip" onclick="setFilter('urgent', this)">🔥 48H急件</div>
        <div class="chip" onclick="setFilter('cvs', this)">🏪 超商取貨</div>
        <div class="chip" onclick="setFilter('shopee', this)">🛍️ 蝦皮店到店</div>
        <div class="chip" onclick="setFilter('guard', this)">🏢 社區警衛室</div>
      </div>
      <div id="pkg-box"></div>
    </div></div>

    <div id="page-add" class="page"><div class="wrap">
      <div class="pkg-card">
        <div style="font-size:17px;font-weight:900;color:#38BDF8;margin-bottom:4px;">➕ 登記新包裹 ＆ 設定取貨倒數</div>
        <div style="font-size:12px;color:#94A3B8;">登記後系統自動計算備妥現金總額，支援一鍵亮碼與請家人代領：</div>
        <form action="{S}api{S}pkg_add" method="post">
          <select name="store" class="field">
            <option value="7-11超商">🏪 7-11 超商取貨</option>
            <option value="全家超商">🏪 全家超商取貨</option>
            <option value="蝦皮店到店">🛍️ 蝦皮店到店／智取店</option>
            <option value="萊爾富超商">🏪 萊爾富 ／ OK 超商</option>
            <option value="社區警衛室">🏢 社區警衛室 ／ 管理室代收</option>
          </select>
          <input name="item" class="field" placeholder="📦 包裹內容物（如：蝦皮生活用品、momo衛生紙）" required/>
          <input name="code3" class="field" placeholder="🔢 取貨編號末三碼 ／ 管理室貨號（如：852 或 A04）" maxlength="6" required/>
          <input name="cod" type="number" class="field" placeholder="💵 貨到付款金額（已付款請填 0）" value="0"/>
          <input name="due" class="field" placeholder="⏰ 截止日期（如：11/28 前取貨 或 明日截止）" value="5日內截止取貨"/>
          <select name="urgent" class="field">
            <option value="0">🟢 一般包裹（正常倒數）</option>
            <option value="1">🔥 急件包裹（即將到期優先置頂警示）</option>
          </select>
          <button type="submit" class="btn btn-blue" style="width:100%;margin-top:12px;padding:14px;">🚀 加入取貨倒數戰情室</button>
        </form>
      </div>
    </div></div>

    <div class="tabbar">
      <div class="tab active" onclick="switchTab('list', this)">📦 待領包裹清單</div>
      <div class="tab" onclick="switchTab('add', this)"><span class="tab-cta">➕ 登記新包裹</span></div>
    </div>

    <script>
      const PKGS = {pkgs_json};
      const NL = String.fromCharCode(10);
      let curMode = 'all';
      function setFilter(m, el) {{ curMode = m; document.querySelectorAll('.chip').forEach(x => x.classList.remove('active')); el.classList.add('active'); renderPkgs(); }}
      function renderPkgs() {{
        const list = PKGS.filter(p => {{
          if (curMode === 'urgent') return p.urgent;
          if (curMode === 'cvs') return p.store.includes('7-11') || p.store.includes('全家') || p.store.includes('萊爾富') || p.store.includes('OK');
          if (curMode === 'shopee') return p.store.includes('蝦皮');
          if (curMode === 'guard') return p.store.includes('警衛') || p.store.includes('管理室');
          return true;
        }});
        const box = document.getElementById('pkg-box');
        if (!list.length) {{ box.innerHTML = '<div class="pkg-card" style="text-align:center;color:#94A3B8;">🎉 太棒了！此分類下目前沒有待領包裹！</div>'; return; }}
        box.innerHTML = list.map((p, idx) => {{
          const codTag = p.cod > 0 ? `<span style="color:#FBBF24;font-weight:900;">💵 貨到付款 $${{p.cod}}</span>` : `<span style="color:#34D399;font-weight:800;">✅ 已付款（0元純取貨）</span>`;
          const mapU = `https:{S}{S}://google.com{S}?q=${{encodeURIComponent(p.store)}}`;
          const helpTxt = '📦【麻煩幫我代領包裹】' + NL + '• 取貨地點：' + p.store + NL + '• 編號末三碼：' + p.code3 + NL + '• 包裹內容：' + p.item + NL + '• 應付金額：' + (p.cod > 0 ? '$' + p.cod + ' 元' : '已付款免付錢') + NL + '謝謝你！';
          const lineHelpU = `https:{S}{S}line.me{S}R{S}share?text=${{encodeURIComponent(helpTxt)}}`;
          return `<div class="pkg-card ${{p.urgent ? 'urgent' : ''}}">
            <div style="display:flex;justify-content:space-between;align-items:center;">
              <span style="font-size:12px;font-weight:800;color:#38BDF8;">${{p.store}}</span>
              <span style="font-size:11px;color:${{p.urgent ? '#FBBF24' : '#94A3B8'}};font-weight:700;">⏰ ${{p.due}}</span>
            </div>
            <div style="font-size:17px;font-weight:900;color:#fff;margin-top:4px;">${{p.item}}</div>
            <div class="code-box">
              <div><div style="font-size:10px;color:#94A3B8;">店員報號末三碼</div><div style="font-size:22px;font-weight:900;color:#38BDF8;letter-spacing:2px;">#${{p.code3}}</div></div>
              <div style="text-align:right;">${{codTag}}<div style="font-size:11px;color:#94A3B8;margin-top:2px;">結帳亮碼快速核對</div></div>
            </div>
            <div class="btn-row">
              <a class="btn btn-glass" href="${{mapU}}" target="_blank">🗺️ 導航門市</a>
              <a class="btn btn-blue" href="${{lineHelpU}}">🤝 請家人代領</a>
              <form action="{S}api{S}pkg_done" method="post" style="flex:1;margin:0;"><input type="hidden" name="pkg_id" value="${{p.pkg_id}}"/><button type="submit" class="btn btn-green" style="width:100%;">✅ 確認領取</button></form>
            </div>
          </div>`;
        }}).join('');
      }}
      function switchTab(t, el) {{ document.querySelectorAll('.page').forEach(x => x.classList.remove('active')); document.querySelectorAll('.tab').forEach(x => x.classList.remove('active')); document.getElementById('page-' + t).classList.add('active'); el.classList.add('active'); }}
      renderPkgs();
    </script></body></html>"""
    return HTMLResponse(content=html)
def make_pkg_app_card():
    S = chr(47)
    app_uri = f"{RENDER_BASE_URL}/pkg_app?openExternalBrowser=1"
    add_uri = f"https:{S}{S}line.me{S}R{S}oaMessage{S}{LINE_BOT_BASIC_ID}{S}?{urllib.parse.quote('登記包裹:')}"
    guard_uri = f"https:{S}{S}line.me{S}R{S}oaMessage{S}{LINE_BOT_BASIC_ID}{S}?{urllib.parse.quote('警衛室:')}"
    share_txt = urllib.parse.quote(f"📦【網購超商取貨倒數 ＆ 社區包裹代收管家 Pro】\n直接貼上超商取貨簡訊自動辨識末三碼與貨到付款金額，一鍵請家人代領！\n📲 免費加入：\nhttps:{S}{S}line.me{S}R{S}ti{S}p{S}{LINE_BOT_BASIC_ID}")
    share_uri = f"https:{S}{S}line.me{S}R{S}share?text={share_txt}"

    total_cnt = len(LOCAL_PACKAGES)
    total_cod = sum(int(x.get("cod", 0)) for x in LOCAL_PACKAGES)

    lines = []
    for p in LOCAL_PACKAGES[:3]:
        fire = "🔥" if p.get("urgent") else "📦"
        cod_s = f"${p['cod']}" if p.get("cod", 0) > 0 else "已付款"
        lines.append(f"{fire} [{p['store']}] #{p['code3']} · {p['item']} ({cod_s})\n   ⏰ {p['due']}")
    preview_txt = "\n".join(lines) if lines else "🎉 目前所有包裹皆已領取完畢！"

    bubble_1 = BubbleContainer(
        size="mega",
        header=BoxComponent(layout="vertical", background_color="#0D111A", padding_all="16px", contents=[
            TextComponent(text="📦 取貨倒數 ＆ 包裹代收管家 Pro", weight="bold", size="md", color="#E0F2FE", wrap=True),
            TextComponent(text="貼上取貨簡訊自動辨識、備妥現金統計、請家人代領", size="xs", color="#38BDF8", weight="bold", wrap=True, margin="xs")
        ]),
        body=BoxComponent(layout="vertical", spacing="sm", background_color="#FFFFFF", contents=[
            BoxComponent(layout="horizontal", spacing="sm", contents=[
                BoxComponent(layout="vertical", background_color="#161C2A", corner_radius="12px", padding_all="10px", align_items="center", contents=[
                    TextComponent(text="📦 待領包裹總數", size="xxs", color="#38BDF8", weight="bold"),
                    TextComponent(text=f"{total_cnt} 件", size="sm", color="#FFFFFF", weight="bold", margin="xs")
                ]),
                BoxComponent(layout="vertical", background_color="#161C2A", corner_radius="12px", padding_all="10px", align_items="center", contents=[
                    TextComponent(text="💵 櫃檯備妥現金", size="xxs", color="#FBBF24", weight="bold"),
                    TextComponent(text=f"${total_cod} 元", size="sm", color="#FFFFFF", weight="bold", margin="xs")
                ])
            ]),
            BoxComponent(layout="vertical", background_color="#F0F9FF", corner_radius="14px", padding_all="12px", contents=[
                TextComponent(text="📋 最新待領包裹看板（可直接貼簡訊新增）：", size="xs", color="#0369A1", weight="bold"),
                TextComponent(text=preview_txt, size="xs", color="#0F172A", wrap=True, margin="xs")
            ])
        ]),
        footer=BoxComponent(layout="vertical", spacing="sm", background_color="#FFFFFF", contents=[
            ButtonComponent(style="primary", color="#0284C7", height="sm", action=URIAction(label="🚀 開啟全螢幕取貨倒數戰情室 App", uri=app_uri)),
            BoxComponent(layout="horizontal", spacing="sm", contents=[
                ButtonComponent(style="primary", color="#10B981", height="sm", action=URIAction(label="➕ 登記超商包裹", uri=add_uri)),
                ButtonComponent(style="secondary", height="sm", action=URIAction(label="🏢 警衛室代收", uri=guard_uri))
            ]),
            BoxComponent(layout="horizontal", spacing="sm", contents=[
                ButtonComponent(style="secondary", height="sm", action=MessageAction(label="🏪 導航附近超商", text="附近超商")),
                ButtonComponent(style="primary", color="#F59E0B", height="sm", action=MessageAction(label="✅ 領取最新包裹", text="領取最新包裹"))
            ])
        ])
    )

    host = "maps." + "google.com"
    tools_btns = [
        BoxComponent(layout="horizontal", spacing="sm", contents=[
            ButtonComponent(style="primary", color="#0284C7", height="sm", action=URIAction(label="🏪 7-11 門市", uri=f"https:{S}{S}{host}{S}?q=7-11")),
            ButtonComponent(style="primary", color="#10B981", height="sm", action=URIAction(label="🏪 全家門市", uri=f"https:{S}{S}{host}{S}?q=全家便利商店"))
        ]),
        BoxComponent(layout="horizontal", spacing="sm", contents=[
            ButtonComponent(style="secondary", height="sm", action=URIAction(label="🛍️ 蝦皮店到店", uri=f"https:{S}{S}{host}{S}?q=蝦皮店到店")),
            ButtonComponent(style="secondary", height="sm", action=MessageAction(label="🎬 開箱錄影須知", text="開箱須知"))
        ]),
        ButtonComponent(style="primary", color="#2563EB", height="sm", action=URIAction(label="📤 分享給家人／網購同好一起管包裹", uri=share_uri))
    ]
    if NOTION_SHOPPING_URL.startswith("http"):
        tools_btns.append(ButtonComponent(style="secondary", height="sm", action=URIAction(label="💳 網購高回饋神卡／開箱好物推薦", uri=NOTION_SHOPPING_URL)))

    bubble_2 = BubbleContainer(
        size="mega",
        header=BoxComponent(layout="vertical", background_color="#0D111A", padding_all="16px", contents=[
            TextComponent(text="🗺️ 超商取貨導航 ＆ 網購防雷工具", weight="bold", size="md", color="#E0F2FE", wrap=True),
            TextComponent(text="一鍵找 7-11、全家、蝦皮店到店與開箱退貨須知", size="xs", color="#38BDF8", weight="bold", wrap=True, margin="xs")
        ]),
        body=BoxComponent(layout="vertical", spacing="xs", background_color="#FFFFFF", contents=[
            TextComponent(text="👈 向左滑動返回「取貨倒數戰情室主畫面」", size="xxs", color="#64748B", weight="bold")
        ]),
        footer=BoxComponent(layout="vertical", spacing="sm", background_color="#FFFFFF", contents=tools_btns)
    )
    return CarouselContainer(contents=[bubble_1, bubble_2])
@app.post("/callback")
async def callback(request: Request):
    sig = request.headers.get("X-Line-Signature", "")
    body = await request.body()
    try:
        handler.handle(body.decode("utf-8"), sig)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    return "OK"

@handler.add(FollowEvent)
def on_follow(event):
    card = make_pkg_app_card()
    line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="📦 網購取貨倒數 ＆ 包裹代收管家 Pro 已啟動", contents=card))

@handler.add(MessageEvent, message=TextMessage)
def on_text(event):
    uid = event.source.user_id
    uname = get_user_name(uid)
    txt = event.message.text.strip()

    try:
        # 1. 一鍵領取最新包裹核銷
        if txt == "領取最新包裹":
            if len(LOCAL_PACKAGES) > 0:
                done_item = LOCAL_PACKAGES.pop(0)
                call_sheet({"action": "done_pkg", "pkg_id": done_item["pkg_id"]})
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"✅ 已核銷領取：【{done_item['store']}】{done_item['item']}（#{done_item['code3']}）！\n🎬 貼心提醒：拆封包裹前請全程錄影，保障退換貨權益喔！"))
            else:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="🎉 目前沒有待領包裹囉！"))
            return

        # 2. 開箱錄影須知與附近超商快捷
        if txt == "開箱須知":
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="🎬【網購開箱防雷 3 步驟】\n1. 拆封前先拍清楚外箱「物流託運單條碼」與封箱膠帶。\n2. 一鏡到底錄影開箱並清點商品數量與外觀。\n3. 若有缺件或破損，24 小時內透過蝦皮／momo 系統申請退貨最安心！"))
            return

        if txt == "附近超商":
            S = chr(47)
            host = "maps." + "google.com"
            u = f"https:{S}{S}{host}{S}?q={urllib.parse.quote('便利商店 蝦皮店到店')}"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"🏪 點擊下方連結一鍵導航附近超商與蝦皮店到店：\n{u}"))
            return

        # 3. 偵測超商取貨簡訊或「登記包裹: / 警衛室:」指令自動解析入庫
        sms_keywords = ["簡訊", "取貨", "到店", "門市", "截止", "包裹", "編號", "末三碼", "貨到付款", "蝦皮", "全家", "7-11", "萊爾富", "警衛室", "管理室", "登記包裹:"]
        is_add_cmd = txt.startswith("登記包裹:") or txt.startswith("登記包裹：") or txt.startswith("警衛室:") or txt.startswith("警衛室：")
        if is_add_cmd or (any(k in txt for k in sms_keywords) and txt not in ["包裹", "查包裹", "我的包裹"]):
            raw = txt.split(":", 1)[-1].split("：", 1)[-1].strip() if is_add_cmd else txt
            if not raw:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="📦 請直接貼上超商取貨簡訊，或輸入「登記包裹:7-11 蝦皮衣服 390元 末三碼852」喔！"))
                return
            parsed = parse_pickup_sms(raw)
            if txt.startswith("警衛室"):
                parsed["store"] = "社區警衛室"
            pid = f"P{int(datetime.datetime.utcnow().timestamp() * 1000)}"
            is_urg = ("明" in parsed["due"]) or ("今" in parsed["due"])
            LOCAL_PACKAGES.insert(0, {
                "pkg_id": pid,
                "store": parsed["store"],
                "item": parsed["item"],
                "code3": parsed["code3"],
                "cod": parsed["cod"],
                "due": parsed["due"],
                "urgent": is_urg
            })
            call_sheet({
                "action": "add_pkg",
                "pkg_id": pid,
                "user_id": uid,
                "user_name": uname,
                "store": parsed["store"],
                "item_name": parsed["item"],
                "code3": parsed["code3"],
                "cod_amount": parsed["cod"],
                "due_date": parsed["due"]
            })
            card = make_pkg_app_card()
            line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text=f"📦 已自動建檔：{parsed['store']} #{parsed['code3']}", contents=card))
            return

        # 4. 預設顯示物流戰情室雙卡輪播主畫面
        card = make_pkg_app_card()
        line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="📦 取貨倒數 ＆ 包裹代收管家 Pro", contents=card))
    except Exception as e:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"📦 系統小提示：{str(e)[:60]}（請輸入「包裹」刷新畫面）"))
