# -*- coding: utf-8 -*-
"""Sugestões explicáveis de camadas candidatas, sem seleção automática."""

# Desenvolvido por João Sipraki
# Copyright (C) 2026 João Sipraki
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import re
import unicodedata

from qgis.core import (
    Qgis, QgsProcessingAlgorithm, QgsProcessingParameterVectorLayer,
    QgsProcessingParameterNumber, QgsProcessingOutputString, QgsProject,
    QgsVectorLayer, QgsRasterLayer, QgsWkbTypes, QgsGeometry,
    QgsCoordinateTransform, QgsProcessing, QgsProcessingException,
)


ROLE_TERMS = {
    'solos': ('solo', 'pedolog', 'latossolo', 'argissolo', 'neossolo', 'gleissolo', 'prim_nivel'),
    'geologia': ('geolog', 'litolog', 'litoestratigraf', 'formacao geolog', 'unidade geolog', 'idade geolog'),
    'geomorfologia': ('geomorf', 'compartimento geomorf', 'unid_morfo', 'theid', 'disseca'),
    'relevo': ('relevo', 'declividade', 'slope', 'hipsometr', 'altimetr', 'umap', 'landform'),
    'vegetação': ('veget', 'fitofisionom', 'cobertura vegetal', 'cvn_', 'ndvi', 'floresta'),
    'clima': ('clima', 'precipit', 'temperatura', 'isoterm', 'pluviometr', 'precip', 'tmean'),
    'uso e cobertura da terra': ('uso da terra', 'uso e cobertura', 'land cover', 'landcover', 'ocupacao', 'mapbioma'),
    'hidrografia/eventos': ('hidrograf', 'hidro_pr', 'rio', 'drenagem', 'córrego', 'corrego', 'stream'),
    'mde/perfil altimétrico': ('mde', 'dem', 'srtm', 'nasadem', 'altimetr', 'elevacao', 'elevation', 'dtm', 'terrain'),
    'localização/contexto': ('municip', 'municipio', 'limite municipal', 'localizacao', 'localidade', 'estado', 'contexto'),
    'núcleo urbano': ('nucleo urbano', 'perimetro urbano', 'area urbana', 'mancha urbana'),
    'observações de campo': ('amostra', 'ponto de campo', 'estacao', 'fotografia', 'foto', 'solo perfil'),
}

FIELD_TERMS = ('classe', 'class', 'categoria', 'tipo', 'formacao', 'unidade', 'legenda',
               'prim_nivel', 'cvn_ds', 'clima', 'uso', 'cobertura', 'codigo', 'sigla', 'nome')
OUTPUT_TABLES = ('faixa_', 'perfil_altimetrico_auto', 'amostras_altimetria_auto',
                 'limites_urbanos_auto', 'rios_ab_auto', 'urbano_ab_auto')


def normalize(text):
    value = unicodedata.normalize('NFKD', str(text or '').casefold())
    return ''.join(ch for ch in value if not unicodedata.combining(ch))


def likely_profile_output(layer):
    if layer.customProperty('geo/role', ''):
        return True
    source = normalize(layer.source().replace('\\', '/'))
    name = normalize(layer.name())
    fields = {normalize(field) for field in layer.fields().names()} if isinstance(layer, QgsVectorLayer) else set()
    table_name = source.split('layername=', 1)[-1].split('|', 1)[0] if 'layername=' in source else ''
    if any(token in table_name for token in OUTPUT_TABLES):
        return True
    if 'perfil_geoecologico.gpkg' in source and ('faixa' in table_name or 'perfil_altimetrico' in table_name):
        return True
    if ('perfil geoecologico' in name or 'perfil_geocologico' in name) and 'faixa' in name:
        return True
    if name.startswith('faixa_') or name.startswith('perfil_geoecologico — faixa'):
        return True
    if {'dist_ini', 'dist_fin'}.issubset(fields) and ('classe' in fields or 'distancia' in fields):
        return True
    return bool(re.match(r'^\d{1,2}\s+(solos|geologia|vegetacao|clima|relevo)', name)
                and {'dist_ini', 'dist_fin'}.issubset(fields))


def candidate_role_evidence(layer):
    name = normalize(layer.name())
    fields = [normalize(field) for field in layer.fields().names()] if isinstance(layer, QgsVectorLayer) else []
    renderer_field = ''
    renderer = layer.renderer() if isinstance(layer, QgsVectorLayer) else None
    if renderer is not None and hasattr(renderer, 'classAttribute'):
        candidate = renderer.classAttribute()
        if candidate in layer.fields().names():
            renderer_field = candidate
    name_roles = []
    renderer_roles = []
    field_roles = set()
    evidence = []
    for role, terms in ROLE_TERMS.items():
        if any(normalize(term) in name for term in terms):
            name_roles.append(role)
            evidence.append('nome compatível com ' + role)
        if renderer_field and any(normalize(term) in normalize(renderer_field) for term in terms):
            renderer_roles.append(role)
            evidence.append('campo de simbologia compatível com ' + role)
        if any(normalize(term) in field for term in terms for field in fields):
            field_roles.add(role)
    # A renderer tells us which field is actually being mapped. Other attributes
    # may describe suitability or metadata and should not create unrelated themes.
    roles = list(dict.fromkeys(name_roles + renderer_roles))
    if not roles and not renderer_field and len(field_roles) == 1:
        roles = list(field_roles)
        evidence.append('um único domínio temático reconhecido nos campos')
    if len(field_roles) > len(roles) and roles:
        evidence.append('há outros campos temáticos; o renderizador/nome orienta a sugestão principal')
    if isinstance(layer, QgsRasterLayer):
        roles.append('tema raster')
        evidence.append('{} banda(s) raster'.format(layer.bandCount()))
    elif isinstance(layer, QgsVectorLayer):
        geometry = QgsWkbTypes.geometryType(layer.wkbType())
        if geometry == QgsWkbTypes.PolygonGeometry:
            evidence.append('polígonos podem formar uma faixa temática')
        elif geometry in (QgsWkbTypes.LineGeometry, QgsWkbTypes.PointGeometry):
            evidence.append('linhas/pontos podem representar eventos')
        if renderer_field:
            evidence.append('simbologia categorizada pelo campo ' + renderer_field)
        elif any(any(term in field for term in FIELD_TERMS) for field in fields):
            evidence.append('há campo(s) com nome compatível com classificação')
    return roles, evidence, renderer_field


def _extent_overlaps_line(layer, line, line_crs, project):
    if not layer.crs().isValid():
        return None
    try:
        transformed = QgsGeometry(line)
        transformed.transform(QgsCoordinateTransform(line_crs, layer.crs(), project))
        return layer.extent().intersects(transformed.boundingBox())
    except Exception:
        return None


class SugerirCamadasPerfil(QgsProcessingAlgorithm):
    def name(self): return 'sugerir_camadas_perfil'
    def displayName(self): return 'Sugerir camadas para o perfil geoecológico'
    def group(self): return 'Perfis'
    def groupId(self): return 'perfis'
    def createInstance(self): return SugerirCamadasPerfil()
    def flags(self):
        return (super().flags() | Qgis.ProcessingAlgorithmFlag.NoThreading) & ~Qgis.ProcessingAlgorithmFlag.SupportsBatch
    def shortHelpString(self):
        return ('Analisa nomes, geometrias, campos, simbologia e extensão das camadas carregadas para sugerir usos possíveis. '
                'As sugestões são explicadas e nunca selecionam temas automaticamente. Camadas que parecem saídas de perfil são marcadas para conferência.')
    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterVectorLayer(
            'AB', 'Linha A–B para priorizar camadas próximas (opcional)',
            types=[QgsProcessing.TypeVectorLine], optional=True))
        self.addParameter(QgsProcessingParameterNumber(
            'LIMITE', 'Máximo de sugestões no relatório', type=QgsProcessingParameterNumber.Integer,
            defaultValue=60, minValue=10, maxValue=200))
        self.addOutput(QgsProcessingOutputString('RELATORIO', 'Relatório de sugestões'))
    def processAlgorithm(self, parameters, context, feedback):
        project = context.project() or QgsProject.instance()
        if project is None:
            raise QgsProcessingException('Abra um projeto QGIS.')
        ab = self.parameterAsVectorLayer(parameters, 'AB', context)
        line = None
        if ab is not None:
            if not ab.isValid() or QgsWkbTypes.geometryType(ab.wkbType()) != QgsWkbTypes.LineGeometry:
                raise QgsProcessingException('A linha A–B selecionada não é uma linha válida.')
            features = list(ab.getFeatures())
            if len(features) != 1 or features[0].geometry().isEmpty():
                raise QgsProcessingException('Para priorizar por área, A–B precisa conter uma única feição válida.')
            line = features[0].geometry()

        report = []
        total_layers = len(project.mapLayers())
        considered = 0
        valid_count = 0
        invalid_count = 0
        for layer in project.mapLayers().values():
            if not isinstance(layer, (QgsVectorLayer, QgsRasterLayer)):
                continue
            considered += 1
            valid = layer.isValid()
            if not valid:
                invalid_count += 1
                continue
            valid_count += 1
            roles, evidence, renderer_field = candidate_role_evidence(layer)
            derived = likely_profile_output(layer)
            is_polygon = isinstance(layer, QgsVectorLayer) and QgsWkbTypes.geometryType(layer.wkbType()) == QgsWkbTypes.PolygonGeometry
            thematic_candidate = bool(roles) or is_polygon or isinstance(layer, QgsRasterLayer)
            if not thematic_candidate:
                continue
            overlaps = _extent_overlaps_line(layer, line, ab.crs(), project) if line is not None else None
            if overlaps is True:
                evidence.append('extensão da camada alcança o envelope de A–B (triagem aproximada)')
            elif overlaps is False and line is not None:
                evidence.append('extensão não alcança o envelope de A–B')
            if derived:
                evidence.append('provável saída/derivada de perfil anterior; conferir antes de reutilizar')
            if isinstance(layer, QgsRasterLayer):
                kind = 'raster'
                geometry_name = 'raster'
                feature_count = None
                bands = layer.bandCount()
                fields = []
                crs = layer.crs().authid()
            else:
                kind = 'vetor'
                geometry_name = QgsWkbTypes.displayString(layer.wkbType())
                feature_count = layer.featureCount()
                bands = None
                fields = layer.fields().names()
                crs = layer.crs().authid()
            name_match = bool(any(normalize(term) in normalize(layer.name())
                                  for termset in ROLE_TERMS.values() for term in termset))
            renderer_role_match = bool(renderer_field and any(
                normalize(term) in normalize(renderer_field)
                for termset in ROLE_TERMS.values() for term in termset))
            score = (25 + (30 if name_match else 0) + (18 if renderer_role_match else 0)
                     + (10 if renderer_field else 0) + (10 if overlaps is True else 0)
                     - (45 if derived else 0) - (15 if overlaps is False and line is not None else 0)
                     - (8 if roles == ['tema personalizado'] else 0))
            score = max(0, min(95, score))
            if not roles:
                roles = ['tema personalizado']
            report.append({
                'camada': layer.name(), 'id': layer.id(), 'fonte': layer.source(),
                'tipo': kind, 'geometria': geometry_name,
                'src': crs, 'pode_classificar_por': renderer_field or None,
                'campos_candidatos': [field for field in fields
                    if any(term in normalize(field) for term in FIELD_TERMS)][:6],
                'bandas': bands, 'feicoes': feature_count, 'papeis_sugeridos': roles,
                'provavel_saida_de_perfil': derived,
                'tipo_fonte_sugerido': 'provável saída/derivada; confirmar antes de reutilizar' if derived else 'possível base; confirmar origem e escala',
                'extensao_alcanca_envelope_ab': overlaps,
                'confianca_sugestao': score, 'evidencias': list(dict.fromkeys(evidence)),
            })
        report.sort(key=lambda item: (item['provavel_saida_de_perfil'],
                                      item['extensao_alcanca_envelope_ab'] is False,
                                      -item['confianca_sugestao'], item['camada'].casefold()))
        limit = self.parameterAsInt(parameters, 'LIMITE', context)
        result = {'camadas_no_projeto': total_layers, 'camadas_vetoriais_raster_avaliadas': considered,
                  'camadas_validas_avaliadas': valid_count, 'camadas_invalidas_ignoradas': invalid_count,
                  'linha_ab_usada': ab.name() if ab is not None else None,
                  'metodo': 'triagem heurística explicável; não escolhe nem altera camadas',
                  'sugestoes_total': len(report), 'sugestoes': report[:limit]}
        feedback.pushInfo('{} camadas temáticas candidatas; apresentando {}.'.format(len(report), min(len(report), limit)))
        for row in report[:min(limit, 12)]:
            feedback.pushInfo('{} — {} — confiança {}{}.'.format(
                row['camada'], ', '.join(row['papeis_sugeridos']), row['confianca_sugestao'],
                ' — provável saída anterior' if row['provavel_saida_de_perfil'] else ''))
        return {'RELATORIO': json.dumps(result, ensure_ascii=False)}

