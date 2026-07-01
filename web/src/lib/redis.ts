// Rate limiting via Upstash Redis
// Endpoint: env UPSTASH_REDIS_REST_URL + UPSTASH_REDIS_REST_TOKEN
// Rule: 1 message per 2 seconds per user (max 30 messages per 60 sec)

interface RateLimitResult {
  allowed: boolean
  remaining: number
  resetAt: number
}

async function redisCall(
  command: string,
  args: (string | number)[]
): Promise<unknown> {
  const url = process.env.UPSTASH_REDIS_REST_URL
  const token = process.env.UPSTASH_REDIS_REST_TOKEN

  if (!url || !token) {
    console.warn('Upstash Redis not configured; rate limiting disabled')
    return null
  }

  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        command,
        args,
      }),
    })

    if (!res.ok) {
      console.error(`Redis error: ${res.status}`)
      return null
    }

    const data = await res.json() as { result?: unknown }
    return data.result
  } catch (error) {
    console.error('Redis call failed:', error)
    return null
  }
}

export async function checkMessageRateLimit(
  userId: string
): Promise<RateLimitResult> {
  const key = `ratelimit:msg:${userId}`
  const window = 2000 // milliseconds (2 seconds)
  const maxPerWindow = 1

  // Attempt to increment the counter
  // First, get current value
  const currentVal = await redisCall('GET', [key])
  const current = currentVal ? parseInt(String(currentVal)) : 0

  // If we've exceeded the limit, return false
  if (current >= maxPerWindow) {
    const ttl = await redisCall('TTL', [key])
    const resetAt = Date.now() + (ttl && typeof ttl === 'number' && ttl > 0 ? ttl * 1000 : window)
    return {
      allowed: false,
      remaining: 0,
      resetAt,
    }
  }

  // Increment the counter and set TTL
  await redisCall('INCR', [key])
  await redisCall('PEXPIRE', [key, window])

  return {
    allowed: true,
    remaining: maxPerWindow - (current + 1),
    resetAt: Date.now() + window,
  }
}

// Optional: strict rate limit check (useful for testing)
// 30 messages per 60 seconds
export async function checkMessageRateLimitStrict(
  userId: string
): Promise<RateLimitResult> {
  const key = `ratelimit:msg:strict:${userId}`
  const window = 60000 // 60 seconds
  const maxPerWindow = 30

  const currentVal = await redisCall('GET', [key])
  const current = currentVal ? parseInt(String(currentVal)) : 0

  if (current >= maxPerWindow) {
    const ttl = await redisCall('TTL', [key])
    const resetAt = Date.now() + (ttl && typeof ttl === 'number' && ttl > 0 ? ttl * 1000 : window)
    return {
      allowed: false,
      remaining: 0,
      resetAt,
    }
  }

  await redisCall('INCR', [key])
  await redisCall('PEXPIRE', [key, window])

  return {
    allowed: true,
    remaining: maxPerWindow - (current + 1),
    resetAt: Date.now() + window,
  }
}
