#!/usr/bin/env python3
"""
Script to create login cookies for TikTok Shop
"""
import asyncio
import argparse
from dotenv import load_dotenv
import structlog

from app.login.tts import TTSLoginManager

# Set up logging
log = structlog.get_logger(__name__)

# Load environment variables
load_dotenv()

async def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Create login cookies for TikTok Shop')
    parser.add_argument('username', help='TikTok Shop username/email')
    parser.add_argument('password', help='TikTok Shop password')
    args = parser.parse_args()

    try:
        # Create TTSLoginManager instance
        login_manager = TTSLoginManager()
        
        # Call create_login_cookies
        print(f"Creating login cookies for user: {args.username}")
        await login_manager.create_login_cookies(args.username, args.password)
        print("Login cookies created successfully")
        
    except Exception as e:
        print(f"Error creating login cookies: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main()) 