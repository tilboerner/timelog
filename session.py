#!/usr/bin/python3
# coding: utf-8
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from itertools import groupby
from pprint import pprint
from statistics import mean

with open('log.txt') as log:
    strdates = [l.strip() for l in log]

dfmt = '%Y-%m-%dT%H:%M:%S%z'
dates = [datetime.strptime(d, dfmt) for d in strdates]
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
week_start = today - timedelta(days=today.weekday())  # Monday=0, Sunday=6

print('Months')
months = groupby(quarter_hours, by_month)
pprint(group_to_dict(months))

print()
print('Weeks')
six_weeks_ago = week_start - timedelta(days=7*6)
weeks = groupby((q for q in quarter_hours if q >= six_weeks_ago), by_week)
pprint(group_to_dict(weeks))

print()
print('Days')
last_week = week_start - timedelta(days=7)
days = groupby((q for q in quarter_hours if q >= last_week), by_day)
pprint(group_to_dict(days))

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
