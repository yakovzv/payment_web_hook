from contextlib import asynccontextmanager

import aiohttp


class HttpRequests:
    def __init__(self):
        self._client_session = aiohttp.ClientSession

    @asynccontextmanager
    async def get_session(self) -> aiohttp.ClientSession:
        async with self._client_session() as session:
            yield session
