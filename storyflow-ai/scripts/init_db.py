"""Initialize StoryFlow AI database."""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.database import init_db, async_engine
from configs.settings import settings

async def main():
    print("Initializing database...")
    await init_db()
    print("Database tables created successfully!")
    await async_engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())