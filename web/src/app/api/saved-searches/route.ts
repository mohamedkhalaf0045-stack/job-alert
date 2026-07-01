import { NextRequest, NextResponse } from 'next/server'
import { createClient } from '@/lib/supabase/server'

export interface SavedSearch {
  id: string
  user_id: string
  name: string
  keywords: string[]
  locations: string[]
  min_score: number | null
  created_at: string
}

// GET /api/saved-searches — list current user's saved searches
export async function GET() {
  try {
    const supabase = await createClient()
    const { data: { user } } = await supabase.auth.getUser()
    if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

    const { data, error } = await supabase
      .from('saved_searches')
      .select('*')
      .eq('user_id', user.id)
      .order('created_at', { ascending: false })

    if (error) throw error

    return NextResponse.json({ searches: data as SavedSearch[] })
  } catch (error) {
    console.error('GET /api/saved-searches error:', error)
    return NextResponse.json({ error: 'Failed to fetch saved searches' }, { status: 500 })
  }
}

// POST /api/saved-searches — create a new saved search
export async function POST(req: NextRequest) {
  try {
    const supabase = await createClient()
    const { data: { user } } = await supabase.auth.getUser()
    if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

    const body = await req.json()
    const { name, keywords, locations, min_score } = body

    if (!name || typeof name !== 'string' || name.trim().length === 0) {
      return NextResponse.json({ error: 'Search name is required' }, { status: 400 })
    }

    const { data, error } = await supabase
      .from('saved_searches')
      .insert({
        user_id: user.id,
        name: name.trim(),
        keywords: Array.isArray(keywords) ? keywords.filter(Boolean) : [],
        locations: Array.isArray(locations) ? locations.filter(Boolean) : [],
        min_score: typeof min_score === 'number' ? min_score : null,
      })
      .select()
      .single()

    if (error) throw error

    return NextResponse.json(data as SavedSearch, { status: 201 })
  } catch (error) {
    console.error('POST /api/saved-searches error:', error)
    return NextResponse.json({ error: 'Failed to create saved search' }, { status: 500 })
  }
}
