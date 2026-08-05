# client.yaml Template

Controls runtime behaviour. Read by etl_deals.py and run_nightly.py.
Stage IDs come from discover_stages.py output.

```yaml
client:
  name: "{{company.name}}"
  methodology: "{{methodology}}"
  crm: hubspot
  call_tools:
    primary: fireflies
    secondary: apollo

pipeline:
  excluded_pipelines:
    - "{{renewal pipeline name}}"
  excluded_stages:
    - "appointmentscheduled"
    - "{{custom meeting set ID}}"
    - "closedwon"
    - "closedlost"
    - "{{custom closed won ID}}"
    - "{{custom closed lost ID}}"
  closed_won_stages:
    - "closedwon"
    - "{{custom closed won ID}}"
  closed_lost_stages:
    - "closedlost"
    - "{{custom closed lost ID}}"

analysis:
  max_iterations: 3
  min_summary_chars: 100
  max_runtime_minutes: 90
  min_evidence_companies: 2

hubspot:
  properties:
    score: meddicc_score
    status: meddicc_status
    last_analyzed: meddicc_last_analyzed
    champion_score: meddicc_champion_score
    economic_buyer_score: meddicc_economic_buyer_score
    summary: meddicc_analysis_summary
```
