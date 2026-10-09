import asyncio

# Concurrent ingestion runs would race on the manifest and on deleting/re-adding the same chunks.
ingestion_lock = asyncio.Lock()
