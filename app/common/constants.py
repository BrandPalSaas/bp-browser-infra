# Directory to store task results like GIFs and screenshots
TASK_RESULTS_DIR = "/tmp/task_results"

# Redis stream name for browser tasks
BROWSER_TASKS_STREAM = "browser_tasks"

# Redis key suffix for task results
TASK_RESULTS_KEY_SUFFIX = "result"

# Redis result expiration seconds
REDIS_RESULT_EXPIRATION_SECONDS = 3600 * 24 * 7 # 7 days

REDIS_COOKIES_KEY_FMT = "cookies:{}"

COOKIES_USERNAME = "oceanicnewline@gmail.com"