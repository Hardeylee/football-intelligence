import pandas as pd
df = pd.read_csv('data/premier_league_teams_flat.csv')

print("=== PPDA check (lower = more pressing) ===")
print(df[['team', 'sequences_overall_ppda']].sort_values(
    'sequences_overall_ppda').to_string())

print("\n=== Set-piece xG containment check ===")
df['sp_xg_exceeds_overall'] = df['attack_set_piece_team_sp_xG'] > df['attack_overall_xg']
print(df[['team', 'attack_overall_xg', 'attack_set_piece_team_sp_xG',
      'sp_xg_exceeds_overall']].to_string())
print(f"\nAny violations: {df['sp_xg_exceeds_overall'].any()}")

print("\n=== Start distance check (higher = higher defensive line) ===")
print(df[['team', 'sequences_overall_start_distance']].sort_values(
    'sequences_overall_start_distance', ascending=False).to_string())
