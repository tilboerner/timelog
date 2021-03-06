#!/usr/bin/python3
# coding: utf-8
"""Simple analyzer and aggregator for a simple time log

Reads a text file containing one iso-8601 timestamp per line and normalizes
them to quarter-hours. These quarter-hours are treated as "time spent", which
gets aggregated into stats by day, week, month and weekday, and printed.
"""

import re

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from functools import partial
from itertools import chain, groupby, islice
from operator import attrgetter
from pprint import pformat
from statistics import mean
from typing import Any, Callable, Dict, Iterable, List, Optional, Type  # noqa


def take(n, iterable):
    return islice(iterable, n)


DEFAULT_FILEPATH = 'log.txt'


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
    """Get the period from a fixed-size grid which contains the given time"""
    # The grid is zeroed at midnight, so resolution must fit into a day without leaving a remainder.
    assert not Period.DAY % resolution
    from_midnight = timedelta(hours=dt.hour, minutes=dt.minute, seconds=dt.second,
                              microseconds=dt.microsecond)
    start = dt - (from_midnight % resolution)
    return Period(start, resolution)


class Period:
    """A period of time defined by (start + duration = end)"""

    ZERO = timedelta()
    HOUR = timedelta(seconds=3600)
    DAY = timedelta(days=1)

    by_start = attrgetter('start')
    by_duration = attrgetter('duration')

    __slots__ = ('start', 'duration')

    _DATETIME_ATTRS = {'year', 'month', 'day', 'hour', 'minute', 'second', 'microsecond', 'tzinfo'}
    _TIMEDELTA_ATTRS = {'days', 'seconds', 'microseconds', 'total_seconds'}

    def __new__(cls: Type['Period'],
                start: datetime,
                duration: Optional[timedelta] = None,
                *,
                end: Optional[datetime] = None):
        if duration is not None:
            if duration < Period.ZERO:
                raise ValueError('duration must not be negative')
            if end is None:
                end = start + duration
        if end is not None:
            if end < start:
                raise ValueError('end must be >= start')
            if duration is None:
                duration = end - start
        if duration is None:
            # should have been provided or computed from end at this point
            raise ValueError('Must provide end or duration')
        if start + duration != end:
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
    def merge(cls, periods, *, max_gap=ZERO):
        """
        Merge neighboring periods if the previous end overlaps with the following start.

        The periods will not be sorted before merging. To merge all periods, sort them by
        period.start first.

        Args:
            periods: An iterable of periods to merge
            max_gap: The maximum difference between start and previous end that still allows meging

        Yields:
            Merged period objects in the same order as the input.

        """
        periods = iter(periods)
        try:
            current = next(periods)
        except StopIteration:
            return
        for period in periods:
            if current.start <= period.start:
                first, second = current, period
            else:
                first, second = period, current
            if first.end + max_gap >= second.start:
                current = first.replace(end=max(first.end, second.end))
            else:
                yield current
                current = period
        yield current

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
            isinstance(other, Period) and
            (self.start, self.duration) == (other.start, other.duration))

    def __hash__(self):
        return hash((self.start, self.duration))

    @property
    def end(self) -> datetime:
        return self.start + self.duration

    def replace(self, *, start: datetime = None, duration: timedelta = None, end: datetime = None):
        start = start or self.start
        if duration is None and end is None:
            duration = self.duration
        return type(self)(start, duration, end=end)

    def astimezone(self, tzinfo):
        return self.replace(start=self.start.astimezone(tzinfo))


def count_hours(periods):
    return sum(x.duration / Period.HOUR for x in periods)


def today(tz=timezone.utc):
    return datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)


def title(string):
    words = re.findall('[A-Z][^A-Z_]*', string)
    groups = groupby(words, key=str.isupper)
    words = chain.from_iterable(
        (''.join(grp),) if is_upper else map(str.lower, grp)
        for is_upper, grp in groups
    )
    return ' '.join(words).capitalize()


class Stat:

    key = lambda period: period  # type: Callable[[Period], Any] # noqa: 731
    fmt_key = str  # type: Callable[[Any], str]
    limit = None  # type: Optional[int]
    group_by = groupby
    aggregate = count_hours  # type: Callable[[Iterable[Period]], Any]

    @classmethod
    def make(cls, periods):
        limit = cls.limit
        grouped = cls.group_by(periods, key=cls.key)
        if limit:
            grouped = take(limit, grouped)
        fmt_key = cls.fmt_key
        aggregate = cls.aggregate
        return {fmt_key(key): aggregate(group) for key, group in grouped}

    def __init__(self, periods):
        self.stats = self.make(periods)

    def __str__(self):
        name = title(type(self).__name__)
        stats = self.stats
        if isinstance(stats, (list, dict)):
            stats = pformat(self.stats)
        return '{name}:\n{stats}\n'.format(**locals())


class Months(Stat):
    key = lambda period: (period.year, period.month)  # noqa: 731
    fmt_key = lambda key: '{}-{:02}'.format(*key)  # noqa: 731


class Weeks(Stat):
    key = lambda period: period.start.isocalendar()[:2]  # noqa: 731
    fmt_key = lambda key: '{}-W{:02}'.format(*key)  # noqa: 731
    limit = 8


class Days(Stat):
    key = lambda x: x.start.date().isoformat() + ' ' + x.start.strftime('%a')  # noqa: 731
    limit = today().isoweekday() + 7  # current week and last


class DaysOfWeek(Stat):
    key = lambda period: period.start.strftime('%w %a')  # noqa: 731

    @classmethod
    def make(cls, periods):
        key = cls.key
        weekdays = defaultdict(list)
        for weekday, grp in groupby(periods, key=key):
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
    def make(cls, periods):
        merged = Period.merge(periods, max_gap=cls.max_gap)
        return max(merged, key=Period.by_duration, default=None)


if __name__ == '__main__':
    import sys
    filepath = sys.argv[1] if (len(sys.argv) > 1) else DEFAULT_FILEPATH
    dates = parse_many(read_lines(filepath))
    quarter_hours = sorted(
        set(map(quantize, dates)),
        key=Period.by_start
    )
    for stat in (Months, Weeks, Days, DaysOfWeek, LongestSession):
        print(stat(quarter_hours))
