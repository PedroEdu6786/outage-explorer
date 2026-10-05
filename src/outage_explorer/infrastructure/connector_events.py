"""Connector diagnostics without raw records, URLs, credentials or exceptions."""

import logging


class LoggingConnectorEvents:
    def emit(self, event: str, **details: str | int) -> None:
        logging.getLogger("outage_explorer.connector").log(
            logging.ERROR if event.endswith("_failed") else logging.INFO,
            "%s %s",
            event,
            " ".join(f"{key}={value}" for key, value in details.items()),
        )
