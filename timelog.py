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
from functools import partial
from itertools import groupby, islice
from operator import attrgetter
from pprint import pprint
from statistics import mean
from typing import Dict, List, Type, TypeVar  # noqa


def take(n, iterable):
    return islice(iterable, n)


FILENAME = 'log.txt'


def read_lines(file, *, encoding='UTF-8'):
    if isinstance(file, (str, bytes)):
        get_file = partial(open, file, encoding=encoding)
    else:
        get_file = lambda: file
    with get_file() as file:
        yield from map(str.strip, file)


_tz_colon_regex = re.compile(
    # YYYY-MM-DDThh:mm:ss[+-]HH:SS match the last colon if surroundings match
    # (It needs to be removed so we can strptime with '%z'.)
    r'(?<=\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[-+]\d{2}):(?=\d{2}\b)'
)
_fix_datestr = partial(_tz_colon_regex.sub, '', count=1)


def parse_many(strings, *, fmt='%Y-%m-%dT%H:%M:%S%z', pre=_fix_datestr):
    parse = datetime.strptime
    if pre:
        strings = map(pre, strings)
    for s in strings:
        yield parse(s, fmt)


def quantize(dt, *, resolution=timedelta(minutes=15)):
    assert resolution < timedelta(days=1)
    # zero == midnight(dt)
    from_zero = timedelta(hours=dt.hour, minutes=dt.minute, seconds=dt.second,
                          microseconds=dt.microsecond)
    start = dt - (from_zero % resolution)
    return span(start, resolution)


SpanType = TypeVar('SpanType', bound='span')


class span:
    """A span of time defined by (start + duration = end)"""

    ZERO = timedelta()
    HOUR = timedelta(seconds=3600)

    by_start = attrgetter('start')
    by_duration = attrgetter('duration')

    __slots__ = ('start', 'duration')

    _DATETIME_ATTRS = {'year', 'month', 'day', 'hour', 'minute', 'second', 'microsecond', 'tzinfo'}
    _TIMEDELTA_ATTRS = {'days', 'seconds', 'microseconds', 'total_seconds'}

    def __new__(cls: Type[SpanType], start: datetime, duration: timedelta=None, *, end: datetime=None):
        if end is None and duration is None:
            raise ValueError('Must provide end or duration')
        if duration and duration < span.ZERO:
            raise ValueError('duration must not be negative')
        if end and end < start:
            raise ValueError('end must be >= start')
        if end is None:
            end = start + duration
        elif duration is None:
            duration = end - start
        elif start + duration != end:
            raise ValueError('duration must match end - start')
        obj = super().__new__(cls)
        cls._init(obj, start=start, duration=duration)
        return obj

    @classmethod
    def _init(cls, obj, **attrs):
        for name, value in attrs.items():
            # use slots descriptors to circumvent our disabled __setattr__
            getattr(cls, name).__set__(obj, value)

    @classmethod
    def combine(cls, spans, *, max_gap=ZERO):
        combined = []
        combining = None
        for nxt in sorted(spans, key=attrgetter('start')):
            if combining is None:
                combining = nxt
                continue
            current_end = combining.end
            if current_end + max_gap >= nxt.start:
                new_end = max(current_end, nxt.end)
                combining = combining.replace(end=new_end)
            else:
                combined.append(combining)
                combining = None
        if combining is not None:
            combined.append(combining)
        return combined

    def __getattr__(self, name):
        if name in self._DATETIME_ATTRS:
            return getattr(self.start, name)
        if name in self._TIMEDELTA_ATTRS:
            return getattr(self.duration, name)
        return object.__getattribute__(self, name)

    def __setattr__(self, name, value):
        raise AttributeError(f'Cannot change {type(self).__name__} attributes')

    def __repr__(self):
        return f'{type(self).__name__}({self.start!r}, {self.duration!r})'

    def __str__(self):
        return f'[{self.start!s}] to [{self.end!s}] ({self.duration!s})'

    def __eq__(self, other):
        return (
            isinstance(other, span)
            and
            (self.start, self.duration) == (other.start, other.duration))

    def __hash__(self):
        return hash((self.start, self.duration))

    @property
    def end(self) -> datetime:
        return self.start + self.duration

    @property
    def resolution(self) -> timedelta:
        one = self.start.resolution
        two = self.duration.resolution
        return one if one >= two else two

    def replace(self, *, start: datetime=None, duration: timedelta=None, end: datetime=None):
        if start is None:
            start = self.start
        if duration is None and end is None:
            duration = self.duration
        return type(self)(start, duration, end=end)

    def astimezone(self, tzinfo):
        return self.replace(start=self.start.astimezone(tzinfo))

dates = parse_many(read_lines(FILENAME))
quarter_hours = sorted(set(map(quantize, dates)), key=span.by_start)

count_hours = lambda spans: sum(x.duration / span.HOUR for x in spans)

by_day = lambda dt: dt.start.date().isoformat() + ' ' + dt.start.strftime('%a')
by_week = lambda dt: '{0} W{1:02}'.format(*dt.start.isocalendar())
by_month = lambda dt: '{dt.year}-{dt.month:02}'.format(dt=dt.start)
by_weekday = lambda dt: dt.start.strftime('%w %a')

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
weekdays = defaultdict(list)  # type: Dict[int, List[float]]
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
max_gap = timedelta(minutes=30, microseconds=-1)  # just short of 2 quarter hours
combined = span.combine(quarter_hours, max_gap=max_gap)
best = sorted(combined, key=span.by_duration)[-1] if combined else None
print(best)
