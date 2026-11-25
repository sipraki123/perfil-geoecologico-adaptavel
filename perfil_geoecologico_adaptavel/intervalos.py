"""Operações simples sobre trechos medidos ao longo do eixo A–B."""

# Desenvolvido por João Sipraki
# Copyright (C) 2026 João Sipraki
# SPDX-License-Identifier: GPL-3.0-or-later

import math
import unicodedata


def merge_ranges(ranges, length=None, precision=2):
    normalized = []
    for item in ranges or []:
        if isinstance(item, dict):
            start, stop = item.get('inicio_m'), item.get('fim_m')
        else:
            start, stop = item[:2]
        try:
            start, stop = float(start), float(stop)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(start) or not math.isfinite(stop):
            continue
        if length is not None:
            start, stop = max(0.0, start), min(float(length), stop)
        if stop > start:
            normalized.append((start, stop))
    normalized.sort()
    merged = []
    for start, stop in normalized:
        if merged and start <= merged[-1][1] + 1e-8:
            merged[-1] = (merged[-1][0], max(merged[-1][1], stop))
        else:
            merged.append((start, stop))
    return [{'inicio_m': round(start, precision), 'fim_m': round(stop, precision)}
            for start, stop in merged]


def overlapping_class_ranges(intervals, length=None, precision=2):
    """Trechos em que duas ou mais classes distintas ocupam o mesmo eixo A–B."""
    events = []
    for item in intervals or []:
        if isinstance(item, dict):
            start, stop, category = item.get('inicio_m'), item.get('fim_m'), item.get('classe')
        else:
            try:
                start, stop, category = item[:3]
            except (TypeError, ValueError):
                continue
        try:
            start, stop = float(start), float(stop)
        except (TypeError, ValueError):
            continue
        category = str(category or '').strip()
        if not category or not math.isfinite(start) or not math.isfinite(stop):
            continue
        if length is not None:
            start, stop = max(0.0, start), min(float(length), stop)
        if stop <= start:
            continue
        events.append((start, 1, category))
        events.append((stop, -1, category))
    events.sort(key=lambda event: (event[0], event[1]))  # encerrar antes de iniciar no mesmo limite
    active = {}
    ranges = []
    previous = None
    for distance, action, category in events:
        classes = {name for name, count in active.items() if count > 0}
        if previous is not None and distance > previous and len(classes) > 1:
            key = lambda name: unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode('ascii').casefold()
            label = ' / '.join(sorted(classes, key=key))
            if ranges and ranges[-1][1] == previous and ranges[-1][2] == label:
                ranges[-1] = (ranges[-1][0], distance, label)
            else:
                ranges.append((previous, distance, label))
        active[category] = active.get(category, 0) + action
        if active[category] <= 0:
            active.pop(category, None)
        previous = distance
    return [{'inicio_m': round(start, precision), 'fim_m': round(stop, precision), 'classes': classes}
            for start, stop, classes in ranges]


def uncovered_ranges(intervals, length, precision=2):
    """Complemento dos intervalos cobertos no eixo, em metros desde A."""
    length = max(0.0, float(length))
    covered = merge_ranges(intervals, length, precision=12)
    gaps = []
    cursor = 0.0
    for item in covered:
        start, stop = item['inicio_m'], item['fim_m']
        if start > cursor + 1e-8:
            gaps.append((cursor, start))
        cursor = max(cursor, stop)
    if cursor < length - 1e-8:
        gaps.append((cursor, length))
    return merge_ranges(gaps, length, precision)


def sampled_failure_ranges(failed_indices, length, count, precision=2):
    """Estima trechos NoData a partir de amostras equidistantes, incluindo meia célula nos extremos."""
    length, count = max(0.0, float(length)), int(count)
    if count < 2 or length <= 0:
        return []
    indices = sorted({int(i) for i in failed_indices if 0 <= int(i) < count})
    if not indices:
        return []
    spacing = length / (count - 1)
    groups = []
    start = previous = indices[0]
    for index in indices[1:]:
        if index != previous + 1:
            groups.append((start, previous))
            start = index
        previous = index
    groups.append((start, previous))
    ranges = [(max(0.0, (start - 0.5) * spacing),
               min(length, (stop + 0.5) * spacing)) for start, stop in groups]
    return merge_ranges(ranges, length, precision)


def sample_missing_ranges(samples, length, precision=2):
    """Estima trechos ausentes a partir de (distância, sem_dado) amostrados no perfil."""
    ordered = []
    for distance, missing in samples:
        try:
            distance = float(distance)
        except (TypeError, ValueError):
            continue
        if math.isfinite(distance):
            ordered.append((distance, bool(missing)))
    ordered.sort()
    ranges = []
    for index, (distance, missing) in enumerate(ordered):
        if not missing:
            continue
        start = 0.0 if index == 0 else (ordered[index - 1][0] + distance) / 2
        stop = float(length) if index == len(ordered) - 1 else (distance + ordered[index + 1][0]) / 2
        ranges.append((start, stop))
    return merge_ranges(ranges, length, precision)


def format_ranges(ranges, approximate=False, max_ranges=4):
    """Texto compacto para mostrar distâncias desde A em relatórios."""
    ranges = list(ranges or [])
    if not ranges:
        return ''

    def number(value):
        text = '{:,.2f}'.format(float(value))
        return text.replace(',', '\0').replace('.', ',').replace('\0', '.')

    parts = []
    for item in ranges[:max_ranges]:
        start, stop = float(item['inicio_m']), float(item['fim_m'])
        prefix = '≈ ' if approximate else ''
        if max(start, stop) >= 1000:
            parts.append('{}{}–{} km desde A'.format(
                prefix, number(start / 1000), number(stop / 1000)))
        else:
            parts.append('{}{}–{} m desde A'.format(prefix, number(start), number(stop)))
    if len(ranges) > max_ranges:
        parts.append('+{} trechos'.format(len(ranges) - max_ranges))
    return '; '.join(parts)
