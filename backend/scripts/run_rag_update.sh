#!/bin/bash

echo "🚀 Starting RAG Update with Best Brands Rebrand..."
echo ""

cd "$(dirname "$0")/.."

echo "📍 Step 1: Deleting old data..."
python3 scripts/cleanup_old_rag_data.py

echo ""
echo "⏰ Waiting 3 seconds..."
sleep 3

echo ""
echo "📍 Step 2: Scraping 11 websites with Best Brands enrichment..."
echo "⏰ This will take 10-15 minutes..."
python3 scripts/batch_ingest_websites.py

echo ""
echo "✅ RAG Update Complete!"
echo "🎯 Maya now speaks about Best Brands!"
