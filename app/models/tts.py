from app.common.constants import BROWSER_TASKS_STREAM, REDIS_COOKIES_KEY_FMT
from pydantic import BaseModel
from enum import Enum

class TTShopName(str, Enum):
    ShopperInc = "ShopperInc"


class TTShop(BaseModel):
    shop: TTShopName
    bind_user_email: str # the user email that bind to this tts shop, used for login

    def __str__(self) -> str:
        return self.shop.value

    # each tts has a unique task queue in redis 
    def task_queue_name(self) -> str:
        return f"{BROWSER_TASKS_STREAM}_{self.shop.value}"
    
    def cookies_key(self) -> str:
        return f"{REDIS_COOKIES_KEY_FMT.format(self.bind_user_email)}"