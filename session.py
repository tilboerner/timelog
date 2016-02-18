#/usr/bin/python3
# coding: utf-8
from datetime import datetime, timedelta, timezone
from itertools import groupby
from pprint import pprint

with open('log.txt') as log:
    strdates = [l.strip() for l in log]

dfmt =  '%Y-%m-%dT%H:%M:%S%z'
dates = [datetime.strptime(d, dfmt) for d in strdates]
quarter_hours = sorted(
    set(
        d.replace(minute=(d.minute//15)* 15, second=0)
        for d in dates
    )
)

count_hours = lambda qts: sum(1 for _ in qts) / 4

by_day = lambda dt: dt.date().isoformat()
by_week = lambda dt: '{0} W{1:02}'.format(*dt.isocalendar())
by_month = lambda dt: '{dt.year}-{dt.month:02}'.format(dt=dt)

group_to_dict = lambda grp: {key: count_hours(qts) for key, qts in grp}

today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

print('Months')
months = groupby(quarter_hours, by_month)
pprint(group_to_dict(months))

print()
print('Weeks')
this_month = today.replace(day=1)
weeks = groupby((q for q in quarter_hours if q >= this_month), by_week)
pprint(group_to_dict(weeks))

print()
print('Days')
days_into_week = today.weekday()  # Mon=0, ..., Sun=6
this_week = today - timedelta(days=days_into_week)
last_week = this_week - timedelta(days=7)
days = groupby((q for q in quarter_hours if q >= last_week), by_day)
pprint(group_to_dict(days))

# qts = sorted(set(d.replace(minute=(d.minute//15)* 15, second=0) for d in dates))
# days = groupby(qts, lambda d: d.date().isoformat())
# list(days)
# {day: sum(q) for day, q in days}
# days = groupby(qts, lambda d: d.date().isoformat())
# {day: sum(q) for day, q in days}
# {day: sum(1 for _ in q)/4 for day, q in days}
