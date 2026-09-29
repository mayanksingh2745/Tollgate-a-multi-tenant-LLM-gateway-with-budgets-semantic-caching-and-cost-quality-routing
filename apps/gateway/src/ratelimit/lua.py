"""
Redis Lua script for atomic token bucket rate limiting.
Ensures check, refill, and consumption happen atomically within Redis.
"""

TOKEN_BUCKET_LUA = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local cost = tonumber(ARGV[3])
local now = tonumber(ARGV[4])

-- Retrieve current state from Redis hash
local data = redis.call('HMGET', key, 'tokens', 'last_updated')
local tokens = tonumber(data[1])
local last_updated = tonumber(data[2])

if not tokens or not last_updated then
    -- Bucket uninitialized: start with full burst capacity
    tokens = capacity
    last_updated = now
else
    -- Calculate refilled tokens since last update
    local elapsed = math.max(0, now - last_updated)
    tokens = math.min(capacity, tokens + (elapsed * refill_rate))
    last_updated = now
end

local allowed = 0
local retry_after = 0
local reset_after = 0

if tokens >= cost then
    allowed = 1
    tokens = tokens - cost
else
    allowed = 0
    local deficit = cost - tokens
    if refill_rate > 0 then
        retry_after = deficit / refill_rate
    else
        retry_after = 60
    end
end

-- Time until bucket is completely replenished to capacity
local missing = capacity - tokens
if missing > 0 and refill_rate > 0 then
    reset_after = missing / refill_rate
else
    reset_after = 0
end

-- Compute TTL to avoid stale keys remaining indefinitely in Redis
local ttl = 60
if refill_rate > 0 then
    ttl = math.ceil((capacity / refill_rate) * 2)
    if ttl < 60 then
        ttl = 60
    end
end

redis.call('HSET', key, 'tokens', tostring(tokens), 'last_updated', tostring(last_updated))
redis.call('EXPIRE', key, ttl)

return {allowed, tostring(tokens), tostring(retry_after), tostring(reset_after)}
"""
