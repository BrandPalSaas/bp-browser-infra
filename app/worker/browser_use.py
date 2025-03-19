import asyncio
import json
import structlog
import base64
from app.common.models import BrowserAction, BrowserTask, ActionResult, TaskResult

# Configure structlog
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ]
)

log = structlog.get_logger()

class BrowserUseAgent:
    """Async browser automation agent that uses Playwright for browser tasks."""
    
    def __init__(self, browser, session_id=None):
        """Initialize the browser agent.
        
        Args:
            browser: Playwright browser context to use
            session_id: Optional session ID for tracking
        """
        self.browser = browser
        self.session_id = session_id
        self.page = None
    
    async def _ensure_page(self):
        """Ensure we have an active page."""
        if not self.page:
            self.page = await self.browser.new_page()
        return self.page
    
    async def process_task(self, task_data):
        """Process a browser task.
        
        Args:
            task_data: Dictionary containing task details:
                - url: URL to navigate to
                - actions: List of actions to perform
        
        Returns:
            Dict with results of the task execution
        """
        try:
            log.info("Processing browser task", session_id=self.session_id)
            
            # Convert task_data to BrowserTask model
            if isinstance(task_data, dict):
                task = BrowserTask(**task_data)
            else:
                task = task_data
            
            # Get or create a page
            page = await self._ensure_page()
            
            # Check URL
            if not task.url:
                return TaskResult(
                    success=False,
                    error="URL is required"
                ).dict()
            
            # Navigate to URL
            log.info("Navigating to URL", url=task.url)
            await page.goto(task.url, wait_until='networkidle')
            
            # Process actions
            actions = task.actions
            results = []
            
            for action in actions:
                # Convert to BrowserAction if it's a dict
                if isinstance(action, dict):
                    action = BrowserAction(**action)
                
                action_result = await self._execute_action(page, action)
                results.append(action_result)
            
            return TaskResult(
                success=True,
                url=task.url,
                results=results
            ).dict()
        
        except Exception as e:
            log.error("Error processing browser task", error=str(e), exc_info=True)
            return TaskResult(
                success=False,
                error=str(e)
            ).dict()
    
    async def _execute_action(self, page, action):
        """Execute a single browser action.
        
        Args:
            page: Playwright page
            action: BrowserAction or dict containing action details
        
        Returns:
            ActionResult with action result
        """
        # Convert to BrowserAction if it's a dict
        if isinstance(action, dict):
            action = BrowserAction(**action)
        
        action_type = action.type
        
        try:
            if action_type == 'click':
                if not action.selector:
                    return ActionResult(
                        type='click',
                        success=False,
                        error='Selector is required for click action'
                    )
                
                await page.click(action.selector)
                return ActionResult(
                    type='click',
                    selector=action.selector,
                    success=True
                )
            
            elif action_type == 'fill':
                if not action.selector:
                    return ActionResult(
                        type='fill',
                        success=False,
                        error='Selector is required for fill action'
                    )
                
                await page.fill(action.selector, action.value or '')
                return ActionResult(
                    type='fill',
                    selector=action.selector,
                    success=True
                )
            
            elif action_type == 'screenshot':
                if action.path:
                    await page.screenshot(path=action.path, full_page=action.fullPage)
                    return ActionResult(
                        type='screenshot',
                        path=action.path,
                        success=True
                    )
                else:
                    screenshot = await page.screenshot(full_page=action.fullPage)
                    # Convert bytes to base64 string
                    screenshot_b64 = base64.b64encode(screenshot).decode('utf-8')
                    return ActionResult(
                        type='screenshot',
                        data=screenshot_b64,
                        format='base64',
                        success=True
                    )
            
            elif action_type == 'wait':
                duration = action.duration or 1000  # Default 1 second
                await asyncio.sleep(duration / 1000)  # Convert ms to seconds
                return ActionResult(
                    type='wait',
                    duration=duration,
                    success=True
                )
            
            elif action_type == 'extract_text':
                selector = action.selector or 'body'
                text = await page.text_content(selector)
                return ActionResult(
                    type='extract_text',
                    selector=selector,
                    text=text,
                    success=True
                )
            
            elif action_type == 'evaluate':
                if not action.expression:
                    return ActionResult(
                        type='evaluate',
                        success=False,
                        error='Expression is required for evaluate action'
                    )
                
                result = await page.evaluate(action.expression)
                return ActionResult(
                    type='evaluate',
                    result=result,
                    success=True
                )
            
            else:
                return ActionResult(
                    type=action_type,
                    success=False,
                    error=f'Unknown action type: {action_type}'
                )
        
        except Exception as e:
            log.error(f"Error executing action {action_type}", error=str(e), exc_info=True)
            return ActionResult(
                type=action_type,
                success=False,
                error=str(e)
            )
    
    async def close(self):
        """Close the browser agent."""
        if self.page:
            await self.page.close()
            self.page = None 