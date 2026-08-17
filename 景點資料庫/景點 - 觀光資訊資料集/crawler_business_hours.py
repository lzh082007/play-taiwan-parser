import json
import os
import time
import urllib.parse
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# 引入 undetected_chromedriver 來避開機器人偵測
try:
    import undetected_chromedriver as uc
except ImportError:
    print("請先安裝 undetected-chromedriver套件: pip install undetected-chromedriver")
    exit(1)

# 檔案路徑
DATASET_DIR = r"C:\Users\lzh08\OneDrive\桌面\日遊所思夜遊所夢資料集\景點資料庫\景點 - 觀光資訊資料集\資料集"
ATTRACTION_LIST_PATH = os.path.join(DATASET_DIR, "AttractionList.json")
SERVICE_TIME_LIST_PATH = os.path.join(DATASET_DIR, "AttractionServiceTimeList.json")
OUTPUT_PATH = os.path.join(DATASET_DIR, "AttractionServiceTimeList_Updated.json")

def load_json_utf8_with_fallback(filepath):
    encodings = ['utf-8-sig', 'utf-8', 'cp950', 'big5']
    for enc in encodings:
        try:
            with open(filepath, 'r', encoding=enc) as f:
                return json.load(f)
        except Exception:
            continue
    raise Exception(f"無法讀取檔案，編碼不支援: {filepath}")

def setup_driver():
    options = uc.ChromeOptions()
    options.add_argument("--lang=zh-TW")
    options.add_argument("--disable-notifications")
    
    # undetected_chromedriver 會啟動一個非常像正常使用者操作的 Chrome
    # 強制指定對應的 Chrome 主版本號為 151，避免下載到 152 的驅動
    driver = uc.Chrome(options=options, version_main=151)
    
    # 稍微放大視窗確保元素可見
    driver.set_window_size(1280, 900)
    return driver

def scrape_hours_from_google_maps(driver, attraction_name):
    """透過 Google Maps 取得營業時間"""
    print(f"正在 Google Maps 搜尋: {attraction_name}...")
    try:
        query = urllib.parse.quote(attraction_name)
        driver.get(f"https://www.google.com.tw/maps/search/{query}")
        
        # 等待地圖左側面板載入 (通常會出現 h1 標題)
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "h1"))
            )
        except TimeoutException:
            # 如果還是跳出機器人驗證，讓程式暫停，等待手動解開
            if "sorry/index" in driver.current_url or "consent" in driver.current_url:
                print("⚠️ 偵測到機器人驗證或登入畫面！請在彈出的瀏覽器中手動解開驗證。")
                input("解開後，請回到這裡按下 Enter 繼續...")
            else:
                print(f"找不到 {attraction_name} 的地點面板")
                return None
                
        time.sleep(2) # 等待 DOM 穩定
        
        # 嘗試點擊展開「營業時間」
        try:
            # Google Maps 的營業時間通常帶有一個 aria-label 包含「營業時間」或以圖示顯示
            expand_btns = driver.find_elements(By.XPATH, "//*[contains(@aria-label, '營業時間') or contains(@aria-label, '隱藏本週')]")
            for btn in expand_btns:
                try:
                    # 如果元素可見就點擊
                    if btn.is_displayed():
                        driver.execute_script("arguments[0].click();", btn)
                        time.sleep(1)
                        break
                except:
                    pass
        except:
            pass
            
        # 抓取表格中的星期與時間
        days_of_week = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
        hours_data = []
        
        # 抓取所有包含星期名稱的列 (tr) 或是 div
        rows = driver.find_elements(By.XPATH, "//tr[.//div[contains(text(), '星期')]] | //table//tr")
        
        for row in rows:
            text = row.text.replace('\n', ' ')
            if any(day in text for day in days_of_week):
                hours_data.append(text)
                
        # 過濾與去重
        seen = set()
        cleaned_data = []
        for h in hours_data:
            if h not in seen:
                seen.add(h)
                cleaned_data.append(h)
                
        if cleaned_data:
            return cleaned_data
            
    except Exception as e:
        print(f"抓取 {attraction_name} 失敗: {e}")
        
    return None

def main():
    print("載入資料集...")
    try:
        attraction_data = load_json_utf8_with_fallback(ATTRACTION_LIST_PATH)
        service_time_data = load_json_utf8_with_fallback(SERVICE_TIME_LIST_PATH)
    except Exception as e:
        print(e)
        return

    existing_hours = {}
    if "AttractionServiceTimes" in service_time_data:
        for ast in service_time_data["AttractionServiceTimes"]:
            has_hours = len(ast.get("ServiceTimes", [])) > 0
            existing_hours[ast["AttractionID"]] = has_hours

    attractions_to_scrape = []
    if "Attractions" in attraction_data:
        for attr in attraction_data["Attractions"]:
            aid = attr["AttractionID"]
            if not existing_hours.get(aid, False):
                attractions_to_scrape.append(attr)

    print(f"總共需要補齊營業時間的景點數量: {len(attractions_to_scrape)}")
    if len(attractions_to_scrape) == 0:
        print("沒有需要補齊的資料。")
        return

    driver = setup_driver()
    
    results = {}
    # 測試前 10 筆
    for attr in attractions_to_scrape[:10]:
        name = attr["AttractionName"]
        hours = scrape_hours_from_google_maps(driver, name)
        
        if hours:
            print(f"✅ 成功取得 {name} 營業時間:\n   " + "\n   ".join(hours))
            results[attr["AttractionID"]] = hours
        else:
            print(f"❌ 找不到 {name} 的營業時間")
            
        time.sleep(3) # 隨機等待 3 秒，模擬人類行為

    driver.quit()

    print("\n爬取結果 (原始格式):")
    print(json.dumps(results, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
