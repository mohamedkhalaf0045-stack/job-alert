import sys
sys.path.insert(0, 'cloud')
from enricher import _load_settings_json
from supabase import create_client
cfg = _load_settings_json()
sb = create_client(cfg['SupabaseUrl'], cfg['SupabaseKey'])
r = sb.table('jobs').select('job_id,title,llm_score,date_collected').not_.is_('llm_score','null').gte('date_collected','2026-06-16').order('date_collected', desc=True).limit(15).execute()
print(f'Scored today: {len(r.data)} jobs')
for row in r.data:
    print(f"  {row['llm_score']}/10  {row['title'][:60]}")
