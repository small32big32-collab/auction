name: STALZONE Auction Collector

on:
  workflow_dispatch:

  schedule:
    - cron: "*/5 * * * *"

jobs:
  collect:
    name: Collect auction prices
    runs-on: ubuntu-latest

    timeout-minutes: 30

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.10"
          cache: "pip"

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt

      - name: Run collector
        env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_KEY: ${{ secrets.SUPABASE_KEY }}

          STALCRAFT_CLIENT_ID: ${{ secrets.STALCRAFT_CLIENT_ID }}
          STALCRAFT_CLIENT_SECRET: ${{ secrets.STALCRAFT_CLIENT_SECRET }}

          STALZONE_DATABASE_PATH: ./stalzone-database/ru/items/artefact

          COLLECT_INTERVAL: "300"
          COLLECT_ONCE: "true"

          REQUEST_DELAY: "0.15"
          REQUEST_TIMEOUT: "30"
          REQUEST_RETRIES: "3"

        run: |
          python collector.py
