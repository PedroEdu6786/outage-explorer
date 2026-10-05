"""Durable admission and fenced background ownership transactions."""

from typing import Protocol

from outage_explorer.domain.publication import (
    RefreshConfiguration,
    RefreshOwner,
    RefreshRun,
    RefreshStage,
    RunStatus,
)


class RefreshStore(Protocol):
    def replay(
        self, requester_id: str, key_digest: str, request_identity: str
    ) -> RefreshRun | None: ...
    def admit(
        self,
        requester_id: str,
        key_digest: str,
        request_identity: str,
        configuration: RefreshConfiguration,
    ) -> RefreshRun: ...
    def get_run(self, run_id: str) -> RefreshRun | None: ...
    def latest(self) -> RefreshRun | None: ...
    def claim(self, identity: str, lease_seconds: int) -> RefreshOwner | None: ...
    def heartbeat(self, owner: RefreshOwner, lease_seconds: int) -> None: ...
    def progress(
        self, owner: RefreshOwner, stage: RefreshStage, quality_json: str | None = None
    ) -> None: ...
    def finish(
        self,
        owner: RefreshOwner,
        status: RunStatus,
        quality_json: str | None = None,
        failure: str | None = None,
    ) -> RefreshRun: ...
    def recover(self, run_id: str) -> RefreshRun: ...
