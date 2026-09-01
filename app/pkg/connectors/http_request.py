from contextlib import asynccontextmanager

import aiohttp

from app.pkg.connectors.base_connector import BaseConnector


class HttpRequests(BaseConnector):
    def __init__(self):
        self._client_session = aiohttp.ClientSession

    @asynccontextmanager
    async def get_session(self) -> aiohttp.ClientSession:
        async with self._client_session() as session:
            yield session
