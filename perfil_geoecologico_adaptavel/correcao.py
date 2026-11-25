# -*- coding: utf-8 -*-
"""Correções geométricas assistidas e sem sobrescrever as fontes."""

# Desenvolvido por João Sipraki
# Copyright (C) 2026 João Sipraki
# SPDX-License-Identifier: GPL-3.0-or-later



def invalid_geometry_report(layer):
    """Conta geometrias vazias ou inválidas e devolve alguns IDs para revisão."""
    from qgis.core import QgsFeatureRequest, QgsVectorLayer

    if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
        raise ValueError('A entrada não é uma camada vetorial válida.')
    invalid_ids = []
    checked = 0
    for feature in layer.getFeatures(QgsFeatureRequest().setSubsetOfAttributes([])):
        checked += 1
        geometry = feature.geometry()
        try:
            valid = not geometry.isNull() and not geometry.isEmpty() and geometry.isGeosValid()
        except Exception:
            valid = False
        if not valid:
            invalid_ids.append(feature.id())
    return {'feicoes_verificadas': checked, 'geometrias_invalidas': len(invalid_ids),
            'ids_exemplo': invalid_ids[:10]}


def repaired_geometry_copy(layer):
    """Executa Fix Geometries numa camada temporária e preserva a simbologia."""
    import processing
    from qgis.core import QgsVectorLayer

    result = processing.run('native:fixgeometries', {
        'INPUT': layer, 'METHOD': 1, 'OUTPUT': 'memory:'})
    corrected = result.get('OUTPUT')
    if not isinstance(corrected, QgsVectorLayer) or not corrected.isValid():
        raise RuntimeError('O QGIS não retornou uma camada temporária válida.')
    corrected.setName('Geometria corrigida temporariamente — ' + layer.name())
    renderer = layer.renderer()
    if renderer is not None:
        corrected.setRenderer(renderer.clone())
    corrected.setCustomProperty('geo/temporary_geometry_repair', True)
    corrected.setCustomProperty('geo/repair_source_layer_id', layer.id())
    return corrected


def replace_theme_sources(rows, replacements):
    """Atualiza apenas o ID da camada, preservando título, campo e QML."""
    updated = []
    for row in rows:
        values = list(row)
        if len(values) >= 2 and values[1] in replacements:
            values[1] = replacements[values[1]]
        updated.append(values)
    return updated
