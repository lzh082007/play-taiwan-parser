"""
Google Web Search 版 - 景點營業時間爬蟲
專門針對 Google Maps 爬蟲點不進去、或是找不到時間的景點，透過一般 Google 搜尋來補強。
"""
import json
import os
import sys
import time
import re
import logging
import urllib.parse
from datetime import datetime
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

try:
    import undetected_chromedriver as uc
    if hasattr(uc.Chrome, '__del__'):
        _orig_del = uc.Chrome.__del__
        def _safe_del(self):
            try:
                _orig_del(self)
            except OSError:
                pass
        uc.Chrome.__del__ = _safe_del
except ImportError:
    print("請先安裝套件: pip install undetected-chromedriver setuptools")
    sys.exit(1)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATASET_DIR = os.path.join(SCRIPT_DIR, "資料集")
OUTPUT_PATH = os.path.join(DATASET_DIR, "AttractionServiceTimeList_Updated.json")
LOG_PATH = os.path.join(SCRIPT_DIR, f"google_crawler_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
SAVE_INTERVAL = 10

DAY_MAPPING = {
    "星期一": "Monday", "星期二": "Tuesday", "星期三": "Wednesday",
    "星期四": "Thursday", "星期五": "Friday",
    "星期六": "Saturday", "星期日": "Sunday"
}
DAYS_OF_WEEK_ZH = list(DAY_MAPPING.keys())

def setup_logging():
    logger = logging.getLogger("google_crawler")
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("[%(asctime)s] %(message)s", datefmt="%H:%M:%S")
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
    fh.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    logger.addHandler(fh)
    return logger

log = setup_logging()

def load_json(filepath):
    for enc in ['utf-8-sig', 'utf-8', 'cp950', 'big5']:
        try:
            with open(filepath, 'r', encoding=enc) as f:
                return json.load(f)
        except Exception:
            continue
    raise Exception(f"無法讀取: {filepath}")

def save_json(data, filepath):
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def parse_hours(raw_list):
    time_groups = {}
    for row in raw_list:
        for zh, en in DAY_MAPPING.items():
            if row.startswith(zh):
                t = row[len(zh):].strip()
                if "休息" in t or "不營業" in t or "休息日" in t:
                    break
                time_groups.setdefault(t, []).append(en)
                break

    result = []
    for t, days in time_groups.items():
        nums = re.findall(r'(\d{1,2}:\d{2})', t)
        if len(nums) == 2:
            result.append(_st("一般營業時間", days, f"{nums[0]:0>5}:00", f"{nums[1]:0>5}:00"))
        elif len(nums) == 4:
            result.append(_st("上午營業時間", days.copy(), f"{nums[0]:0>5}:00", f"{nums[1]:0>5}:00"))
            result.append(_st("下午營業時間", days.copy(), f"{nums[2]:0>5}:00", f"{nums[3]:0>5}:00"))
        elif "24 小時" in t or "24小時" in t:
            result.append(_st("24小時營業", days, "00:00:00", "23:59:59"))
        else:
            result.append(_st("特殊營業時間", days, "00:00:00", "23:59:59", desc=t))
    return result

def _st(name, days, start, end, desc=None):
    return {
        "Name": name, "Description": desc,
        "ServiceDays": days, "StartTime": start, "EndTime": end,
        "EffectiveDate": None, "ExpireDate": None
    }

def setup_driver():
    opts = uc.ChromeOptions()
    opts.add_argument("--lang=zh-TW")
    opts.add_argument("--disable-notifications")
    driver = uc.Chrome(options=opts, version_main=151)
    driver.set_window_size(1280, 900)
    return driver

def scrape_google(driver, name, address=""):
    # 將地址的縣市或鄉鎮加入關鍵字中，避免搜到同名景點
    search_keyword = f"{address} {name} 營業時間".strip()
    q = urllib.parse.quote(search_keyword)
    driver.get(f"https://www.google.com.tw/search?q={q}")
    time.sleep(2)
    
    if "sorry/index" in driver.current_url or "consent" in driver.current_url:
        log.info("⚠️ 偵測到機器人驗證！請在瀏覽器中手動解開。")
        input("完成後請按 Enter 繼續...")
        
    try:
        # 嘗試點選知識面板的展開按鈕 (通常是下拉箭頭)
        btns = driver.find_elements(By.XPATH, "//*[contains(@class, 'vk_gy') or contains(text(), '營業時間')]")
        for btn in btns:
            try:
                if btn.is_displayed():
                    driver.execute_script("arguments[0].click();", btn)
                    time.sleep(1)
            except:
                pass
    except:
        pass
        
    # 找尋所有包含星期的文字
    elements = driver.find_elements(By.XPATH, "//tr | //div")
    seen = set()
    out = []
    
    for el in elements:
        try:
            txt = el.text.replace('\n', ' ').strip()
            if any(d in txt for d in DAYS_OF_WEEK_ZH) and len(txt) < 40:
                # 簡單過濾掉不是營業時間的雜訊
                if "休息" in txt or re.search(r'\d{1,2}:\d{2}', txt):
                    if txt not in seen:
                        seen.add(txt)
                        out.append(txt)
        except:
            continue
            
    return out or None

def get_city_town(attr):
    p = attr.get("PostalAddress") or {}
    return f"{p.get('City','')}{p.get('Town','')}"

def main():
    log.info("=" * 60)
    log.info("Google Search 版營業時間爬蟲啟動")
    log.info("=" * 60)

    # 讀取原始景點資料來獲取地址
    ATTRACTION_LIST_PATH = os.path.join(DATASET_DIR, "AttractionList.json")
    attr_data = load_json(ATTRACTION_LIST_PATH)
    address_map = {}
    for a in attr_data.get("Attractions", []):
        address_map[a["AttractionID"]] = get_city_town(a)

    svc_data = load_json(OUTPUT_PATH)
    
    # 篩選出需要爬取的目標：沒有 ServiceTimes，而且也沒有被標記為永久歇業/暫停營業的，而且沒被 Google 版爬過的
    todo = []
    for rec in svc_data.get("AttractionServiceTimes", []):
        has_time = bool(rec.get("ServiceTimes"))
        is_closed = rec.get("BusinessStatus") in ("永久歇業", "暫停營業")
        google_tried = rec.get("_scraped_google")
        
        if not has_time and not is_closed and not google_tried:
            todo.append(rec)
            
    total = len(todo)
    log.info(f"共有 {total} 個景點將使用 Google Search 進行補強。")
    if total == 0:
        log.info("沒有需要補強的景點！")
        return

    driver = setup_driver()
    success = 0
    fail = 0
    start_time = time.time()

    try:
        for i, rec in enumerate(todo, 1):
            name = rec["AttractionName"]
            aid = rec["AttractionID"]
            
            # 取得縣市鄉鎮
            city_town = address_map.get(aid, "")
            
            log.info(f"[{i}/{total}] {city_town} {name} ({aid})")
            hrs = scrape_google(driver, name, city_town)
            
            if hrs:
                success += 1
                log.info(f"   ✅ Google 搜尋成功抓到 {len(hrs)} 筆時段")
                parsed = parse_hours(hrs)
                rec["ServiceTimes"] = parsed
                rec["BusinessStatus"] = "正常營業 (由 Google Search 補強)"
            else:
                fail += 1
                log.info(f"   ❌ Google 搜尋也找不到營業時間")
            
            # 標記已嘗試過
            rec["_scraped_google"] = True
            rec["UpdateTime"] = time.strftime("%Y-%m-%dT%H:%M:%S+08:00")
            
            if i % SAVE_INTERVAL == 0:
                save_json(svc_data, OUTPUT_PATH)
                log.info(f"   💾 存檔！目前進度 {i}/{total} | 成功補強 {success}")
                
            time.sleep(2)
            
    except KeyboardInterrupt:
        log.info(f"\n⏸️ 使用者中斷！已處理 {i} 筆")
        
    save_json(svc_data, OUTPUT_PATH)
    elapsed = time.time() - start_time
    log.info("=" * 60)
    log.info(f"🎉 執行結束！耗時 {elapsed/60:.1f} 分鐘")
    log.info(f"   本次成功補強: {success} | 依然找不到: {fail}")
    log.info("=" * 60)
    
    try:
        driver.quit()
    except OSError:
        pass

if __name__ == "__main__":
    main()
