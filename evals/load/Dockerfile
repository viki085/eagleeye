# Private k6 image for the load test, built just before the run (never pushed anywhere public).
#   copy tokens.json (scripts/loadtest_seed.py users) and the question pool next to this file first
FROM grafana/k6:0.54.0
WORKDIR /test
COPY chat.js loadtest_questions.json tokens.json ./
ENTRYPOINT ["k6", "run", "--no-color", "chat.js"]
