# Phase 2: HR-to-Candidate Chat System — Setup & Testing Guide

## What's Built

Phase 2 delivers a complete real-time chat system for HR and candidate communication:

### Database Schema
- **conversations** table: One per (job_posting, candidate, employer) tuple
- **messages** table: Message content with read/sent timestamps
- **blocked_users**: JSONB array in profiles (list of blocked user IDs)
- **message_reports**: Moderation table for abuse reports
- **RLS Policies**: Strict isolation—users only see their own conversations and messages

### API Routes
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/conversations` | POST | Start a new chat |
| `/api/conversations` | GET | List user's conversations (paginated) |
| `/api/conversations/[id]/messages` | POST | Send message (rate-limited) |
| `/api/conversations/[id]/messages` | GET | Fetch messages (paginated, marks as read) |
| `/api/users/[id]/block` | PUT | Block/unblock a user |
| `/api/messages/[id]/report` | POST | Report message for moderation |

### UI Components & Pages
- **ChatMessagesPanel.tsx**: Reusable message display + input (Realtime-powered)
- **/app/messages**: Conversation inbox
- **/app/messages/[id]**: Conversation detail page

### Rate Limiting
- Upstash Redis-based: 1 message per 2 seconds per user
- Graceful degradation if Redis not configured (warns in logs)
- Returns HTTP 429 with retry-after on limit exceeded

### Real-Time Updates
- Supabase Realtime channels for instant message delivery
- Automatic message read marking
- Subscribe to `messages:{conversationId}` on component mount

---

## Setup Checklist

### 1. Run Database Migration

In Supabase SQL Editor, run:
```sql
-- Copy-paste the contents of:
-- cloud/migrations/2026-07-01-phase2-chat.sql
```

**Verify after running:**
```sql
select table_name from information_schema.tables 
where table_schema = 'public' and table_name in ('conversations', 'messages', 'message_reports');
-- Should return 3 rows
```

### 2. Configure Upstash Redis (for rate limiting)

**Option A: Local Development**

1. Create Upstash account: https://upstash.com
2. Create a Redis database (free tier OK)
3. Copy the REST API credentials
4. Add to `web/.env.local`:
```
UPSTASH_REDIS_REST_URL=https://...
UPSTASH_REDIS_REST_TOKEN=...
```

**Option B: Production (Vercel)**

1. In Vercel project settings, add env vars:
   - `UPSTASH_REDIS_REST_URL`
   - `UPSTASH_REDIS_REST_TOKEN`
2. Deploy to Vercel (rate limiting will auto-activate)

**Fallback:** If Redis not configured, the app still works but logs a warning and allows unlimited messages. Update rate limiting rules in `web/src/lib/redis.ts` as needed.

### 3. Enable Realtime for messages table (Supabase)

In Supabase dashboard:
1. Go to Replication → Realtime
2. Find `messages` table
3. Toggle "Enable Realtime" ON
4. Repeat for `conversations` table if you want conversation list updates

---

## Testing Plan

### Test 1: RLS Isolation

**Goal:** Ensure users only see conversations they participate in.

```bash
# Terminal 1: Login as User A (candidate)
# Terminal 2: Login as User B (employer)

# From Terminal 1 (User A):
curl -H "Authorization: Bearer USER_A_JWT" \
  https://your-app.com/api/conversations

# From Terminal 2 (User B):
curl -H "Authorization: Bearer USER_B_JWT" \
  https://your-app.com/api/conversations

# Expected: Each user only sees conversations where they are a participant
# HR A should NOT see HR B's conversations (even if same employer domain)
```

### Test 2: Rate Limiting

**Goal:** Verify 1 message per 2 seconds limit.

```bash
USER_ID="<uuid>"

# Message 1: Should succeed
curl -X POST https://your-app.com/api/conversations/[conv_id]/messages \
  -H "Content-Type: application/json" \
  -d '{"content":"Message 1"}' \
  # HTTP 200

# Message 2 (within 2 seconds): Should be rate-limited
curl -X POST https://your-app.com/api/conversations/[conv_id]/messages \
  -H "Content-Type: application/json" \
  -d '{"content":"Message 2"}' \
  # HTTP 429 with {"error":"Rate limit exceeded", "retryAfter":2}

# Message 3 (after waiting 2+ seconds): Should succeed
sleep 2
curl -X POST https://your-app.com/api/conversations/[conv_id]/messages \
  -H "Content-Type: application/json" \
  -d '{"content":"Message 3"}' \
  # HTTP 200
```

### Test 3: Real-Time Message Delivery

**Goal:** Verify new messages appear instantly on other participant's screen.

1. Open `/app/messages/[conversation-id]` in two browser tabs (User A and User B)
2. From Tab A, send a message
3. Check Tab B: message should appear within 1-2 seconds (Realtime subscription)
4. Check timestamp and read indicator appear correctly

### Test 4: Blocking

**Goal:** Verify blocked users can't message each other.

```bash
# User A blocks User B
curl -X PUT https://your-app.com/api/users/[user-b-id]/block \
  -H "Authorization: Bearer USER_A_JWT" \
  -H "Content-Type: application/json" \
  -d '{"action":"block"}' \
  # HTTP 200

# User B tries to message User A
curl -X POST https://your-app.com/api/conversations \
  -H "Authorization: Bearer USER_B_JWT" \
  -H "Content-Type: application/json" \
  -d '{"recipient_id":"[user-a-id]","initiated_by":"employer"}' \
  # HTTP 403 with {"error":"Cannot message this user (blocked)"}
```

### Test 5: Message Reports (Moderation)

**Goal:** Verify users can report abusive messages.

```bash
# User A reports User B's message
curl -X POST https://your-app.com/api/messages/[message-id]/report \
  -H "Authorization: Bearer USER_A_JWT" \
  -H "Content-Type: application/json" \
  -d '{"reason":"Spam and harassment"}' \
  # HTTP 200

# Check in Supabase: message_reports table should have a row with:
# - message_id: [reported message]
# - reporter_id: [user-a-id]
# - reason: "Spam and harassment"
# - resolved: false

# Admin can check reports via service_role (not exposed in UI yet)
```

### Test 6: Pagination

**Goal:** Verify messages load in batches (50 per page).

```bash
# Load messages (default 50, first page)
curl https://your-app.com/api/conversations/[conv_id]/messages

# Load second page (50 messages at offset 50)
curl "https://your-app.com/api/conversations/[conv_id]/messages?limit=50&offset=50"
```

---

## UI Integration Checklist

**Remaining work (not yet built):**

- [ ] Add "Message" button to candidate profile cards (for HR)
- [ ] Add "HR messaged you" badge in candidate navigation
- [ ] Add conversation count badge in nav (shows # of unread conversations)
- [ ] Optional: Typing indicators via Realtime

**To add a "Message" button to candidate profiles:**

```tsx
// In candidate profile component
<button onClick={() => {
  fetch('/api/conversations', {
    method: 'POST',
    body: JSON.stringify({
      recipient_id: candidateId,
      initiated_by: 'employer',
      job_posting_id: null // or pass a job ID if relevant
    })
  }).then(r => r.json()).then(conv => {
    router.push(`/app/messages/${conv.id}`)
  })
}} >
  Message Candidate
</button>
```

---

## File Reference

| Path | Purpose |
|------|---------|
| `cloud/migrations/2026-07-01-phase2-chat.sql` | Database schema + RLS policies |
| `web/src/lib/redis.ts` | Rate limiting utility (Upstash) |
| `web/src/app/api/conversations/route.ts` | POST (create) + GET (list) conversations |
| `web/src/app/api/conversations/[id]/messages/route.ts` | POST (send) + GET (fetch) messages |
| `web/src/app/api/users/[id]/block/route.ts` | Block/unblock users |
| `web/src/app/api/messages/[id]/report/route.ts` | Report messages |
| `web/src/components/ChatMessagesPanel.tsx` | Reusable chat UI (Realtime-enabled) |
| `web/src/app/app/messages/page.tsx` | Conversation inbox |
| `web/src/app/app/messages/[id]/page.tsx` | Conversation detail view |

---

## Security Notes

- **RLS**: Enforced at database level (Supabase). Users cannot see other users' conversations via SQL injection or direct API calls.
- **Blocked users**: Checked on conversation creation AND message send. Block list stored in profiles table as JSONB array.
- **Rate limiting**: Server-side Redis check on every message POST. Client-side UI respects HTTP 429 responses.
- **Reports**: Stored in public schema (anyone can report), but admin review panel is not yet built (manual SQL queries needed for now).

---

## Debugging

### Realtime not working?
- Check Supabase: Replication → Realtime, ensure `messages` table is enabled
- Check browser console for subscription errors
- Verify JWT token has correct claims

### Rate limit bypassed?
- Verify Upstash Redis env vars are set correctly
- Check server logs for "Redis call failed" warnings
- Test Redis connectivity: `curl https://your-redis-url -H "Authorization: Bearer TOKEN"`

### RLS blocking valid queries?
- Check Supabase: go to table → Row Level Security → verify policies are active
- Ensure user JWT has the correct `sub` claim (UUID)
- Test with service_role key (no RLS) to isolate the issue

---

## Next Phase Ideas

1. **Admin Moderation Dashboard**: View reports, approve/reject, auto-block repeat offenders
2. **Typing Indicators**: "User is typing..." via Realtime broadcast
3. **Conversation Archiving**: Users can archive conversations
4. **Search**: Full-text search over message content
5. **Attachments**: File upload in messages
6. **Read Receipts UI**: Show when other user opened the chat
