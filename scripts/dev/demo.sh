#!/usr/bin/env bash
# ROADMAP 6.6: walks through every milestone's headline capability against a
# running `docker compose up` stack. Milestones 3-5's agent endpoints need
# OPENAI_API_KEY or ANTHROPIC_API_KEY set in .env before `docker compose up`
# -- those steps are skipped (not failed) if AGENT_OPS_HAS_LLM=0 is passed.
set -e

GATEWAY=http://localhost:8080
SCHEDULER=http://localhost:8002
AGENT_OPS=http://localhost:8004
HAS_LLM="${AGENT_OPS_HAS_LLM:-1}"

section() { echo; echo "=== $1 ==="; }

section "Milestone 1: Rate Limiter + Gateway"
echo "-> GET /api/ping through the Gateway (rate-limit checked):"
curl -s -i "$GATEWAY/api/ping" -H "X-Client-Id: demo" | head -1

section "Milestone 2: Scheduler + Worker Pool"
echo "-> Submitting a 2-job DAG (b depends on a):"
RESPONSE=$(curl -s -X POST "$SCHEDULER/v1/jobs" \
  -H "Content-Type: application/json" \
  -d '{"jobs":[{"ref":"a","name":"extract","priority":5},{"ref":"b","name":"load","priority":1,"depends_on":["a"]}]}')
echo "$RESPONSE"
JOB_A=$(echo "$RESPONSE" | grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4)
echo "-> Job a's id: $JOB_A -- poll GET $SCHEDULER/v1/jobs/$JOB_A to watch it move through the state machine"
echo "-> Queue depth (Milestone 5's Monitor Agent uses this too):"
curl -s "$SCHEDULER/v1/jobs/stats"
echo

if [ "$HAS_LLM" = "1" ]; then
  section "Milestone 3: RAG debugging"
  curl -s -X POST "$AGENT_OPS/v1/debug/ask" \
    -H "Content-Type: application/json" \
    -d '{"question": "the dead letter queue is growing fast, what should I check?"}'
  echo

  section "Milestone 4: Tool-calling (non-destructive)"
  curl -s -X POST "$AGENT_OPS/v1/agent/schedule" \
    -H "Content-Type: application/json" \
    -d '{"question": "create a job called demo-job with priority 2"}'
  echo

  section "Milestone 5: Unified entry point + Monitor Agent"
  curl -s -X POST "$AGENT_OPS/v1/agent/ask" \
    -H "Content-Type: application/json" \
    -d '{"question": "how'"'"'s the queue looking right now?"}'
  echo
else
  section "Milestones 3-5 skipped (AGENT_OPS_HAS_LLM=0 -- no OPENAI_API_KEY/ANTHROPIC_API_KEY)"
fi

section "Milestone 5: Monitor Agent, no LLM needed"
curl -s "$AGENT_OPS/v1/monitor/status"
echo

section "Milestone 6: per-node trace on the last debug/ask call"
echo "(see the \"trace\" field in the Milestone 3 response above -- latency_ms and usage per node)"
