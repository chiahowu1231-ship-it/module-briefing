"""
MODULE INDUSTRY BRIEFING
全球模組產業日報 — 5G / RF / IoT / ODM 供應鏈每日情報

當 RSS snippet 內容不足時，自動抓取原文網頁擷取內文，確保 AI 摘要基於實際內容。
"""

import os, re, smtplib, time, random, socket, feedparser
import urllib.request, urllib.error
from google import genai

# ✅ 全域 socket timeout（防止 feedparser / urllib 無限掛住）
socket.setdefaulttimeout(15)
from datetime import datetime, timedelta, timezone
from html import escape
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import parsedate_to_datetime

# ==========================================================
# 環境變數
# ==========================================================
GEMINI_API_KEY     = os.getenv("GEMINI_API_KEY")
GMAIL_USER         = os.getenv("GMAIL_USER")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
GMAIL_TO           = os.getenv("GMAIL_TO", "").strip()
GMAIL_BCC          = os.getenv("GMAIL_BCC", "").strip()

TZ_TAIPEI = timezone(timedelta(hours=8))
PER_SOURCE_LIMIT  = int(os.getenv("PER_SOURCE_LIMIT", "30"))
MAX_TOTAL_ITEMS   = int(os.getenv("MAX_TOTAL_ITEMS", "100"))
BATCH_SIZE        = int(os.getenv("BATCH_SIZE", "20"))
GEMINI_TIMEOUT    = int(os.getenv("GEMINI_TIMEOUT_SEC", "120"))
GEMINI_RETRIES    = int(os.getenv("GEMINI_MAX_RETRIES", "4"))
ALLOW_UNKNOWN_DATE = False

# 內文擷取設定
ENRICH_MIN_CHARS  = int(os.getenv("ENRICH_MIN_CHARS", "120"))   # snippet 低於此字數就去抓原文
ENRICH_TIMEOUT    = int(os.getenv("ENRICH_TIMEOUT", "10"))       # 每頁抓取 timeout (秒)
ENRICH_MAX_ITEMS  = int(os.getenv("ENRICH_MAX_ITEMS", "50"))     # 最多抓幾篇原文

# ==========================================================
# 來源定義
# ==========================================================
NEWS_SOURCES = {
    # ━━━ CAT1: 硬體技術與射頻 ━━━
    "Everything RF":          ("https://www.everythingrf.com/news/rss", "CAT1"),
    "Microwave Journal":      ("https://www.microwavejournal.com/rss/news", "CAT1"),
    "EDN":                    ("https://www.edn.com/feed/", "CAT1"),
    "EE Times":               ("https://www.eetimes.com/feed/", "CAT1"),
    "EE Times Wireless/RF":   ("https://www.eetimes.com/category/wireless-rf/feed/", "CAT1"),
    "5G Technology World":    ("https://www.5gtechnologyworld.com/feed/", "CAT1"),
    "RF Globalnet":           ("https://www.rfglobalnet.com/rss/rss.ashx", "CAT1"),
    "Electronics Weekly 5G":  ("https://www.electronicsweekly.com/search/5G/feed/rss2", "CAT1"),
    "Semiconductor Eng.":     ("https://semiengineering.com/feed/", "CAT1"),
    "FierceElectronics":      ("https://www.fierceelectronics.com/rss/xml", "CAT1"),
    "Embedded.com":           ("https://www.embedded.com/feed/", "CAT1"),
    "TechBriefs RF":          ("https://www.techbriefs.com/rss/all", "CAT1"),
    "EE Times Europe":        ("https://www.eetimes.eu/feed/", "CAT1"),
    "Microwaves & RF":        ("https://www.mwrf.com/rss", "CAT1"),
    "EE Times Taiwan":        ("https://www.eettaiwan.com/feed/", "CAT1"),
    "IEEE Spectrum":          ("https://spectrum.ieee.org/feeds/feed.rss", "CAT1"),
    "IEEE Comm. Letters":     ("https://ieeexplore.ieee.org/rss/TOC80.XML", "CAT1"),
    "IEEE Trans. Wireless":   ("https://ieeexplore.ieee.org/rss/TOC8352948.XML", "CAT1"),

    # ━━━ CAT2: 產業趨勢與營運商 ━━━
    "Fierce Wireless":        ("https://www.fiercewireless.com/rss/xml", "CAT2"),
    "Fierce Network":         ("https://www.fierce-network.com/rss/xml", "CAT2"),
    "6GWorld":                ("https://6gworld.com/feed", "CAT2"),
    "Light Reading":          ("https://www.lightreading.com/rss_simple", "CAT2"),
    "Mobile World Live":      ("https://www.mobileworldlive.com/feed/", "CAT2"),
    "RCR Wireless":           ("https://www.rcrwireless.com/feed", "CAT2"),
    "Telecoms.com":           ("https://telecoms.com/feed/", "CAT2"),
    "SDxCentral":             ("https://www.sdxcentral.com/feed/", "CAT2"),
    "Capacity Media":         ("https://www.capacitymedia.com/rss", "CAT2"),
    "Total Telecom":          ("https://totaltele.com/feed/", "CAT2"),
    "The Fast Mode":          ("https://www.thefastmode.com/feed", "CAT2"),
    "5G Americas":            ("https://www.5gamericas.org/feed/", "CAT2"),
    "GSA":                    ("https://gsacom.com/news/feed/", "CAT2"),
    "5G-PPP":                 ("https://5g-ppp.eu/feed/", "CAT2"),
    "M2M Now":                ("https://m2mnow.biz/feed/", "CAT2"),
    "ConnectedWorld":         ("https://connectedworld.com/feed/", "CAT2"),
    # 台灣供應鏈媒體
    "經濟日報 科技":           ("https://money.udn.com/rssfeed/news/1001/5591/12925", "CAT2"),
    "工商時報 科技":           ("https://ctee.com.tw/feed", "CAT2"),
    "科技新報 TechNews":      ("https://technews.tw/feed/", "CAT2"),

    # ━━━ CAT3: 競爭對手動態 (ODM / 模組廠) ━━━
    "Digitimes":              ("https://www.digitimes.com/rss/rss.asp", "CAT3"),
    # 韓國科技媒體
    "ETNews (Korea)":         ("https://english.etnews.com/rss/allArticle.xml", "CAT3"),
    "Pulse News Korea":       ("https://pulse.mk.co.kr/rss/", "CAT3"),
    "The Elec":               ("https://www.thelec.net/rss/S1N3.xml", "CAT3"),
    # 日本科技媒體
    "EE Times Japan":         ("https://eetimes.itmedia.co.jp/rss/2.0/eetimes.xml", "CAT1"),
    "ITmedia Mobile":         ("https://rss.itmedia.co.jp/rss/2.0/mobile.xml", "CAT3"),
    "ケータイ Watch":          ("https://k-tai.watch.impress.co.jp/data/rss/1.0/ktw/feed.rdf", "CAT3"),
    "Nikkei xTECH":          ("https://xtech.nikkei.com/rss/index.rdf", "CAT3"),
    "Nikkei Asia Tech":       ("https://asia.nikkei.com/RSS/feed.aspx?t=technology", "CAT2"),
    "NTT Technical Review":   ("https://www.ntt.com/en/journal/rss.xml", "CAT5"),
    # 全球模組五強
    "Quectel Newsroom":       ("https://www.quectel.com/news/feed/", "CAT3"),             # 移遠 全球市佔第一 / AI 智能模組
    "Quectel Press":          ("https://www.quectel.com/category/press-releases/feed/", "CAT3"),
    "Fibocom News":           ("https://www.fibocom.com/en/news/feed/", "CAT3"),          # 廣和通 5G-A / Wi-Fi 8 CPE
    "Fibocom Blog":           ("https://www.fibocom.com/en/blog/feed/", "CAT3"),
    "Telit Cinterion":        ("https://www.telit.com/blog/feed/", "CAT3"),
    "u-blox News":            ("https://www.u-blox.com/en/newsroom/rss.xml", "CAT3"),
    "Semtech (Sierra)":       ("https://www.sierrawireless.com/resources/blog/feed/", "CAT3"),
    # 車載模組
    "Rolling Wireless":       ("https://www.rollingwireless.com/en/news/feed", "CAT3"),
    "Kontron IoT":            ("https://www.kontron.com/en/blog/rss", "CAT3"),
    # 中國模組廠
    "China Mobile IoT":       ("https://www.chinamobileltd.com/en/ir/press_rss.xml", "CAT3"),
    "SIMCom News":            ("https://www.simcom.com/news/feed", "CAT3"),
    "MeiG Smart":             ("https://www.meiglink.com/en/news/feed", "CAT3"),
    "Neoway News":            ("https://www.neoway.com/en/news/feed", "CAT3"),
    # 產業媒體（模組/IoT 專題）
    "IoT World Today":        ("https://www.iotworldtoday.com/feed", "CAT3"),
    "IoT For All":            ("https://www.iotforall.com/feed", "CAT3"),
    "IoT Now":                ("https://iot-now.com/feed/", "CAT3"),
    "IoT Business News":      ("https://iotbusinessnews.com/feed/", "CAT3"),

    # ━━━ CAT4: 關鍵元件供應商 ━━━
    "Qualcomm Newsroom":      ("https://www.qualcomm.com/news/releases/feed/rss", "CAT4"),  # Press releases
    "Qualcomm OnQ":           ("https://www.qualcomm.com/news/onq/feed/rss", "CAT4"),       # On-Q Blog
    "Qualcomm IR News":       ("https://news.google.com/rss/search?q=site%3Ainvestor.qualcomm.com+press+release&hl=en&gl=US&ceid=US:en", "CAT4"),  # IR proxy（原頁無RSS）
    "MediaTek Press":         ("https://corp.mediatek.com/news-events/press-releases/feed", "CAT4"),
    "MediaTek Blog":          ("https://corp.mediatek.com/news-events/blog/feed", "CAT4"),
    "Fierce Wireless Qualcomm": ("https://www.fiercewireless.com/tag/qualcomm/rss", "CAT4"), # Qualcomm tag
    "Qorvo Blog":             ("https://www.qorvo.com/design-hub/blog/rss", "CAT4"),
    "Skyworks News":          ("https://www.skyworksinc.com/en/Press-Releases/rss", "CAT4"),
    "Murata News":            ("https://www.murata.com/en-global/api/rss/newsrss", "CAT4"),
    "TDK News":               ("https://www.tdk.com/en/news_center/press/rss", "CAT4"),
    "Keysight Blog":          ("https://blogs.keysight.com/feed/", "CAT4"),
    "Tom's Hardware":         ("https://www.tomshardware.com/feeds/all", "CAT4"),
    # IoT 晶片 / 模組核心元件供應商
    "Nordic Semiconductor":   ("https://www.nordicsemi.com/News?format=rss", "CAT4"),
    "Sequans Comms":          ("https://www.sequans.com/press-releases/feed/", "CAT4"),
    "Digi International":     ("https://www.digi.com/blog/rss", "CAT4"),

    # ━━━ CAT5: 標準與規範 ━━━
    "3GPP News":              ("https://www.3gpp.org/news-events/rss", "CAT5"),
    "ETSI":                   ("https://www.etsi.org/newsroom/rss", "CAT5"),
    "Wi-Fi Alliance":         ("https://www.wi-fi.org/news-events/newsroom/feed", "CAT5"),
    "GSMA News":              ("https://www.gsma.com/newsroom/rss/", "CAT5"),
    # SEMI 官網無標準 RSS；改用 PR Newswire SEMI tag feed 作替代
    "SEMI (PRN)":             ("https://www.prnewswire.com/rss/news-releases-list.rss?tagid=semi", "CAT5"),
    # ESA 歐洲太空總署 — 衛星通訊 / NTN / 太空 IoT
    "ESA Connectivity":       ("https://www.esa.int/rssfeed/Our_Activities/Connectivity_and_Secure_Communications", "CAT5"),
    # Science|Business — EU Horizon 研發政策與資金動態（半導體/6G/IoT 計畫）
    "Science|Business":       ("https://sciencebusiness.net/feed", "CAT5"),
    # LPWAN 與短距離連接標準組織
    "LoRa Alliance":          ("https://lora-alliance.org/feed/", "CAT5"),
    "CSA (Matter/Zigbee)":    ("https://csa-iot.org/feed/", "CAT5"),

    # ━━━ CAT6: 市場研究與分析機構 ━━━
    "TrendForce":             ("https://www.trendforce.com/presscenter/rss/news.xml", "CAT6"),
    "TrendForce 中文":         ("https://www.trendforce.com.tw/presscenter/rss/news.xml", "CAT6"),
    "TechInsights Blog":      ("https://www.techinsights.com/blog/feed", "CAT6"),
    "ABI Research":           ("https://www.abiresearch.com/press/feed/", "CAT6"),
    "ABI Research IoT HW":   ("https://www.abiresearch.com/category/internet-of-things/iot-hardware/feed/", "CAT6"),
    "Yole Intelligence":      ("https://www.yolegroup.com/feed/", "CAT6"),
    "Dell'Oro Group":         ("https://www.delloro.com/feed/", "CAT6"),
    "Omdia":                  ("https://omdia.tech.informa.com/rss/insights", "CAT6"),
    # Counterpoint Research — RSS 由程式動態決定（見 _try_counterpoint_rss）
    # 此欄位僅作 placeholder，fetch_news 會攔截並走 fallback 流程
    "Counterpoint Research":  ("__COUNTERPOINT_FALLBACK__", "CAT6"),
    "IoT Analytics":          ("https://iot-analytics.com/feed/", "CAT6"),
    "IDC Blog":               ("https://blogs.idc.com/feed/", "CAT6"),
    # 管理顧問 — 產業展望報告
    "Deloitte TMT":           ("https://www.deloitte.com/us/en/insights/industry/technology.rss.xml", "CAT6"),
    "McKinsey Tech":          ("https://www.mckinsey.com/industries/technology-media-and-telecommunications/our-insights/rss", "CAT6"),
    "Gartner Newsroom":       ("https://www.gartner.com/en/newsroom/rss", "CAT6"),
    "KPMG Tech":              ("https://kpmg.com/us/en/insights-by-topic/technology.rss.xml", "CAT6"),
}

CAT_META = {
    "CAT1": {"zh":"硬體技術與射頻","en":"RF & Baseband","color":"#818CF8","dark":"#312E81","light":"#EEF2FF",
             "icon":"&#9889;","desc":"RFFE 整合 &middot; AiP 封裝 &middot; 信號完整性 &middot; 嵌入式系統 &middot; 電路設計"},
    "CAT2": {"zh":"產業趨勢與營運商","en":"Operators & Trends","color":"#22D3EE","dark":"#164E63","light":"#ECFEFF",
             "icon":"&#127758;","desc":"5G 部署 &middot; 頻段規劃 &middot; 電信策略 &middot; 台灣供應鏈 &middot; 市場預測"},
    "CAT3": {"zh":"競爭對手動態","en":"ODM & Module Vendors","color":"#F87171","dark":"#7F1D1D","light":"#FEF2F2",
             "icon":"&#127981;","desc":"Quectel(AI模組/市佔#1) &middot; Fibocom(5G-A/Wi-Fi 8) &middot; China Mobile IoT &middot; Telit &middot; Rolling Wireless &middot; SIMCom &middot; MeiG &middot; ODM"},
    "CAT4": {"zh":"關鍵元件供應商","en":"Key Components","color":"#34D399","dark":"#064E3B","light":"#ECFDF5",
             "icon":"&#128268;","desc":"晶片 Roadmap &middot; RFFE &middot; 被動元件 &middot; 基材"},
    "CAT5": {"zh":"標準與規範","en":"Standards & Spectrum","color":"#FBBF24","dark":"#78350F","light":"#FFFBEB",
             "icon":"&#128220;","desc":"3GPP Release &middot; 頻譜拍賣 &middot; 認證法規"},
    "CAT6": {"zh":"市場研究與分析","en":"Market Research","color":"#EC4899","dark":"#831843","light":"#FDF2F8",
             "icon":"&#128202;","desc":"TrendForce &middot; TechInsights &middot; IDC &middot; Counterpoint &middot; Omdia &middot; Deloitte &middot; McKinsey &middot; Gartner &middot; KPMG"},
}
CAT_ORDER = ["CAT6","CAT2","CAT3","CAT1","CAT4","CAT5"]

# ==========================================================
# 預篩
# ==========================================================
EXCLUDE_KW = ["celebrity","red carpet","Grammy","Oscar","box office","movie review",
              "Premier League","Champions League","NBA","NFL","FIFA","recipe","cooking"]
PRIORITY_KW = ["5G","6G","LTE","RedCap","eRedCap","NR","modem","RFFE","RF front","antenna","AiP",
               "mmWave","sub-6","CA ","EN-DC","DSS","FDD","TDD","OFDM","MIMO","beamforming",
               "module","modul","ODM","OEM","Quectel","Fibocom","Sierra","Telit","u-blox",
               "Rolling Wireless","Kontron","SIMCom","MeiG","美格","Neoway","Gosuncn",
               "Sunsea","Longsung","龍旗","華勤","SG Wireless","Trasna","Eagle Electronics",
               "China Mobile IoT","中國移動","中移物聯",
               "Qualcomm","Snapdragon","MediaTek","Dimensity","Helio",
               "Qorvo","Skyworks","Murata","MLCC","filter","duplexer","PA ","LNA",
               "3GPP","Release 18","Release 19","Rel-18","Rel-19","5G-Advanced","6G-Advanced",
               "AI-RAN","AI RAN","AI-native","agentic RAN","O-RAN","Open RAN",
               "FR3","7GHz","upper mid-band","golden band","sub-24GHz",
               "spectrum","頻段","頻譜","IoT","cellular","base station","small cell",
               "NTN","satellite","non-terrestrial","LEO","NB-IoT","eMTC","LPWA",
               "PCB","laminate","Rogers","substrate","packaging","SiP","SoC",
               "Compal","仁寶","Pegatron","和碩","Wistron","緯創","Foxconn","鴻海",
               "Samsung","semiconductor","半導體","wafer","foundry","TSMC","台積電",
               "Digitimes","電子時報","Counterpoint","TechInsights","teardown",
               "TrendForce","集邦","Omdia","ABI Research","Yole","Dell'Oro","IDC",
               "Deloitte","McKinsey","Gartner","KPMG",
               "SK Hynix","SK hynix","SK Telecom","KT Corp","LG Electronics",
               "經濟日報","工商時報","科技新報","TechNews","embedded","RTOS",
               "market share","forecast","shipment","revenue",
               "IEEE","Transactions","Letters","xTECH","ITmedia","GSA","eettaiwan",
               "MWC","CES","investor","earnings","press release","Qualcomm IR",
               "MediaTek CES","MediaTek MWC","Snapdragon Summit","Dimensity Summit"]

def _should_exclude(title, snippet):
    text = (title+" "+snippet).lower()
    for kw in PRIORITY_KW:
        if kw.lower() in text: return False
    for kw in EXCLUDE_KW:
        if kw.lower() in text: return True
    return False


# ==========================================================
# 原文擷取：當 RSS snippet 太短時，去網頁抓內文
# ==========================================================
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"

def _fetch_article_text(url, timeout=ENRICH_TIMEOUT):
    """抓取網頁，擷取 <p> 段落內文，回傳純文字。"""
    if not url:
        return ""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "text/html"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            # 只處理 HTML
            ct = resp.headers.get("Content-Type", "")
            if "html" not in ct.lower():
                return ""
            raw = resp.read(500_000)  # 最多讀 500KB
            # 嘗試偵測編碼
            charset = "utf-8"
            if "charset=" in ct:
                charset = ct.split("charset=")[-1].strip().split(";")[0]
            html_text = raw.decode(charset, errors="replace")

        # 擷取 <article> 或 <main> 區塊（如有）
        article_match = re.search(r'<article[^>]*>(.*?)</article>', html_text, re.DOTALL | re.IGNORECASE)
        main_match = re.search(r'<main[^>]*>(.*?)</main>', html_text, re.DOTALL | re.IGNORECASE)
        search_zone = article_match.group(1) if article_match else (main_match.group(1) if main_match else html_text)

        # 提取所有 <p> 標籤內容
        paragraphs = re.findall(r'<p[^>]*>(.*?)</p>', search_zone, re.DOTALL | re.IGNORECASE)
        if not paragraphs:
            return ""

        # 清除 HTML tags + 合併
        clean_parts = []
        for p in paragraphs:
            text = re.sub(r'<[^>]+>', '', p).strip()
            text = re.sub(r'\s+', ' ', text)
            # 過濾太短的段落（通常是按鈕文字或 UI 元素）
            if len(text) > 30:
                clean_parts.append(text)

        return " ".join(clean_parts)[:2000]  # 最多 2000 字元

    except Exception:
        return ""


def enrich_short_snippets(items):
    """對 snippet 字數不足的項目，去抓原文網頁補充內容。"""
    to_enrich = [(i, it) for i, it in enumerate(items) if len(it.get("snippet","")) < ENRICH_MIN_CHARS and it.get("link")]
    if not to_enrich:
        return

    count = min(len(to_enrich), ENRICH_MAX_ITEMS)
    print(f"  📄 {count}/{len(to_enrich)} items need full-text fetch (snippet < {ENRICH_MIN_CHARS} chars)...")
    fetched = 0

    for idx, (i, it) in enumerate(to_enrich[:count]):
        url = it["link"]
        text = _fetch_article_text(url)
        if text and len(text) > len(it.get("snippet","")):
            items[i]["snippet"] = text[:2000]
            fetched += 1
        # 禮貌延遲，避免被封
        if idx < count - 1:
            time.sleep(0.5)

    print(f"  📄 Enriched {fetched}/{count} articles with full text")


# ==========================================================
# Counterpoint Research — 三層策略：
#   Layer 1: 原生 RSS（若 Counterpoint 日後重新提供）
#   Layer 2: Google News RSS（搜尋 site:counterpointresearch.com/en/insights）
#   Layer 3: 個別 SSR 文章頁直接抓取（列表頁是 CSR 無法爬，文章頁是 SSR 可抓）
# ==========================================================
_COUNTERPOINT_RSS_CANDIDATES = [
    # 原生 RSS（目前無效，但保留以備未來重啟）
    "https://counterpointresearch.com/en/insights/feed/",
    "https://counterpointresearch.com/feed/",
    "https://www.counterpointresearch.com/insights/feed/",
    # Google News RSS — 自動索引最新文章，不需要任何 key
    "https://news.google.com/rss/search?q=site:counterpointresearch.com/en/insights&hl=en-US&gl=US&ceid=US:en",
    # Bing News RSS 備援
    "https://www.bing.com/news/search?q=site:counterpointresearch.com+insights&format=rss",
]

# 已知的 IoT/5G/模組相關 insight slug patterns（供 Layer 3 直接抓取）
# 格式：quarterly 報告通常有穩定 slug 規律
_COUNTERPOINT_KNOWN_SLUGS = [
    # Cellular IoT module quarterly — 自動產生最近 6 季的 slug 嘗試
    # 實際存在的會成功抓到，不存在的會 404 靜默跳過
]


def _try_counterpoint_rss():
    """
    Layer 1 & 2：嘗試原生 RSS 和 Google News RSS。
    回傳第一個有 entries 的 feedparser feed；全失敗回傳 None。
    """
    for url in _COUNTERPOINT_RSS_CANDIDATES:
        try:
            feed = feedparser.parse(url)
            entries = getattr(feed, "entries", None) or []
            if entries:
                label = "Google News" if "news.google.com" in url else \
                        "Bing News" if "bing.com" in url else "原生 RSS"
                print(f"    ✅ Counterpoint {label} OK → {len(entries)} entries")
                # Google/Bing News 的 link 指向 Google 跳轉頁，要換成原始 URL
                if "news.google.com" in url or "bing.com" in url:
                    _fix_news_aggregator_links(entries)
                return feed
        except Exception:
            pass
    return None


def _fix_news_aggregator_links(entries):
    """
    Google News / Bing News 的 entry.link 是 aggregator 跳轉 URL。
    嘗試從 entry.source 或 entry.id 還原出 counterpointresearch.com 原始 URL。
    無法還原的保留跳轉 URL（enrich_short_snippets 會去抓原文）。
    """
    for entry in entries:
        # Google News: source url 常在 entry.source.href 或 entry.links
        src = getattr(entry, "source", None)
        if src:
            href = getattr(src, "href", "") or (src.get("href", "") if isinstance(src, dict) else "")
            if "counterpointresearch.com" in href:
                entry.link = href
                continue
        # 嘗試從 entry.id 解析（Google News id 有時含原始 URL base64）
        # 保留 aggregator URL，讓 enrich 去跟蹤
        pass


def _fetch_counterpoint_article(url, timeout=15):
    """
    抓取 Counterpoint /en/insights/<slug> SSR 文章頁。
    頁面是 SSR，包含 <h1> 標題、<time> 日期、<p> 內文。
    回傳 dict {title, snippet, published_dt} 或 None。
    """
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": _UA, "Accept": "text/html", "Accept-Language": "en-US,en;q=0.9"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            raw = resp.read(600_000)
        html = raw.decode("utf-8", errors="replace")

        # 標題：<h1>
        h1 = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.DOTALL | re.IGNORECASE)
        title = re.sub(r'<[^>]+>', '', h1.group(1)).strip() if h1 else ""
        if not title:
            return None

        # 日期：<time datetime="...">
        time_tag = re.search(r'<time[^>]+datetime="([^"]+)"', html, re.IGNORECASE)
        dt = _parse_dt(time_tag.group(1)) if time_tag else None

        # 內文：找 <article> 或 <main>，取所有 <p>
        zone_m = re.search(r'<(?:article|main)[^>]*>(.*?)</(?:article|main)>', html, re.DOTALL | re.IGNORECASE)
        zone = zone_m.group(1) if zone_m else html
        paragraphs = re.findall(r'<p[^>]*>(.*?)</p>', zone, re.DOTALL | re.IGNORECASE)
        clean = []
        for p in paragraphs:
            t = re.sub(r'<[^>]+>', ' ', p).strip()
            t = re.sub(r'\s+', ' ', t)
            if len(t) > 40:
                clean.append(t)
        snippet = " ".join(clean)[:2000]

        return {"title": title, "dt": dt, "snippet": snippet}
    except Exception:
        return None


def _scrape_counterpoint_insights(cutoff, per_limit):
    """
    Layer 3：當所有 RSS 失敗時的最終備援。
    /en/insights 列表頁是 CSR（JS 渲染），無法直接爬取文章列表。
    改用 Google Site Search 的 Atom feed 作為文章發現機制，
    再逐篇抓 SSR 文章頁取得標題、日期、內文。
    """
    BASE = "https://counterpointresearch.com"
    articles = []

    # ── 用 Google Custom Search RSS 找最近文章 URL ────────────
    # 這是 Google 的公開免費 Atom，不需要 API key
    discovery_feeds = [
        "https://news.google.com/rss/search?q=counterpointresearch+insight+IoT+5G&hl=en&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=Counterpoint+Research+cellular+module+5G+IoT&hl=en&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=Counterpoint+Research+semiconductor+network+telecom&hl=en&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=Counterpoint+Research+IoT+hardware+module+shipment&hl=en&gl=US&ceid=US:en",  # IoT section
    ]
    seen_urls: set = set()
    for feed_url in discovery_feeds:
        try:
            feed = feedparser.parse(feed_url)
            for entry in getattr(feed, "entries", [])[:20]:
                link = getattr(entry, "link", "") or ""
                title = getattr(entry, "title", "") or ""
                # Google News 跳轉 URL 或直接 counterpointresearch URL
                if "counterpointresearch.com/en/insights" in link and link not in seen_urls:
                    seen_urls.add(link)
                    articles.append({"url": link, "title": title, "via": "gnews"})
                # 也找 source 中的 counterpointresearch URL
                src = getattr(entry, "source", {})
                src_url = getattr(src, "href", "") or (src.get("href","") if isinstance(src, dict) else "")
                if "counterpointresearch.com/en/insights" in src_url and src_url not in seen_urls:
                    seen_urls.add(src_url)
                    articles.append({"url": src_url, "title": title, "via": "gnews-src"})
        except Exception:
            pass

    print(f"    🔍 Google News 發現 {len(articles)} 篇 Counterpoint articles")

    if not articles:
        print("    ⚠️ Counterpoint: 無法發現任何文章 URL，跳過")
        return []

    # ── 逐篇抓 SSR 文章頁取得完整內容 ───────────────────────
    _ID_BASE = 900_000
    result = []
    fetched = 0
    for i, a in enumerate(articles[:per_limit]):
        url = a["url"]
        # 若是 Google News 跳轉 URL，嘗試先用標題和外部資訊
        if "news.google.com" in url:
            # 無法直接抓，用 title 和空 snippet，後續由 enrich 處理
            dt = None
            pub = "UNKNOWN"
            if pub == "UNKNOWN" and not ALLOW_UNKNOWN_DATE:
                continue
            title = re.sub(r'\s*-\s*Counterpoint.*$', '', a["title"]).strip()
            if not title or _should_exclude(title, ""):
                continue
            result.append({
                "id": _ID_BASE + i, "cat": "CAT6",
                "source": "Counterpoint Research",
                "title_orig": title, "snippet": "",
                "link": url, "published": pub,
            })
            continue

        # SSR 文章頁：直接抓取
        info = _fetch_counterpoint_article(url)
        if not info:
            continue
        dt = info.get("dt")
        if dt is not None and dt < cutoff:
            continue
        pub = f"{dt:%Y-%m-%d %H:%M}" if dt else "UNKNOWN"
        if pub == "UNKNOWN" and not ALLOW_UNKNOWN_DATE:
            continue
        title = info["title"] or a["title"]
        if not title or _should_exclude(title, info.get("snippet", "")):
            continue
        result.append({
            "id": _ID_BASE + i, "cat": "CAT6",
            "source": "Counterpoint Research",
            "title_orig": title,
            "snippet": info.get("snippet", "")[:2000],
            "link": url, "published": pub,
        })
        fetched += 1
        if i < len(articles) - 1:
            time.sleep(0.3)   # 禮貌延遲

    print(f"    🕷️ Counterpoint Layer 3: {fetched}/{len(articles)} 篇取得完整內容")
    return result


# ==========================================================
# 抓新聞
# ==========================================================
def _parse_dt(s):
    if not s: return None
    s = s.strip()
    try:
        dt = parsedate_to_datetime(s)
        if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(TZ_TAIPEI)
    except: pass
    try:
        s2 = s[:-1]+'+00:00' if s.endswith('Z') else s
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(TZ_TAIPEI)
    except: pass
    return None

def _entry_dt(entry):
    for k in ("published_parsed","updated_parsed"):
        t = getattr(entry,k,None)
        if t: return datetime(t.tm_year,t.tm_mon,t.tm_mday,t.tm_hour,t.tm_min,t.tm_sec,tzinfo=timezone.utc).astimezone(TZ_TAIPEI)
    for k in ("published","updated","date"):
        s = getattr(entry,k,None)
        if s:
            dt = _parse_dt(s)
            if dt: return dt
    return None

def _extract_rss_content(entry):
    """從 RSS entry 中盡可能多地擷取內文。"""
    for field in ("content", "summary", "description"):
        val = getattr(entry, field, None)
        if isinstance(val, list) and val:
            raw = val[0].get("value","") if isinstance(val[0], dict) else str(val[0])
        elif isinstance(val, str) and val:
            raw = val
        else:
            continue
        if raw:
            text = re.sub(r'<[^>]+>', ' ', raw).strip()
            text = re.sub(r'\s+', ' ', text)
            if text:
                return text
    return ""


def fetch_news(per_limit=PER_SOURCE_LIMIT):
    now = datetime.now(TZ_TAIPEI)
    cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    print(f"[{now:%Y-%m-%d %H:%M %z}] Scanning {len(NEWS_SOURCES)} sources...")

    items, iid, seen = [], 1, set()
    stats = {"generated_at": f"{now:%Y-%m-%d %H:%M %z}", "kept": 0, "filtered": 0, "per_source": {}}

    for idx_src, (name, (url, cat)) in enumerate(NEWS_SOURCES.items()):
        kept = 0
        print(f"  [{idx_src+1}/{len(NEWS_SOURCES)}] {name}...", end=" ", flush=True)

        # ── Counterpoint Research：RSS 優先，全部失敗改用爬蟲 ──────
        if url == "__COUNTERPOINT_FALLBACK__":
            feed = _try_counterpoint_rss()
            if feed is None:
                print("RSS 全失敗，改爬蟲...", flush=True)
                scraped = _scrape_counterpoint_insights(cutoff, per_limit)
                for it in scraped:
                    key = it.get("link") or it.get("title_orig", "")
                    if key in seen:
                        continue
                    seen.add(key)
                    it["id"] = iid          # 重新對齊全域 iid
                    items.append(it)
                    iid += 1
                    kept += 1
                print(f"    🕷️ 爬蟲取得 {kept} 篇（snippet 不足者由 enrich 補充）", flush=True)
                stats["per_source"][name] = kept
                stats["kept"] += kept
                continue
            # RSS 有 entries → 直接走下方共用迴圈
            entries = getattr(feed, "entries", []) or []
            print(f"{len(entries)} entries (RSS)", flush=True)

        # ── 一般 RSS 來源 ────────────────────────────────────────────
        else:
            try:
                feed = feedparser.parse(url)
                entries = getattr(feed, "entries", []) or []
                print(f"{len(entries)} entries", flush=True)
            except Exception as e:
                print(f"⚠️ FAILED: {e}", flush=True)
                stats["per_source"][name] = 0
                continue

        # ── 共用：把 entries 逐筆塞入 items ────────────────────────
        try:
            for entry in entries[:per_limit]:
                title   = (getattr(entry, "title", "") or "").strip()
                summary = _extract_rss_content(entry)
                link    = (getattr(entry, "link",  "") or "").strip()
                dt      = _entry_dt(entry)
                if dt is None:
                    if not ALLOW_UNKNOWN_DATE: continue
                    pub = "UNKNOWN"
                else:
                    if dt < cutoff: continue
                    pub = f"{dt:%Y-%m-%d %H:%M}"
                key = link or title
                if key in seen: continue
                seen.add(key)
                if _should_exclude(title, summary):
                    stats["filtered"] += 1; continue
                items.append({"id": iid, "source": name, "cat": cat,
                              "title_orig": title, "snippet": summary[:2000],
                              "link": link, "published": pub})
                iid += 1; kept += 1
            stats["per_source"][name] = kept
            stats["kept"] += kept
        except Exception as e:
            print(f"  ⚠️ entry loop FAILED: {e}", flush=True)
            stats["per_source"][name] = 0

    print(f"  ✅ {stats['kept']} kept, {stats['filtered']} filtered")
    return items, stats


def build_payload(items):
    return "\n\n".join(
        f"<<<ITEM {it['id']}>>>\nSOURCE: {it['source']}\nCAT: {it['cat']}\n"
        f"TITLE: {it['title_orig']}\nPUBLISHED: {it['published']}\nLINK: {it['link']}\n"
        f"SNIPPET: {it['snippet']}\n<<<END>>>" for it in items)


# ==========================================================
# AI
# ==========================================================
def parse_ai(text):
    items = []
    for b in re.split(r"\n---\s*\n", (text or "").strip()):
        b = b.strip()
        if not b: continue
        def gf(n):
            m = re.search(rf"^{n}:\s*(.*)$",b,re.MULTILINE)
            return m.group(1).strip() if m else ""
        iid,cat,tzh = gf("ITEM"),gf("CATEGORY"),gf("TITLE_ZH")
        if iid and cat and tzh:
            items.append({"item_id":iid,"category":cat,"title_zh":tzh,"summary":gf("SUMMARY"),
                          "source":gf("SOURCE"),"published":gf("PUBLISHED"),"link":gf("LINK")})
    return items

def make_prompt(payload):
    return f"""
你是一位資深無線通訊與模組產業分析師，專精於 5G/LTE 模組、射頻前端(RFFE)、基頻處理器(BB)、ODM 供應鏈。

【規則】
1) 每個 ITEM 各寫一條摘要，禁止合併。保留 ITEM / SOURCE / PUBLISHED / LINK。
2) 分類六擇一：
   - CAT1：硬體技術與射頻 — RF/BB 設計、AiP 封裝、信號完整性
   - CAT2：產業趨勢與營運商 — 5G 部署、頻段規劃、市場預測
   - CAT3：競爭對手動態 — 模組廠（Quectel/China Mobile IoT/Fibocom/Telit/SIMCom/MeiG/Rolling Wireless等）新品、市佔率、併購、設計案
   - CAT4：關鍵元件供應商 — 晶片/RFFE/被動元件新品與 Roadmap
   - CAT5：標準與規範 — 3GPP Release、頻譜拍賣、認證法規
   - CAT6：市場研究與分析 — 市調機構報告、管理顧問產業展望、產業預測、市佔率數據、拆解分析
3) 摘要 2-3 句繁體中文，**必須根據 SNIPPET 中的實際內容撰寫**，專業術語保留英文。
4) 禁止自行編造未出現在 SNIPPET 中的數字、日期或事實。
5) 如果 SNIPPET 有充足內容（超過一兩句），請提取關鍵事實寫成摘要。
6) 如果 SNIPPET 內容極短或完全為空（只有一個標題），寫「資訊不足，請點擊原文閱讀」。
   不要用標題去猜測或推測文章內容。
7) 明確為娛樂/體育/名人八卦等與產業無關的主題，寫「非本產業相關」。

【格式（--- 分隔）】
ITEM: <數字>
CATEGORY: <CAT1|CAT2|CAT3|CAT4|CAT5|CAT6>
TITLE_ZH: <繁中標題>
SUMMARY: <2-3句，基於 SNIPPET 實際內容>
SOURCE: <照抄>
PUBLISHED: <照抄>
LINK: <照抄>
---

{payload}
""".strip()

def call_gemini(client, prompt):
    for attempt in range(1, GEMINI_RETRIES+1):
        try:
            resp = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
            return resp.text or ""
        except Exception as e:
            if not any(k in str(e) for k in ["429","500","503","504","timeout","Timed out"]) or attempt==GEMINI_RETRIES: raise
            time.sleep(min(2**attempt,30)+random.random())


# ==========================================================
# 專業科技電子報 HTML
# ==========================================================
def render_html(items, stats=None):
    SKIP = ["資訊不足", "非本產業相關", "非本產業", "與產業無關"]
    grouped = {c:[] for c in CAT_ORDER}
    skipped = 0
    for it in items:
        summ = it.get("summary","").strip()
        if any(p in summ for p in SKIP):
            skipped += 1; continue
        c = it.get("category","").strip()
        if c not in grouped: c = "CAT2"
        grouped[c].append(it)

    now = datetime.now(TZ_TAIPEI)
    wd = ["一","二","三","四","五","六","日"][now.weekday()]
    total = sum(len(v) for v in grouped.values())
    active_src = sum(1 for n in (stats or {}).get("per_source",{}).values() if n>0)
    filtered = (stats or {}).get("filtered", 0)

    BG_PAGE="#0B0F19"; BG_CARD="#FFFFFF"; TEXT_P="#0F172A"; TEXT_S="#64748B"; TEXT_M="#94A3B8"
    BORDER="#E2E8F0"; ACCENT="#38BDF8"

    h = []
    h.append(f"<!DOCTYPE html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'></head>")
    h.append(f"<body style='margin:0;padding:0;background:{BG_PAGE};'>")
    h.append(f"<table width='100%' cellpadding='0' cellspacing='0' style='background:{BG_PAGE};'><tr><td align='center' style='padding:20px 8px;'>")
    h.append(f"<table width='640' cellpadding='0' cellspacing='0' style='background:{BG_CARD};border-radius:12px;overflow:hidden;"
             f"font-family:-apple-system,BlinkMacSystemFont,\"Segoe UI\",Roboto,\"Helvetica Neue\",Arial,sans-serif;'>")

    # ═══ HEADER ═══
    h.append(f"<tr><td style='background:linear-gradient(160deg,#0F172A 0%,#1E293B 50%,#0F172A 100%);padding:0;'>")
    h.append(f"<div style='height:3px;background:linear-gradient(90deg,{ACCENT},#818CF8,#A78BFA);'></div>")
    h.append(f"<table width='100%' cellpadding='0' cellspacing='0'><tr><td style='padding:26px 32px 10px;'>")
    h.append(f"<table width='100%' cellpadding='0' cellspacing='0'><tr>")
    h.append(f"<td><div style='font-size:11px;font-weight:700;color:{ACCENT};letter-spacing:3px;'>MODULE INDUSTRY</div>"
             f"<div style='font-size:24px;font-weight:800;color:#FFF;margin-top:2px;'>BRIEFING</div></td>")
    h.append(f"<td align='right' valign='top'><div style='font-size:36px;font-weight:800;color:#FFF;line-height:1;letter-spacing:-1px;'>{now:%m.%d}</div>"
             f"<div style='font-size:11px;color:{TEXT_M};text-align:right;margin-top:2px;'>星期{wd} {now:%H:%M} TPE</div></td>")
    h.append(f"</tr></table>")
    h.append(f"<div style='margin-top:14px;padding-top:12px;border-top:1px solid #334155;'>"
             f"<span style='font-size:12px;color:#CBD5E1;'>5G &middot; RF/BB &middot; IoT Module &middot; ODM Supply Chain &middot; Component Roadmap</span></div>")
    h.append(f"</td></tr></table></td></tr>")

    # ═══ STATS BAR ═══
    h.append(f"<tr><td style='padding:16px 32px;background:#F1F5F9;border-bottom:1px solid {BORDER};'>")
    h.append(f"<table width='100%' cellpadding='0' cellspacing='0'><tr>")
    for c in CAT_ORDER:
        m=CAT_META[c]; cnt=len(grouped[c]); lb=m["en"].split("&")[0].split("/")[0].strip()[:10]
        h.append(f"<td align='center' style='padding:2px;'><span style='display:inline-block;background:{m['light']};color:{m['dark']};"
                 f"border:1px solid {m['color']}30;font-size:10px;font-weight:700;padding:4px 10px;border-radius:6px;white-space:nowrap;'>"
                 f"{lb}&nbsp;<span style='color:{m['color']};'>{cnt}</span></span></td>")
    h.append(f"</tr><tr><td colspan='5' style='padding-top:8px;text-align:center;'>"
             f"<span style='font-size:10px;color:{TEXT_M};'>&#9679; {active_src} sources &nbsp;&#9679; {total} articles &nbsp;"
             f"&#9679; {filtered + skipped} filtered</span></td></tr></table></td></tr>")

    # ═══ SECTIONS ═══
    for c in CAT_ORDER:
        if not grouped[c]: continue
        m = CAT_META[c]

        h.append(f"<tr><td style='padding:0;'><table width='100%' cellpadding='0' cellspacing='0' style='background:{m['light']};border-top:1px solid {BORDER};'>"
                 f"<tr><td style='padding:16px 32px;'><table width='100%' cellpadding='0' cellspacing='0'><tr>"
                 f"<td style='border-left:4px solid {m['color']};padding-left:14px;'>"
                 f"<div style='font-size:16px;font-weight:700;color:{TEXT_P};line-height:1.3;'>{m['icon']}&nbsp;&nbsp;{m['zh']}</div>"
                 f"<div style='font-size:11px;color:{TEXT_S};margin-top:2px;'>{m['en']}</div></td>"
                 f"<td align='right' valign='top'><div style='font-size:20px;font-weight:800;color:{m['color']};line-height:1;'>{len(grouped[c])}</div>"
                 f"<div style='font-size:10px;color:{TEXT_M};'>articles</div></td>"
                 f"</tr></table><div style='margin-top:8px;font-size:11px;color:{TEXT_M};'>{m['desc']}</div>"
                 f"</td></tr></table></td></tr>")

        for idx, it in enumerate(grouped[c]):
            tzh=escape(it.get("title_zh","")); torig=escape(it.get("title_orig",""))
            summ=escape(it.get("summary","")); src=escape(it.get("source",""))
            pub=escape(it.get("published","")); lnk=(it.get("link") or "").strip()
            bg="#FAFBFC" if idx%2 else "#FFFFFF"

            h.append(f"<tr><td style='padding:0 32px;'><table width='100%' cellpadding='0' cellspacing='0' style='background:{bg};"
                     f"border-bottom:1px solid #F1F5F9;'><tr><td width='4' style='background:{m['color']}20;'></td><td style='padding:16px 18px;'>")

            if lnk:
                h.append(f"<a href='{escape(lnk)}' target='_blank' style='text-decoration:none;'>"
                         f"<div style='font-size:15px;font-weight:600;color:{TEXT_P};line-height:1.45;'>{tzh}</div></a>")
            else:
                h.append(f"<div style='font-size:15px;font-weight:600;color:{TEXT_P};line-height:1.45;'>{tzh}</div>")

            if torig and torig != tzh:
                h.append(f"<div style='font-size:11px;color:{TEXT_M};margin-top:3px;font-style:italic;'>{torig}</div>")
            if summ:
                h.append(f"<div style='font-size:13px;color:{TEXT_S};margin-top:8px;line-height:1.7;'>{summ}</div>")

            h.append(f"<table cellpadding='0' cellspacing='0' style='margin-top:10px;'><tr>"
                     f"<td><span style='display:inline-block;background:{m['light']};color:{m['dark']};border:1px solid {m['color']}25;"
                     f"font-size:10px;font-weight:600;padding:2px 8px;border-radius:4px;'>{src}</span></td>"
                     f"<td style='padding-left:8px;'><span style='font-size:11px;color:{TEXT_M};'>{pub}</span></td>")
            if lnk:
                h.append(f"<td style='padding-left:12px;'><a href='{escape(lnk)}' target='_blank' style='display:inline-block;font-size:10px;"
                         f"font-weight:700;color:{m['color']};text-decoration:none;background:{m['color']}10;padding:2px 10px;"
                         f"border-radius:4px;border:1px solid {m['color']}30;'>READ &#8594;</a></td>")
            h.append(f"</tr></table></td></tr></table></td></tr>")

        h.append(f"<tr><td style='height:4px;'></td></tr>")

    # ═══ FOOTER ═══
    h.append(f"<tr><td style='background:#F8FAFC;padding:20px 32px;border-top:1px solid {BORDER};'>"
             f"<div style='text-align:center;margin-bottom:12px;'>"
             f"<span style='display:inline-block;width:60px;height:2px;background:linear-gradient(90deg,{ACCENT},#818CF8);border-radius:1px;'></span></div>"
             f"<div style='text-align:center;font-size:11px;color:{TEXT_M};line-height:1.8;'>"
             f"<b style='color:{TEXT_S};'>MODULE INDUSTRY BRIEFING</b><br>"
             f"Powered by Gemini AI &middot; {active_src} sources &middot; {filtered} pre-filtered &middot; {skipped} off-topic removed<br>"
             f"此為自動產生之每日產業摘要，僅供內部參考。</div></td></tr>")
    h.append(f"<tr><td><div style='height:3px;background:linear-gradient(90deg,{ACCENT},#818CF8,#A78BFA);'></div></td></tr>")
    h.append(f"</table></td></tr></table></body></html>")
    return "\n".join(h)


# ==========================================================
# 批次產出
# ==========================================================
def generate_report(items, stats=None, title_map=None):
    if not GEMINI_API_KEY: return "錯誤：缺少 GEMINI_API_KEY"
    client = genai.Client(api_key=GEMINI_API_KEY)
    all_parsed = []

    for start in range(0, len(items), BATCH_SIZE):
        batch = items[start:start+BATCH_SIZE]
        bn = start//BATCH_SIZE+1
        print(f"  Batch {bn}: {start+1}~{start+len(batch)}")
        try:
            parsed = parse_ai(call_gemini(client, make_prompt(build_payload(batch))))
            if not parsed:
                for it in batch:
                    all_parsed.append({"item_id":str(it["id"]),"category":it["cat"],"title_zh":it.get("title_orig",""),
                                       "summary":"（解析失敗，請點擊原文閱讀）","source":it.get("source",""),
                                       "published":it.get("published",""),"link":it.get("link","")})
            else:
                all_parsed.extend(parsed)
        except Exception as e:
            for it in batch:
                all_parsed.append({"item_id":str(it["id"]),"category":it["cat"],"title_zh":it.get("title_orig",""),
                                   "summary":f"（失敗：{e}）","source":it.get("source",""),
                                   "published":it.get("published",""),"link":it.get("link","")})

    if title_map:
        for it in all_parsed:
            if not it.get("title_orig"):
                it["title_orig"] = title_map.get(str(it.get("item_id","")), "")

    return render_html(all_parsed, stats=stats)


# ==========================================================
# Email
# ==========================================================
def send_email(html_body):
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        print("❌ 缺少郵件設定"); return
    bcc = [e.strip() for e in (GMAIL_BCC or GMAIL_TO).split(',') if e.strip()]
    msg = MIMEMultipart('alternative')
    msg["From"], msg["To"] = GMAIL_USER, GMAIL_USER
    if bcc: msg["Bcc"] = ", ".join(bcc)
    now = datetime.now(TZ_TAIPEI)
    msg["Subject"] = f"MODULE BRIEFING | {now:%Y-%m-%d} 5G・RF・IoT 模組產業日報"
    msg.attach(MIMEText(f"Module Industry Briefing {now:%Y-%m-%d}", "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as s:
            s.starttls(); s.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            s.send_message(msg, to_addrs=[GMAIL_USER]+bcc)
        print("✅ 已發送")
    except Exception as e:
        print(f"❌ {e}")


# ==========================================================
if __name__ == "__main__":
    items, stats = fetch_news()

    # ✅ 關鍵步驟：對內容不足的項目，去抓網頁原文
    enrich_short_snippets(items)

    if MAX_TOTAL_ITEMS > 0 and len(items) > MAX_TOTAL_ITEMS:
        items = items[:MAX_TOTAL_ITEMS]
    if not items:
        print("⚠️ 無新聞")
    else:
        title_map = {str(it["id"]): it.get("title_orig","") for it in items}
        send_email(generate_report(items, stats=stats, title_map=title_map))
