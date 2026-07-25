import logging

from telethon import TelegramClient, events
from telethon.sessions import StringSession

from src.core.config import settings
from src.core.database import async_session_maker
from src.jobs.services.ingestion import MessageIngestionService

logger = logging.getLogger(__name__)


class TelegramPoller:
    """
    Manages the Telethon client and event listeners.
    """

    def __init__(self):
        self.client = TelegramClient(
            StringSession(settings.TELEGRAM_SESSION_STRING),
            settings.TELEGRAM_API_ID,
            settings.TELEGRAM_API_HASH,
        )

    async def start(self):
        logger.info("Starting Telegram Poller...")
        await self.client.start()

        @self.client.on(events.NewMessage(chats=settings.TELEGRAM_CHANNEL_ID))
        async def handler(event):
            await self._handle_new_message(event)

        logger.info(f"Listening for messages on channel {settings.TELEGRAM_CHANNEL_ID}")
        await self.client.run_until_disconnected()

    async def _handle_new_message(self, event):
        try:
            async with async_session_maker() as session:
                async with session.begin():
                    ingestion_service = MessageIngestionService(session)
                    await ingestion_service.ingest_message(
                        telegram_message_id=event.id,
                        channel_id=event.chat_id,
                        text=event.raw_text,
                    )
        except Exception as e:
            logger.error(f"Error handling new message: {e}")
