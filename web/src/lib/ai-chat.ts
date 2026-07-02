import Groq from 'groq-sdk'

const GROQ_MODEL   = 'llama-3.3-70b-versatile'
const OLLAMA_MODEL = process.env.OLLAMA_MODEL    ?? 'llama3.2'
const OLLAMA_URL   = process.env.OLLAMA_BASE_URL ?? 'http://localhost:11434'

interface Message { role: 'user' | 'assistant' | 'system'; content: string }

function isTPD(err: unknown): boolean {
  const msg = (err as { message?: string })?.message ?? ''
  return msg.includes('per day') || msg.includes('TPD')
}

async function callOllama(messages: Message[], maxTokens: number): Promise<string> {
  const resp = await fetch(`${OLLAMA_URL}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model: OLLAMA_MODEL, messages, stream: false, options: { num_predict: maxTokens } }),
    signal: AbortSignal.timeout(90_000),
  })
  if (!resp.ok) throw new Error(`Ollama ${resp.status}: ${await resp.text()}`)
  const data = await resp.json() as { message?: { content?: string } }
  const content = data.message?.content ?? ''
  if (!content) throw new Error('Ollama returned empty response')
  return content
}

/**
 * Call Groq with per-minute 429 retry. On daily limit (TPD) or full
 * retry exhaustion, falls back to Ollama automatically.
 */
export async function callAI(messages: Message[], maxTokens: number): Promise<string> {
  let groqLastErr: unknown

  if (process.env.GROQ_API_KEY) {
    const groq = new Groq({ apiKey: process.env.GROQ_API_KEY })
    for (let attempt = 0; attempt < 3; attempt++) {
      if (attempt > 0) await new Promise(r => setTimeout(r, attempt * 2000))
      try {
        const res = await groq.chat.completions.create({
          model: GROQ_MODEL,
          max_tokens: maxTokens,
          messages,
        })
        return res.choices[0]?.message?.content ?? ''
      } catch (err: unknown) {
        groqLastErr = err
        const status = (err as { status?: number })?.status
        if (status !== 429) break          // non-rate-limit → skip to Ollama
        if (isTPD(err))     break          // daily cap → skip to Ollama
        // per-minute 429 → retry loop continues
      }
    }
    console.warn('[ai-chat] Groq failed, falling back to Ollama:', (groqLastErr as Error)?.message)
  }

  // Ollama fallback
  try {
    return await callOllama(messages, maxTokens)
  } catch (ollamaErr) {
    // Both failed — surface Groq error if we have it (more informative for TPD)
    const groqMsg  = (groqLastErr  as Error)?.message ?? ''
    const ollamaMsg = (ollamaErr  as Error)?.message ?? ''
    const isGroqTPD = isTPD(groqLastErr)
    const msg = isGroqTPD
      ? `AI daily limit reached. Ollama fallback also failed: ${ollamaMsg}`
      : `Groq error: ${groqMsg} | Ollama error: ${ollamaMsg}`
    throw new Error(msg)
  }
}
