"""
Atomic Redis Lua scripts for Tollgate budget reservation, settlement, and release.
Ensures multi-scope (tenant + project, daily + monthly) atomicity and leak-proof leases.
"""

BUDGET_RESERVE_LUA = """
local num_keys = tonumber(ARGV[1])
local estimated_cost = tonumber(ARGV[num_keys + 2])
local now = tonumber(ARGV[num_keys + 3])
local ttl = tonumber(ARGV[num_keys + 4])
local res_id = tostring(ARGV[num_keys + 5])
local tenant_id = tostring(ARGV[num_keys + 6])
local project_id = tostring(ARGV[num_keys + 7])

local res_record_key = KEYS[num_keys + 1]

-- Step 1: Clean up any expired reservations on all involved budget keys
for i = 1, num_keys do
    local key = KEYS[i]
    local exp_key = key .. ':res_exp'
    local cost_key = key .. ':res_cost'

    local expired_ids = redis.call('ZRANGEBYSCORE', exp_key, '-inf', now)
    for _, expired_id in ipairs(expired_ids) do
        local exp_cost = tonumber(redis.call('HGET', cost_key, expired_id) or 0)
        if exp_cost > 0 then
            redis.call('HINCRBY', key, 'reserved', -exp_cost)
            redis.call('HDEL', cost_key, expired_id)
        end
        redis.call('ZREM', exp_key, expired_id)
        redis.call('HSET', 'tg:reservation:' .. expired_id, 'status', 'expired')
    end
end

-- Step 2: Evaluate available budget across all scopes
for i = 1, num_keys do
    local key = KEYS[i]
    local limit = tonumber(ARGV[1 + i])

    -- limit >= 0 means a budget is configured; -1 means unlimited
    if limit >= 0 then
        local spent = tonumber(redis.call('HGET', key, 'spent') or 0)
        local reserved = tonumber(redis.call('HGET', key, 'reserved') or 0)
        if (spent + reserved + estimated_cost) > limit then
            -- Budget exceeded on this scope
            return {0, 'budget_exceeded', key, tostring(limit), tostring(spent + reserved)}
        end
    end
end

-- Step 3: All scopes passed. Atomically reserve estimated_cost on all keys
for i = 1, num_keys do
    local key = KEYS[i]
    local exp_key = key .. ':res_exp'
    local cost_key = key .. ':res_cost'

    redis.call('HINCRBY', key, 'reserved', estimated_cost)
    redis.call('HSET', cost_key, res_id, tostring(estimated_cost))
    redis.call('ZADD', exp_key, now + ttl, res_id)

    -- Ensure keys have long-term retention
    redis.call('EXPIRE', key, 5184000)      -- 60 days
    redis.call('EXPIRE', exp_key, 5184000)
    redis.call('EXPIRE', cost_key, 5184000)
end

-- Step 4: Record reservation state
redis.call('HSET', res_record_key,
    'reservation_id', res_id,
    'tenant_id', tenant_id,
    'project_id', project_id,
    'estimated_cost', tostring(estimated_cost),
    'status', 'reserved',
    'created_at', tostring(now),
    'num_keys', tostring(num_keys)
)
for i = 1, num_keys do
    redis.call('HSET', res_record_key, 'key_' .. i, KEYS[i])
end
redis.call('EXPIRE', res_record_key, math.max(600, ttl * 3))

return {1, 'reserved', res_id}
"""

BUDGET_SETTLE_LUA = """
local res_record_key = KEYS[1]
local actual_cost = tonumber(ARGV[1])
local now = tonumber(ARGV[2])

local status = redis.call('HGET', res_record_key, 'status')
if not status then
    return {0, 'reservation_not_found'}
end

if status == 'settled' then
    return {1, 'already_settled', '0'}
end

if status == 'released' then
    return {0, 'already_released'}
end

local res_id = redis.call('HGET', res_record_key, 'reservation_id')
local estimated_cost = tonumber(redis.call('HGET', res_record_key, 'estimated_cost') or 0)
local num_keys = tonumber(redis.call('HGET', res_record_key, 'num_keys') or 0)

if status == 'expired' then
    -- Reservation had expired so reserved amount was already released.
    -- Settle actual_cost onto spent.
    for i = 1, num_keys do
        local key = redis.call('HGET', res_record_key, 'key_' .. i)
        if key then
            redis.call('HINCRBY', key, 'spent', actual_cost)
        end
    end
    redis.call('HSET', res_record_key, 'status', 'settled', 'actual_cost', tostring(actual_cost))
    return {1, 'settled_after_expiry', '0'}
end

-- Normal settlement (status == 'reserved')
for i = 1, num_keys do
    local key = redis.call('HGET', res_record_key, 'key_' .. i)
    if key then
        local exp_key = key .. ':res_exp'
        local cost_key = key .. ':res_cost'

        redis.call('HINCRBY', key, 'reserved', -estimated_cost)
        redis.call('HINCRBY', key, 'spent', actual_cost)
        redis.call('HDEL', cost_key, res_id)
        redis.call('ZREM', exp_key, res_id)
    end
end

local refund = math.max(0, estimated_cost - actual_cost)
redis.call('HSET', res_record_key, 'status', 'settled', 'actual_cost', tostring(actual_cost))

return {1, 'settled', tostring(refund)}
"""

BUDGET_RELEASE_LUA = """
local res_record_key = KEYS[1]
local now = tonumber(ARGV[1])

local status = redis.call('HGET', res_record_key, 'status')
if not status then
    return {0, 'reservation_not_found'}
end

if status == 'released' then
    return {1, 'already_released'}
end

if status == 'settled' then
    return {0, 'cannot_release_settled'}
end

if status == 'expired' then
    return {1, 'already_expired'}
end

local res_id = redis.call('HGET', res_record_key, 'reservation_id')
local estimated_cost = tonumber(redis.call('HGET', res_record_key, 'estimated_cost') or 0)
local num_keys = tonumber(redis.call('HGET', res_record_key, 'num_keys') or 0)

for i = 1, num_keys do
    local key = redis.call('HGET', res_record_key, 'key_' .. i)
    if key then
        local exp_key = key .. ':res_exp'
        local cost_key = key .. ':res_cost'

        redis.call('HINCRBY', key, 'reserved', -estimated_cost)
        redis.call('HDEL', cost_key, res_id)
        redis.call('ZREM', exp_key, res_id)
    end
end

redis.call('HSET', res_record_key, 'status', 'released')

return {1, 'released'}
"""
