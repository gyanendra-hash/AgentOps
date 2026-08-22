"""Redis SETNX+TTL leader election so exactly one scheduler replica dispatches
jobs at a time (SRS FR-6), even with 2+ replicas running for availability.

`try_acquire()` doubles as the periodic renewal call: `SET key val NX` only
succeeds for a replica that doesn't already hold the lock, so a replica that
already is leader falls through to the CAS-renew script instead, refreshing
its own TTL. If a leader dies without releasing, the key simply expires and
another replica's next `try_acquire()` picks it up.
"""

import uuid

from redis.asyncio import Redis

_RENEW_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('PEXPIRE', KEYS[1], ARGV[2])
end
return 0
"""

_RELEASE_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""


class LeaderElection:
    def __init__(
        self,
        redis: Redis,
        key: str,
        ttl_seconds: float,
        instance_id: str | None = None,
    ) -> None:
        self._redis = redis
        self._key = key
        self._ttl_ms = int(ttl_seconds * 1000)
        self.instance_id = instance_id or str(uuid.uuid4())
        self._renew_script = None
        self._release_script = None
        self._is_leader = False

    async def try_acquire(self) -> bool:
        acquired = await self._redis.set(
            self._key, self.instance_id, nx=True, px=self._ttl_ms
        )
        if acquired:
            self._is_leader = True
            return True
        return await self.renew()

    async def renew(self) -> bool:
        if self._renew_script is None:
            self._renew_script = self._redis.register_script(_RENEW_SCRIPT)
        result = await self._renew_script(
            keys=[self._key], args=[self.instance_id, self._ttl_ms]
        )
        self._is_leader = bool(result)
        return self._is_leader

    async def release(self) -> None:
        if self._release_script is None:
            self._release_script = self._redis.register_script(_RELEASE_SCRIPT)
        await self._release_script(keys=[self._key], args=[self.instance_id])
        self._is_leader = False

    @property
    def is_leader(self) -> bool:
        return self._is_leader
