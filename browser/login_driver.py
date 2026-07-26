"""AI 的眼睛和手 · 登录驱动（常驻会话 + 指令文件）。

drive.py 的 shot 是「开页→截图→关」的一次性动作，扛不住登录：
登录要「机器发验证码 → 人读手机短信 → 机器回填」这段人机接力，
中途一旦关掉浏览器，会话和验证码上下文就全丢了。

所以登录用这个脚本：浏览器**开着不关**，轮询一个指令文件，
你（或你的 AI）往文件里写一行指令，它读到就执行、回写状态。

用法：
    ./venv/bin/python login_driver.py <platform>
    # platform 见下面 PLATFORMS，例如 taobao / meituan

投指令（另一个终端 / AI 的 shell 工具）：
    echo -n "SNAP"        > /root/browser/<platform>_cmd.txt   # 重新截图看现况
    echo -n "SEND"        > /root/browser/<platform>_cmd.txt   # 点「发送验证码」
    echo -n "CODE:123456" > /root/browser/<platform>_cmd.txt   # 填验证码并提交
    echo -n "GOTO:https://..." > /root/browser/<platform>_cmd.txt  # 跳转
    echo -n "QUIT"        > /root/browser/<platform>_cmd.txt   # 收工

看状态：
    cat /root/browser/<platform>_result.txt

安全：手机号走环境变量，登录 cookie 存 profiles/（.gitignore 已排除），都不入库。
"""
import sys, os, time
from playwright.sync_api import sync_playwright

IMG = "/var/www/你的站点/wallet/img/"   # 截图输出目录，改成你的
BROWSER_DIR = "/root/browser"
PHONE = os.environ.get("WALLET_PHONE", "")   # export WALLET_PHONE=1xxxxxxxxxx

# 反自动化检测：淘宝这类硬风控站点必须抹掉 webdriver 标记，否则扫码「成功」却不落 cookie
STEALTH = """
Object.defineProperty(navigator,'webdriver',{get:()=>undefined});
window.chrome = {runtime:{}};
Object.defineProperty(navigator,'languages',{get:()=>['zh-CN','zh','en']});
"""

# 每个平台的登录入口与它的脾气。send/submit 是「发送验证码」「提交」按钮的候选文案。
PLATFORMS = {
    "taobao": {
        "login_url": "https://login.taobao.com/member/login.jhtml",
        "desktop": True,            # 淘宝 PC 版扫码/短信；移动版风控更严
        "stealth": True,
        "pre": ["短信登录"],        # 进页面先点的按钮（切到短信 tab）
        "send": ["获取验证码", "发送验证码", "获取短信校验码"],
        "submit": ["登录", "确定"],
    },
    "meituan": {
        "login_url": "https://h5.waimai.meituan.com/waimai/mindex/poipicker",
        "desktop": False,           # 美团外卖 H5，手机 UA
        "stealth": False,
        "pre": ["选择城市"],        # 一点就撞登录墙，正好把登录页顶出来
        "send": ["发送验证码", "重新发送"],
        "submit": ["登录"],
        "need_agree": True,         # 协议 checkbox 必须勾，否则点登录弹「请先勾选」
    },
}


def click_any(page, texts, timeout=6000):
    for t in texts:
        loc = page.locator("text=%s" % t)
        if loc.count():
            loc.first.click(timeout=timeout, force=True)
            return True
    return False


def tick_agreement(page):
    """勾「我已阅读并同意」。checkbox 常无稳定选择器，用 className 关键词 + 坐标兜底。"""
    hit = page.evaluate("""() => {
        for (const e of document.querySelectorAll('*')) {
            const c = ((e.className||'')+'').toLowerCase();
            if (/(check|agree|radio|circle)/.test(c) && e.offsetParent) {
                const r = e.getBoundingClientRect();
                if (r.top > 400 && r.top < 620 && r.left < 60 && r.width < 40) { e.click(); return true; }
            }
        }
        return false;
    }""")
    if not hit:
        page.mouse.click(33, 497)


def main(platform):
    cfg = PLATFORMS[platform]
    res = "%s/%s_result.txt" % (BROWSER_DIR, platform)
    cmd = "%s/%s_cmd.txt" % (BROWSER_DIR, platform)
    if os.path.exists(cmd):
        os.remove(cmd)

    def W(s):
        open(res, "w").write(s)

    def snap(page, name=None):
        try:
            page.screenshot(path=IMG + (name or platform + "-live") + ".png", timeout=12000)
        except Exception:
            pass

    def peek(page, n=120):
        try:
            return page.evaluate("() => document.body.innerText.slice(0,%d)" % n).replace("\n", "|")
        except Exception:
            return "?"

    W("STARTING")
    with sync_playwright() as p:
        if cfg["desktop"]:
            viewport = {"width": 1180, "height": 820}
            ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            args = ["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"]
        else:
            viewport = {"width": 420, "height": 900}
            ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
            args = ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]

        ctx = p.chromium.launch_persistent_context(
            "%s/profiles/%s" % (BROWSER_DIR, platform),
            headless=True, viewport=viewport, user_agent=ua,
            locale="zh-CN", timezone_id="Asia/Shanghai", args=args)
        if cfg.get("stealth"):
            ctx.add_init_script(STEALTH)

        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(cfg["login_url"], timeout=60000, wait_until="domcontentloaded")
        time.sleep(7)
        for t in cfg.get("pre", []):
            try:
                click_any(page, [t]); time.sleep(4)
            except Exception:
                pass
        # 填手机号（页面第一个输入框）
        try:
            inp = page.locator("input").first
            inp.click(); inp.fill(PHONE); time.sleep(1)
            if cfg.get("need_agree"):
                tick_agreement(page); time.sleep(1)
            snap(page)
            W("READY |" + peek(page))
        except Exception as e:
            snap(page); W("ERR_setup:" + str(e)[:100])

        # 指令循环，最多约 40 分钟；会话全程不关
        for _ in range(800):
            time.sleep(3)
            if not os.path.exists(cmd):
                continue
            v = open(cmd).read().strip(); os.remove(cmd)
            if v == "QUIT":
                break
            if v == "SNAP":
                snap(page); W("SNAPPED |url:" + page.url[:70] + " |" + peek(page)); continue
            if v.startswith("GOTO:"):
                try:
                    page.goto(v[5:], timeout=40000, wait_until="domcontentloaded")
                    time.sleep(6); snap(page)
                    W("WENT |url:" + page.url[:80] + " |title:" + page.title()[:30])
                except Exception as e:
                    W("ERR_goto:" + str(e)[:100])
                continue
            if v == "SEND":
                try:
                    click_any(page, cfg["send"]); time.sleep(4); snap(page)
                    W("SENT |" + peek(page))
                except Exception as e:
                    W("ERR_send:" + str(e)[:100]); snap(page)
                continue
            if v.startswith("CODE:"):
                code = v[5:]
                try:
                    # 验证码填第二个输入框
                    page.locator("input").nth(1).fill(code); time.sleep(1)
                    if cfg.get("need_agree"):
                        tick_agreement(page); time.sleep(1)   # 登录前再补勾一次
                    snap(page, platform + "-before-login")
                    click_any(page, cfg["submit"]); time.sleep(9); snap(page)
                    u = page.url
                    ok = "/login" not in u and "login." not in u
                    W(("LOGIN_OK " if ok else "LOGIN_FAIL ") + "|url:" + u[:70] + " |" + peek(page))
                except Exception as e:
                    W("ERR_code:" + str(e)[:110]); snap(page)
                continue
        ctx.close()


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in PLATFORMS:
        print("usage: login_driver.py <%s>" % "|".join(PLATFORMS))
        sys.exit(1)
    main(sys.argv[1])
