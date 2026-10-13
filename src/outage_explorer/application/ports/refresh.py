"""Durable admission and fenced background ownership transactions."""

from contextlib import AbstractContextManager
from typing import Protocol

from outage_explorer.domain.publication import (
    RefreshConfiguration,
    RefreshOwner,
    RefreshRun,
    RefreshStage,
    RunStatus,
)


class RefreshAdmissionTransaction(Protocol):
    @property
    def active_run_id(self) -> str | None: ...

    @property
    def base_generation_id(self) -> str | None: ...

    def replay(self, requester_id: str, key_digest: str) -> RefreshRun | None: ...
    def require_supported_base(self) -> None: ...
    def create_queued_run(
        self,
        requester_id: str,
        key_digest: str,
        configuration: RefreshConfiguration,
    ) -> RefreshRun: ...


class RefreshStore(Protocol):
    def replay(self, requester_id: str, key_digest: str) -> RefreshRun | None: ...
    def admission_transaction(
        self,
    ) -> AbstractContextManager[RefreshAdmissionTransaction]: ...
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
