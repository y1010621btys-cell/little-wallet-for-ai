"""AI的眼睛和手 - VPS上的按需浏览器。
用法:
  shot <profile> <url> <name> [wait_sec]   打开页面截图到 IMG 目录/<name>.png
  profiles 独立保存登录态: taobao / meituan / ...（登录一次长期有效）
内存注意: 用完即退, 不常驻。"""
import sys, time
from playwright.sync_api import sync_playwright

IMG = "/var/www/你的站点/wallet/img/"  # 截图输出目录，改成你的
PROFILES = "/root/browser/profiles/"

def shot(profile, url, name, wait=6):
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            PROFILES + profile,
            headless=True,
            viewport={"width": 420, "height": 900},
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(url, timeout=60000, wait_until="domcontentloaded")
        time.sleep(float(wait))
        out = IMG + name + ".png"
        page.screenshot(path=out, full_page=False)
        print("saved:", out, "| title:", page.title()[:60])
        ctx.close()

if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "shot":
        shot(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5] if len(sys.argv) > 5 else 6)
