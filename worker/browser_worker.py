from browser_use import BrowserUseAgent
from playwright.sync_api import sync_playwright
import os
import time
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
from urllib.parse import parse_qs
import structlog

# Configure structlog
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ]
)

log = structlog.get_logger()

class BrowserWorker:
    def __init__(self):
        self.playwright = None
        self.browser = None
        self.ready = False
    
    def start(self):
        """Start the browser."""
        log.info("Starting browser")
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(
            headless=True,
            args=['--no-sandbox']
        )
        self.ready = True
        log.info("Browser started successfully")
        return self.browser
    
    def stop(self):
        """Stop the browser."""
        log.info("Stopping browser")
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()
        self.ready = False
        log.info("Browser stopped")
    
    def execute_task(self, task_description):
        """
        Execute a task using browser-use.
        
        Args:
            task_description: A string describing the task to perform
            
        Returns:
            A string with the result
        """
        task_id = os.urandom(4).hex()
        log_ctx = log.bind(task_id=task_id)
        
        try:
            log_ctx.info("Executing task", task=task_description[:100])
            if not self.ready:
                log_ctx.info("Browser not ready, starting")
                self.start()
                
            # Create a browser-use agent
            agent = BrowserUseAgent(browser=self.browser)
            result = agent.run(task_description)
            
            log_ctx.info("Task completed successfully")
            return {
                "success": True,
                "result": result
            }
        except Exception as e:
            log_ctx.error("Error executing task", error=str(e), exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

# Create a global worker instance
browser_worker = BrowserWorker()

class TaskHandler(BaseHTTPRequestHandler):
    def _set_headers(self, status_code=200, content_type='application/json'):
        self.send_response(status_code)
        self.send_header('Content-type', content_type)
        self.end_headers()
    
    def log_request(self, code='-', size='-'):
        # Override to use structlog instead of default logging
        log.info("Request received", 
                 method=self.command, 
                 path=self.path, 
                 status=code,
                 client=self.client_address[0])
    
    def log_error(self, format, *args):
        # Override to use structlog instead of default logging
        log.error("HTTP error", error=format % args)
        
    def do_GET(self):
        if self.path == '/healthz':
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'OK')
        else:
            self.send_response(404)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Not Found')
            
    def do_POST(self):
        if self.path == '/execute':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            
            req_id = os.urandom(4).hex()
            request_log = log.bind(request_id=req_id)
            
            try:
                data = json.loads(post_data.decode('utf-8'))
                task = data.get('task')
                
                if not task:
                    request_log.warning("Missing task field in request")
                    self._set_headers(400)
                    self.wfile.write(json.dumps({"error": "Missing 'task' field"}).encode())
                    return
                
                # Execute the task
                request_log.info("Executing task", task_length=len(task))
                result = browser_worker.execute_task(task)
                
                # Return the result
                if result.get("success"):
                    request_log.info("Task executed successfully", result_length=len(str(result.get("result", ""))))
                else:
                    request_log.warning("Task execution failed", error=result.get("error"))
                
                self._set_headers()
                self.wfile.write(json.dumps(result).encode())
            except json.JSONDecodeError:
                request_log.error("Invalid JSON in request")
                self._set_headers(400)
                self.wfile.write(json.dumps({"error": "Invalid JSON"}).encode())
            except Exception as e:
                request_log.error("Server error processing request", error=str(e), exc_info=True)
                self._set_headers(500)
                self.wfile.write(json.dumps({"error": str(e)}).encode())
        else:
            self._set_headers(404)
            self.wfile.write(json.dumps({"error": "Not Found"}).encode())

def run_server(port=3000):
    server_address = ('', port)
    httpd = HTTPServer(server_address, TaskHandler)
    log.info("Starting server", port=port)
    
    # Start the browser in a background thread
    def start_browser():
        browser_worker.start()
    
    browser_thread = threading.Thread(target=start_browser)
    browser_thread.daemon = True
    browser_thread.start()
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log.info("Server interrupted by user")
    except Exception as e:
        log.error("Server error", error=str(e), exc_info=True)
    finally:
        httpd.server_close()
        browser_worker.stop()
        log.info("Server stopped")

if __name__ == '__main__':
    port = int(os.getenv('PORT', 3000))
    run_server(port) 