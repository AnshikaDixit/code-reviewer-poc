import os
import asyncpg
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://user:pass@localhost:5432/db")

async def init_db():
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS review_state (
                id SERIAL PRIMARY KEY,
                repo_name VARCHAR(255) NOT NULL,
                pr_number INT NOT NULL,
                commit_sha VARCHAR(255) NOT NULL,
                filename TEXT NOT NULL,
                UNIQUE(repo_name, pr_number, commit_sha, filename)
            )
        ''')
        await conn.close()
    except Exception as e:
        print(f"Failed to init DB: {e}")


async def get_reviewed_files(repo_name: str, pr_number: int, commit_sha: str) -> set:
    reviewed_files = set()
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        rows = await conn.fetch('''
            SELECT filename FROM review_state
            WHERE repo_name = $1 AND pr_number = $2 AND commit_sha = $3
        ''', repo_name, pr_number, commit_sha)
        for row in rows:
            reviewed_files.add(row['filename'])
        await conn.close()
    except Exception as e:
        print(f"Failed to fetch reviewed files from DB: {e}")
    return reviewed_files


async def mark_files_as_reviewed(repo_name: str, pr_number: int, commit_sha: str, filenames: list[str]):
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        for filename in filenames:
            await conn.execute('''
                INSERT INTO review_state (repo_name, pr_number, commit_sha, filename)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT DO NOTHING
            ''', repo_name, pr_number, commit_sha, filename)
        await conn.close()
    except Exception as e:
        print(f"DB Error marking files as reviewed: {e}")
