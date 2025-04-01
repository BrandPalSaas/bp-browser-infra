import asyncio
from playwright.async_api import async_playwright, TimeoutError
import asyncio
from playwright.async_api import async_playwright, TimeoutError
import subprocess
import time

chrome_path = r'"C:\Program Files\Google\Chrome\Application\chrome.exe"'
debugging_port = "--remote-debugging-port=9222"

async def connect_to_browser(p, max_retries=5, delay=1):
    """Helper function to connect to browser with retries"""
    for attempt in range(max_retries):
        try:
            browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
            return browser
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            print(f"Connection attempt {attempt + 1} failed, retrying in {delay} seconds...")
            await asyncio.sleep(delay)

async def download_gmv_csv():
    """下载 GMV CSV 文件的主逻辑"""
    async with async_playwright() as p:
        print('Launching Chrome browser...')
        subprocess.Popen(f"{chrome_path} {debugging_port}")
        
        try:
            print('Connecting to browser...')
            browser = await connect_to_browser(p)
            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            page = context.pages[0] if context.pages else await context.new_page()

            # ... rest of the existing download logic ...
            
        except TimeoutError:
            print("Connection timed out. Please ensure Chrome is running with remote debugging enabled.")
            return {'status': 'error', 'message': 'Connection timeout'}
        except Exception as e:
            print(f"An error occurred: {str(e)}")
            return {'status': 'error', 'message': str(e)}

        browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = context.pages[0] if context.pages else await context.new_page()
        
        browser = await p.chromium.launch_persistent_context(
            user_data_dir='./user_data',
        )
      
        # 创建 Future 对象用于等待下载开始
        download_future = asyncio.Future()
        
        def handle_download(download):
            print(f"Download started: {download.url}")
            # 设置 Future 的结果
            download_future.set_result({
                'status': 'success',
                'download_url': download.url
            })
        
        # 设置下载事件监听器
        page.on('download', handle_download)
        
        # 访问一个tts 网页
        await asyncio.sleep(5)
        await page.goto('https://seller-us.tiktok.com/compass/video-analytics/video-details?is_new_connect=0&shop_region=US')
        print('访问成功')
        # 点击时间赛选框 
        await asyncio.sleep(6)
        print('打开网页！')
        # await page.click('.theme-arco-picker')
        await page.evaluate(" document.querySelector('.theme-arco-picker').click()")
        print('点击时间组件')
        await asyncio.sleep(2)
        await page.click("text=Last 28 days")
        print('选择最近的28天选项')
        await asyncio.sleep(10)
        await page.click("text=Affiliate accounts")
        print('选择tab项')
        await asyncio.sleep(8)
        await page.evaluate("document.querySelectorAll('.theme-m4b-button')[1].click()")
        await asyncio.sleep(0.5)
        await page.evaluate("document.querySelector('.RecordItem__StyledButton-sc-a4nsjm-0').click()")
        print('点击下载按钮')
        
        # 等待下载开始并返回结果
        return await download_future

async def main():
    """主函数，用于测试"""
    await download_gmv_csv()

if __name__ == "__main__":
    asyncio.run(main())