import asyncio

from app.leader_election import LeaderElection


async def test_first_replica_acquires_leadership(redis_client):
    leader = LeaderElection(redis_client, "leader:test", ttl_seconds=5.0)
    assert await leader.try_acquire() is True
    assert leader.is_leader is True


async def test_second_replica_cannot_acquire_while_first_holds_lock(redis_client):
    leader_a = LeaderElection(redis_client, "leader:test", ttl_seconds=5.0)
    leader_b = LeaderElection(redis_client, "leader:test", ttl_seconds=5.0)

    assert await leader_a.try_acquire() is True
    assert await leader_b.try_acquire() is False
    assert leader_b.is_leader is False


async def test_leader_can_renew_its_own_lock(redis_client):
    leader = LeaderElection(redis_client, "leader:test", ttl_seconds=5.0)
    assert await leader.try_acquire() is True
    assert await leader.try_acquire() is True  # second call renews, doesn't fail


async def test_release_lets_another_replica_take_over(redis_client):
    leader_a = LeaderElection(redis_client, "leader:test", ttl_seconds=5.0)
    leader_b = LeaderElection(redis_client, "leader:test", ttl_seconds=5.0)

    await leader_a.try_acquire()
    await leader_a.release()

    assert await leader_b.try_acquire() is True


async def test_expired_lock_lets_another_replica_take_over(redis_client):
    leader_a = LeaderElection(redis_client, "leader:test", ttl_seconds=0.1)
    leader_b = LeaderElection(redis_client, "leader:test", ttl_seconds=5.0)

    await leader_a.try_acquire()
    await asyncio.sleep(0.2)

    assert await leader_b.try_acquire() is True


async def test_replica_cannot_release_another_replicas_lock(redis_client):
    leader_a = LeaderElection(redis_client, "leader:test", ttl_seconds=5.0)
    leader_b = LeaderElection(redis_client, "leader:test", ttl_seconds=5.0)

    await leader_a.try_acquire()
    await leader_b.release()  # no-op: b never held the lock

    assert await redis_client.get("leader:test") == leader_a.instance_id
