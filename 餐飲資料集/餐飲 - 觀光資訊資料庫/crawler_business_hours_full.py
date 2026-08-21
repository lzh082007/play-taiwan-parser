"""
餐飲營業時間爬蟲 - Google Maps 版
功能：自動爬取缺失營業時間的餐飲資料，每 10 筆自動存檔，支援中斷後接續。
使用方式：python crawler_business_hours_full.py
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
from selenium.common.exceptions import TimeoutException

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

# ================= 設定區 =================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATASET_DIR = os.path.join(SCRIPT_DIR, "資料集")
RESTAURANT_LIST_PATH = os.path.join(DATASET_DIR, "RestaurantList.json")
SERVICE_TIME_LIST_PATH = os.path.join(DATASET_DIR, "RestaurantServiceTimeList.json")
OUTPUT_PATH = os.path.join(DATASET_DIR, "RestaurantServiceTimeList_Updated.json")
LOG_PATH = os.path.join(SCRIPT_DIR, f"crawler_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
SAVE_INTERVAL = 10

DAY_MAPPING = {
    "星期一": "Monday", "星期二": "Tuesday", "星期三": "Wednesday",
    "星期四": "Thursday", "星期五": "Friday",
    "星期六": "Saturday", "星期日": "Sunday"
}
DAYS_OF_WEEK_ZH = list(DAY_MAPPING.keys())
# ==========================================


# ─────────────────── Log 設定 ───────────────────

def setup_logging():
    """同時輸出到終端機和 log 檔"""
    logger = logging.getLogger("crawler")
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("[%(asctime)s] %(message)s", datefmt="%H:%M:%S")

    # 終端機
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    # 檔案
    fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
    fh.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    logger.addHandler(fh)

    return logger

log = setup_logging()


# ─────────────────── 工具函式 ───────────────────

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


def clean_name(name):
    cleaned = re.sub(r'[（\(][^）\)]*[）\)]', '', name).strip()
    return cleaned if cleaned else name


def get_address(attr):
    p = attr.get("PostalAddress") or {}
    return f"{p.get('City','')}{p.get('Town','')}{p.get('StreetAddress','')}"


def parse_hours(raw_list):
    time_groups = {}
    for row in raw_list:
        for zh, en in DAY_MAPPING.items():
            if row.startswith(zh):
                t = row[len(zh):].strip()
                if "休息" in t or "不營業" in t:
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


# ─────────────────── 瀏覽器操作 ───────────────────

def setup_driver():
    opts = uc.ChromeOptions()
    opts.add_argument("--lang=zh-TW")
    opts.add_argument("--disable-notifications")
    driver = uc.Chrome(options=opts, version_main=151)
    driver.set_window_size(1280, 900)
    return driver


def try_click_first_result(driver):
    selectors = [
        "a.hfpxzc",
        "div[role='feed'] a",
        "div.Nv2PK a",
        "a[href*='/maps/place/']",
    ]
    for sel in selectors:
        try:
            for el in driver.find_elements(By.CSS_SELECTOR, sel):
                if el.is_displayed():
                    driver.execute_script("arguments[0].click();", el)
                    WebDriverWait(driver, 5).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "h1"))
                    )
                    return True
        except Exception:
            continue
    return False


def extract_hours(driver):
    try:
        for btn in driver.find_elements(By.XPATH,
                "//*[contains(@aria-label,'營業時間') or contains(@aria-label,'隱藏本週')]"):
            if btn.is_displayed():
                driver.execute_script("arguments[0].click();", btn)
                time.sleep(1)
                break
    except Exception:
        pass

    rows = driver.find_elements(By.XPATH,
        "//tr[.//div[contains(text(),'星期')]] | //table//tr")
    seen, out = set(), []
    for r in rows:
        txt = r.text.replace('\n', ' ')
        if any(d in txt for d in DAYS_OF_WEEK_ZH) and txt not in seen:
            seen.add(txt)
            out.append(txt)
    return out or None


def wait_for_place_page(driver):
    try:
        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "h1")))
        return True
    except TimeoutException:
        if try_click_first_result(driver):
            return True
        if "sorry/index" in driver.current_url or "consent" in driver.current_url:
            log.info("⚠️ 偵測到機器人驗證！請在瀏覽器中手動解開。")
            input("完成後請按 Enter 繼續...")
            return True
        return False


def scrape(driver, name, address=""):
    queries = [name]
    if address:
        queries.append(f"{name} {address}")
    cn = clean_name(name)
    if cn != name:
        queries.append(cn)

    for i, q in enumerate(queries):
        try:
            driver.get(f"https://www.google.com.tw/maps/search/{urllib.parse.quote(q)}")
            if not wait_for_place_page(driver):
                if i < len(queries) - 1:
                    log.info(f"   策略{i+1}失敗，嘗試下一個...")
                continue
            time.sleep(1.5)
            hrs = extract_hours(driver)
            if hrs:
                if i > 0:
                    log.info(f"   (透過策略{i+1}成功)")
                return hrs
        except Exception:
            continue
    return None


# ─────────────────── 主程式 ───────────────────

def main():
    log.info("=" * 60)
    log.info("餐飲營業時間爬蟲啟動")
    log.info(f"Log 檔案: {LOG_PATH}")
    log.info("=" * 60)

    log.info("載入資料集...")
    restaurant_data = load_json(RESTAURANT_LIST_PATH)

    if os.path.exists(OUTPUT_PATH):
        log.info("偵測到上次的進度檔案，將接續爬取...")
        svc_data = load_json(OUTPUT_PATH)
    else:
        svc_data = load_json(SERVICE_TIME_LIST_PATH)

    if "RestaurantServiceTimes" not in svc_data:
        svc_data["RestaurantServiceTimes"] = []

    # 已爬過的 ID（包含有資料的 + 標記為已嘗試的）
    done_ids = set()
    for a in svc_data["RestaurantServiceTimes"]:
        if a.get("ServiceTimes") or a.get("_scraped"):
            done_ids.add(a["RestaurantID"])

    todo = [a for a in restaurant_data.get("Restaurants", [])
            if a["RestaurantID"] not in done_ids]

    total = len(todo)
    log.info(f"總共還有 {total} 個餐飲需要爬取。")
    if total == 0:
        log.info("所有資料已補齊！")
        return

    driver = setup_driver()
    success, fail = 0, 0
    start_time = time.time()

    try:
        for i, attr in enumerate(todo, 1):
            name = attr["RestaurantName"]
            aid  = attr["RestaurantID"]
            addr = get_address(attr)

            log.info(f"[{i}/{total}] {name} ({aid})")
            hrs = scrape(driver, name, addr)

            if hrs:
                success += 1
                log.info(f"   ✅ 成功抓到 {len(hrs)} 筆時段")
                parsed = parse_hours(hrs)
                found = False
                for rec in svc_data["RestaurantServiceTimes"]:
                    if rec["RestaurantID"] == aid:
                        rec["ServiceTimes"] = parsed
                        rec["UpdateTime"] = time.strftime("%Y-%m-%dT%H:%M:%S+08:00")
                        rec["_scraped"] = True
                        found = True
                        break
                if not found:
                    svc_data["RestaurantServiceTimes"].append({
                        "RestaurantID": aid,
                        "RestaurantName": name,
                        "ServiceTimes": parsed,
                        "UpdateTime": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
                        "_scraped": True
                    })
            else:
                fail += 1
                log.info(f"   ❌ 三種策略皆失敗")
                # 標記為已嘗試過，避免重複爬取
                found = False
                for rec in svc_data["RestaurantServiceTimes"]:
                    if rec["RestaurantID"] == aid:
                        rec["_scraped"] = True
                        found = True
                        break
                if not found:
                    svc_data["RestaurantServiceTimes"].append({
                        "RestaurantID": aid,
                        "RestaurantName": name,
                        "ServiceTimes": [],
                        "UpdateTime": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
                        "_scraped": True
                    })

            # 每 SAVE_INTERVAL 筆存檔
            if i % SAVE_INTERVAL == 0:
                total_records = len(svc_data["RestaurantServiceTimes"])
                filled = sum(1 for a in svc_data["RestaurantServiceTimes"] if a.get("ServiceTimes"))
                elapsed = time.time() - start_time
                speed = i / elapsed * 60  # 每分鐘幾筆
                eta_min = (total - i) / speed if speed > 0 else 0
                log.info(f"   💾 存檔！已處理 {i}/{total} | 成功 {success} | 失敗 {fail}")
                log.info(f"      資料庫共 {total_records} 筆，其中 {filled} 筆有營業時間")
                log.info(f"      速度 {speed:.1f} 筆/分鐘 | 預估剩餘 {eta_min:.0f} 分鐘")
                save_json(svc_data, OUTPUT_PATH)

            time.sleep(2)

    except KeyboardInterrupt:
        log.info(f"\n⏸️ 使用者中斷！已處理 {i} 筆")

    # 最終存檔
    save_json(svc_data, OUTPUT_PATH)
    total_records = len(svc_data["RestaurantServiceTimes"])
    filled = sum(1 for a in svc_data["RestaurantServiceTimes"] if a.get("ServiceTimes"))
    elapsed = time.time() - start_time

    log.info("=" * 60)
    log.info(f"🎉 執行結束！耗時 {elapsed/60:.1f} 分鐘")
    log.info(f"   本次成功: {success} | 本次失敗: {fail}")
    log.info(f"   資料庫共 {total_records} 筆，其中 {filled} 筆有營業時間")
    log.info(f"📁 資料匯出: {OUTPUT_PATH}")
    log.info(f"📋 完整 Log: {LOG_PATH}")
    log.info("=" * 60)

    try:
        driver.quit()
    except OSError:
        pass

    sys.stderr = open(os.devnull, "w")


if __name__ == "__main__":
    main()
