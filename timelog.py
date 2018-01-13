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
from pprint import pformat
from statistics import mean
from typing import Any, Callable, Dict, Iterable, List, Optional, Type, TypeVar  # noqa


def take(n, iterable):
    return islice(iterable, n)


FILENAME = 'log.txt'


def read_lines(file, *, encoding='UTF-8'):
    if isinstance(file, (str, bytes)):
        get_file = partial(open, file, encoding=encoding)
    else:
        get_file = lambda: file  # noqa: E731
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


SpanT = TypeVar('SpanT', bound='span')


class span:
    """A span of time defined by (start + duration = end)"""

    ZERO = timedelta()
    HOUR = timedelta(seconds=3600)

    by_start = attrgetter('start')
    by_duration = attrgetter('duration')

    __slots__ = ('start', 'duration')

    _DATETIME_ATTRS = {'year', 'month', 'day', 'hour', 'minute', 'second', 'microsecond', 'tzinfo'}
    _TIMEDELTA_ATTRS = {'days', 'seconds', 'microseconds', 'total_seconds'}

    def __new__(cls: Type[SpanT], start: datetime, duration: timedelta=None, *, end: datetime=None):
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
            isinstance(other, span) and
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


def count_hours(spans):
    return sum(x.duration / span.HOUR for x in spans)


def today(tz=timezone.utc):
    return datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)


class Stat:

    key = lambda span: span  # type: Callable[[span], Any] # noqa: 731
    fmt_key = str  # type: Callable[[Any], str]
    limit = None  # type: Optional[int]
    group_by = groupby
    aggregate = count_hours  # type: Callable[[Iterable[span]], Any]

    @classmethod
    def make(cls, spans):
        limit = cls.limit
        grouped = cls.group_by(spans, key=cls.key)
        if limit:
            grouped = take(limit, grouped)
        fmt_key = cls.fmt_key
        aggregate = cls.aggregate
        return {fmt_key(key): aggregate(group) for key, group in grouped}

    def __init__(self, spans):
        self.stats = self.make(spans)

    def __str__(self):
        name = type(self).__name__
        stats = self.stats
        if isinstance(stats, (list, dict)):
            stats = pformat(self.stats)
        return '{name}:\n{stats}\n'.format(**locals())


class Months(Stat):
    key = lambda span: (span.year, span.month)  # noqa: 731
    fmt_key = lambda key: '{}-{:02}'.format(*key)  # noqa: 731


class Weeks(Stat):
    key = lambda span: span.start.isocalendar()[:2]  # noqa: 731
    fmt_key = lambda key: '{}-W{:02}'.format(*key)  # noqa: 731
    limit = 8


class Days(Stat):
    key = lambda x: x.start.date().isoformat() + ' ' + x.start.strftime('%a')  # noqa: 731
    limit = today().isoweekday() + 7  # current week and last


class Weekday(Stat):
    key = lambda span: span.start.strftime('%w %a')  # noqa: 731

    @classmethod
    def make(cls, spans):
        key = cls.key
        weekdays = defaultdict(list)
        for weekday, grp in groupby(spans, key=key):
            hours = count_hours(grp)
            weekdays[weekday].append(hours)
        return {
            weekday: {
                'avg': round(mean(hours), 2),
                'sum': sum(hours),
            } for weekday, hours in weekdays.items()
        }


class LongestSession(Stat):
    max_gap = timedelta(minutes=30, microseconds=-1)  # just < 2 quarter hours

    @classmethod
    def make(cls, spans):
        combined = span.combine(spans, max_gap=cls.max_gap)
        if combined:
            return sorted(combined, key=span.by_duration)[-1]


if __name__ == '__main__':
    dates = parse_many(read_lines(FILENAME))
    quarter_hours = sorted(
        set(map(quantize, dates)),
        key=span.by_start
    )
    for stat in (Months, Weeks, Days, Weekday, LongestSession):
        print(stat(quarter_hours))

# noqa: E731
