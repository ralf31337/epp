import asyncio
import datetime as dt
import logging

from epp.appconfig import ConfigStore, next_runs
from epp.config import Settings
from epp.sync import Runner

log = logging.getLogger(__name__)


class Scheduler:
    def __init__(self, settings: Settings, config: ConfigStore, runner: Runner):
        self.settings = settings
        self.config = config
        self.runner = runner
        self.next_run: dt.datetime | None = None
        self.last_skip_reason: str | None = None
        self._wake = asyncio.Event()

    def reschedule(self) -> None:
        self._wake.set()

    async def run_forever(self) -> None:
        while True:
            self._wake.clear()
            self.next_run = next_runs(self.config.get().schedule_cron, self.settings.tz, 1)[0]
            delay = (self.next_run - dt.datetime.now(self.settings.tz)).total_seconds()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=max(delay, 0))
                continue
            except TimeoutError:
                pass
            self._trigger()
            await asyncio.sleep(1)

    def _trigger(self) -> None:
        if self.runner.credentials.get() is None:
            self.last_skip_reason = "Skipped scheduled sync: credentials not entered since the last restart"
            log.warning(self.last_skip_reason)
            return
        self.runner.request_sync()
        self.last_skip_reason = None
