# Phase 2: Quick Reference — Files & Testing

## Files Created

### Database (1 file)
- `cloud/migrations/2026-07-01-phase2-chat.sql` (208 lines)
  - 4 tables: conversations, messages, blocked_users (column), message_reports
  - 13 RLS policies for security isolation
  - Indexes for performance

### Rate Limiting (1 file)
- `web/src/lib/redis.ts` (85 lines)
  - Upstash Redis integration
  - 1 msg per 2 sec limit
  - Graceful fallback if Redis unavailable

### API Routes (4 files)
- `web/src/app/api/conversations/route.ts` (188 lines)
  - POST: Create conversation (blocks check, validation)
  - GET: List conversations (paginated)

- `web/src/app/api/conversations/[id]/messages/route.ts` (182 lines)
  - POST: Send message (rate-limited, sender validation)
  - GET: Fetch messages (paginated, marks read)

- `web/src/app/api/users/[id]/block/route.ts` (98 lines)
  - PUT: Block/unblock users (updates blocked_users array)

- `web/src/app/api/messages/[id]/report/route.ts` (110 lines)
  - POST: Report message (deduplication, validation)

### UI Components (1 file)
- `web/src/components/ChatMessagesPanel.tsx` (285 lines)
  - Reusable chat panel (message list + input)
  - Realtime subscription via Supabase channels
  - Report/block buttons
  - Read indicators, timestamps

### Pages (2 files)
- `web/src/app/app/messages/page.tsx` (163 lines)
  - Conversation inbox (list of threads)
  - Last message preview
  - Timestamp formatting (1m ago, 2h ago, etc.)

- `web/src/app/app/messages/[id]/page.tsx` (118 lines)
  - Conversation detail (messages + compose)
  - Participant info, job context badge

### Documentation (2 files)
- `PHASE2-SETUP.md` — Complete setup & testing guide
- `PHASE2-QUICK-REF.md` — This file

**Total: 12 files, ~1400 lines of code**

---

## Quick Test Checklist

### ✓ Database
- [ ] Run migration in Supabase SQL Editor
- [ ] Verify tables created: `select table_name from information_schema.tables where table_schema='public' and table_name in ('conversations','messages','message_reports');`
- [ ] Verify RLS enabled: `select tablename from pg_tables where schemaname='public' and tablename in ('conversations','messages','message_reports');`

### ✓ API — Create Conversation
```bash
curl -X POST http://localhost:3000/api/conversations \
  -H "Authorization: Bearer [JWT]" \
  -H "Content-Type: application/json" \
  -d '{
    "recipient_id": "[user-uuid]",
    "job_posting_id": null,
    "initiated_by": "employer"
  }'
# Expected: HTTP 200 with conversation object
```

### ✓ API — Send Message
```bash
curl -X POST http://localhost:3000/api/conversations/[conv-id]/messages \
  -H "Authorization: Bearer [JWT]" \
  -H "Content-Type: application/json" \
  -d '{"content": "Hello!"}' 
# Expected: HTTP 200 with message object
```

### ✓ API — Rate Limiting
```bash
# Message 1: OK
# Message 2 (within 2 sec): HTTP 429
# After 2 sec: OK
```

### ✓ API — Block User
```bash
curl -X PUT http://localhost:3000/api/users/[user-id]/block \
  -H "Authorization: Bearer [JWT]" \
  -H "Content-Type: application/json" \
  -d '{"action":"block"}'
# Expected: HTTP 200
```

### ✓ API — Report Message
```bash
curl -X POST http://localhost:3000/api/messages/[msg-id]/report \
  -H "Authorization: Bearer [JWT]" \
  -H "Content-Type: application/json" \
  -d '{"reason":"Spam"}'
# Expected: HTTP 200
```

### ✓ UI — Inbox Page
1. Navigate to `/app/messages`
2. Should see list of conversations
3. Click conversation → open `/app/messages/[id]`

### ✓ UI — Real-Time Chat
1. Open `/app/messages/[id]` in two browsers (different users)
2. Send message in one
3. Should appear instantly in the other (Realtime subscription)

### ✓ RLS Isolation
1. Login as User A
2. Query `/api/conversations` → only see conversations where User A is participant
3. Logout, login as User B
4. Query `/api/conversations` → only see conversations where User B is participant
5. User A should NOT see User B's conversations (even if same job posting)

---

## Environment Setup

### Local Development
```bash
# In web/.env.local
NEXT_PUBLIC_SUPABASE_URL=https://...
NEXT_PUBLIC_SUPABASE_ANON_KEY=...
SUPABASE_SERVICE_ROLE_KEY=...

# Optional: Upstash Redis (for rate limiting)
UPSTASH_REDIS_REST_URL=https://...
UPSTASH_REDIS_REST_TOKEN=...
```

### Supabase Config
1. Ensure `messages` table has Realtime enabled (Replication → Realtime)
2. Ensure `conversations` table has Realtime enabled (optional, for inbox updates)

### Deploy to Production
1. Add `UPSTASH_REDIS_REST_URL` + `UPSTASH_REDIS_REST_TOKEN` to Vercel env
2. Run migration in production Supabase instance
3. Enable Realtime on `messages` table in production

---

## Known Limitations & Next Steps

### Not Yet Implemented
- [ ] Typing indicators ("User is typing...")
- [ ] Conversation archiving
- [ ] File attachments
- [ ] Admin moderation dashboard (reports can be viewed via SQL only)
- [ ] Message search / full-text search
- [ ] Unread message count badges

### To Integrate Into UI
1. Add "Message" button to candidate profile cards (HR view)
2. Add "HR messaged you" badge in candidate nav
3. Add conversation unread count badge
4. Add link to messages from job posting detail

---

## Code Patterns

### Rate Limiting Check
```typescript
import { checkMessageRateLimit } from '@/lib/redis'

const result = await checkMessageRateLimit(userId)
if (!result.allowed) {
  return NextResponse.json(
    { error: 'Rate limited', retryAfter: result.resetAt - Date.now() },
    { status: 429 }
  )
}
```

### Realtime Subscription (ChatMessagesPanel)
```typescript
const channel = supabase
  .channel(`messages:${conversationId}`)
  .on('postgres_changes', {
    event: 'INSERT',
    schema: 'public',
    table: 'messages',
    filter: `conversation_id=eq.${conversationId}`
  }, (payload) => {
    setMessages(prev => [...prev, payload.new])
  })
  .subscribe()
```

### RLS Check (Verified at DB level)
```sql
-- Users can only see conversations they participate in
create policy conversations_select_own on public.conversations
  for select to authenticated
  using (auth.uid() = candidate_id or auth.uid() = employer_id);
```

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Messages don't appear instantly | Check Realtime enabled on `messages` table |
| Rate limiting too strict | Adjust `checkMessageRateLimit()` window in `web/src/lib/redis.ts` |
| RLS blocks valid queries | Verify JWT has correct `sub` claim; test with service_role |
| "Cannot message yourself" error | Validate recipient_id != user.id on client side |
| Blocked user can still message | Verify block list is checked before message insert |

---

## Performance Notes

- Conversations indexed on (candidate_id, employer_id)
- Messages indexed on (conversation_id, sent_at)
- Pagination: 50 messages per page
- Realtime: Supabase default polling (1 sec)
- Rate limit: Redis lookup per message (atomic)

All queries use prepared statements / parameterized inserts (Supabase SDK).
