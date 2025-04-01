import asyncio
from playwright.async_api import async_playwright
import time
from typing import List
from playwright._impl._api_structures import Cookie
from app.common.task_manager import get_task_manager
from app.models import TTShop
import json
import structlog
import tempfile
from typing import Optional
# Set up logging
log = structlog.get_logger(__name__)


TTS_LOGIN_URL = 'https://affiliate-us.tiktok.com/connection/creator?shop_region=US'

class TTSLoginManager:

    async def create_login_cookies(self, username: str, password: str):
        # Authenticate and save browser context
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context()

            page = await context.new_page()
            await page.goto(TTS_LOGIN_URL)
            await page.locator('span.theme-arco-tabs-header-title-text', has_text="Email").click()

            await page.fill('input#TikTok_Ads_SSO_Login_Email_Input', username)
            await page.fill('input#TikTok_Ads_SSO_Login_Pwd_Input', password)
            await page.click('button#TikTok_Ads_SSO_Login_Btn')

            # need this time to enter the confirmation code in browser
            await asyncio.sleep(60)

            # Save browser context
            context_storage = await context.storage_state()
            cookies = context_storage['cookies']
            await browser.close()

            log.info("Login cookies created", cookies=cookies)
        
        task_manager = await get_task_manager()
        await task_manager.save_cookies(username, cookies)

        log.info("Successfully saved login cookies for username", username=username)


    async def get_login_cookies(self, shop: TTShop) -> List[Cookie]:
        task_manager = await get_task_manager()
        return await task_manager.get_cookies(shop.bind_user_email)

    async def save_login_cookies_to_tmp_file(self, shop: TTShop) -> Optional[str]:
        cookies = await self.get_login_cookies(shop)
        if cookies:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".json", mode='w') as f:
                json.dump(cookies, f)
                return f.name
