import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
import time
import re
import urllib.parse

def setup_driver():
    opts = uc.ChromeOptions()
    opts.add_argument("--lang=zh-TW")
    opts.add_argument("--disable-notifications")
    driver = uc.Chrome(options=opts, version_main=151)
    return driver

def scrape_google_search(driver, name):
    q = urllib.parse.quote(f"{name} 營業時間")
    url = f"https://www.google.com.tw/search?q={q}"
    driver.get(url)
    time.sleep(3)
    
    try:
        if "sorry/index" in driver.current_url or "consent" in driver.current_url:
            print("CAPTCHA DETECTED")
            return []
            
        # Click expand if there is a button like "營業時間"
        try:
            btns = driver.find_elements(By.XPATH, "//*[contains(text(), '營業時間') and not(contains(text(), '星期'))]")
            for btn in btns:
                driver.execute_script("arguments[0].click();", btn)
                time.sleep(1)
        except:
            pass
            
        days = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
        found_hours = []
        
        elements = driver.find_elements(By.XPATH, "//tr | //div")
        for e in elements:
            try:
                t = e.text.replace('\n', ' ').strip()
                if any(d in t for d in days) and re.search(r'\d{1,2}:\d{2}', t) and len(t) < 50:
                    if t not in found_hours:
                        found_hours.append(t)
            except:
                pass
                
        return found_hours
    except Exception as e:
        return []

if __name__ == "__main__":
    driver = setup_driver()
    res = scrape_google_search(driver, "赤崁樓")
    print(res)
    driver.quit()
