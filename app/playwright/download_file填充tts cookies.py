import asyncio
from playwright.async_api import async_playwright, TimeoutError
import asyncio
import subprocess
import time
import json

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

async def download_gmv_csv(cookies_json:json):
    """下载 GMV CSV 文件的主逻辑"""
    async with async_playwright() as p:
        print('Launching Chrome browser...')
        subprocess.Popen(f"{chrome_path} {debugging_port}")
        
        try:
            print('Connecting to browser...')
            browser = await connect_to_browser(p)
            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            page = context.pages[0] if context.pages else await context.new_page()
             # 获取cookies file
            if cookies_json:
                print('cookies--------------------------', cookies_json)
                await context.add_cookies(cookies_json)  # 将 cookies 添加到浏览器上下文
            
        except TimeoutError:
            print("Connection timed out. Please ensure Chrome is running with remote debugging enabled.")
            return {'status': 'error', 'message': 'Connection timeout'}
        except Exception as e:
            print(f"An error occurred: {str(e)}")
            return {'status': 'error', 'message': str(e)}

        browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = context.pages[0] if context.pages else await context.new_page()

        # 获取cookies file
        if cookies_json:
            print('cookies--------------------------', cookies_json)
            await context.add_cookies(cookies_json)  # 将 cookies 添加到浏览器上下文
                
        # 创建 Future 对象用于等待下载开始
        download_future = asyncio.Future()
        
        def handle_download(download):
            print(f"Download started: {download.url}")

            # 获取下载文件的路径
            download_path = download.path()  # 获取文件的下载路径
            download_filename = download.suggested_filename()  # 获取下载的文件名
            # 拼接文件路径和文件名
            full_file_path = f"{download_path}/{download_filename}"
            print(f"Download file path: {download_path}")
            print(f"Download file name: {download_filename}")

            # 设置 Future 的结果
            download_future.set_result({
                'status': 'success',
                'status': 'success',
                'download_url': download.url,
                'full_file_path': full_file_path  # 返回完整的文件路径（路径 + 文件名）
            })
        
        # 设置下载事件监听器
        page.on('download',handle_download)
        
        # 访问一个tts 网页
        await asyncio.sleep(5)
        await page.goto('https://seller-us.tiktok.com/compass/video-analytics/video-details?is_new_connect=0&shop_region=US')
        print('访问成功')
        # 点击时间赛选框 
        await asyncio.sleep(6)
        print('打开网页！')
        # await page.click('.theme-arco-picker')
        try:
            if not await click_btn_dom(page,"document.querySelector('.theme-arco-picker').click()"):
                return {"status": "error", "message": "无法找到时间组件"}
        except Exception as e:
            return {"status": "error", "message": f"点击时间组件失败: {str(e)}"}        
        print('点击时间组件')
        
        
        # 增加重试逻辑
        max_retries = 3
        for attempt in range(max_retries):
            try:
                await page.click("text=Last 28 days")
                print('选择最近的28天选项')
                break
            except Exception as e:
                if attempt == max_retries - 1:
                    return {"status": "error", "message": f"无法选择最近28天: {str(e)}"}
                print(f"第 {attempt + 1} 次尝试选择最近28天失败，重新点击时间组件...")
                await click_btn_dom(page,"document.querySelector('.theme-arco-picker').click()")
                await asyncio.sleep(2)
        
        await asyncio.sleep(10)
        await page.click("text=Affiliate accounts")
        print('选择tab项')
        await asyncio.sleep(8)
        
        try:
            if not await click_btn_dom(page,"document.querySelectorAll('.theme-m4b-button')[1].click()"):
                return {"status": "error", "message": "无法找到下载按钮"}
        except Exception as e:
            print('点击下载按钮报错')
            return {"status": "error", "message": str(e)}
        
        try:
            button = page.locator('.RecordItem__StyledButton-sc-a4nsjm-0')
            print('下载按钮',button )
            await button.wait_for(state='visible', timeout=1100)  # 10秒超时
            await button.click()
            print('点击下载按钮')
        except Exception as e:
            return {"status": "success", "message": '文件下载成功'}
        
        # 等待下载开始并返回结果
        return await download_future
    
    #点击时间组件
async def click_btn_dom(page, evaluateVal, max_retries=3, initial_timeout=2000):
    """改进后的点击时间组件逻辑"""
    for attempt in range(max_retries):
        try:
            # 每次重试增加等待时间
            timeout = initial_timeout * (attempt + 1)
            await page.wait_for_selector('.theme-arco-picker', state='visible', timeout=timeout)
            await page.evaluate(evaluateVal)
            print(f'第 {attempt + 1} 次尝试，执行js脚本')
            return True
        except Exception as e:
            print(f'第 {attempt + 1} 次尝试失败: {str(e)}')
            if attempt < max_retries - 1:
                await asyncio.sleep(1)  # 重试前等待1秒
    return False


async def main():
    """主函数，用于测试"""
    await download_gmv_csv()

if __name__ == "__main__":
    asyncio.run(main())