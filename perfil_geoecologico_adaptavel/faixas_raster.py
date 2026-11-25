"""Convert classified raster samples into distance intervals for the profile."""

# Desenvolvido por João Sipraki
# Copyright (C) 2026 João Sipraki
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import math
import re
from bisect import bisect_right
from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtGui import QColor
from qgis.core import (QgsCoordinateTransform, QgsField, QgsFillSymbol, QgsGeometry,
                       QgsPointXY, QgsProcessingException, QgsRendererCategory)


def parse_classes(text):
    classes = []
    for number, row in enumerate(text.splitlines(), 1):
        if not row.strip():
            continue
        try:
            lo, hi, label, color = [value.strip() for value in row.split(';')]
            lo, hi = float(lo.replace(',', '.')), float(hi.replace(',', '.'))
        except ValueError:
            raise ValueError(f'Classe {number}: use mínimo; máximo; rótulo; #RRGGBB.') from None
        if not math.isfinite(lo) or not math.isfinite(hi) or lo >= hi:
            raise ValueError(f'Classe {number}: informe limites finitos com mínimo menor que máximo.')
        if not label or len(label) > 100 or not re.fullmatch(r'#[a-fA-F0-9]{6}', color):
            raise ValueError(f'Classe {number}: informe um rótulo de até 100 caracteres e uma cor #RRGGBB.')
        classes.append((lo, hi, label, color))
    if not classes:
        raise ValueError('Informe pelo menos uma classe raster.')
    classes.sort(key=lambda interval: interval[0])
    if len({row[2].casefold() for row in classes}) != len(classes):
        raise ValueError('Use rótulos diferentes para as classes.')
    if any(a[1] > b[0] for a, b in zip(classes, classes[1:])):
        raise ValueError('Os intervalos das classes não podem se sobrepor.')
    return classes


def catalog(classes):
    return {label: QgsRendererCategory(label, QgsFillSymbol.createSimple({
        'color': color, 'outline_style': 'no'}), label) for _, _, label, color in classes}


PALETTES = {
    'Viridis': ('#440154', '#31688e', '#35b779', '#fde725'),
    'Spectral': ('#9e0142', '#f46d43', '#ffffbf', '#66c2a5', '#5e4fa2'),
    'RdYlGn': ('#d7191c', '#fdae61', '#ffffbf', '#a6d96a', '#1a9641'),
    'Risco crescente': ('#1a9641', '#a6d96a', '#ffffbf', '#fdae61', '#d7191c'),
    'Azuis': ('#eff3ff', '#9ecae1', '#3182bd', '#08519c'),
}


def parse_auto_style(text):
    if not text.startswith('@auto|'):
        return None
    parts = text.split('|')
    if len(parts) != 4 or parts[1] not in ('equal', 'quantile') or parts[3] not in PALETTES:
        raise ValueError('Configuração automática de raster inválida; reabra a faixa para ajustá-la.')
    try:
        count = int(parts[2])
    except ValueError:
        raise ValueError('Número de classes inválido.') from None
    if not 2 <= count <= 12:
        raise ValueError('Use de 2 a 12 classes raster.')
    return parts[1], count, parts[3]


def _is_nodata(provider, band, value):
    if provider.sourceHasNoDataValue(band) and provider.useSourceNoDataValue(band):
        if value == provider.sourceNoDataValue(band):
            return True
    return any(row.min() <= value <= row.max() for row in provider.userNoDataValues(band))


def _color(palette, index, count):
    stops = [QColor(value) for value in PALETTES[palette]]
    pos = 0 if count <= 1 else index * (len(stops) - 1) / (count - 1)
    left = min(int(pos), len(stops) - 2)
    f = pos - left
    a, b = stops[left], stops[left + 1]
    return QColor(round(a.red() + f * (b.red() - a.red())),
                   round(a.green() + f * (b.green() - a.green())),
                   round(a.blue() + f * (b.blue() - a.blue()))).name()


def _class_label(low, high, constant_value=None):
    """Show the numeric range used by automatically generated raster classes."""
    if constant_value is not None:
        return format(constant_value, '.6g')
    low_text, high_text = format(low, '.4g'), format(high, '.4g')
    if low_text == high_text:
        low_text, high_text = format(low, '.7g'), format(high, '.7g')
    return '{}–{}'.format(low_text, high_text)


def automatic_classes(raster, band, line, crs, context, step, method, count, palette, feedback):
    curve = next(line.getFeatures()).geometry()
    length = curve.length()
    if not math.isfinite(step) or step <= 0:
        raise QgsProcessingException('Passo de amostragem raster inválido; use um valor maior que zero.')
    samples = math.ceil(length / step)
    if samples > 250_000:
        raise QgsProcessingException('Aumente o passo raster para usar até 250.000 amostras.')
    transform = QgsCoordinateTransform(crs, raster.crs(), context.project())
    provider = raster.dataProvider()
    values = []
    for index in range(samples):
        if feedback.isCanceled():
            raise QgsProcessingException('Classificação raster cancelada.')
        start, stop = index * step, min(length, (index + 1) * step)
        point = curve.interpolate((start + stop) / 2).asPoint()
        value, ok = provider.sample(transform.transform(QgsPointXY(point)), band)
        if ok and math.isfinite(value) and not _is_nodata(provider, band, value):
            values.append(float(value))
    if not values:
        raise QgsProcessingException('O raster não tem pixels válidos junto ao perfil para calcular classes.')
    values.sort()
    minimum, maximum = values[0], values[-1]
    if minimum == maximum:
        delta = max(abs(minimum) * 1e-9, 1e-6)
        breaks = [minimum - delta, maximum + delta]
    elif method == 'equal':
        breaks = [minimum + (maximum - minimum) * i / count for i in range(count)] + [maximum]
    else:
        breaks = [minimum] + [values[min(len(values) - 1, math.ceil(i * len(values) / count))]
                               for i in range(1, count)] + [maximum]
    unique = [breaks[0]]
    for value in breaks[1:]:
        if value > unique[-1]:
            unique.append(value)
    if unique[-1] != maximum and minimum != maximum:
        unique[-1] = maximum
    generated = len(unique) - 1
    classes = [(unique[i], unique[i + 1],
                _class_label(unique[i], unique[i + 1], minimum if minimum == maximum else None),
                _color(palette, i, generated)) for i in range(generated)]
    if not classes:
        raise QgsProcessingException('Os valores do raster não permitem separar classes.')
    report = {'metodo': method, 'classes_solicitadas': count,
              'classes_geradas': generated, 'paleta': palette,
              'amostras_validas': len(values), 'valor_minimo': minimum,
              'valor_maximo': maximum}
    return classes, report


def build_intervals(engine, raster, band, classes, step, line, crs, context, feedback, title,
                    interval_utils=None):
    curve = next(line.getFeatures()).geometry()
    length = curve.length()
    height = length * engine.H_RATIO
    if not math.isfinite(step) or step <= 0:
        raise QgsProcessingException(title + ': passo de amostragem raster inválido; use um valor maior que zero.')
    count = math.ceil(length / step)
    if count > 250_000:
        raise QgsProcessingException(title + ': aumente o passo raster para usar até 250.000 amostras.')
    transform = QgsCoordinateTransform(crs, raster.crs(), context.project())
    provider = raster.dataProvider()
    limits = [interval[0] for interval in classes]
    fields = [QgsField('classe', QVariant.String), QgsField('dist_ini', QVariant.Double),
              QgsField('dist_fin', QVariant.Double), QgsField('atributos_json', QVariant.String)]
    output = engine.memory_layer('Polygon', crs, fields, title)
    nodata_m = unclassified_m = 0.0
    nodata_ranges = []
    unclassified_ranges = []
    spans = []
    for index in range(count):
        engine.cancelled(feedback)
        start, stop = index * step, min(length, (index + 1) * step)
        point = curve.interpolate((start + stop) / 2).asPoint()
        value, ok = provider.sample(transform.transform(QgsPointXY(point)), band)
        if not ok or not math.isfinite(value) or _is_nodata(provider, band, value):
            nodata_m += stop - start
            nodata_ranges.append((start, stop))
            continue
        i = bisect_right(limits, value) - 1
        if i < 0 or not (value < classes[i][1] or (i == len(classes) - 1 and value == classes[i][1])):
            unclassified_m += stop - start
            unclassified_ranges.append((start, stop))
            continue
        if spans and spans[-1][2] == i and spans[-1][1] == start:
            spans[-1] = (spans[-1][0], stop, i)
        else:
            spans.append((start, stop, i))
    for start, stop, i in spans:
        lo, hi, label, _ = classes[i]
        ring = [QgsPointXY(start, 0), QgsPointXY(stop, 0), QgsPointXY(stop, height),
                QgsPointXY(start, height), QgsPointXY(start, 0)]
        metadata = json.dumps({'origem': 'raster', 'camada': raster.name(), 'banda': band,
                               'minimo': lo, 'maximo': hi, 'passo_m': step}, ensure_ascii=False)
        engine.add_record(output, QgsGeometry.fromPolygonXY([ring]), [label, start, stop, metadata])
    output.updateExtents()
    if nodata_m or unclassified_m:
        feedback.pushWarning(f'{title}: {nodata_m:.2f} m sem dado raster e {unclassified_m:.2f} m fora das classes.')
    merge = interval_utils.merge_ranges if interval_utils is not None else lambda values: [
        {'inicio_m': round(start, 2), 'fim_m': round(stop, 2)} for start, stop in values]
    return output, {'amostras': count, 'passo_m': step, 'sem_dado_m': nodata_m,
                    'fora_das_classes_m': unclassified_m,
                    'intervalos_sem_dados_m': merge(nodata_ranges),
                    'intervalos_fora_das_classes_m': merge(unclassified_ranges)}
