#!/bin/sh
# Trusted runner in the judge container: runs the mounted tests (whose `solution` import is the
# stub in /runner/judge), then prints sentinel-delimited results on stdout, so no writable host
# mount is needed. The report and log carry strings from the candidate, so they stay untrusted.
cd /tmp || exit 1
python -m pytest /work/tests -q -p no:cacheprovider \
  --timeout="${PER_TEST_TIMEOUT:-5}" \
  --junitxml=/tmp/report.xml >/tmp/pytest.log 2>&1
echo "@@PL_EXIT $?"
echo "@@PL_REPORT"
# Capped so a huge report can't push the sentinels out of Docker's 1 MB log.
head -c 200000 /tmp/report.xml 2>/dev/null
# pytest's XML has no trailing newline; keep the next sentinel on its own line.
echo
echo "@@PL_LOG"
head -c 20000 /tmp/pytest.log
