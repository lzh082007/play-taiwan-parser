"""
Google Maps 營業時間爬蟲 (景點-遊憩據點)
根據 cleaned_attractions.json 中的 ServiceTimeInfo 欄位為空的資料，從 Google Maps 爬取營業時間。
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
DATA_PATH = os.path.join(SCRIPT_DIR, "cleaned_attractions.json")
LOG_PATH = os.path.join(SCRIPT_DIR, f"crawler_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
SAVE_INTERVAL = 10

DAY_MAPPING = {
    "星期一": "Monday", "星期二": "Tuesday", "星期三": "Wednesday",
    "星期四": "Thursday", "星期五": "Friday",
    "星期六": "Saturday", "星期日": "Sunday"
}

# ================= 記錄檔設定 =================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_PATH, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# ================= 輔助函式 =================
def load_json(filepath):
    """讀取 JSON 檔案，支援多種編碼"""
    encodings = ['utf-8', 'utf-8-sig', 'cp950']
    for enc in encodings:
        try:
            with open(filepath, 'r', encoding=enc) as f:
                return json.load(f)
        except Exception:
            continue
    raise ValueError(f"無法讀取檔案 {filepath}，請確認編碼")

def save_json(data, filepath):
    """儲存資料到 JSON 檔案"""
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def clean_name(name):
    """清理名稱，移除括號內的文字"""
    return re.sub(r'\(.*?\)|（.*?）', '', name).strip()

def get_address(attr):
    """組合完整地址"""
    return f"{attr.get('City', '')}{attr.get('Town', '')}{attr.get('StreetAddress', '')}"

def is_service_time_empty(service_time):
    """檢查 ServiceTimeInfo 是否全空"""
    if not service_time:
        return True
    for day in service_time.values():
        for slot in day:
            if slot.get('open') != "" or slot.get('close') != "":
                return False
    return True

def create_empty_service_time():
    """建立空白的營業時間結構"""
    return {
        "Monday": [{"open": "", "close": ""}, {"open": "", "close": ""}],
        "Tuesday": [{"open": "", "close": ""}, {"open": "", "close": ""}],
        "Wednesday": [{"open": "", "close": ""}, {"open": "", "close": ""}],
        "Thursday": [{"open": "", "close": ""}, {"open": "", "close": ""}],
        "Friday": [{"open": "", "close": ""}, {"open": "", "close": ""}],
        "Saturday": [{"open": "", "close": ""}, {"open": "", "close": ""}],
        "Sunday": [{"open": "", "close": ""}, {"open": "", "close": ""}]
    }

def parse_hours(raw_list):
    """
    將 Google Maps 的營業時間字串解析為標準 ServiceTimeInfo 格式
    輸入: ["星期一 09:00–17:00", "星期二 休息", ...]
    """
    service_info = create_empty_service_time()
    
    for raw in raw_list:
        parts = raw.split(maxsplit=1)
        if len(parts) < 2:
            continue
            
        day_ch, hours_str = parts[0], parts[1].strip()
        day_en = DAY_MAPPING.get(day_ch.replace("\u200e", "")) # 處理特殊隱藏字元
        
        if not day_en:
            # 嘗試模糊比對
            for k, v in DAY_MAPPING.items():
                if k in day_ch:
                    day_en = v
                    break
                    
        if not day_en:
            continue
            
        # 處理特殊狀況
        if "休息" in hours_str or "不營業" in hours_str:
            continue  # 維持空白
            
        if "24 小時營業" in hours_str:
            service_info[day_en][0] = {"open": "00:00", "close": "23:59"}
            continue
            
        # 處理時間區段 (例如 "09:00–12:00, 14:00–17:00" 或 "09:00–17:00")
        times = re.split(r'[,、，]', hours_str)
        for i, time_range in enumerate(times[:2]): # 最多取兩個時段
            # 處理各種連接符號
            time_range = time_range.replace('–', '-').replace('~', '-')
            time_parts = time_range.split('-')
            
            if len(time_parts) == 2:
                o, c = time_parts[0].strip(), time_parts[1].strip()
                # 簡單的補零驗證 (例如 9:00 變 09:00)
                if len(o) == 4 and ':' in o: o = '0' + o
                if len(c) == 4 and ':' in c: c = '0' + c
                service_info[day_en][i] = {"open": o, "close": c}
                
    return service_info

# ================= 瀏覽器與爬蟲 =================
def setup_driver():
    """設定並啟動瀏覽器"""
    logger.info("正在啟動瀏覽器...")
    opts = uc.ChromeOptions()
    opts.add_argument("--lang=zh-TW")
    opts.add_argument("--disable-notifications")
    driver = uc.Chrome(options=opts, version_main=151)
    driver.set_window_size(1280, 900)
    return driver

def check_captcha(driver):
    """檢查是否遇到機器人驗證"""
    if "sorry/index" in driver.current_url or "captcha" in driver.page_source.lower():
        logger.warning("!!! 偵測到機器人驗證 (Captcha) !!!")
        logger.warning("請在瀏覽器中手動完成驗證，然後在終端機按 Enter 繼續...")
        input("完成驗證後請按 Enter...")
        return True
    return False

def search_and_extract(driver, query):
    """執行搜尋並嘗試提取營業時間"""
    url = f"https://www.google.com/maps/search/{urllib.parse.quote(query)}"
    driver.get(url)
    
    check_captcha(driver)
    
    try:
        # 等待結果載入或直接跳轉至地點頁面
        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "h1.DUwDvf"))
        )
    except TimeoutException:
        # 可能有多個結果，需要點擊第一個
        try:
            first_result = WebDriverWait(driver, 3).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "a.hfpxzc"))
            )
            first_result.click()
            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "h1.DUwDvf"))
            )
        except Exception:
            return None

    # 嘗試尋找營業時間按鈕並點擊展開
    try:
        hours_btn = WebDriverWait(driver, 3).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "div[aria-label*='營業時間'], div[aria-label*='隱藏本週']"))
        )
        if "營業時間" in hours_btn.get_attribute("aria-label"):
            hours_btn.click()
            time.sleep(1) # 等待展開動畫
    except Exception:
        pass # 可能沒有營業時間按鈕，或者已經展開

    # 提取時間表
    try:
        tables = driver.find_elements(By.CSS_SELECTOR, "table")
        for table in tables:
            rows = table.find_elements(By.TAG_NAME, "tr")
            if not rows:
                continue
                
            raw_hours = []
            for row in rows:
                text = row.text.strip().replace('\n', ' ')
                # 檢查是否包含星期幾
                if any(day in text for day in DAY_MAPPING.keys()):
                    raw_hours.append(text)
            
            if raw_hours:
                # 簡單去重，保持順序
                seen = set()
                dedup_hours = [x for x in raw_hours if not (x in seen or seen.add(x))]
                return parse_hours(dedup_hours)
    except Exception as e:
        logger.debug(f"提取時間表失敗: {e}")
        
    return None

def process_data():
    """主迴圈：處理資料"""
    if not os.path.exists(DATA_PATH):
        logger.error(f"找不到資料檔: {DATA_PATH}")
        return

    logger.info("載入資料中...")
    data = load_json(DATA_PATH)
    
    # 篩選出需要爬取的資料 (ServiceTimeInfo 全空，且尚未爬取)
    targets = []
    for item in data:
        if item.get("_scraped", False):
            continue
            
        st = item.get("ServiceTimeInfo")
        if st is None:
            item["ServiceTimeInfo"] = create_empty_service_time()
            st = item["ServiceTimeInfo"]
            
        if is_service_time_empty(st):
            targets.append(item)
            
    total = len(targets)
    if total == 0:
        logger.info("沒有需要爬取的資料！")
        return
        
    logger.info(f"總共需要爬取 {total} 筆資料")
    
    driver = setup_driver()
    processed_count = 0
    start_time = time.time()
    
    try:
        for idx, item in enumerate(targets, 1):
            name = item.get("AttractionName", "")
            address = get_address(item)
            c_name = clean_name(name)
            
            logger.info(f"[{idx}/{total}] 處理中: {name}")
            
            # 策略清單
            strategies = [
                f"{name} {address}".strip(),  # 策略 2: 名稱 + 地址
                name,                         # 策略 1: 僅名稱
                c_name                        # 策略 3: 清理後的名稱
            ]
            
            success = False
            for strategy in strategies:
                if not strategy:
                    continue
                    
                logger.debug(f"嘗試搜尋: {strategy}")
                hours = search_and_extract(driver, strategy)
                
                if hours:
                    # 如果取得的營業時間非全空，則視為成功
                    if not is_service_time_empty(hours):
                        item["ServiceTimeInfo"] = hours
                        logger.info(f"成功取得營業時間！")
                        success = True
                        break
            
            if not success:
                logger.info(f"無法取得營業時間。")
                
            # 標記為已處理
            item["_scraped"] = True
            processed_count += 1
            
            # 隨機等待避免被封鎖
            time.sleep(2)
            
            # 定期存檔
            if processed_count % SAVE_INTERVAL == 0:
                logger.info(f"達到存檔間隔 ({SAVE_INTERVAL})，儲存進度...")
                save_json(data, DATA_PATH)
                
            # 計算進度
            elapsed = time.time() - start_time
            speed = elapsed / processed_count
            eta = speed * (total - processed_count)
            logger.info(f"預估剩餘時間: {eta/60:.1f} 分鐘")
            
    except KeyboardInterrupt:
        logger.info("使用者中斷，儲存當前進度...")
    except Exception as e:
        logger.error(f"發生非預期錯誤: {e}", exc_info=True)
    finally:
        if driver:
            driver.quit()
        logger.info("進行最後存檔...")
        save_json(data, DATA_PATH)
        logger.info(f"執行完畢！共處理 {processed_count} 筆資料。")

if __name__ == "__main__":
    process_data()
