import asyncio
from sqlalchemy import text
from app.db.schema import init_db
from app.db.session import SessionLocal
from app.knowledge.service import ingest_document


async def run_once() -> None:
    db = SessionLocal()
    try:
        init_db(db)
        rows = db.execute(text("""
            SELECT document_id FROM ingestion_jobs
            WHERE status IN ('pending','failed')
            ORDER BY created_at ASC
            LIMIT 3
        """)).mappings().all()
        for row in rows:
            await ingest_document(db, str(row["document_id"]))
    finally:
        db.close()


async def main() -> None:
    while True:
        await run_once()
        await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
