from pathlib import Path
from datetime import datetime
import json

class TokenTracker:

    def __init__(self, memory_dir: Path):
        self.usage_dir = memory_dir / 'token_usage'
        self.usage_dir.mkdir(parents=True, exist_ok=True)

        # Use absolute path from script location (scripts/ -> repo root -> config/)
        costs_path = Path(__file__).parent.parent / 'config' / 'model_costs.json'
        with open(costs_path) as f:
            self.model_costs = json.load(f)

        self.today = datetime.now().strftime('%Y-%m-%d')
        self.month = datetime.now().strftime('%Y-%m')
        self.session_records = []

    def record(self, response, model: str, role: str,
               company: str = '') -> float:
        """
        Pass the raw Anthropic response object.
        Extracts usage, calculates cost, appends to session records.
        Returns cost in USD.
        """
        input_tokens  = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        cost = self._cost(model, input_tokens, output_tokens)

        self.session_records.append({
            'timestamp': datetime.now().isoformat(),
            'model':         model,
            'role':          role,
            'company':       company,
            'input_tokens':  input_tokens,
            'output_tokens': output_tokens,
            'cost_usd':      cost,
        })
        return cost

    def _cost(self, model: str, inp: int, out: int) -> float:
        rates = self.model_costs.get(model, {'input': 0, 'output': 0})
        return round((inp * rates['input'] + out * rates['output']) / 1_000_000, 8)

    def save(self) -> dict:
        """
        Merge session records into today's daily file.
        Update monthly rollup.
        Return the day's summary dict.
        """
        daily_path = self.usage_dir / f'{self.today}.json'

        # Load existing records for today if any
        existing = []
        if daily_path.exists():
            with open(daily_path) as f:
                existing = json.load(f).get('records', [])

        all_records = existing + self.session_records
        summary = self._summarize(all_records)

        with open(daily_path, 'w') as f:
            json.dump({
                'date':    self.today,
                'summary': summary,
                'records': all_records,
            }, f, indent=2)

        self._update_monthly(summary)
        return summary

    def _summarize(self, records: list) -> dict:
        by_model, by_role = {}, {}
        total_cost = 0

        for r in records:
            m = r['model']
            if m not in by_model:
                by_model[m] = {'input_tokens': 0, 'output_tokens': 0,
                                'cost_usd': 0.0, 'calls': 0}
            by_model[m]['input_tokens']  += r['input_tokens']
            by_model[m]['output_tokens'] += r['output_tokens']
            by_model[m]['cost_usd']      += r['cost_usd']
            by_model[m]['calls']         += 1

            role = r['role']
            if role not in by_role:
                by_role[role] = {'input_tokens': 0, 'output_tokens': 0,
                                  'cost_usd': 0.0}
            by_role[role]['input_tokens']  += r['input_tokens']
            by_role[role]['output_tokens'] += r['output_tokens']
            by_role[role]['cost_usd']      += r['cost_usd']
            total_cost += r['cost_usd']

        # Round model costs
        for m in by_model:
            by_model[m]['cost_usd'] = round(by_model[m]['cost_usd'], 6)
        for role in by_role:
            by_role[role]['cost_usd'] = round(by_role[role]['cost_usd'], 6)

        return {
            'total_cost_usd':     round(total_cost, 6),
            'total_input_tokens': sum(r['input_tokens'] for r in records),
            'total_output_tokens':sum(r['output_tokens'] for r in records),
            'total_calls':        len(records),
            'by_model':           by_model,
            'by_role':            by_role,
        }

    def _update_monthly(self, day_summary: dict):
        path = self.usage_dir / f'monthly_{self.month}.json'
        data = {'month': self.month, 'days': {}, 'total_cost_usd': 0.0,
                'by_model': {}, 'by_role': {}}
        if path.exists():
            with open(path) as f:
                data = json.load(f)

        data['days'][self.today] = {
            'total_cost_usd':     day_summary['total_cost_usd'],
            'total_input_tokens': day_summary['total_input_tokens'],
            'total_output_tokens':day_summary['total_output_tokens'],
        }

        # Recompute monthly totals from all days
        data['total_cost_usd'] = round(
            sum(d['total_cost_usd'] for d in data['days'].values()), 6)

        with open(path, 'w') as f:
            json.dump(data, f, indent=2)

    def print_summary(self, summary: dict, deals_processed: int = 0):
        print("\n=== TOKEN USAGE ===")
        for model, s in summary['by_model'].items():
            label = model.replace('claude-', '').replace('-20250929','').replace('-20251001','')
            print(f"  {label:<35}  "
                  f"{s['input_tokens']:>8,} in  "
                  f"{s['output_tokens']:>7,} out  "
                  f"${s['cost_usd']:.5f}  "
                  f"({s['calls']} calls)")
        print(f"  {'─'*70}")
        print(f"  {'TOTAL':<35}  "
              f"{summary['total_input_tokens']:>8,} in  "
              f"{summary['total_output_tokens']:>7,} out  "
              f"${summary['total_cost_usd']:.5f}")
        if deals_processed > 0:
            cph = round(summary['total_cost_usd'] / deals_processed, 5)
            print(f"  Cost per deal: ${cph}")
        print()
