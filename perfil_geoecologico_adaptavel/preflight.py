# -*- coding: utf-8 -*-
"""Pré-verificação das entradas do perfil, sem criar ou alterar dados."""

# Desenvolvido por João Sipraki
# Copyright (C) 2026 João Sipraki
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import math

from qgis.core import (
    Qgis, QgsProcessingAlgorithm, QgsProcessingParameterVectorLayer,
    QgsProcessingParameterRasterLayer, QgsProcessingParameterMatrix,
    QgsProcessingParameterNumber, QgsProcessingOutputString,
    QgsProcessingParameterEnum, QgsProcessingParameterCrs, QgsCoordinateReferenceSystem,
    QgsProcessingUtils, QgsVectorLayer, QgsRasterLayer, QgsWkbTypes,
    QgsGeometry, QgsFeatureRequest, QgsCoordinateTransform, QgsPointXY,
    QgsRaster, QgsProject, QgsProcessing, QgsProcessingException,
)

from .configuracao_personalizada import parse_themes
from .intervalos import sampled_failure_ranges, uncovered_ranges
from .unidades_vertical import UNIT_CHOICES, resolve_vertical_conversion


MAX_SAMPLES = 1000


def _line_geometry(layer, feedback):
    """Retorna a geometria da linha se houver exatamente uma linha aberta válida."""
    if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
        raise QgsProcessingException('Selecione uma camada de linha válida para A–B.')
    if QgsWkbTypes.geometryType(layer.wkbType()) != QgsWkbTypes.LineGeometry:
        raise QgsProcessingException('A camada A–B precisa ser do tipo linha.')
    if layer.featureCount() != 1:
        raise QgsProcessingException('A camada A–B precisa conter exatamente uma feição.')
    feature = next(layer.getFeatures())
    geom = feature.geometry()
    if geom.isNull() or geom.isEmpty() or not geom.isGeosValid():
        raise QgsProcessingException('A feição A–B está vazia ou tem geometria inválida.')
    parts = geom.asMultiPolyline() if geom.isMultipart() else [geom.asPolyline()]
    if len(parts) != 1 or len(parts[0]) < 2:
        raise QgsProcessingException('A–B precisa ser uma única linha contínua, sem partes separadas.')
    if parts[0][0] == parts[0][-1]:
        raise QgsProcessingException('A linha A–B está fechada; informe um transecto aberto.')
    length = geom.length()
    if not math.isfinite(length) or length <= 0:
        raise QgsProcessingException('A linha A–B não tem comprimento positivo.')
    return geom, length


def _sample_points(line, count):
    return [line.interpolate(line.length() * i / max(1, count - 1)).asPoint()
            for i in range(count)]


def _transform_geometry(geometry, source_crs, target_crs, project):
    cloned = QgsGeometry(geometry)
    cloned.transform(QgsCoordinateTransform(source_crs, target_crs, project))
    return cloned


def _line_intervals(geometry, line):
    """Converte cada parte linear da interseção em seu intervalo no eixo."""
    if geometry.isNull() or geometry.isEmpty():
        return []
    if QgsWkbTypes.geometryType(geometry.wkbType()) != QgsWkbTypes.LineGeometry:
        return []
    parts = geometry.asMultiPolyline() if geometry.isMultipart() else [geometry.asPolyline()]
    intervals = []
    for part in parts:
        if len(part) < 2:
            continue
        distances = [line.lineLocatePoint(QgsGeometry.fromPointXY(QgsPointXY(point)))
                     for point in part]
        distances = [distance for distance in distances if math.isfinite(distance) and distance >= 0]
        if len(distances) < 2:
            continue
        start, end = min(distances), max(distances)
        if end > start:
            intervals.append((start, end))
    return intervals


def _interval_coverage(intervals, length):
    """Retorna comprimento coberto, lacunas e sobreposição por classes."""
    clipped = [(max(0.0, a), min(length, b)) for a, b in intervals]
    clipped = [(a, b) for a, b in clipped if b > a]
    ordered = sorted(clipped)
    covered = 0.0
    overlap = 0.0
    end = 0.0
    for start, stop in ordered:
        if stop <= end:
            overlap += stop - start
        elif start < end:
            overlap += end - start
            covered += stop - end
            end = stop
        else:
            covered += stop - start
            end = stop
    return covered, max(0.0, length - covered), overlap


def _raster_check(layer, band, line, line_crs, project, sample_step, feedback, title):
    if not isinstance(layer, QgsRasterLayer) or not layer.isValid():
        raise QgsProcessingException(title + ': raster indisponível ou inválido.')
    if not layer.crs().isValid():
        raise QgsProcessingException(title + ': raster sem SRC válido.')
    if not 1 <= band <= layer.bandCount():
        raise QgsProcessingException(title + ': a banda selecionada não existe.')
    transformed = _transform_geometry(line, line_crs, layer.crs(), project)
    step = max(float(sample_step), 0.1)
    count = min(MAX_SAMPLES, max(2, int(math.ceil(line.length() / step)) + 1))
    points = _sample_points(transformed, count)
    provider = layer.dataProvider()
    valid = []
    failed_indices = []
    for index, point in enumerate(points):
        result = provider.identify(QgsPointXY(point), QgsRaster.IdentifyFormatValue)
        values = result.results() if result.isValid() else {}
        value = values.get(band)
        if value is None:
            failed_indices.append(index)
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            failed_indices.append(index)
            continue
        is_nodata = (provider.sourceHasNoDataValue(band) and provider.useSourceNoDataValue(band)
                     and provider.sourceNoDataValue(band) == number)
        if not is_nodata:
            is_nodata = any(value_range.min() <= number <= value_range.max()
                            for value_range in provider.userNoDataValues(band))
        if not math.isfinite(number) or is_nodata:
            failed_indices.append(index)
            continue
        valid.append(number)
    failed = len(failed_indices)
    percent = 100.0 * len(valid) / count if count else 0.0
    resolution = (layer.rasterUnitsPerPixelX(), layer.rasterUnitsPerPixelY())
    feedback.pushInfo('{}: cobertura amostrada {:.1f}% ({}/{}); resolução {:.3g} × {:.3g} unidades do SRC.'.format(
        title, percent, len(valid), count, resolution[0], resolution[1]))
    if not valid:
        feedback.pushWarning(title + ': nenhum valor válido foi encontrado ao longo de A–B.')
        status = 'bloqueio'
    elif percent < 100:
        feedback.pushWarning(title + ': há pixels NoData ou trechos fora da cobertura do raster.')
        status = 'aviso'
    else:
        status = 'ok'
    if layer.crs().isGeographic():
        feedback.pushWarning(title + ': SRC geográfico; confirme a unidade da resolução e da amostragem.')
        if status == 'ok':
            status = 'aviso'
    return {'status': status, 'cobertura_pct': round(percent, 1), 'amostras_validas': len(valid),
            'amostras_sem_dados': failed,
            'intervalos_sem_dados_m': sampled_failure_ranges(failed_indices, line.length(), count),
            'amostras': count, 'min': min(valid) if valid else None,
            'max': max(valid) if valid else None, 'crs': layer.crs().authid(),
            'valores_distintos_amostrados': len(set(valid)),
            'resolucao': [resolution[0], resolution[1]], 'band': band}


def _vector_check(layer, field, line, line_crs, project, feedback, title):
    if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
        raise QgsProcessingException(title + ': camada vetorial indisponível ou inválida.')
    if layer.isEditable():
        feedback.pushWarning(title + ': a camada está em edição; salve ou encerre a edição antes de gerar.')
    geometry_type = QgsWkbTypes.geometryType(layer.wkbType())
    if geometry_type not in (QgsWkbTypes.PointGeometry, QgsWkbTypes.LineGeometry, QgsWkbTypes.PolygonGeometry):
        raise QgsProcessingException(title + ': tipo de geometria não suportado.')
    if field not in layer.fields().names():
        raise QgsProcessingException(title + ': o campo “{}” não existe.'.format(field))
    total = layer.featureCount()
    feedback.pushInfo('{}: verificando geometrias em toda a camada{}.'.format(
        title, ' ({} feições)'.format(total) if total >= 0 else ''))
    invalid_ids = []
    scanned = 0
    geometry_request = QgsFeatureRequest().setSubsetOfAttributes([])
    for feature in layer.getFeatures(geometry_request):
        scanned += 1
        geom = feature.geometry()
        try:
            valid = not geom.isNull() and not geom.isEmpty() and geom.isGeosValid()
        except Exception:
            valid = False
        if not valid:
            invalid_ids.append(feature.id())
    if invalid_ids:
        sample_ids = ', '.join(map(str, invalid_ids[:10]))
        suffix = ' …' if len(invalid_ids) > 10 else ''
        feedback.pushWarning('{}: {} geometria(s) inválida(s) em {} feição(ões) verificadas (IDs: {}{}). A geração atual não consegue recuperar algumas destas geometrias.'.format(
            title, len(invalid_ids), scanned, sample_ids, suffix))
    # Use the same metric work CRS as the generator. Transforming the line into
    # each source CRS changes its measured length and makes reported distances
    # disagree with the generated GeoPackage.
    tolerance = 5.0 if geometry_type != QgsWkbTypes.PolygonGeometry else 0.0
    search_analysis = line.buffer(tolerance, 4) if tolerance else line
    search = _transform_geometry(search_analysis, line_crs, layer.crs(), project)
    request = QgsFeatureRequest().setFilterRect(search.boundingBox())
    hits = []
    invalid_nearby = 0
    null_classes = 0
    encountered = set()
    for feature in layer.getFeatures(request):
        geom = feature.geometry()
        if geom.isNull() or geom.isEmpty() or not geom.isGeosValid():
            invalid_nearby += 1
            continue
        geom_analysis = _transform_geometry(geom, layer.crs(), line_crs, project)
        if geometry_type == QgsWkbTypes.PolygonGeometry:
            if geom_analysis.intersects(line):
                intersection = geom_analysis.intersection(line)
                if not intersection.isEmpty() and intersection.length() > 0:
                    hits.append(intersection)
                    value = feature[field]
                    if value is None or not str(value).strip():
                        null_classes += 1
                    else:
                        encountered.add(str(value))
        elif geom_analysis.distance(line) <= tolerance:
            hits.append(geom_analysis)
            value = feature[field]
            if value is None or not str(value).strip():
                null_classes += 1
            else:
                encountered.add(str(value))
    if invalid_nearby and not invalid_ids:
        feedback.pushWarning('{}: {} geometrias inválidas dentro da área consultada.'.format(title, invalid_nearby))
    if geometry_type == QgsWkbTypes.PolygonGeometry:
        intervals = [interval for hit in hits for interval in _line_intervals(hit, line)]
        covered, gap, overlap = _interval_coverage(intervals, line.length())
        gap_intervals = uncovered_ranges(intervals, line.length())
        percent = 100.0 * covered / line.length()
        status = 'bloqueio' if percent == 0 or null_classes or invalid_ids else ('aviso' if percent < 99.9 or overlap > 0.01 or invalid_nearby else 'ok')
        feedback.pushInfo('{}: classes que cruzam A–B: {}; cobertura estimada {:.1f}%; lacunas {:.1f} m; sobreposições {:.1f} m.'.format(
            title, len(encountered), percent, gap, overlap))
        if percent == 0:
            feedback.pushWarning(title + ': nenhum polígono cruza o perfil.')
        elif percent < 99.9:
            feedback.pushWarning(title + ': existem trechos sem cobertura poligonal.')
        if overlap > 0.01:
            feedback.pushWarning(title + ': há classes poligonais sobrepostas ao longo do eixo (aprox. {:.1f} m); confira a base.'.format(overlap))
        if null_classes:
            feedback.pushWarning('{}: {} feição(ões) que cruzam o perfil não têm valor no campo de classe.'.format(title, null_classes))
        renderer = layer.renderer()
        categorized = bool(renderer and hasattr(renderer, 'classAttribute') and renderer.classAttribute() == field)
        return {'status': status, 'classes_cruzadas': sorted(encountered), 'cobertura_pct': round(percent, 1),
                'lacunas_estimadas_m': round(gap, 2), 'sobreposicao_estimada_m': round(overlap, 2),
                'intervalos_sem_cobertura_m': gap_intervals,
                'feicoes_candidatas': len(hits), 'geometrias_invalidas': invalid_nearby,
                'geometrias_invalidas_globais': len(invalid_ids), 'ids_geometrias_invalidas': invalid_ids[:10],
                'feicoes_verificadas': scanned,
                'valores_nulos_cruzados': null_classes, 'campo': field,
                'tipo_campo': layer.fields().field(field).typeName(), 'crs': layer.crs().authid(),
                'renderer_categorized_for_field': categorized}
    status = 'bloqueio' if null_classes or invalid_ids else ('aviso' if not hits or invalid_nearby else 'ok')
    feedback.pushInfo('{}: {} evento(s) dentro da tolerância de 5 m; {} classe(s) encontrada(s).'.format(
        title, len(hits), len(encountered)))
    if not hits:
        feedback.pushWarning(title + ': nenhum evento foi encontrado a até 5 m do eixo; isso pode ser esperado.')
    if null_classes:
        feedback.pushWarning('{}: {} evento(s) próximo(s) ao eixo não têm valor no campo de classe.'.format(title, null_classes))
    return {'status': status, 'eventos': len(hits), 'classes_cruzadas': sorted(encountered),
            'geometrias_invalidas': invalid_nearby, 'geometrias_invalidas_globais': len(invalid_ids),
            'ids_geometrias_invalidas': invalid_ids[:10], 'feicoes_verificadas': scanned,
            'valores_nulos_cruzados': null_classes,
            'campo': field, 'tipo_campo': layer.fields().field(field).typeName(), 'crs': layer.crs().authid()}


def _classes_without_visible_symbol(renderer, field, values):
    """Return crossed classes missing an enabled category symbol for the selected field."""
    if not renderer or not hasattr(renderer, 'classAttribute') or renderer.classAttribute() != field:
        return []
    categories = {}
    for category in renderer.categories():
        value = category.value()
        key = '' if value is None else str(value)
        categories[key] = category
    missing = []
    for value in values or []:
        category = categories.get(str(value))
        if category is None or category.symbol() is None:
            missing.append(str(value))
            continue
        render_state = getattr(category, 'renderState', None)
        if callable(render_state) and not render_state():
            missing.append(str(value))
    return sorted(set(missing))


class PreVerificarPerfilGeoecologico(QgsProcessingAlgorithm):
    def name(self): return 'preverificar_entradas_perfil'
    def displayName(self): return 'Pré-verificar entradas do perfil geoecológico'
    def group(self): return 'Perfis'
    def groupId(self): return 'perfis'
    def createInstance(self): return PreVerificarPerfilGeoecologico()
    def flags(self):
        return (super().flags() | Qgis.ProcessingAlgorithmFlag.NoThreading) & ~Qgis.ProcessingAlgorithmFlag.SupportsBatch
    def shortHelpString(self):
        return ('Faz uma leitura sem alterar dados nem criar saídas. Verifica A–B, cobertura do MDE, SRC, campos e cobertura das faixas. '
                'Avisos não impedem a geração; bloqueios indicam entradas sem as quais o resultado não é confiável. '
                'Usa o mesmo SRC métrico do gerador (ou o SRC informado) para medir intervalos. '
                'A unidade vertical declarada do MDE é convertida para metros; sem confirmação, valores permanecem sem conversão.')
    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterVectorLayer('AB', 'Linha A–B (uma feição)', types=[QgsProcessing.TypeVectorLine]))
        self.addParameter(QgsProcessingParameterRasterLayer('MDE', 'MDE de altimetria — banda 1'))
        self.addParameter(QgsProcessingParameterEnum('UNIDADE_VERTICAL','Unidade vertical das cotas do MDE',
                            options=list(UNIT_CHOICES), defaultValue=0))
        self.addParameter(QgsProcessingParameterNumber('FATOR_VERTICAL','Fator personalizado para metros',
                            type=QgsProcessingParameterNumber.Double, defaultValue=1.0,
                            minValue=0.000001, maxValue=1000000))
        self.addParameter(QgsProcessingParameterCrs('SRC', 'SRC métrico para análise (vazio: automático)', optional=True))
        themes_parameter = QgsProcessingParameterMatrix('TEMAS', 'Faixas a verificar', numberRows=1, hasFixedNumberRows=False,
                            headers=['Título da faixa', 'ID da camada', 'Campo da classe', 'Arquivo QML (opcional)'])
        # Mantém o mesmo seletor visual das faixas usado pelo algoritmo de geração.
        from .perfil_geoecologico_personalizado import load_local
        themes_ui = load_local('interface_temas.py')
        themes_parameter.setMetadata({'widget_wrapper': {'class': themes_ui.ThemesWrapper}})
        self.addParameter(themes_parameter)
        self.addParameter(QgsProcessingParameterNumber('PASSO', 'Passo entre amostras (m)',
                            type=QgsProcessingParameterNumber.Double, defaultValue=30, minValue=0.1))
        self.addOutput(QgsProcessingOutputString('RELATORIO', 'Relatório da pré-verificação'))
    def processAlgorithm(self, parameters, context, feedback):
        project = context.project() or QgsProject.instance()
        if project is None:
            raise QgsProcessingException('Abra um projeto QGIS.')
        try:
            themes = parse_themes(self.parameterAsMatrix(parameters, 'TEMAS', context))
        except (ValueError, TypeError) as exc:
            raise QgsProcessingException(str(exc)) from exc
        ab = self.parameterAsVectorLayer(parameters, 'AB', context)
        line, line_length = _line_geometry(ab, feedback)
        from .perfil_geoecologico_personalizado import load_local
        engine = load_local('_motor/perfil_core.py.inc')
        requested_crs = self.parameterAsCrs(parameters, 'SRC', context)
        try:
            analysis_crs = engine.work_crs(ab, requested_crs, project, feedback)
            analysis_line = _transform_geometry(line, ab.crs(), analysis_crs, project)
        except Exception as exc:
            raise QgsProcessingException('Não foi possível determinar o SRC métrico da análise: ' + str(exc)) from exc
        analysis_length = analysis_line.length()
        dem = self.parameterAsRasterLayer(parameters, 'MDE', context)
        if dem is None or not dem.isValid():
            raise QgsProcessingException('Selecione um MDE válido.')
        try:
            vertical=resolve_vertical_conversion(
                self.parameterAsEnum(parameters,'UNIDADE_VERTICAL',context),
                self.parameterAsDouble(parameters,'FATOR_VERTICAL',context))
        except ValueError as exc:
            raise QgsProcessingException(str(exc)) from exc
        step = self.parameterAsDouble(parameters, 'PASSO', context)
        feedback.pushInfo('Linha A–B: válida, aberta, uma feição; comprimento {:.2f} unidades do SRC {}.'.format(
            line_length, ab.crs().authid() or ab.crs().description()))
        if ab.crs() != analysis_crs:
            feedback.pushInfo('A–B será analisada no SRC métrico {} para alinhar distâncias, amostragem e saída.'.format(
                analysis_crs.authid() or analysis_crs.description()))
        checks = {'A-B': {'status': 'ok', 'comprimento': line_length,
                          'comprimento_m': analysis_length, 'crs': ab.crs().authid(),
                          'src_analise': analysis_crs.authid() or analysis_crs.description()}}
        try:
            checks['MDE'] = _raster_check(dem, 1, analysis_line, analysis_crs, project, step, feedback, 'MDE')
            checks['MDE'].update(
                confirmar_unidade_vertical_metros=(vertical['unit'] == 'Metros'),
                unidade_vertical_confirmada=vertical['confirmed'],
                unidade_vertical_entrada=vertical['unit'],
                fator_vertical_para_metros=vertical['factor_to_meters'],
                minimo_convertido_m=(checks['MDE']['min'] * vertical['factor_to_meters'])
                    if vertical['confirmed'] and checks['MDE']['min'] is not None else None,
                maximo_convertido_m=(checks['MDE']['max'] * vertical['factor_to_meters'])
                    if vertical['confirmed'] and checks['MDE']['max'] is not None else None)
            if not vertical['confirmed']:
                if checks['MDE']['status'] == 'ok':
                    checks['MDE']['status'] = 'aviso'
                feedback.pushWarning('Unidade vertical do MDE não confirmada; valores serão mantidos sem conversão.')
            else:
                feedback.pushInfo('Unidade vertical declarada: {} · fator para metros: {:.9g}.'.format(
                    vertical['unit'], vertical['factor_to_meters']))
        except Exception as exc:
            checks['MDE'] = {'status': 'bloqueio', 'erro': str(exc)}
            feedback.pushWarning('MDE: falha de transformação ou amostragem: ' + str(exc))
        checks['faixas'] = []
        for theme in themes:
            title, source_key, field = theme['title'], theme['source'], theme['field']
            source = project.mapLayer(source_key) or QgsProcessingUtils.mapLayerFromString(source_key, context)
            if source is None or not source.isValid():
                feedback.pushWarning(title + ': camada indisponível; escolha novamente a entrada.')
                checks['faixas'].append({'tema': title, 'status': 'bloqueio', 'erro': 'camada indisponível'})
                continue
            if source.customProperty('geo/role', ''):
                feedback.pushWarning(title + ': parece ser uma saída de perfil; prefira a camada original.')
            if theme['raster']:
                try:
                    band = int(field.split(':', 1)[1])
                    report = _raster_check(source, band, analysis_line, analysis_crs, project, step, feedback, title)
                    raster_tools = __import__(__package__ + '.faixas_raster', fromlist=['parse_classes', 'parse_auto_style'])
                    auto = raster_tools.parse_auto_style(theme['style'])
                    if auto is None:
                        classes = raster_tools.parse_classes(theme['style'])
                        if report.get('min') is not None and (report['min'] < classes[0][0] or report['max'] > classes[-1][1]):
                            report['status'] = 'aviso'
                            feedback.pushWarning(title + ': os intervalos manuais não cobrem toda a faixa de valores amostrada.')
                    elif report.get('valores_distintos_amostrados', 0) < auto[1]:
                        report['status'] = 'aviso'
                        feedback.pushWarning(title + ': há menos valores distintos amostrados do que classes solicitadas; o número efetivo de classes pode ser menor.')
                    report.update({'tema': title, 'camada': source.name(), 'papel': 'raster classificado'})
                except Exception as exc:
                    report = {'tema': title, 'status': 'bloqueio', 'erro': str(exc)}
                    feedback.pushWarning(title + ': ' + str(exc))
            elif isinstance(source, QgsVectorLayer):
                try:
                    report = _vector_check(source, field, analysis_line, analysis_crs, project, feedback, title)
                    report.update({'tema': title, 'camada': source.name(), 'papel':
                                   'faixa poligonal' if QgsWkbTypes.geometryType(source.wkbType()) == QgsWkbTypes.PolygonGeometry else 'eventos'})
                    categorized = report.get('renderer_categorized_for_field')
                    if theme['style']:
                        styled = source.clone()
                        message, ok = styled.loadNamedStyle(theme['style'])
                        renderer = styled.renderer() if ok else None
                        categorized = bool(renderer and hasattr(renderer, 'classAttribute') and renderer.classAttribute() == field)
                        if not ok:
                            report['status'] = 'bloqueio'
                            feedback.pushWarning(title + ': QML não foi carregado: ' + str(message))
                    if not categorized:
                        report['status'] = 'bloqueio'
                        feedback.pushWarning(title + ': a simbologia precisa estar categorizada pelo campo escolhido ou vir de um QML categorizado compatível.')
                    else:
                        if not theme['style']:
                            renderer = source.renderer()
                        missing_symbols = _classes_without_visible_symbol(
                            renderer, field, report.get('classes_cruzadas', []))
                        report['classes_sem_simbolo'] = missing_symbols
                        if missing_symbols:
                            report['status'] = 'bloqueio'
                            feedback.pushWarning(
                                title + ': classe(s) que cruzam A–B sem símbolo categorizado visível: ' +
                                ', '.join(missing_symbols) + '. Ajuste a simbologia ou indique um QML categorizado compatível.')
                    if 'faixa_tema_' in source.source().lower() or 'faixa_' in source.name().lower() or source.customProperty('geo/role', ''):
                        if report['status'] == 'ok':
                            report['status'] = 'aviso'
                        feedback.pushWarning(title + ': a camada parece derivada de um perfil anterior; confirme se é a base original que deseja usar.')
                except Exception as exc:
                    report = {'tema': title, 'status': 'bloqueio', 'erro': str(exc)}
                    feedback.pushWarning(title + ': ' + str(exc))
            else:
                report = {'tema': title, 'status': 'bloqueio', 'erro': 'tipo da camada não suportado'}
                feedback.pushWarning(title + ': tipo da camada não suportado.')
            checks['faixas'].append(report)
        statuses = [checks['A-B'].get('status'), checks['MDE'].get('status')] + [item.get('status') for item in checks['faixas']]
        summary = {'bloqueios': statuses.count('bloqueio'), 'avisos': statuses.count('aviso'),
                   'resultado': 'REVISE AS ENTRADAS' if 'bloqueio' in statuses else ('CONTINUE COM ATENÇÃO' if 'aviso' in statuses else 'ENTRADAS SEM PROBLEMAS DETECTADOS'),
                   'verificacoes': checks}
        feedback.pushInfo('Pré-verificação: ' + summary['resultado'] + ' — {} bloqueio(s), {} aviso(s).'.format(summary['bloqueios'], summary['avisos']))
        return {'RELATORIO': json.dumps(summary, ensure_ascii=False)}

