# -*- coding: utf-8 -*-
"""Fluxo guiado: selecionar dados, confirmar faixas, pré-verificar e abrir geração."""

# Desenvolvido por João Sipraki
# Copyright (C) 2026 João Sipraki
# SPDX-License-Identifier: GPL-3.0-or-later

import json

from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout,
    QLabel, QMessageBox, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)
from qgis.core import QgsMapLayerProxyModel, QgsProject, QgsRasterLayer
from qgis.gui import QgsMapLayerComboBox
try:
    from .unidades_vertical import UNIT_CHOICES
    from .intervalos import format_ranges
    from .modelos_estudo import (STUDY_MODELS, model_candidate_match, model_availability,
                                 candidate_visible_for_model)
except ImportError:
    from unidades_vertical import UNIT_CHOICES
    from intervalos import format_ranges
    from modelos_estudo import (STUDY_MODELS, model_candidate_match, model_availability,
                                candidate_visible_for_model)


ROLE_TITLES = {
    'solos': 'Solos', 'geologia': 'Geologia', 'geomorfologia': 'Geomorfologia',
    'relevo': 'Relevo', 'vegetação': 'Vegetação', 'clima': 'Clima',
    'uso e cobertura da terra': 'Uso e cobertura da terra',
    'hidrografia/eventos': 'Hidrografia', 'localização/contexto': 'Contexto',
    'observações de campo': 'Observações de campo', 'tema raster': 'Tema raster',
    'tema personalizado': 'Tema personalizado',
}


def source_label(source):
    """Short visible provenance, retaining table name for GeoPackage sources."""
    value = str(source or '')
    path, separator, query = value.partition('|')
    normalized = path.replace('\\', '/').rstrip('/')
    parts = [part for part in normalized.split('/') if part]
    if len(parts) >= 2:
        label = '{} / {}'.format(parts[-2], parts[-1])
    else:
        label = normalized[-100:]
    if separator and 'layername=' in query:
        table = query.split('layername=', 1)[1].split('|', 1)[0].split('&', 1)[0]
        if table:
            label += ' · ' + table
    return label or 'Fonte não informada'


def suggested_theme_row(candidate, layer):
    """Build an editable default row; the user still has to check the candidate."""
    roles = candidate.get('papeis_sugeridos') or []
    role = next((value for value in roles if value != 'tema raster'),
                roles[0] if roles else 'tema personalizado')
    title = ROLE_TITLES.get(role, role[:1].upper() + role[1:])
    if role == 'relevo' and 'declividade' in layer.name().casefold():
        title = 'Declividade'
    if role == 'tema personalizado':
        title = layer.name()
    if isinstance(layer, QgsRasterLayer):
        return [title, layer.id(), 'banda:1', '@auto|quantile|5|Viridis']
    field = candidate.get('pode_classificar_por') or ''
    if not field:
        fields = candidate.get('campos_candidatos') or []
        field = fields[0] if fields else ''
    return [title, layer.id(), field, '']


def flatten_rows(rows):
    return [cell for row in rows for cell in row]


def preflight_message(report):
    checks = report.get('verificacoes', {})
    ab = checks.get('A-B', {})
    dem = checks.get('MDE', {})
    lines = [report.get('resultado', 'Pré-verificação concluída.'),
             'Bloqueios: {} · Avisos: {}'.format(report.get('bloqueios', 0), report.get('avisos', 0))]
    if ab.get('comprimento_m') is not None:
        lines.append('A–B: {:.1f} m no SRC métrico {} · origem {}'.format(
            ab['comprimento_m'], ab.get('src_analise', 'não informado'),
            ab.get('crs', 'SRC não informado')))
    elif ab.get('comprimento') is not None:
        lines.append('A–B: {:.1f} unidades do SRC · {}'.format(
            ab['comprimento'], ab.get('crs', 'SRC não informado')))
    if dem.get('amostras'):
        lines.append('MDE: {:.1f}% de cobertura ({} / {} amostras).'.format(
            dem.get('cobertura_pct', 0), dem.get('amostras_validas', 0), dem['amostras']))
    if dem.get('intervalos_sem_dados_m'):
        lines.append('MDE sem dado (aprox.): ' + format_ranges(
            dem['intervalos_sem_dados_m'], approximate=True) + '.')
    if dem.get('unidade_vertical_confirmada'):
        lines.append('Cotas declaradas em {} · fator para metros: {:.9g}.'.format(
            dem.get('unidade_vertical_entrada', 'unidade informada'),
            dem.get('fator_vertical_para_metros', 1.0)))
    for theme in checks.get('faixas', []):
        detail = '{}: {}'.format(theme.get('tema', 'Faixa'), theme.get('status', 'sem resultado'))
        if theme.get('cobertura_pct') is not None:
            detail += ' · {:.1f}% de cobertura'.format(theme['cobertura_pct'])
        if theme.get('classes_cruzadas'):
            detail += ' · {} classe(s) no eixo'.format(len(theme['classes_cruzadas']))
        if theme.get('intervalos_sem_cobertura_m'):
            detail += ' · lacunas: ' + format_ranges(theme['intervalos_sem_cobertura_m'])
        if theme.get('intervalos_sem_dados_m'):
            detail += ' · sem dado (aprox.): ' + format_ranges(
                theme['intervalos_sem_dados_m'], approximate=True)
        if theme.get('erro'):
            detail += ' · ' + theme['erro']
        lines.append(detail)
    if not dem.get('unidade_vertical_confirmada', dem.get('confirmar_unidade_metros') is True):
        lines.append('Unidade vertical não confirmada; as cotas serão mantidas sem conversão.')
    return '\n'.join(lines)


class AssistentePerfilDialog(QDialog):
    def __init__(self, iface, parent=None, load_candidates=True):
        super().__init__(parent or iface.mainWindow())
        self.iface = iface
        self.project = QgsProject.instance()
        self.theme_rows = []
        self.candidate_data = {}
        self.setWindowTitle('Assistente do perfil geoecológico')
        self.resize(1220, 720)

        root = QVBoxLayout(self)
        intro = QLabel(
            'Escolha a linha A–B e o MDE. Confira candidatos, marque os temas que deseja usar, '
            'ordene as faixas e faça a pré-verificação antes de abrir a geração.'
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        guide = QHBoxLayout()
        guide.addWidget(QLabel('Objetivo / guia de estudo'))
        self.study_model = QComboBox()
        self.study_model.addItems([item['titulo'] for item in STUDY_MODELS.values()])
        self.study_model.currentIndexChanged.connect(self._update_model_guidance)
        guide.addWidget(self.study_model, 1)
        root.addLayout(guide)
        self.model_guidance = QLabel('')
        self.model_guidance.setWordWrap(True)
        root.addWidget(self.model_guidance)

        form = QFormLayout()
        self.ab = QgsMapLayerComboBox()
        self.ab.setFilters(QgsMapLayerProxyModel.LineLayer)
        self.ab.setAllowEmptyLayer(True)
        self.ab.setLayer(None)
        self.dem = QgsMapLayerComboBox()
        self.dem.setFilters(QgsMapLayerProxyModel.RasterLayer)
        self.dem.setAllowEmptyLayer(True)
        self.dem.setLayer(None)
        self.vertical_unit = QComboBox()
        self.vertical_unit.addItems(list(UNIT_CHOICES))
        self.vertical_factor = QDoubleSpinBox()
        self.vertical_factor.setRange(0.000001, 1000000.0)
        self.vertical_factor.setDecimals(9)
        self.vertical_factor.setSingleStep(0.1)
        self.vertical_factor.setValue(1.0)
        self.vertical_factor.setEnabled(False)
        self.vertical_unit.currentIndexChanged.connect(self._vertical_unit_changed)
        form.addRow('Linha A–B', self.ab)
        form.addRow('MDE', self.dem)
        form.addRow('Unidade vertical do MDE', self.vertical_unit)
        form.addRow('Fator personalizado para metros', self.vertical_factor)
        root.addLayout(form)

        self.status = QLabel('As sugestões são opcionais e nenhuma faixa começa marcada.')
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.candidates = QTreeWidget()
        self.candidates.setColumnCount(6)
        self.candidates.setHeaderLabels(['Usar', 'Camada · ID curto', 'Origem da fonte', 'Papel sugerido', 'Campo / banda', 'Confiança e evidências'])
        self.candidates.setRootIsDecorated(False)
        self.candidates.setAlternatingRowColors(True)
        self.candidates.setUniformRowHeights(True)
        self.candidates.setColumnWidth(0, 48)
        self.candidates.setColumnWidth(1, 230)
        self.candidates.setColumnWidth(2, 220)
        self.candidates.setColumnWidth(3, 160)
        self.candidates.setColumnWidth(4, 130)
        root.addWidget(self.candidates, 1)
        self.filter_compatible = QCheckBox('Mostrar apenas camadas compatíveis com o guia')
        self.filter_compatible.toggled.connect(self._apply_candidate_filter)
        root.addWidget(self.filter_compatible)

        buttons = QHBoxLayout()
        self.refresh_button = QPushButton('Atualizar sugestões')
        self.refresh_button.clicked.connect(self.refresh_candidates)
        buttons.addWidget(self.refresh_button)
        self.themes_button = QPushButton('Configurar / ordenar faixas…')
        self.themes_button.clicked.connect(self.edit_themes)
        buttons.addWidget(self.themes_button)
        self.repair_button = QPushButton('Diagnosticar / corrigir geometrias…')
        self.repair_button.clicked.connect(self.diagnose_and_repair_geometries)
        buttons.addWidget(self.repair_button)
        self.themes_summary = QLabel('Nenhuma faixa configurada')
        self.themes_summary.setWordWrap(True)
        buttons.addWidget(self.themes_summary, 1)
        root.addLayout(buttons)

        options = QHBoxLayout()
        self.include_map = QCheckBox('Incluir mapa de localização')
        options.addWidget(self.include_map)
        self.context = QgsMapLayerComboBox()
        self.context.setFilters(QgsMapLayerProxyModel.VectorLayer | QgsMapLayerProxyModel.RasterLayer)
        self.context.setAllowEmptyLayer(True)
        self.context.setLayer(None)
        self.context.setEnabled(False)
        options.addWidget(QLabel('Camada de contexto'))
        options.addWidget(self.context, 1)
        self.include_map.toggled.connect(self.context.setEnabled)
        root.addLayout(options)
        optional = QLabel('Rios e núcleo urbano continuam opcionais e podem ser definidos na próxima janela de geração.')
        optional.setWordWrap(True)
        root.addWidget(optional)

        controls = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.go_button = controls.addButton('Pré-verificar e abrir geração…', QDialogButtonBox.AcceptRole)
        self.go_button.clicked.connect(self.preflight_and_continue)
        controls.rejected.connect(self.reject)
        root.addWidget(controls)

        self.ab.layerChanged.connect(lambda layer: self.refresh_candidates())
        self._update_model_guidance()
        if load_candidates:
            self.refresh_candidates()

    def _selected_model_key(self):
        return list(STUDY_MODELS)[self.study_model.currentIndex()]

    def _update_model_guidance(self):
        key = self._selected_model_key()
        model = STUDY_MODELS[key]
        if not model['papeis']:
            self.model_guidance.setText(model['descricao'])
        else:
            present, missing = model_availability(list(self.candidate_data.values()), key)
            message = model['descricao']
            if self.candidate_data:
                message += '\nPapéis encontrados nas sugestões: {}. Não identificados: {}.'.format(
                    ', '.join(present) if present else 'nenhum',
                    ', '.join(missing) if missing else 'nenhum')
            message += ' A lista abaixo destaca compatibilidades; nada é marcado ou adicionado automaticamente.'
            self.model_guidance.setText(message)
        self._apply_candidate_filter()

    def _apply_candidate_filter(self):
        key = self._selected_model_key()
        enabled = self.filter_compatible.isChecked()
        visible = 0
        for index in range(self.candidates.topLevelItemCount()):
            item = self.candidates.topLevelItem(index)
            candidate = self.candidate_data.get(item.data(0, Qt.ItemDataRole.UserRole), {})
            show = candidate_visible_for_model(candidate, key, enabled)
            item.setHidden(not show)
            visible += int(show)
        if enabled:
            self.filter_compatible.setText('Mostrar apenas compatíveis ({} de {})'.format(
                visible, self.candidates.topLevelItemCount()))
        else:
            self.filter_compatible.setText('Mostrar apenas camadas compatíveis com o guia')

    def _vertical_unit_changed(self, index):
        if index == 1:
            self.vertical_factor.setValue(1.0)
            self.vertical_factor.setEnabled(False)
        elif index == 2:
            self.vertical_factor.setValue(0.3048)
            self.vertical_factor.setEnabled(False)
        elif index == 3:
            self.vertical_factor.setEnabled(True)
        else:
            self.vertical_factor.setValue(1.0)
            self.vertical_factor.setEnabled(False)

    def refresh_candidates(self):
        import processing
        self.candidates.clear()
        self.candidate_data.clear()
        line = self.ab.currentLayer()
        try:
            result = processing.run(
                'perfil_geoecologico_adaptavel:sugerir_camadas_perfil',
                {'AB': line if line and line.isValid() else None, 'LIMITE': 200},
            )
            report = json.loads(result['RELATORIO'])
        except Exception as exc:
            self.status.setText('Não foi possível analisar as camadas: {}'.format(exc))
            return

        for candidate in report.get('sugestoes', []):
            layer = self.project.mapLayer(candidate.get('id', ''))
            if layer is None or not layer.isValid():
                continue
            roles = ', '.join(candidate.get('papeis_sugeridos') or ['tema personalizado'])
            matches_model = model_candidate_match(candidate, self._selected_model_key())
            field = candidate.get('pode_classificar_por') or (
                'banda 1' if candidate.get('tipo') == 'raster' else ', '.join(candidate.get('campos_candidatos') or [])
            )
            details = '{}% · {}'.format(candidate.get('confianca_sugestao', 0),
                                        '; '.join(candidate.get('evidencias') or []))
            if candidate.get('provavel_saida_de_perfil'):
                details = 'POSSÍVEL SAÍDA DE PERFIL · ' + details
            if matches_model:
                details = 'COMPATÍVEL COM O GUIA · ' + details
            short_id = layer.id()[:8]
            item = QTreeWidgetItem(['', '{} · {}'.format(layer.name(), short_id),
                                    source_label(candidate.get('fonte') or layer.source()), roles, field, details])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Unchecked)
            item.setData(0, Qt.ItemDataRole.UserRole, layer.id())
            item.setToolTip(1, 'ID: {}'.format(layer.id()))
            item.setToolTip(2, layer.source())
            item.setToolTip(5, '\n'.join(candidate.get('evidencias') or []))
            if candidate.get('provavel_saida_de_perfil'):
                item.setToolTip(2, item.toolTip(2) + '\nProvável saída de perfil anterior; confira a origem antes de reutilizar.')
            self.candidates.addTopLevelItem(item)
            self.candidate_data[layer.id()] = candidate
        self.candidates.resizeColumnToContents(0)
        self.status.setText(
            '{} camadas avaliadas · {} candidatas listadas · {} camadas inválidas ignoradas. '
            'As sugestões são heurísticas; confira a origem, a escala e o campo antes de usar.'.format(
                report.get('camadas_vetoriais_raster_avaliadas', 0),
                report.get('sugestoes_total', 0), report.get('camadas_invalidas_ignoradas', 0))
        )
        self._update_model_guidance()

    def _checked_candidate_rows(self):
        rows = []
        for index in range(self.candidates.topLevelItemCount()):
            item = self.candidates.topLevelItem(index)
            if item.checkState(0) != Qt.CheckState.Checked:
                continue
            layer_id = item.data(0, Qt.ItemDataRole.UserRole)
            layer = self.project.mapLayer(layer_id)
            candidate = self.candidate_data.get(layer_id)
            if layer is not None and candidate is not None:
                rows.append(suggested_theme_row(candidate, layer))
        return rows

    def edit_themes(self):
        try:
            from .interface_temas import ThemesDialog
        except ImportError:
            from interface_temas import ThemesDialog
        rows = list(self.theme_rows)
        existing_ids = {row[1] for row in rows}
        for row in self._checked_candidate_rows():
            if row[1] not in existing_ids:
                rows.append(row)
                existing_ids.add(row[1])
        dialog = ThemesDialog(flatten_rows(rows), self)
        if dialog.exec():
            flat = dialog.values()
            self.theme_rows = [flat[i:i + 4] for i in range(0, len(flat), 4)]
            names = [row[0] for row in self.theme_rows]
            self.themes_summary.setText('{} faixa(s): {}'.format(len(names), ' → '.join(names)))

    def diagnose_and_repair_geometries(self):
        """Oferece reparo temporário para vetores configurados, sem editar as fontes."""
        if not self.theme_rows:
            QMessageBox.information(self, 'Diagnóstico de geometrias',
                                    'Configure as faixas primeiro para selecionar quais camadas verificar.')
            return
        from qgis.core import QgsVectorLayer
        from .correcao import invalid_geometry_report, repaired_geometry_copy, replace_theme_sources

        layers = {}
        for row in self.theme_rows:
            layer = self.project.mapLayer(row[1]) if len(row) > 1 else None
            if isinstance(layer, QgsVectorLayer) and layer.isValid():
                layers[layer.id()] = layer
        if not layers:
            QMessageBox.information(self, 'Diagnóstico de geometrias',
                                    'As faixas configuradas não contêm camadas vetoriais para reparar.')
            return

        reports = {}
        lines = []
        for layer_id, layer in layers.items():
            try:
                report = invalid_geometry_report(layer)
                reports[layer_id] = report
                lines.append('{}: {} inválida(s) em {} feição(ões)'.format(
                    layer.name(), report['geometrias_invalidas'], report['feicoes_verificadas']))
            except Exception as exc:
                lines.append('{}: falha no diagnóstico ({})'.format(layer.name(), exc))
        invalid = [layer_id for layer_id, report in reports.items() if report['geometrias_invalidas']]
        if not invalid:
            QMessageBox.information(self, 'Diagnóstico de geometrias',
                                    '\n'.join(lines) + '\n\nNenhum reparo geométrico foi necessário.')
            return

        answer = QMessageBox.question(
            self, 'Reparar cópias temporárias?',
            '\n'.join(lines) + '\n\nO QGIS tentará corrigir as geometrias inválidas em cópias temporárias. '
            'As camadas originais não serão alteradas. Se o resultado continuar inválido, a faixa original será mantida. '
            'Sobreposições, lacunas temáticas e erros de classificação não são corrigidos por este filtro.\n\n'
            'Usar as cópias corrigidas nesta sessão?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return

        replacements = {}
        outcomes = []
        for layer_id in invalid:
            source = layers[layer_id]
            try:
                corrected = repaired_geometry_copy(source)
                after = invalid_geometry_report(corrected)
                if after['geometrias_invalidas']:
                    outcomes.append('{}: ainda restam {} inválida(s); original mantida.'.format(
                        source.name(), after['geometrias_invalidas']))
                    continue
                self.project.addMapLayer(corrected)
                replacements[layer_id] = corrected.id()
                outcomes.append('{}: {} feição(ões) verificadas; cópia temporária pronta.'.format(
                    source.name(), after['feicoes_verificadas']))
            except Exception as exc:
                outcomes.append('{}: não foi possível corrigir ({}); original mantida.'.format(source.name(), exc))

        if replacements:
            self.theme_rows = replace_theme_sources(self.theme_rows, replacements)
            names = [row[0] for row in self.theme_rows]
            self.themes_summary.setText('{} faixa(s): {}'.format(len(names), ' → '.join(names)))
        QMessageBox.information(self, 'Resultado do reparo assistido',
                                '\n'.join(outcomes) + '\n\nAs bases originais permanecem intactas. '
                                'As cópias temporárias ficam no projeto atual; salve/exporte os dados corrigidos '
                                'se quiser reutilizá-los em outra sessão.')

    def preflight_and_continue(self):
        import processing
        line = self.ab.currentLayer()
        dem = self.dem.currentLayer()
        if line is None or not line.isValid():
            QMessageBox.warning(self, 'Linha A–B', 'Selecione uma linha A–B válida.')
            return
        if dem is None or not dem.isValid():
            QMessageBox.warning(self, 'MDE', 'Selecione um MDE válido.')
            return
        if not self.theme_rows:
            QMessageBox.warning(self, 'Faixas', 'Marque candidatos e configure pelo menos uma faixa.')
            return
        if self.include_map.isChecked() and self.context.currentLayer() is None:
            QMessageBox.warning(self, 'Mapa de localização', 'Selecione a camada de contexto ou desmarque o mapa.')
            return
        parameters = {'AB': line, 'MDE': dem, 'TEMAS': flatten_rows(self.theme_rows), 'PASSO': 30,
                      'UNIDADE_VERTICAL': self.vertical_unit.currentIndex(),
                      'FATOR_VERTICAL': self.vertical_factor.value()}
        try:
            result = processing.run('perfil_geoecologico_adaptavel:preverificar_entradas_perfil', parameters)
            report = json.loads(result['RELATORIO'])
        except Exception as exc:
            QMessageBox.critical(self, 'Pré-verificação', 'Não foi possível verificar as entradas:\n{}'.format(exc))
            return
        message = preflight_message(report)
        if report.get('bloqueios', 0):
            QMessageBox.critical(self, 'Revise as entradas', message + '\n\nVolte às faixas e corrija os bloqueios antes de gerar.')
            return
        if report.get('avisos', 0):
            answer = QMessageBox.question(
                self, 'Entradas verificadas com avisos',
                message + '\n\nDeseja abrir a geração e revisar as opções de saída?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        else:
            QMessageBox.information(self, 'Entradas verificadas', message)

        generator_parameters = {
            'AB': line, 'MDE': dem, 'TEMAS': flatten_rows(self.theme_rows),
            'UNIDADE_VERTICAL': self.vertical_unit.currentIndex(),
            'FATOR_VERTICAL': self.vertical_factor.value(),
            'MAPA_LOCALIZACAO': self.include_map.isChecked(),
            'MAPA_CONTEXTO': self.context.currentLayer() if self.include_map.isChecked() else None,
        }
        self.accept()
        QTimer.singleShot(0, lambda params=generator_parameters: processing.execAlgorithmDialog(
            'perfil_geoecologico_adaptavel:perfil_geoecologico_personalizado', params))
