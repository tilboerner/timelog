#!/usr/bin/python3
# coding: utf-8
""" Simple analyzer and aggregator for a simple time log

Reads a text file containing one iso-8601 timestamp per line and normalizes
them to quarter-hours. These quarter-hours are treated as "time spent", which
gets aggregated into stats by day, week, month and weekday, and printed.
"""

import re

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from itertools import groupby, islice
from pprint import pprint
from statistics import mean


def take(n, iterable):
    return islice(iterable, n)


with open('log.txt') as log:
    strdates = [l.strip() for l in log]


dfmt = '%Y-%m-%dT%H:%M:%S%z'
tz_colon_regex = re.compile(
    # YYYY-MM-DDThh:mm:ss[+-]HH:SS match the last colon if surroundings match
    # (It needs to be removed so we can strptime with '%z'.)
    r'(?<=\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[-+]\d{2}):(?=\d{2}\b)'
)


dates = [
    datetime.strptime(tz_colon_regex.sub('', d, 1), dfmt) for d in strdates
]
quarter_hours = sorted(
    set(
        d.replace(minute=(d.minute//15) * 15, second=0)
        for d in dates
    )
)

count_hours = lambda qts: sum(1 for _ in qts) / 4

by_day = lambda dt: dt.date().isoformat() + ' ' + dt.strftime('%a')
by_week = lambda dt: '{0} W{1:02}'.format(*dt.isocalendar())
by_month = lambda dt: '{dt.year}-{dt.month:02}'.format(dt=dt)
by_weekday = lambda dt: dt.strftime('%w %a')

group_to_dict = lambda grp: {key: count_hours(qts) for key, qts in grp}

today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

print('Months')
months = groupby(quarter_hours, by_month)
pprint(group_to_dict(months))

print()
print('Weeks')
weeks = groupby(quarter_hours, by_week)
pprint(group_to_dict(take(8, weeks)))

print()
print('Days')
days_count = today.isoweekday() + 7  # this week and last
days = groupby(quarter_hours, by_day)
pprint(group_to_dict(take(days_count, days)))

print()
print('Days of Week')
weekdays = defaultdict(list)
for weekday, qts in groupby(quarter_hours, by_weekday):
    hours = count_hours(qts)
    weekdays[weekday].append(hours)
pprint({
    weekday: {
        'avg': round(mean(hours), 2),
        'sum': sum(hours),
    } for weekday, hours in weekdays.items()
})

print()
print('Longest session')
best_start = last_start = previous = quarter_hours[0] if quarter_hours else None
best_duration = timedelta(0)
max_gap = timedelta(minutes=30, microseconds=-1)  # just short of 2 quarter hours
for q in quarter_hours:
    if q - previous > max_gap:
        current_duration = previous - last_start
        if current_duration > best_duration:
            best_start = last_start
            best_duration = current_duration
        last_start = q
    previous = q
print(
    best_start and '{} to {} ({})'.format(
        str(best_start), str(best_start + best_duration), str(best_duration)
    )
)
