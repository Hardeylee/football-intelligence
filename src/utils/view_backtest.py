import json

with open('data/backtest_results.json') as f:
    data = json.load(f)

print('OVER 2.5 VALUE BETS:')
print(f"{'Date':<12} {'Match':<35} {'Model':>6} {'Odds':>6} {'Edge':>6} {'Result':>8} {'Profit':>10}")
print('-' * 85)

total_profit = 0
for m in data['matches']:
    market = m['markets'].get('over25', {})
    if market.get('is_value'):
        match = f"{m['home']} vs {m['away']}"
        result = 'WIN' if market['correct'] else 'LOSS'
        profit = market['profit'] or 0
        total_profit += profit
        print(
            f"{m['date']:<12} {match:<35} "
            f"{market['model_prob']:>6.1%} "
            f"{market['odds']:>6.2f} "
            f"{market['edge']:>6.1%} "
            f"{result:>8} "
            f"N{profit:>8,.0f}"
        )

print('-' * 85)
print(f"Total profit: N{total_profit:,.0f}")
print(
    f"Total bets: {sum(1 for m in data['matches'] if m['markets'].get('over25', {}).get('is_value'))}")
