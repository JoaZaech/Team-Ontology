-- Atomically records a final decision for one live run and maintains a rolling
-- approved-spend window. All four keys must share a Redis Cluster hash tag,
-- for example: viseca:run:{RUN123}:decisions.
--
-- KEYS[1] = decisions hash (authorization_id -> approve|decline|step_up)
-- KEYS[2] = approved events sorted set (authorization_id -> simulated timestamp ms)
-- KEYS[3] = approved amount hash (authorization_id -> CHF cents)
-- KEYS[4] = run state hash (approved_spend_cents, audit fields)
--
-- ARGV[1] = authorization_id
-- ARGV[2] = original simulated timestamp in milliseconds
-- ARGV[3] = amount in CHF cents
-- ARGV[4] = final decision: approve | decline | step_up
-- ARGV[5] = rolling window in milliseconds
-- ARGV[6] = mode: record | resolve_step_up

local authorization_id = ARGV[1]
local event_time = tonumber(ARGV[2])
local amount_cents = tonumber(ARGV[3])
local decision = ARGV[4]
local window_ms = tonumber(ARGV[5])
local mode = ARGV[6]

if decision ~= 'approve' and decision ~= 'decline' and decision ~= 'step_up' then
  return redis.error_reply('decision must be approve, decline, or step_up')
end
if not event_time or not amount_cents or amount_cents < 0 or not window_ms or window_ms < 0 then
  return redis.error_reply('invalid numeric argument')
end

local existing = redis.call('HGET', KEYS[1], authorization_id)
local resolving_step_up = existing == 'step_up' and mode == 'resolve_step_up'

if existing and not resolving_step_up then
  return {existing, redis.call('HGET', KEYS[4], 'approved_spend_cents') or '0', 'duplicate'}
end

if existing == 'step_up' and not resolving_step_up then
  return {existing, redis.call('HGET', KEYS[4], 'approved_spend_cents') or '0', 'pending_step_up'}
end

if resolving_step_up and decision == 'step_up' then
  return redis.error_reply('a step_up must resolve to approve or decline')
end

if decision == 'approve' then
  -- The lower bound is exclusive: an event exactly at the window boundary remains.
  local cutoff = event_time - window_ms
  local expired_ids = redis.call('ZRANGEBYSCORE', KEYS[2], '-inf', '(' .. cutoff)
  for _, expired_id in ipairs(expired_ids) do
    local expired_amount = tonumber(redis.call('HGET', KEYS[3], expired_id) or '0')
    if expired_amount ~= 0 then
      redis.call('HINCRBY', KEYS[4], 'approved_spend_cents', -expired_amount)
    end
    redis.call('HDEL', KEYS[3], expired_id)
  end
  if #expired_ids > 0 then
    redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', '(' .. cutoff)
  end

  redis.call('ZADD', KEYS[2], event_time, authorization_id)
  redis.call('HSET', KEYS[3], authorization_id, amount_cents)
  redis.call('HINCRBY', KEYS[4], 'approved_spend_cents', amount_cents)
end

redis.call('HSET', KEYS[1], authorization_id, decision)
redis.call('HSET', KEYS[4], 'last_authorization_id', authorization_id, 'last_simulated_at_ms', event_time)

return {decision, redis.call('HGET', KEYS[4], 'approved_spend_cents') or '0', resolving_step_up and 'resolved' or 'recorded'}
