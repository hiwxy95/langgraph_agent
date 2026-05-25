import asyncio

from app.db.init_db import init_all


if __name__ == "__main__":
    asyncio.run(init_all())
