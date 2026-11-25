# -*- coding: utf-8 -*-
"""Perfil personalizado com faixas vetoriais e raster. Reutiliza uma instância isolada do motor.
Mantém o estado global do motor compartilhado isolado.
"""

# Desenvolvido por João Sipraki
# Copyright (C) 2026 João Sipraki
# SPDX-License-Identifier: GPL-3.0-or-later

import importlib.util
from importlib.machinery import SourceFileLoader
import json
import math
import uuid
from pathlib import Path
from qgis.PyQt.QtCore import Qt
from qgis.core import (Qgis, QgsProcessingAlgorithm, QgsProcessingParameterVectorLayer,
    QgsProcessingParameterRasterLayer, QgsProcessingParameterMatrix,
    QgsProcessingParameterString, QgsProcessingParameterFileDestination,
    QgsProcessingParameterNumber, QgsProcessingParameterCrs, QgsProcessingParameterEnum,
    QgsProcessingOutputString, QgsProcessingParameterBoolean, QgsProcessingParameterMapLayer,
    QgsMapLayerStyle, QgsLineSymbol, QgsFillSymbol, QgsRectangle, QgsGeometry, QgsSingleSymbolRenderer,
    QgsProcessing, QgsProcessingException, QgsProcessingUtils, QgsVectorLayer, QgsRasterLayer,
    QgsWkbTypes, QgsRendererCategory, QgsCoordinateTransform, QgsLayoutSize, QgsLayoutPoint, QgsLayoutItemLabel, QgsLayoutItemMap,
    QgsLayoutItem, QgsLayoutItemLegend, QgsLayoutItemElevationProfile, QgsLayoutItemShape, QgsPrintLayout,
    QgsLegendRenderer, QgsLegendStyle, QgsLayoutUtils)
from qgis.PyQt.QtGui import QColor, QFont, QImage, QPainter

VERSION = '2026-11-24.23.2'
LEGEND_COMPONENT = getattr(Qgis, "LegendComponent", QgsLegendStyle)
ORIENTATIONS = ('Retrato', 'Paisagem')
PAGE_SIZES = ((210, 297), (297, 210))
MARGIN = 10
COLUMN_GAP = 6
HERE = Path(__file__).resolve().parent


def theme_band_number(index):
    """Algarismo romano para identificar a faixa na ordem escolhida."""
    value = int(index) + 1
    if value < 1 or value > 3999:
        return str(value)
    numerals = ((1000, 'M'), (900, 'CM'), (500, 'D'), (400, 'CD'),
                (100, 'C'), (90, 'XC'), (50, 'L'), (40, 'XL'),
                (10, 'X'), (9, 'IX'), (5, 'V'), (4, 'IV'), (1, 'I'))
    result = []
    for amount, numeral in numerals:
        count, value = divmod(value, amount)
        result.append(numeral * count)
    return ''.join(result)


def theme_legend_label(index, title):
    """Nome e número aparecem uma vez, na legenda abaixo das faixas."""
    return '{} — {}'.format(theme_band_number(index), title)


def river_crossing_legend_text(text, count):
    """Substitui o indicador genérico pela quantidade real de cruzamentos."""
    count = int(count or 0)
    if count <= 0:
        return text
    noun = 'cruzamento' if count == 1 else 'cruzamentos'
    return str(text or '').replace(
        '♦ Cruzamento de rio',
        '♦ {} {} de rio ao longo do perfil'.format(count, noun), 1)


def add_overlap_hatching(layout, layers, themes, length, distance_utils):
    """Assinala no mapa as distâncias em que classes diferentes se sobrepõem."""
    for item in list(layout.items()):
        if hasattr(item, 'id') and item.id().startswith('geo_sobreposicao_'):
            layout.removeLayoutItem(item)
    report = {}
    for theme in themes:
        role = theme['role']
        layer = layers.get(role)
        map_item = layout.itemById('geo_' + role.lower())
        if layer is None or map_item is None or not layer.isValid():
            continue
        intervals = []
        for feature in layer.getFeatures():
            try:
                intervals.append((feature['dist_ini'], feature['dist_fin'], feature['classe']))
            except (KeyError, TypeError):
                continue
        overlaps = distance_utils.overlapping_class_ranges(intervals, length)
        if not overlaps:
            continue
        x = map_item.positionWithUnits().x()
        y = map_item.positionWithUnits().y()
        width = map_item.sizeWithUnits().width()
        height = map_item.sizeWithUnits().height()
        for index, overlap in enumerate(overlaps):
            item = QgsLayoutItemShape(layout)
            item.setShapeType(QgsLayoutItemShape.Rectangle)
            item.setId('geo_sobreposicao_{}_{}'.format(role.lower(), index + 1))
            item.setSymbol(QgsFillSymbol.createSimple({
                'style': 'b_diagonal', 'color': '0,105,140,210', 'outline_style': 'no'}))
            layout.addLayoutItem(item)
            item.setReferencePoint(QgsLayoutItem.UpperLeft)
            item.attemptMove(QgsLayoutPoint(x + width * overlap['inicio_m'] / length, y))
            item.attemptResize(QgsLayoutSize(width * (overlap['fim_m'] - overlap['inicio_m']) / length, height))
            item.setZValue(1000)
        report[theme['title']] = overlaps
    layout.setCustomProperty('geo/sobreposicoes_tematicas', json.dumps(report, ensure_ascii=False))
    return report

def load_local(filename):
    path = HERE / filename
    if not path.is_file():
        raise QgsProcessingException('Arquivo do pacote ausente: ' + str(path))
    module_name = '_perfil_' + uuid.uuid4().hex
    spec = importlib.util.spec_from_file_location(module_name, str(path), loader=SourceFileLoader(module_name, str(path)))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def resolve_source(text, context):
    project = context.project()
    layer = project.mapLayer(text)
    if layer is None:
        matches = project.mapLayersByName(text)
        if len(matches) > 1:
            raise QgsProcessingException('Há camadas com nome repetido: ' + text + '. Renomeie ou use o ID da camada.')
        layer = matches[0] if matches else QgsProcessingUtils.mapLayerFromString(text, context)
    if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
        raise QgsProcessingException('Camada vetorial não encontrada: ' + text)
    if QgsWkbTypes.geometryType(layer.wkbType()) not in (QgsWkbTypes.PointGeometry, QgsWkbTypes.LineGeometry, QgsWkbTypes.PolygonGeometry):
        raise QgsProcessingException(text + ': use uma camada vetorial de pontos, linhas ou polígonos.')
    return layer


def position_item(item, x, y, width, height):
    item.attemptMove(QgsLayoutPoint(x, y))
    item.attemptResize(QgsLayoutSize(width, height))


def style_title(title):
    title.setFont(QFont('Times New Roman', 12, QFont.Bold))
    title.setHAlign(Qt.AlignmentFlag.AlignHCenter)
    title.setVAlign(Qt.AlignmentFlag.AlignVCenter)
    title.setFrameEnabled(True)
    title.setFrameStrokeColor(QColor('#262626'))
    title.setBackgroundEnabled(True)
    title.setBackgroundColor(QColor('#ffffff'))


def build_layout(project, name, themes, urban_name, has_urban):
    layout = QgsPrintLayout(project)
    layout.initializeDefaults()
    layout.setName(name)

    def add_item(item, item_id):
        item.setId(item_id)
        layout.addLayoutItem(item)
        return item

    def add_label(item_id, text=''):
        label = add_item(QgsLayoutItemLabel(layout), item_id)
        font = QFont('Arial', 9)
        if item_id == 'geo_titulo':
            font.setPointSize(12)
            font.setBold(True)
        label.setFont(font)
        label.setText(text)

    add_label('geo_titulo')
    style_title(layout.itemById('geo_titulo'))
    add_label('geo_unidade_altimetria')
    add_item(QgsLayoutItemElevationProfile(layout), 'geo_altimetria')
    for index, theme in enumerate(themes):
        role = theme['role'].lower()
        add_label('geo_rotulo_' + role, theme_band_number(index))
        add_item(QgsLayoutItemMap(layout), 'geo_' + role)
    add_label('geo_indicacao_rios_urbano')
    if has_urban:
        add_label('geo_nome_nucleo', 'Núcleo urbano: ' + urban_name)
    for number in (1, 2):
        legend = add_item(QgsLayoutItemLegend(layout), 'geo_legenda_' + str(number))
        legend.setTitle('')
    layout.setCustomProperty('geo/custom_themes', json.dumps(themes, ensure_ascii=False))
    layout.setCustomProperty('geo/custom_urban', has_urban)
    project.layoutManager().addLayout(layout)
    return layout


def arrange_profile(layout, themes, orientation, urban_name, page_width):
    minimum_height = PAGE_SIZES[orientation][1]
    """Posiciona o quadro antes de o motor alinhar as faixas ao eixo de distância."""
    content_width = page_width - 2 * MARGIN
    page = layout.pageCollection().pages()[0]
    page.setPageSize(QgsLayoutSize(page_width, minimum_height))

    title_item = layout.itemById('geo_titulo')
    style_title(title_item)
    position_item(title_item, MARGIN, 5, content_width, 16)
    profile_y = 27
    profile_height = 65 if orientation == 0 else 52
    position_item(layout.itemById('geo_altimetria'), MARGIN, profile_y, content_width, profile_height)
    vertical_label = layout.itemById('geo_unidade_altimetria')
    if vertical_label is not None:
        vertical_label.setFont(QFont('Arial', 7))
        vertical_label.setFontColor(QColor('#555555'))
        position_item(vertical_label, MARGIN, profile_y + profile_height + 1, content_width, 5.5)
    first_band = profile_y + profile_height + 11
    for i, theme in enumerate(themes):
        role = theme['role'].lower()
        y = first_band + i * 13
        label = layout.itemById('geo_rotulo_' + role)
        if label is None:
            # Nos layouts da revisão anterior, os títulos das faixas vinham sem ID.
            label = next((item for item in layout.items() if isinstance(item, QgsLayoutItemLabel)
                          and not item.id() and item.text() in
                          (theme['title'], theme_band_number(i))), None)
            if label is None:
                label = QgsLayoutItemLabel(layout)
                label.setFont(QFont('Arial', 9))
                layout.addLayoutItem(label)
            label.setId('geo_rotulo_' + role)
        label.setText(theme_band_number(i))
        position_item(label, MARGIN, y, 7, 5.5)
        label.setFont(QFont('Arial', 8, QFont.Bold))
        label.setFontColor(QColor('#27483e'))
        position_item(layout.itemById('geo_' + role), MARGIN + 9, y, content_width - 9, 5.5)

    details_y = first_band + (len(themes) - 1) * 13 + 9
    indication = layout.itemById('geo_indicacao_rios_urbano')
    position_item(indication, MARGIN, details_y, content_width, 6)
    if urban_name:
        urban_text = 'Núcleo urbano: ' + urban_name
        label = layout.itemById('geo_nome_nucleo')
        if label is None:
            label = next((item for item in layout.items() if isinstance(item, QgsLayoutItemLabel)
                          and not item.id() and item.text() == urban_text), None)
            if label is None:
                label = QgsLayoutItemLabel(layout)
                label.setFont(QFont('Arial', 9))
                layout.addLayoutItem(label)
            label.setId('geo_nome_nucleo')
        label.setText(urban_text)
        position_item(label, MARGIN, details_y + 6, content_width, 6)
    return details_y


def finish_legends(layout, layers, themes, orientation, details_y, urban_name, page_width,
                   side_by_side_map=False):
    """Distribui os temas em colunas e dimensiona a folha pelo conteúdo medido."""
    columns = min(len(themes), 2 if orientation == 0 or side_by_side_map else 3)
    map_reserve = 68 + 8 if side_by_side_map else 0
    legend_width = page_width - 2 * MARGIN - map_reserve
    column_width = (legend_width - (columns - 1) * COLUMN_GAP) / columns
    legend_y = details_y + 4
    if layout.itemById('geo_indicacao_rios_urbano').isVisible():
        legend_y += 6
    if urban_name:
        legend_y = details_y + 16

    size_per_column, extra = divmod(len(themes), columns)
    offset = 0
    bottom = legend_y
    for column in range(3):
        item_id = 'geo_legenda_' + str(column + 1)
        legend = layout.itemById(item_id)
        if legend is None:
            if column >= columns:
                continue
            legend = QgsLayoutItemLegend(layout)
            legend.setId(item_id)
            legend.setTitle('')
            layout.addLayoutItem(legend)
        legend.setAutoUpdateModel(False)
        legend.model().rootGroup().removeAllChildren()
        legend.setVisibility(column < columns)
        if column >= columns:
            continue
        count = size_per_column + int(column < extra)
        for theme_index in range(offset, offset + count):
            theme = themes[theme_index]
            node = legend.model().rootGroup().addLayer(layers[theme['role']])
            node.setName(theme_legend_label(theme_index, theme['title']))
            QgsLegendRenderer.setNodeLegendStyle(node, LEGEND_COMPONENT.Subgroup)
        offset += count
        legend.setSymbolHeight(3)
        legend.setBoxSpace(1)
        if hasattr(legend, "setAutoWrapLinesAfter"):
            legend.setAutoWrapLinesAfter(column_width - legend.symbolWidth() - 10)
        heading = QFont('Arial', 9)
        heading.setBold(True)
        legend.setStyleFont(LEGEND_COMPONENT.Subgroup, heading)
        legend.setStyleFont(LEGEND_COMPONENT.SymbolLabel, QFont('Arial', 8))
        legend.setStyleMargin(LEGEND_COMPONENT.Subgroup, QgsLegendStyle.Top, 2.5)
        legend.setResizeToContents(True)
        dpi = layout.renderContext().dpi()
        device = QImage(64, 64, QImage.Format_ARGB32)
        device.setDotsPerMeterX(round(dpi / .0254))
        device.setDotsPerMeterY(round(dpi / .0254))
        painter = QPainter(device)
        try:
            context = QgsLayoutUtils.createRenderContextForLayout(layout, painter, dpi)
            context.setExpressionContext(legend.createExpressionContext())
            context.setFlag(Qgis.RenderContextFlag.ApplyScalingWorkaroundForTextRendering, True)
            size = QgsLegendRenderer(legend.model(), legend.legendSettings()).minimumSize(context)
            if not math.isfinite(size.width()) or not math.isfinite(size.height()) or size.width() > column_width:
                raise QgsProcessingException('A legenda excede a largura disponível. Revise os textos das classes ou dos títulos.')
        finally:
            painter.end()
        x = MARGIN + column * (column_width + COLUMN_GAP)
        position_item(legend, x, legend_y, size.width(), size.height())
        bottom = max(bottom, legend_y + size.height())

    height = bottom + MARGIN
    if height > 5000:
        raise QgsProcessingException('Legenda excessivamente longa para exportação. Revise os temas.')
    return height


def add_location_map(layout, project, ab, background, curve, crs, page_width, top,
                     side_by_side=False, urban_layer=None):
    """Frame the study area; a global context layer must not set the map extent."""
    ids = ('geo_mapa_contexto', 'geo_mapa_titulo', 'geo_mapa_A', 'geo_mapa_B')
    for item_id in ids:
        item = layout.itemById(item_id)
        if item is not None:
            layout.removeLayoutItem(item)
    if ab is None:
        return top

    width = min(68, page_width - 2 * MARGIN) if side_by_side else min(120, page_width - 2 * MARGIN)
    height = 52 if side_by_side else 45
    map_x = page_width - MARGIN - width if side_by_side else MARGIN
    map_y = top + 9
    bounds = QgsRectangle(curve.boundingBox())
    if (urban_layer is not None and isinstance(urban_layer, QgsVectorLayer)
            and urban_layer.isValid() and urban_layer.crs().isValid()):
        urban_transform = None
        if urban_layer.crs().isValid() and urban_layer.crs() != crs:
            urban_transform = QgsCoordinateTransform(urban_layer.crs(), crs, project)
        for feature in urban_layer.getFeatures():
            geometry = feature.geometry()
            if geometry.isNull() or geometry.isEmpty():
                continue
            if urban_transform is not None:
                geometry = QgsGeometry(geometry)
                geometry.transform(urban_transform)
            if geometry.intersects(curve):
                bounds.combineExtentWith(geometry.boundingBox())
    center = bounds.center()
    half_width = max(bounds.width() / 2, bounds.height() * width / (2 * height)) * 1.08
    half_height = half_width * height / width

    map_item = QgsLayoutItemMap(layout)
    map_item.setId(ids[0])
    layout.addLayoutItem(map_item)
    position_item(map_item, map_x, map_y, width, height)
    map_item.setCrs(crs)
    map_item.setLayers([ab] if background is None or background.id() == ab.id() else [ab, background])
    map_item.setKeepLayerSet(True)
    highlight = ab.clone()
    highlight.setLabelsEnabled(False)
    highlight.setRenderer(QgsSingleSymbolRenderer(QgsLineSymbol.createSimple({
        'line_color': '#ad392b', 'line_width': '0.65'})))
    style = QgsMapLayerStyle()
    style.readFromLayer(highlight)
    map_item.setLayerStyleOverrides({ab.id(): style.xmlData()})
    map_item.setKeepLayerStyles(True)
    map_item.setFrameEnabled(True)
    map_item.zoomToExtent(QgsRectangle(center.x() - half_width, center.y() - half_height,
                                       center.x() + half_width, center.y() + half_height))
    extent = map_item.extent()

    def label(item_id, value, x, y, w):
        item = QgsLayoutItemLabel(layout)
        item.setId(item_id)
        item.setText(value)
        font = QFont('Arial', 9)
        font.setBold(True)
        item.setFont(font)
        layout.addLayoutItem(item)
        position_item(item, x, y, w, 6)

    label(ids[1], 'Localização da linha A–B', map_x, top, width)
    for item_id, letter, distance in ((ids[2], 'A', 0), (ids[3], 'B', curve.length())):
        end = curve.interpolate(distance)
        point = end.asPoint()
        x = map_x + width * (point.x() - extent.xMinimum()) / extent.width()
        y = map_y + height * (extent.yMaximum() - point.y()) / extent.height()
        label(item_id, letter, x - 2, max(map_y, y - 6), 7)
    return map_y + height


class PerfilGeoecologicoPersonalizado(QgsProcessingAlgorithm):
    def name(self):return 'perfil_geoecologico_personalizado'
    def displayName(self):return 'Perfil geoecológico — temas personalizados'
    def group(self):return 'Perfis'
    def groupId(self):return 'perfis'
    def createInstance(self):return PerfilGeoecologicoPersonalizado()
    def flags(self):
        return ((super().flags()|Qgis.ProcessingAlgorithmFlag.NoThreading)&~Qgis.ProcessingAlgorithmFlag.SupportsBatch)
    def shortHelpString(self):
        return ('No projeto, deixe carregadas uma linha A–B aberta com uma feição, um MDE e as bases temáticas. '
                'Declare a unidade vertical do MDE; cotas em pés ou outro fator são convertidas para metros. '
                'Use Selecionar faixas para ordenar polígonos, eventos de linhas e pontos ou rasters classificados. '
                'Para vetores, use um renderizador categorizado pelo campo escolhido ou indique um QML categorizado. '
                'Rios, núcleo urbano e mapa de localização são opcionais. Escolha orientação, nome do layout e um GeoPackage de saída. '
                'Depois de executar, confira a cobertura, salve o projeto QGIS e exporte o layout para PNG ou PDF se precisar compartilhar.')
    def initAlgorithm(self,config=None):
        self.addParameter(QgsProcessingParameterVectorLayer('AB','Linha A–B (uma feição)',types=[QgsProcessing.TypeVectorLine]))
        self.addParameter(QgsProcessingParameterRasterLayer('MDE','MDE de altimetria — banda 1'))
        UNIT_CHOICES = load_local('unidades_vertical.py').UNIT_CHOICES
        self.addParameter(QgsProcessingParameterEnum('UNIDADE_VERTICAL','Unidade vertical das cotas do MDE',
                            options=list(UNIT_CHOICES), defaultValue=0))
        self.addParameter(QgsProcessingParameterNumber('FATOR_VERTICAL','Fator personalizado para metros',
                            type=QgsProcessingParameterNumber.Double, defaultValue=1.0,
                            minValue=0.000001, maxValue=1000000))
        self._themes_ui = load_local('interface_temas.py')
        themes_parameter = QgsProcessingParameterMatrix('TEMAS','Faixas temáticas na ordem escolhida',numberRows=1,hasFixedNumberRows=False,headers=['Título da faixa','ID da camada','Campo da classe','Arquivo QML (opcional)'])
        themes_parameter.setMetadata({'widget_wrapper': {'class': self._themes_ui.ThemesWrapper}})
        self.addParameter(themes_parameter)
        self.addParameter(QgsProcessingParameterVectorLayer('RIOS','Rios (opcional)',types=[QgsProcessing.TypeVectorLine],optional=True))
        self.addParameter(QgsProcessingParameterVectorLayer('URBANO','Núcleo urbano (opcional)',types=[QgsProcessing.TypeVectorPolygon],optional=True))
        self.addParameter(QgsProcessingParameterString('NOME_NUCLEO','Nome do núcleo (somente com núcleo)',optional=True))
        self.addParameter(QgsProcessingParameterString('TITULO','Título',defaultValue='PERFIL GEOECOLÓGICO'))
        self.addParameter(QgsProcessingParameterString('LAYOUT','Nome do layout personalizado',defaultValue='Perfil personalizado'))
        self.addParameter(QgsProcessingParameterEnum('ORIENTACAO','Orientação da folha',options=list(ORIENTATIONS),defaultValue=0))
        self.addParameter(QgsProcessingParameterBoolean('MAPA_LOCALIZACAO','Incluir mapa de localização',defaultValue=False))
        self.addParameter(QgsProcessingParameterMapLayer('MAPA_CONTEXTO','Camada de contexto do mapa (opcional)',optional=True))
        self.addParameter(QgsProcessingParameterCrs('SRC','SRC métrico (vazio: automático)',optional=True))
        self.addParameter(QgsProcessingParameterNumber('PASSO','Amostragem altimétrica em metros',type=QgsProcessingParameterNumber.Double,defaultValue=10,minValue=.1))
        self.addParameter(QgsProcessingParameterNumber('PASSO_RASTER','Passo das faixas raster em metros',type=QgsProcessingParameterNumber.Double,defaultValue=10,minValue=.1))
        self.addParameter(QgsProcessingParameterNumber('LARGURA_EVENTO','Largura visual dos eventos (m)',type=QgsProcessingParameterNumber.Double,defaultValue=20,minValue=.1))
        self.addParameter(QgsProcessingParameterNumber('TOLERANCIA_EVENTO','Distância máxima de linhas/pontos ao perfil (m)',type=QgsProcessingParameterNumber.Double,defaultValue=5,minValue=0))
        self.addParameter(QgsProcessingParameterFileDestination('GPKG','GeoPackage próprio deste perfil',fileFilter='GeoPackage (*.gpkg)'))
        self.addOutput(QgsProcessingOutputString('RESUMO','Resumo'))
        self.addOutput(QgsProcessingOutputString('STATUS_LAYOUT','Estado do layout'))
        self.addOutput(QgsProcessingOutputString('BACKUP','Backup'))
    def processAlgorithm(self,parameters,context,feedback):
        project=context.project()
        if project is None:raise QgsProcessingException('Abra um projeto QGIS.')
        cfg=load_local('configuracao_personalizada.py')
        distance_utils=load_local('intervalos.py')
        try:themes=cfg.parse_themes(self.parameterAsMatrix(parameters,'TEMAS',context))
        except ValueError as exc:raise QgsProcessingException(str(exc)) from exc
        units=load_local('unidades_vertical.py')
        try:
            vertical=units.resolve_vertical_conversion(
                self.parameterAsEnum(parameters,'UNIDADE_VERTICAL',context),
                self.parameterAsDouble(parameters,'FATOR_VERTICAL',context))
        except ValueError as exc:
            raise QgsProcessingException(str(exc)) from exc
        engine=load_local('_motor/perfil_core.py.inc')
        engine.ROLES=tuple(t['role'] for t in themes)
        engine.TITLES={t['role']:t['title'] for t in themes}
        engine.TABLES={t['role']:t['table'] for t in themes}|{k:v for k,v in engine.TABLES.items() if k not in ('GEOLOGIA','CLIMA','GEOMORFOLOGIA','RELEVO','SOLOS','VEGETACAO')}
        core=engine.PerfilGeoecologicoGeral();core.initAlgorithm()
        run={k:v for k,v in parameters.items() if k!='TEMAS'}
        run.update(PADROES='',MODELO='',TABELAS='',FONTES='Bases selecionadas pelo operador')
        catalogs={};owned=[]
        raster_tools = load_local('faixas_raster.py') if any(theme['raster'] for theme in themes) else None
        raster_reports = {}
        core.theme_interval_builders = {}
        core.theme_event_roles = set()
        core.event_tolerance_m = self.parameterAsDouble(parameters, 'TOLERANCIA_EVENTO', context)
        raster_step = self.parameterAsDouble(parameters, 'PASSO_RASTER', context)

        def build_raster(source, band, classes, theme, auto=None):
            def builder(line, crs):
                auto_report = {}
                active_classes = classes
                if auto is not None:
                    active_classes, auto_report = raster_tools.automatic_classes(
                        source, band, line, crs, context, raster_step,
                        auto[0], auto[1], auto[2], feedback)
                    catalogs[theme['role']] = raster_tools.catalog(active_classes)
                output, report = raster_tools.build_intervals(engine, source, band, active_classes,
                    raster_step, line, crs, context, feedback, theme['title'], distance_utils)
                if auto is not None:
                    report.update(auto_report)
                raster_reports[theme['title']] = report
                return source, theme['field'], output
            return builder
        for theme in themes:
            if theme['raster']:
                source = QgsProcessingUtils.mapLayerFromString(theme['source'], context)
                if not isinstance(source, QgsRasterLayer) or not source.isValid() or not source.crs().isValid():
                    raise QgsProcessingException(theme['title'] + ': selecione um raster válido com SRC.')
                try:
                    band = int(theme['field'].split(':', 1)[1])
                    if not 1 <= band <= source.bandCount():
                        raise ValueError('Selecione uma banda existente.')
                    auto = raster_tools.parse_auto_style(theme['style'])
                    classes = None if auto else raster_tools.parse_classes(theme['style'])
                except ValueError as exc:
                    raise QgsProcessingException(theme['title'] + ': ' + str(exc)) from exc
                if classes is not None:
                    catalogs[theme['role']] = raster_tools.catalog(classes)
                core.theme_interval_builders[theme['role']] = build_raster(source, band, classes, theme, auto)
                continue
            source=resolve_source(theme['source'],context)
            if source.isEditable():raise QgsProcessingException('Encerre a edição de '+source.name())
            if source.customProperty('geo/role',''):
                raise QgsProcessingException('Selecione a base geográfica original, não uma saída do perfil: '+source.name())
            if theme['field'] not in source.fields().names():raise QgsProcessingException('Campo ausente em '+theme['title']+': '+theme['field'])
            run[theme['role']]=source;run['CAMPO_'+theme['role']]=theme['field']
            event_theme = QgsWkbTypes.geometryType(source.wkbType()) in (QgsWkbTypes.PointGeometry, QgsWkbTypes.LineGeometry)
            if event_theme:
                if theme['style']:
                    styled = source.clone()
                    message, ok = styled.loadNamedStyle(theme['style'])
                    if not ok:
                        raise QgsProcessingException(theme['title'] + ': QML could not be loaded: ' + message)
                    raw_catalog = engine.category_catalog(styled.renderer(), theme['field'])
                else:
                    raw_catalog = engine.category_catalog(source.renderer(), theme['field'])
                if not raw_catalog:
                    raise QgsProcessingException(theme['title'] + ': categorize the selected field or provide a categorized QML.')
                catalogs[theme['role']] = {value: QgsRendererCategory(value,
                    QgsFillSymbol.createSimple({'color': category.symbol().color().name(), 'outline_style': 'no'}),
                    category.label()) for value, category in raw_catalog.items()}
                def build_event(source_layer, field, title, role):
                    def builder(line, crs):
                        prepared = engine.prepare_input(source_layer, crs, context, feedback)
                        output = engine.event_intervals_from_features(line, prepared, crs, field,
                            context, feedback, title,
                            self.parameterAsDouble(parameters, 'LARGURA_EVENTO', context),
                            self.parameterAsDouble(parameters, 'TOLERANCIA_EVENTO', context))
                        present = {engine.class_value(f['classe']) for f in output.getFeatures()}
                        missing = present - set(catalogs[role])
                        if missing:
                            raise QgsProcessingException(title + ': missing symbols for classes: ' + ', '.join(repr(v) for v in sorted(missing)))
                        return source_layer, field, output
                    return builder
                core.theme_interval_builders[theme['role']] = build_event(source, theme['field'], theme['title'], theme['role'])
                core.theme_event_roles.add(theme['role'])
                continue
            if theme['style']:
                catalogs[theme['role']]=engine.load_standard_catalog(theme['style'],source.crs())
            elif not engine.category_catalog(source.renderer(),theme['field']):
                raise QgsProcessingException(theme['title']+': categorize a base pelo campo escolhido ou informe um QML categorizado; nenhuma cor será inventada.')
            else:catalogs[theme['role']]=engine.category_catalog(source.renderer(),theme['field'])
        # Validar classes efetivamente atravessadas ANTES de gravar o GeoPackage.
        original_intervals=engine.intervals_from_polygons
        def intervals(*args,**kwargs):
            result=original_intervals(*args,**kwargs);role=args[3]
            if role in catalogs:
                present={engine.class_value(f['classe']) for f in result.getFeatures()}
                missing=present-set(catalogs[role])
                if missing:raise QgsProcessingException(engine.TITLES[role]+': classes sem símbolo: '+', '.join(repr(v) for v in sorted(missing)))
            return result
        engine.intervals_from_polygons=intervals
        original_style=engine.thematic_style
        def style(layer,source,field,standard=None):
            return original_style(layer,source,field,catalogs[layer.customProperty('geo/role','')])
        engine.thematic_style=style
        has_urban=self.parameterAsVectorLayer(parameters,'URBANO',context) is not None
        nucleus=self.parameterAsString(parameters,'NOME_NUCLEO',context).strip()
        if has_urban and not nucleus:raise QgsProcessingException('Com núcleo selecionado, preencha seu nome.')
        title=self.parameterAsString(parameters,'TITULO',context).strip()
        name=self.parameterAsString(parameters,'LAYOUT',context).strip()
        if not title or not name:raise QgsProcessingException('Preencha título e nome de layout.')
        old=project.layoutManager().layoutByName(name)
        signature=cfg.layout_signature(themes)
        if old is not None and (old.customProperty('geo/custom_signature','')!=signature or old.customProperty('geo/custom_urban_name','')!=(nucleus if has_urban else '')):
            raise QgsProcessingException('Este layout tem outra configuração. Use novo nome e GeoPackage para outra composição de temas ou núcleo.')
        ab=self.parameterAsVectorLayer(parameters,'AB',context)
        if ab is None or not ab.isValid():raise QgsProcessingException('Selecione uma linha A–B válida.')
        if self.parameterAsVectorLayer(parameters,'RIOS',context) is None:
            # Uma camada vazia evita fabricar cruzamentos e mantém o schema de saída.
            rivers=engine.memory_layer('LineString',ab.crs(),[],'Sem rios informados')
            owned.append(rivers);run['RIOS']=rivers
        orientation = self.parameterAsEnum(parameters, 'ORIENTACAO', context)
        if orientation not in range(len(ORIENTATIONS)):
            raise QgsProcessingException('Escolha Retrato ou Paisagem.')
        include_map = self.parameterAsBool(parameters, 'MAPA_LOCALIZACAO', context)
        background = self.parameterAsLayer(parameters, 'MAPA_CONTEXTO', context) if include_map else None
        if include_map and project.mapLayer(ab.id()) is None:
            raise QgsProcessingException('Para incluir o mapa, carregue a linha A–B no projeto.')
        if include_map and parameters.get('MAPA_CONTEXTO') and (background is None or project.mapLayer(background.id()) is None):
            raise QgsProcessingException('Selecione uma camada de contexto carregada no projeto.')
        urban_name = nucleus if has_urban else ''
        engine.new_layout = lambda p, n: build_layout(p, n, themes, nucleus, has_urban)
        original_refresh = engine.refresh_layout

        def layout_height(layout, layers, args, orientation, details_y, urban_name, page_width, minimum_height):
            side_by_side_map = include_map and orientation == 1
            content_height = finish_legends(layout, layers, themes, orientation, details_y, urban_name,
                                            page_width, side_by_side_map=side_by_side_map)
            if side_by_side_map:
                legend_top = details_y + (16 if urban_name else 10)
                map_bottom = add_location_map(layout, project, ab, background,
                                              args[0], args[1], page_width, legend_top,
                                              side_by_side=True,
                                              urban_layer=self.parameterAsVectorLayer(parameters, 'URBANO', context))
                height = max(minimum_height, content_height, map_bottom + MARGIN)
            else:
                map_bottom = add_location_map(layout, project, ab if include_map else None, background,
                                              args[0], args[1], page_width, content_height - 4,
                                              urban_layer=self.parameterAsVectorLayer(parameters, 'URBANO', context))
                height = max(minimum_height, content_height, map_bottom + 4)
            if height > 5000:
                raise QgsProcessingException('O conteúdo excede a altura máxima da folha.')
            return height

        def refresh(layout, layers, *args):
            page_width, minimum_height = PAGE_SIZES[orientation]
            details_y = arrange_profile(layout, themes, orientation, urban_name, page_width)

            def update_custom_labels():
                vertical_label = layout.itemById('geo_unidade_altimetria')
                if vertical_label is not None:
                    vertical_label.setText(units.layout_vertical_label(vertical))
                    vertical_label.setVisibility(True)
                indication = layout.itemById('geo_indicacao_rios_urbano')
                river_layer = layers.get('RIOS')
                river_count = river_layer.featureCount() if river_layer is not None else 0
                if indication is not None and river_count:
                    indication.setText(river_crossing_legend_text(indication.text(), river_count))

            original_refresh(layout, layers, *args)
            overlaps = add_overlap_hatching(layout, layers, themes, float(args[2]), distance_utils)
            update_custom_labels()
            indication = layout.itemById('geo_indicacao_rios_urbano')
            if indication is not None and overlaps:
                indication.setText(indication.text() + '   ▧ Hachura: classes sobrepostas; conferir a base.')
            layout.setCustomProperty('geo/unidade_vertical_entrada',vertical['unit'])
            layout.setCustomProperty('geo/fator_vertical_para_metros',vertical['factor_to_meters'])
            profile_item = layout.itemById('geo_altimetria')
            profile_item.setFrameEnabled(False)
            profile_item.plot().setChartBorderSymbol(
                QgsFillSymbol.createSimple({'style': 'no', 'outline_style': 'no'}))
            layout.itemById('geo_titulo').setText(title)
            layout.setCustomProperty('geo/custom_signature', signature)
            layout.setCustomProperty('geo/custom_urban_name', urban_name)
            height = layout_height(layout, layers, args, orientation, details_y, urban_name, page_width, minimum_height)
            if orientation == 1 and height >= page_width:
                page_width = height + 2 * MARGIN
                details_y = arrange_profile(layout, themes, orientation, urban_name, page_width)
                original_refresh(layout, layers, *args)
                overlaps = add_overlap_hatching(layout, layers, themes, float(args[2]), distance_utils)
                update_custom_labels()
                indication = layout.itemById('geo_indicacao_rios_urbano')
                if indication is not None and overlaps:
                    indication.setText(indication.text() + '   ▧ Hachura: classes sobrepostas; conferir a base.')
                profile_item = layout.itemById('geo_altimetria')
                profile_item.setFrameEnabled(False)
                profile_item.plot().setChartBorderSymbol(
                    QgsFillSymbol.createSimple({'style': 'no', 'outline_style': 'no'}))
                height = layout_height(layout, layers, args, orientation, details_y, urban_name, page_width, minimum_height)
            layout.pageCollection().pages()[0].setPageSize(QgsLayoutSize(page_width, height))
            layout.setCustomProperty('geo/pagina_expandida', height > minimum_height)
            layout.refresh()

        engine.refresh_layout = refresh
        original_sample=engine.sample_raster
        def sample_converted(*args, **kwargs):
            value=original_sample(*args, **kwargs)
            return None if value is None else value * vertical['factor_to_meters']
        engine.sample_raster=sample_converted
        try:
            if not vertical['confirmed']:
                feedback.pushWarning('Unidade vertical do MDE não confirmada; valores foram mantidos sem conversão. Revise o perfil antes de interpretar as cotas.')
            result=core.processAlgorithm(run,context,feedback)
        finally:
            engine.sample_raster=original_sample
        summary = json.loads(result['RESUMO'])
        # The shared engine has a separate build identity; expose both explicitly.
        summary['versao_motor'] = summary.pop('versao', None)
        try:
            gpkg_path = str(result.get('GPKG') or self.parameterAsFileOutput(parameters, 'GPKG', context))
            length_m = float(summary.get('comprimento_m', 0.0))
            tables = summary.get('tabelas', {})
            sample_table = tables.get('AMOSTRAS', 'amostras_altimetria_auto')
            samples_layer = QgsVectorLayer(gpkg_path + '|layername=' + sample_table,
                                           'Amostras altimétricas', 'ogr')
            if samples_layer.isValid():
                samples = []
                for feature in samples_layer.getFeatures():
                    distance = feature['distancia']
                    elevation = feature['cota']
                    try:
                        valid_elevation = elevation is not None and math.isfinite(float(elevation))
                    except (TypeError, ValueError):
                        valid_elevation = False
                    samples.append((float(distance), not valid_elevation))
                missing_ranges = distance_utils.sample_missing_ranges(samples, length_m)
                summary['intervalos_sem_dados_altimetricos_m'] = missing_ranges
                summary['texto_trechos_sem_dado_altimetrico'] = distance_utils.format_ranges(
                    missing_ranges, approximate=True)

            gaps_by_theme = {}
            quality = summary.get('qualidade_tematicas', {})
            for theme in themes:
                source = project.mapLayer(theme['source'])
                if source is None or not source.isValid():
                    continue
                is_polygon = (not theme['raster'] and
                              QgsWkbTypes.geometryType(source.wkbType()) == QgsWkbTypes.PolygonGeometry)
                if not (theme['raster'] or is_polygon):
                    continue
                table = tables.get(theme['role'])
                if not table:
                    continue
                output_layer = QgsVectorLayer(gpkg_path + '|layername=' + table,
                                              theme['title'] + ' — faixa gerada', 'ogr')
                if not output_layer.isValid():
                    continue
                covered = []
                for feature in output_layer.getFeatures():
                    try:
                        start, stop = float(feature['dist_ini']), float(feature['dist_fin'])
                    except (TypeError, ValueError):
                        continue
                    covered.append((start, stop))
                gaps = distance_utils.uncovered_ranges(covered, length_m)
                gaps_by_theme[theme['title']] = gaps
                if theme['role'] in quality:
                    quality[theme['role']]['intervalos_sem_cobertura_m'] = gaps
            summary['intervalos_sem_cobertura_por_tema_m'] = gaps_by_theme
        except Exception as exc:
            feedback.pushWarning('O perfil foi gerado, mas não foi possível localizar todos os intervalos sem dado no resumo: ' + str(exc))
        summary.update(modo='personalizado', temas=[t['title'] for t in themes],
                       numero_temas=len(themes), orientacao=ORIENTATIONS[orientation],
                       versao='17.23.2', versao_personalizado=VERSION, mapa_localizacao=include_map,
                       mapa_contexto=background.name() if background is not None else None, faixas_raster=raster_reports,
                       unidade_vertical_entrada=vertical['unit'],
                       fator_vertical_para_metros=vertical['factor_to_meters'],
                       unidade_vertical_confirmada=vertical['confirmed'])
        if not vertical['confirmed']:
            summary['requer_conferencia']=True
            summary['status_dados']='CONFERIR_UNIDADE_VERTICAL'
        if result['STATUS_LAYOUT'] == 'ATUALIZADO':
            layout = project.layoutManager().layoutByName(name)
            page = layout.pageCollection().pages()[0].pageSize()
            summary['folha_mm'] = [page.width(), page.height()]
            try:
                summary['sobreposicoes_tematicas_m'] = json.loads(
                    layout.customProperty('geo/sobreposicoes_tematicas', '{}'))
            except (TypeError, ValueError):
                summary['sobreposicoes_tematicas_m'] = {}
        result['RESUMO'] = json.dumps(summary, ensure_ascii=False)
        return result
