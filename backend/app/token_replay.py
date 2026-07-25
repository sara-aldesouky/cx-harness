"""Provider-independent replay protection for signed authentication tokens."""

from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
from math import ceil
from threading import Lock
from typing import Callable, Protocol


class TokenUsagePolicy(str, Enum):
    """Supported credential reuse policies."""

    SESSION = "session"
    ONE_TIME = "one_time"


class TokenReplayDecision(str, Enum):
    """Internal replay-store decisions; callers expose only safe failures."""

    ALLOWED = "allowed"
    REVOKED = "revoked"
    REPLAYED = "replayed"


class TokenReplayProtector(Protocol):
    """Contract suitable for in-memory, Redis, or database implementations."""

    def check_and_record(
        self,
        token_identifier: str,
        expires_at: datetime,
        policy: TokenUsagePolicy,
    ) -> TokenReplayDecision: ...

    def revoke(self, token_identifier: str, expires_at: datetime) -> None: ...


class DistributedTokenReplayStore(Protocol):
    """Atomic shared-state operations required by distributed protection."""

    def check_and_record(
        self, key: str, ttl_seconds: int, policy: TokenUsagePolicy
    ) -> TokenReplayDecision: ...

    def revoke(self, key: str, ttl_seconds: int) -> None: ...


class DistributedTokenReplayProtector:
    """Adapt an atomic shared store to the existing replay-protector contract."""

    def __init__(
        self,
        store: DistributedTokenReplayStore,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        namespace: str = "cx:authentication:replay",
    ) -> None:
        if not callable(getattr(store, "check_and_record", None)) or not callable(
            getattr(store, "revoke", None)
        ):
            raise TypeError("store must implement atomic replay operations")
        if not namespace.strip():
            raise ValueError("namespace must not be blank")
        self._store = store
        self._clock = clock
        self._namespace = namespace.strip().rstrip(":")

    def check_and_record(
        self,
        token_identifier: str,
        expires_at: datetime,
        policy: TokenUsagePolicy,
    ) -> TokenReplayDecision:
        InMemoryTokenReplayProtector._validate(token_identifier, expires_at)
        ttl = self._ttl(expires_at)
        return TokenReplayDecision(
            self._store.check_and_record(
                self._key(token_identifier), ttl, TokenUsagePolicy(policy)
            )
        )

    def revoke(self, token_identifier: str, expires_at: datetime) -> None:
        InMemoryTokenReplayProtector._validate(token_identifier, expires_at)
        self._store.revoke(self._key(token_identifier), self._ttl(expires_at))

    def _ttl(self, expires_at: datetime) -> int:
        remaining = ceil((expires_at - self._clock()).total_seconds())
        if remaining < 1:
            raise ValueError("replay state must expire in the future")
        return remaining

    def _key(self, token_identifier: str) -> str:
        # Raw JTIs never enter infrastructure keys or diagnostics.
        digest = sha256(token_identifier.strip().encode("utf-8")).hexdigest()
        return f"{self._namespace}:{{{digest}}}"


class RedisAtomicClient(Protocol):
    """Minimal client surface implemented by redis-py and compatible clients."""

    def eval(self, script: str, numkeys: int, *keys_and_args): ...


class RedisTokenReplayStore:
    """Redis-backed cluster-safe atomic replay state with native TTL cleanup.

    Each operation touches exactly one hash-tagged key, so it remains atomic in
    Redis Cluster. The Redis client is injected; importing this module does not
    require a concrete Redis SDK.
    """

    _CHECK_SCRIPT = """
local state = redis.call('GET', KEYS[1])
if state == 'revoked' then return 'revoked' end
if ARGV[2] == 'session' then return 'allowed' end
if state == 'consumed' then return 'replayed' end
local created = redis.call('SET', KEYS[1], 'consumed', 'EX', ARGV[1], 'NX')
if created then return 'allowed' end
state = redis.call('GET', KEYS[1])
if state == 'revoked' then return 'revoked' end
return 'replayed'
""".strip()
    _REVOKE_SCRIPT = """
redis.call('SET', KEYS[1], 'revoked', 'EX', ARGV[1])
return 1
""".strip()

    def __init__(self, client: RedisAtomicClient) -> None:
        if not callable(getattr(client, "eval", None)):
            raise TypeError("client must provide eval()")
        self._client = client

    def check_and_record(
        self, key: str, ttl_seconds: int, policy: TokenUsagePolicy
    ) -> TokenReplayDecision:
        result = self._client.eval(
            self._CHECK_SCRIPT, 1, key, ttl_seconds, TokenUsagePolicy(policy).value
        )
        if isinstance(result, bytes):
            result = result.decode("ascii")
        return TokenReplayDecision(result)

    def revoke(self, key: str, ttl_seconds: int) -> None:
        self._client.eval(self._REVOKE_SCRIPT, 1, key, ttl_seconds)


class InMemoryTokenReplayProtector:
    """Bounded, thread-safe development replay and revocation store.

    Session credentials may be reused until expiry unless revoked. One-time
    credentials are atomically consumed on first successful authentication.
    Expired state is removed during each operation, and the oldest-expiring
    entries are evicted when the configured bound is exceeded.
    """

    def __init__(
        self,
        *,
        max_entries: int = 10_000,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        if not isinstance(max_entries, int) or isinstance(max_entries, bool) or max_entries < 1:
            raise ValueError("max_entries must be a positive integer")
        self._max_entries = max_entries
        self._clock = clock
        self._revoked: OrderedDict[str, datetime] = OrderedDict()
        self._consumed: OrderedDict[str, datetime] = OrderedDict()
        self._lock = Lock()

    def check_and_record(
        self,
        token_identifier: str,
        expires_at: datetime,
        policy: TokenUsagePolicy,
    ) -> TokenReplayDecision:
        self._validate(token_identifier, expires_at)
        policy = TokenUsagePolicy(policy)
        now = self._clock()
        with self._lock:
            self._cleanup(now)
            if token_identifier in self._revoked:
                return TokenReplayDecision.REVOKED
            if policy is TokenUsagePolicy.ONE_TIME:
                if token_identifier in self._consumed:
                    return TokenReplayDecision.REPLAYED
                self._ensure_capacity()
                self._consumed[token_identifier] = expires_at
        return TokenReplayDecision.ALLOWED

    def revoke(self, token_identifier: str, expires_at: datetime) -> None:
        self._validate(token_identifier, expires_at)
        now = self._clock()
        with self._lock:
            self._cleanup(now)
            if token_identifier not in self._revoked:
                self._ensure_capacity()
            self._revoked[token_identifier] = expires_at

    @property
    def state_size(self) -> int:
        """Return tracked entries for diagnostics and bounded-state tests."""

        with self._lock:
            self._cleanup(self._clock())
            return len(self._revoked) + len(self._consumed)

    def _cleanup(self, now: datetime) -> None:
        for store in (self._revoked, self._consumed):
            expired = [key for key, expiry in store.items() if expiry <= now]
            for key in expired:
                store.pop(key, None)

    def _ensure_capacity(self) -> None:
        # Never evict a still-valid revocation or one-time consumption marker:
        # doing so would silently re-enable a credential. Capacity exhaustion
        # therefore fails closed until expiry cleanup frees space.
        if len(self._revoked) + len(self._consumed) >= self._max_entries:
            raise RuntimeError("replay protection capacity exhausted")

    @staticmethod
    def _validate(token_identifier: str, expires_at: datetime) -> None:
        if not isinstance(token_identifier, str) or not token_identifier.strip():
            raise ValueError("token_identifier must not be blank")
        if expires_at.tzinfo is None or expires_at.utcoffset() is None:
            raise ValueError("expires_at must include a timezone")
