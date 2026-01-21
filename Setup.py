#!/usr/bin/env python3
import os
import subprocess
import sys

def check_and_install():
    """Check for missing packages and install them"""
    required_packages = [
        'python-telegram-bot',
        'aiohttp',
        'aiohttp-socks'
    ]
    
    print("Checking for required packages...")
    for package in required_packages:
        try:
            __import__(package.replace('-', '_'))
            print(f"✓ {package} is installed")
        except ImportError:
            print(f"✗ {package} is missing, installing...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])

if __name__ == "__main__":
    check_and_install()
